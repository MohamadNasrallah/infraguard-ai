"""
iep1_app/violations.py

Layer 4 — rule-based violation engine. Pure code, no trained models.
Implements five detection rules backed by the papers cited in
docs/REFERENCES.md:

  wrong_way           — sign short-circuit OR heading rule (Rahman 2022)
  illegal_uturn       — heading reversal > 150° within 3s (Springer 2024)
  speeding            — m/px × pixel-displacement × fps (Llorca 2021)
  red_light_running   — stop-line crossing + state==red (Ong 2024)
  shoulder_driving    — sustained position right of rightmost solid lane

Every rule emits an event dict matching the `events` PostgreSQL schema:
  {class_name, confidence, bbox, track_id, metadata}
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

# ═══ config loader ══════════════════════════════════════════════════════
DEFAULT = {
    "camera": {
        "camera_id": "cam_default",
        "latitude": None,
        "longitude": None,
    },
    "wrong_way": {
        "sign_conf_threshold": 0.92,
        "expected_heading_deg": None,
        "heading_tolerance_deg": 30,
        "wrong_way_threshold_deg": 120,
        "min_track_frames": 10,
        "heading_window_frames": 10,
    },
    "illegal_uturn": {
        "angle_threshold_deg": 150,
        "window_sec": 3.0,
        "enabled_zones": None,
    },
    "speeding": {
        "speed_limit_kmh": 80,
        "meter_per_pixel": 0.05,
        "fps": 30,
        "homography": None,
        "min_track_frames": 10,
    },
    "red_light_running": {
        "stop_line": None,
        "state_conf_threshold": 0.75,
        "crossing_window_sec": 1.5,
    },
    "shoulder_driving": {"sustained_sec": 2.0, "min_lane_confidence": 0.6},
}


def load_config(path: str | Path) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULT.items()}
    if path and Path(path).exists():
        with open(path) as f:
            override = json.load(f)
        for section, vals in override.items():
            if section.startswith("_"):
                continue
            if isinstance(vals, dict):
                cfg.setdefault(section, {}).update(vals)
    return cfg


# ═══ geometry helpers ═══════════════════════════════════════════════════
def _heading_deg(p0, p1) -> float:
    dx = p1[0] - p0[0]
    dy = -(p1[1] - p0[1])  # image Y grows downward
    return math.degrees(math.atan2(dy, dx)) % 360


def _angle_diff(a, b) -> float:
    return abs((a - b + 180) % 360 - 180)


def _in_bbox(point, bbox) -> bool:
    x, y = point
    x1, y1, x2, y2 = bbox
    return x1 <= x <= x2 and y1 <= y <= y2


def _segments_intersect(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def _crossed_line(prev, curr, line):
    if line is None or len(line) < 2:
        return False
    return _segments_intersect(prev, curr, tuple(line[0]), tuple(line[1]))


def _point_right_of_polyline(point, polyline) -> bool:
    """Returns True if point lies to the right of the polyline (in pixel space)."""
    if not polyline or len(polyline) < 2:
        return False
    px, py = point
    for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
        lo_y, hi_y = min(y1, y2), max(y1, y2)
        if lo_y <= py <= hi_y and y2 != y1:
            t = (py - y1) / (y2 - y1)
            line_x_at_py = x1 + t * (x2 - x1)
            return px > line_x_at_py
    mean_x = sum(p[0] for p in polyline) / len(polyline)
    return px > mean_x


# ═══ rule 1 — wrong_way (hybrid) ════════════════════════════════════════
def detect_wrong_way(tracks, detections, cfg, emitted_tracks: set) -> list:
    wcfg = cfg["wrong_way"]
    events = []

    sign_dets = [
        d
        for d in detections
        if d.cls_name in {"sign_no_entry", "sign_wrong_way"}
        and d.conf >= wcfg["sign_conf_threshold"]
    ]
    for sign in sign_dets:
        sx1, sy1, sx2, sy2 = sign.bbox
        zone = [sx1 - 100, sy1, sx2 + 100, sy2 + 400]
        for t in tracks:
            if t["track_id"] in emitted_tracks:
                continue
            if _in_bbox(t["centroid"], zone):
                events.append({
                    "class_name": "wrong_way",
                    "confidence": sign.conf,
                    "bbox": t["bbox"],
                    "track_id": t["track_id"],
                    "metadata": {
                        "source": "sign_rule",
                        "sign_class": sign.cls_name,
                    },
                })
                emitted_tracks.add(t["track_id"])

    if wcfg.get("expected_heading_deg") is None:
        return events

    W = wcfg["heading_window_frames"]
    for t in tracks:
        if t["track_id"] in emitted_tracks:
            continue
        hist = t["history"]
        if len(hist) < max(wcfg["min_track_frames"], W + 1):
            continue
        heading = _heading_deg(hist[-W - 1], hist[-1])
        delta = _angle_diff(heading, wcfg["expected_heading_deg"])
        if delta > wcfg["wrong_way_threshold_deg"]:
            events.append({
                "class_name": "wrong_way",
                "confidence": min(0.99, 0.5 + delta / 360),
                "bbox": t["bbox"],
                "track_id": t["track_id"],
                "metadata": {
                    "source": "heading_rule",
                    "delta_deg": round(delta, 1),
                    "heading_deg": round(heading, 1),
                },
            })
            emitted_tracks.add(t["track_id"])
    return events


# ═══ rule 2 — illegal_uturn ═════════════════════════════════════════════
def detect_illegal_uturn(tracks, cfg) -> list:
    ucfg = cfg["illegal_uturn"]
    fps = cfg["speeding"]["fps"]
    win = int(ucfg["window_sec"] * fps)
    events = []
    for t in tracks:
        h = t["history"]
        if len(h) < win + 1:
            continue
        early = _heading_deg(h[-win - 1], h[-win])
        late = _heading_deg(h[-2], h[-1])
        if _angle_diff(early, late) > ucfg["angle_threshold_deg"]:
            zones = ucfg.get("enabled_zones")
            if zones is not None:
                in_zone = any(_in_bbox(t["centroid"], z) for z in zones)
                if not in_zone:
                    continue
            events.append({
                "class_name": "illegal_uturn",
                "confidence": 0.85,
                "bbox": t["bbox"],
                "track_id": t["track_id"],
                "metadata": {
                    "early_heading": round(early, 1),
                    "late_heading": round(late, 1),
                },
            })
    return events


# ═══ rule 3 — speeding ══════════════════════════════════════════════════
def _pixel_to_meter(px_point, homography):
    """Transform (x, y) pixel to (X, Y) meter using 3x3 homography."""
    if homography is None:
        return None
    import numpy as np

    p = np.array([px_point[0], px_point[1], 1.0])
    w = homography @ p
    return (w[0] / w[2], w[1] / w[2])


def detect_speeding(tracks, cfg) -> list:
    scfg = cfg["speeding"]
    fps = scfg["fps"]
    W = scfg["min_track_frames"]
    events = []
    for t in tracks:
        h = t["history"]
        if len(h) < W + 1:
            continue
        p0, p1 = h[-W - 1], h[-1]

        if scfg.get("homography") is not None:
            m0 = _pixel_to_meter(p0, scfg["homography"])
            m1 = _pixel_to_meter(p1, scfg["homography"])
            if m0 is None:
                continue
            dist_m = math.hypot(m1[0] - m0[0], m1[1] - m0[1])
        else:
            dist_px = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            dist_m = dist_px * scfg["meter_per_pixel"]

        speed_mps = dist_m * fps / W
        speed_kmh = speed_mps * 3.6
        if speed_kmh > scfg["speed_limit_kmh"]:
            events.append({
                "class_name": "speeding",
                "confidence": 0.80,
                "bbox": t["bbox"],
                "track_id": t["track_id"],
                "metadata": {
                    "speed_kmh": round(speed_kmh, 1),
                    "limit_kmh": scfg["speed_limit_kmh"],
                },
            })
    return events


# ═══ rule 4 — red_light_running ═════════════════════════════════════════
_prev_centroids: dict[int, tuple] = {}


def detect_red_light(tracks, detections, cfg) -> list:
    rcfg = cfg["red_light_running"]
    global _prev_centroids
    stop_line = rcfg.get("stop_line")
    if stop_line is None:
        _prev_centroids = {t["track_id"]: t["centroid"] for t in tracks}
        return []

    reds_present = any(
        d.cls_name == "traffic_light"
        and d.state == "red"
        and (d.state_conf or 0) >= rcfg["state_conf_threshold"]
        for d in detections
    )
    events = []
    if reds_present:
        for t in tracks:
            prev = _prev_centroids.get(t["track_id"])
            if prev is None:
                continue
            if _crossed_line(prev, t["centroid"], stop_line):
                events.append({
                    "class_name": "red_light_running",
                    "confidence": 0.85,
                    "bbox": t["bbox"],
                    "track_id": t["track_id"],
                    "metadata": {"stop_line": stop_line},
                })
    _prev_centroids = {t["track_id"]: t["centroid"] for t in tracks}
    return events


# ═══ rule 5 — shoulder_driving ══════════════════════════════════════════
_shoulder_frame_count: dict[int, int] = defaultdict(int)


def detect_shoulder_driving(tracks, rightmost_solid_polyline, cfg) -> list:
    scfg = cfg["shoulder_driving"]
    fps = cfg["speeding"]["fps"]
    threshold_frames = int(scfg["sustained_sec"] * fps)
    events = []

    if rightmost_solid_polyline is None:
        _shoulder_frame_count.clear()
        return []

    active_ids = set()
    for t in tracks:
        active_ids.add(t["track_id"])
        x1, y1, x2, y2 = t["bbox"]
        foot = ((x1 + x2) / 2, y2)
        if _point_right_of_polyline(foot, rightmost_solid_polyline):
            _shoulder_frame_count[t["track_id"]] += 1
            if _shoulder_frame_count[t["track_id"]] == threshold_frames:
                events.append({
                    "class_name": "shoulder_driving",
                    "confidence": 0.82,
                    "bbox": t["bbox"],
                    "track_id": t["track_id"],
                    "metadata": {"frames_on_shoulder": threshold_frames},
                })
        else:
            _shoulder_frame_count[t["track_id"]] = 0

    for tid in list(_shoulder_frame_count):
        if tid not in active_ids:
            del _shoulder_frame_count[tid]
    return events


# ═══ rule 6 — passthrough (pothole, road_crack) ═════════════════════════
PASSTHROUGH = {"pothole", "road_crack"}


def detect_passthrough(detections) -> list:
    return [
        {
            "class_name": d.cls_name,
            "confidence": d.conf,
            "bbox": d.bbox,
            "track_id": None,
            "metadata": {},
        }
        for d in detections
        if d.cls_name in PASSTHROUGH
    ]


# ═══ location attachment (Option 1: camera-centroid GPS) ═══════════════
def _attach_location(event: dict, cfg: dict) -> dict:
    """Stamp every event with the camera's GPS coordinates."""
    cam = cfg.get("camera", {})
    event["latitude"] = cam.get("latitude")
    event["longitude"] = cam.get("longitude")
    event["camera_id"] = cam.get("camera_id")
    event.setdefault("metadata", {})["location_source"] = "camera_centroid"
    return event


# ═══ master entrypoint ══════════════════════════════════════════════════
def run_all_rules(detections, tracks, rightmost_solid_polyline, cfg) -> list:
    events = []
    emitted_tracks: set[int] = set()
    events += detect_wrong_way(tracks, detections, cfg, emitted_tracks)
    events += detect_illegal_uturn(tracks, cfg)
    events += detect_speeding(tracks, cfg)
    events += detect_red_light(tracks, detections, cfg)
    events += detect_shoulder_driving(tracks, rightmost_solid_polyline, cfg)
    events += detect_passthrough(detections)
    for ev in events:
        _attach_location(ev, cfg)
    return events
