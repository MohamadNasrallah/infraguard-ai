"""
iep1_app/detector.py

Primary detection layer for IEP1. Loads two models:
  1. infraguard_v1.pt (YOLOv8m, 8 classes)
  2. tl_state_resnet18.pt (HSV color classifier for traffic_light state)

Falls back to stub mode if either weights file is missing — keeps the service
deployable in CI and during development.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ─── env config ──────────────────────────────────────────────────────────
YOLO_WEIGHTS = os.getenv("IEP1_YOLO_WEIGHTS", "/app/models/infraguard_v1.pt")
STATE_WEIGHTS = os.getenv("IEP1_STATE_WEIGHTS", "/app/models/tl_state_resnet18.pt")
IEP1_MODE = os.getenv("IEP1_MODE", "real").lower()
CONF_THRESHOLD = float(os.getenv("IEP1_CONF", "0.35"))
IOU_THRESHOLD = float(os.getenv("IEP1_IOU", "0.45"))

CLASS_NAMES = {
    0: "pothole",
    1: "road_crack",
    2: "traffic_light",
    3: "sign_no_entry",
    4: "sign_wrong_way",
    5: "vehicle",
    6: "lane_line_solid",
    7: "lane_line_dashed",
}
VEHICLE_CLS_ID = 5
TRAFFIC_LIGHT_CLS_ID = 2


# ─── Detection dataclass ────────────────────────────────────────────────
@dataclass
class Detection:
    cls_id: int
    cls_name: str
    conf: float
    bbox: list  # [x1, y1, x2, y2] absolute pixels
    state: Optional[str] = None  # 'red' | 'yellow' | 'green' | None
    state_conf: Optional[float] = None

    def to_dict(self):
        return asdict(self)

    @property
    def centroid(self):
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)


# ─── model loading ───────────────────────────────────────────────────────
_yolo = None
_state_net = None
_state_classes = None


def _load():
    global _yolo, _state_net, _state_classes
    if IEP1_MODE == "stub":
        log.warning("IEP1_MODE=stub — detector returns empty.")
        return
    try:
        from ultralytics import YOLO

        if os.path.exists(YOLO_WEIGHTS):
            _yolo = YOLO(YOLO_WEIGHTS)
            log.info("Loaded YOLO %s", YOLO_WEIGHTS)
        else:
            log.warning("YOLO weights missing (%s) — stub.", YOLO_WEIGHTS)
            return

        import torch
        import torch.nn as nn
        import torchvision.models as tvm

        if os.path.exists(STATE_WEIGHTS):
            ckpt = torch.load(STATE_WEIGHTS, map_location="cpu")
            _state_classes = ckpt.get("classes", ["red", "yellow", "green"])
            net = tvm.resnet18(weights=None)
            net.fc = nn.Linear(net.fc.in_features, len(_state_classes))
            net.load_state_dict(ckpt["state_dict"])
            net.eval()
            if torch.cuda.is_available():
                net = net.cuda()
            _state_net = net
            log.info("Loaded state classifier %s", STATE_WEIGHTS)
    except Exception as e:  # noqa: BLE001
        log.exception("Model load failed: %s", e)
        _yolo = None
        _state_net = None


_load()


# ─── traffic-light state inference ──────────────────────────────────────
def _classify_light_state(frame_bgr, bbox):
    """Crop the traffic_light bbox, convert to HSV, run ResNet-18."""
    if _state_net is None:
        return None, None
    import cv2
    import torch

    x1, y1, x2, y2 = map(int, bbox)
    x1, y1 = max(0, x1), max(0, y1)
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None, None
    crop = cv2.resize(crop, (64, 64))
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype("float32") / 255.0
    tensor = torch.from_numpy(np.transpose(hsv, (2, 0, 1))).unsqueeze(0)
    if torch.cuda.is_available():
        tensor = tensor.cuda()
    with torch.no_grad():
        logits = _state_net(tensor)
        probs = torch.softmax(logits, dim=1)[0]
        idx = probs.argmax().item()
    return _state_classes[idx], float(probs[idx])


# ─── public API ──────────────────────────────────────────────────────────
def detect(frame_bgr: np.ndarray) -> list[Detection]:
    """Run full detection on one BGR frame. Returns Detection list."""
    if _yolo is None:
        return []

    res = _yolo.predict(
        frame_bgr, conf=CONF_THRESHOLD, iou=IOU_THRESHOLD, verbose=False
    )[0]
    out: list[Detection] = []
    if res.boxes is None:
        return out

    for b in res.boxes:
        cls_id = int(b.cls[0])
        x1, y1, x2, y2 = b.xyxy[0].tolist()
        d = Detection(
            cls_id=cls_id,
            cls_name=CLASS_NAMES.get(cls_id, str(cls_id)),
            conf=float(b.conf[0]),
            bbox=[x1, y1, x2, y2],
        )
        if cls_id == TRAFFIC_LIGHT_CLS_ID:
            state, sc = _classify_light_state(frame_bgr, d.bbox)
            d.state = state
            d.state_conf = sc
        out.append(d)
    return out
