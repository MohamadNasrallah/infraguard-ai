"""
iep1_app/pipeline.py

Top-level orchestrator. Given a video path + camera config, runs:

  for each frame:
      detections  = detector.detect(frame)              # YOLO + state classifier
      vehicles    = [d for d in detections if d.cls_id == VEHICLE_CLS_ID]
      tracks      = tracker.update(frame, vehicles)
      lanes       = lane_detector.detect_lanes(frame, detections)
      events      = violations.run_all_rules(detections, tracks, rightmost_solid, cfg)
      → yield events with frame_idx + timestamp

FastAPI's POST /process handler consumes this and INSERTs into the events
table. The stub fallback is preserved: if detector.detect() returns [],
nothing downstream fires, and the service still responds 200.
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

# Absolute imports — iep1/app/ is on sys.path via uvicorn workdir
import detector
import lane_detector
import tracker
import violations

log = logging.getLogger(__name__)

VEHICLE_CLS_ID = 5

def process_video(video_path: str, camera_config_path: str,
                  run_id: str) -> Iterator[dict]:
    """Stream events one-by-one as they're detected in the video."""
    import cv2
    cfg = violations.load_config(camera_config_path)
    fps = cfg['speeding']['fps']

    tracker.reset()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.error("Failed to open %s", video_path)
        return

    video_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    cfg['speeding']['fps'] = video_fps  # override with actual

    frame_idx = 0
    t0 = time.time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = frame_idx / video_fps

            detections = detector.detect(frame)
            vehicles   = [d for d in detections if d.cls_id == VEHICLE_CLS_ID]
            tracks     = tracker.update(frame, vehicles)

            lanes = lane_detector.detect_lanes(frame, detections)
            rightmost_solid = lane_detector.rightmost_solid(lanes)

            events = violations.run_all_rules(detections, tracks, rightmost_solid, cfg)
            for ev in events:
                ev.update({
                    'run_id': run_id,
                    'frame_idx': frame_idx,
                    'timestamp': ts,
                })
                yield ev

            frame_idx += 1
    finally:
        cap.release()
        dur = time.time() - t0
        log.info('Processed %d frames in %.1fs (%.1f fps)',
                 frame_idx, dur, frame_idx / dur if dur else 0)
