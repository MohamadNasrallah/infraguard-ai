"""
iep1_app/lane_detector.py

Ultra-Fast-Lane-Detection wrapper (Qin et al., ECCV 2020).

We try the UFLD pretrained model first (TuSimple weights, ~6ms inference on
GPU). If unavailable, fall back to OpenCV Hough-based detection from the
YOLO lane_line_solid/lane_line_dashed bboxes produced by the primary
detector.

Output: list of 'lane polylines' (each polyline = list of (x, y) points)
tagged as 'solid' or 'dashed'. Violations.py consumes these.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

UFLD_WEIGHTS = os.getenv("IEP1_UFLD_WEIGHTS", "/app/models/ufld_tusimple.pth")


@dataclass
class Lane:
    polyline: list  # list of (x, y) pixel coords
    kind: str  # 'solid' | 'dashed' | 'unknown'
    confidence: float = 1.0


_ufld = None


def _load_ufld():
    """Attempt to load UFLD. Returns True on success."""
    global _ufld
    if not os.path.exists(UFLD_WEIGHTS):
        return False
    try:
        import torch

        _ufld = torch.load(UFLD_WEIGHTS, map_location="cpu")
        _ufld.eval()
        if torch.cuda.is_available():
            _ufld = _ufld.cuda()
        log.info("UFLD loaded from %s", UFLD_WEIGHTS)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("UFLD load failed: %s", e)
        return False


_UFLD_OK = _load_ufld()


# ─── UFLD inference ─────────────────────────────────────────────────────
def _detect_ufld(frame_bgr):
    """Placeholder — plug your UFLD repo's inference path here.
    For capstone scope we use the fallback unless you've wired UFLD locally."""
    return None


# ─── Fallback: derive polylines from YOLO lane_line bboxes ──────────────
def _fit_line_from_bbox(bbox):
    """Given a bbox around a lane segment, return its likely direction polyline."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w >= h:
        return [(x1, (y1 + y2) / 2), (x2, (y1 + y2) / 2)]
    return [((x1 + x2) / 2, y1), ((x1 + x2) / 2, y2)]


def detect_lanes(frame_bgr, yolo_detections=None):
    """
    Returns list[Lane]. Use yolo_detections to leverage the lane_line_solid /
    lane_line_dashed classes from the main detector when UFLD isn't available.
    """
    if _UFLD_OK:
        lanes = _detect_ufld(frame_bgr)
        if lanes is not None:
            return lanes

    if yolo_detections is None:
        return []

    lanes = []
    for d in yolo_detections:
        if d.cls_name not in {"lane_line_solid", "lane_line_dashed"}:
            continue
        poly = _fit_line_from_bbox(d.bbox)
        kind = "solid" if d.cls_name == "lane_line_solid" else "dashed"
        lanes.append(Lane(polyline=poly, kind=kind, confidence=d.conf))
    return lanes


def rightmost_solid(lanes: list[Lane]):
    """Return the polyline of the rightmost solid lane (or None)."""
    solids = [lane for lane in lanes if lane.kind == "solid"]
    if not solids:
        return None

    def max_x(lane):
        return max(p[0] for p in lane.polyline)

    return max(solids, key=max_x).polyline
