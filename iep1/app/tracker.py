"""
iep1_app/tracker.py

Multi-object tracking wrapper. ByteTrack is primary (Zhang et al., ECCV 2022);
DeepSORT kept as fallback for A/B comparison through MLflow.

Primary tracker runs on the 'vehicle' class only. Infrastructure classes
(pothole, crack, signs, traffic_light) don't need temporal tracking — they're
static relative to the scene.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)

TRACKER_KIND: Literal["bytetrack", "deepsort"] = os.getenv(
    "IEP1_TRACKER", "bytetrack"
).lower()
HISTORY_N = 30  # centroids retained per track — enough for 1s at 30fps


# ─── ByteTrack impl (via Ultralytics built-in) ──────────────────────────
class _ByteTrackWrapper:
    def __init__(self):
        from ultralytics.trackers import BYTETracker
        from ultralytics.utils import IterableSimpleNamespace

        args = IterableSimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=0.5,
            track_low_thresh=0.1,
            new_track_thresh=0.6,
            track_buffer=30,
            match_thresh=0.8,
            fuse_score=True,
        )
        self.tracker = BYTETracker(args, frame_rate=30)

    def update(self, detections, frame):
        """detections: list of Detection objects (vehicles only)."""
        import types

        if not detections:
            empty = types.SimpleNamespace(
                xywh=np.empty((0, 4)),
                conf=np.empty(0),
                cls=np.empty(0),
                xyxy=np.empty((0, 4)),
            )
            return self.tracker.update(empty, frame)

        import torch

        xyxy = np.array([d.bbox for d in detections], dtype=np.float32)
        conf = np.array([d.conf for d in detections], dtype=np.float32)
        cls = np.zeros(len(detections), dtype=np.float32)
        xywh = np.column_stack([
            (xyxy[:, 0] + xyxy[:, 2]) / 2,
            (xyxy[:, 1] + xyxy[:, 3]) / 2,
            xyxy[:, 2] - xyxy[:, 0],
            xyxy[:, 3] - xyxy[:, 1],
        ])
        results = types.SimpleNamespace(
            xywh=torch.from_numpy(xywh),
            conf=torch.from_numpy(conf),
            cls=torch.from_numpy(cls),
            xyxy=torch.from_numpy(xyxy),
        )
        return self.tracker.update(results, frame)


# ─── DeepSORT fallback ──────────────────────────────────────────────────
class _DeepSortWrapper:
    def __init__(self):
        from deep_sort_realtime.deepsort_tracker import DeepSort

        self.tracker = DeepSort(max_age=30, n_init=3, embedder="mobilenet")

    def update(self, detections, frame):
        if not detections:
            return self.tracker.update_tracks([], frame=frame)
        ds_input = []
        for d in detections:
            x1, y1, x2, y2 = d.bbox
            ds_input.append(([x1, y1, x2 - x1, y2 - y1], d.conf, d.cls_name))
        return self.tracker.update_tracks(ds_input, frame=frame)


# ─── public API ─────────────────────────────────────────────────────────
_impl = None
_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_N))


def _get_impl():
    global _impl
    if _impl is not None:
        return _impl
    if TRACKER_KIND == "bytetrack":
        try:
            _impl = _ByteTrackWrapper()
            log.info("Using ByteTrack.")
        except Exception as e:  # noqa: BLE001
            log.warning("ByteTrack init failed (%s), falling back to DeepSORT.", e)
            _impl = _DeepSortWrapper()
    else:
        _impl = _DeepSortWrapper()
        log.info("Using DeepSORT.")
    return _impl


def reset():
    """Clear state between runs."""
    global _impl, _history
    _impl = None
    _history = defaultdict(lambda: deque(maxlen=HISTORY_N))


def update(frame_bgr: np.ndarray, vehicle_dets: list) -> list[dict]:
    """
    Advance tracker by one frame on vehicle detections only.

    Returns list of dicts: {track_id, bbox, centroid, history, cls_name}
    where history = list[(cx, cy)] in chronological order.
    """
    impl = _get_impl()
    raw = impl.update(vehicle_dets, frame_bgr)

    active = []
    # ByteTrack returns np array; DeepSORT returns list of Track objects
    if isinstance(raw, np.ndarray):
        for row in raw:
            x1 = float(row[0])
            y1 = float(row[1])
            x2 = float(row[2])
            y2 = float(row[3])
            tid = int(row[4])
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            _history[tid].append((cx, cy))
            active.append({
                "track_id": tid,
                "bbox": [x1, y1, x2, y2],
                "centroid": (cx, cy),
                "history": list(_history[tid]),
                "cls_name": "vehicle",
            })
    else:
        for t in raw:
            if not t.is_confirmed():
                continue
            tid = int(t.track_id)
            x1, y1, x2, y2 = t.to_ltrb()
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            _history[tid].append((cx, cy))
            active.append({
                "track_id": tid,
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "centroid": (float(cx), float(cy)),
                "history": list(_history[tid]),
                "cls_name": t.get_det_class() or "vehicle",
            })
    return active
