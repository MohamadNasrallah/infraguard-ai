# IEP1 — Model Integration Plan

> **Scope.** This document is the single source of truth for the IEP1 video-detection pipeline.
> It tracks what we're building, which datasets we use, how we train, and how the model gets
> slotted behind the existing FastAPI contract without breaking anything downstream.
>
> **Status.** Infrastructure and API contract are complete. Real model not yet integrated — this
> plan covers exactly that work.
>
> **Owner.** Mohamad Nasrallah
> **Last updated.** 2026-04-18

---

## 1. What IEP1 actually does

IEP1 is the video-ingestion-and-detection service. Its job is to take a video path, run
detection + tracking on it, and emit a list of violation events with spatiotemporal metadata.
Everything downstream (IEP2 clustering, IEP3 reporting) assumes this shape.

**Fixed API contract (do not change).**

```
POST /process
{
  "video_path": "...",
  "run_id": "..."
}

→ events[] written to PostgreSQL `events` table:
    { run_id, frame_idx, timestamp, class_name, confidence,
      bbox: [x, y, w, h], track_id, latitude, longitude }
```

The real model replaces the stub that currently writes hardcoded events. Nothing else moves.

---

## 2. Classes and how each one is actually detected

Not every class is a YOLO image-classification label. IEP1 is a **multi-layer detection
stack** where each layer is responsible for a different kind of signal, and the classes are
distributed across those layers. Getting this right up front prevents wasted labeling effort
and makes the whole downstream design make sense.

### 2.1 The four layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1 — YOLOv8 (single-frame visual detection)               │
│    Detects: pothole, road_crack, shoulder_lane, traffic_light   │
│    Output:  bboxes with class + confidence                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 2 — DeepSORT (multi-frame tracking)                      │
│    Assigns stable track_id to every detected vehicle.           │
│    Output: trajectories (sequence of bboxes over frames)        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 3 — Trajectory rules (motion-based violations)           │
│    wrong_way:    track heading vector opposes configured         │
│                  lane-flow direction by > threshold degrees      │
│    illegal_uturn: heading change > 150° within 3s               │
│    speeding:     pixel displacement × m/px × fps > threshold    │
│    Output: events tagged with track_id                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 4 — Stateful rules (context-dependent violations)        │
│    red_light_running: track crosses stop-line polygon while     │
│                       Layer 1's traffic_light.state == red      │
│    Output: events tagged with track_id                          │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    All layers write rows to
                    the `events` table, each
                    tagged with run_id + track_id
```

### 2.2 Classes by layer

| # | Class              | Layer               | Source of truth                       |
|---|--------------------|---------------------|---------------------------------------|
| 1 | pothole            | 1 (YOLO visual)     | RDD2022                               |
| 2 | road_crack         | 1 (YOLO visual)     | RDD2022                               |
| 3 | shoulder_lane      | 1 (YOLO visual)     | Self-labeled frames                   |
| 4 | normal (negative)  | 1 (YOLO visual)     | RDD2022 negative samples              |
| 5 | traffic_light      | 1 (YOLO visual)     | Roboflow traffic-light datasets       |
| 6 | wrong_way          | 3 (trajectory rule) | Pure rule — no dataset needed         |
| 7 | illegal_uturn      | 3 (trajectory rule) | Pure rule — no dataset needed         |
| 8 | speeding           | 3 (trajectory rule) | Pure rule — no dataset needed         |
| 9 | red_light_running  | 4 (stateful rule)   | Pure rule — no dataset needed         |

**Key insight.** Layer 1 trains on **5 visual classes** (pothole, crack, shoulder_lane,
normal, traffic_light). Layers 3 and 4 are code, not models — they need zero training data,
just correct rule logic. That's **5 YOLO classes to label and train**, not 9.

### 2.3 Wrong-way detection — how it actually works

Wrong-way is a **temporal, motion-based phenomenon**. A single video frame cannot tell you
whether a vehicle is going the wrong way — direction of movement only emerges across
multiple frames. This is why the violation lives at the DeepSORT layer, not the YOLO layer.

The standard approach in the literature (YOLO + DeepSORT for traffic violation detection)
follows this exact pattern: YOLO handles object detection, DeepSORT builds trajectories,
and a heading rule interprets those trajectories. No separate classifier is trained for
wrong-way specifically.

**Detection logic:**

```
For each active DeepSORT track with length ≥ MIN_TRACK_FRAMES:

  1. Compute smoothed heading:
       displacement = centroid(frame[T]) - centroid(frame[T - WINDOW])
       heading_deg  = atan2(displacement.y, displacement.x) in degrees

  2. Load expected lane direction from camera_config.json:
       expected_heading_deg = zone config for this camera/road segment

  3. Compute angular difference:
       delta = abs((heading_deg - expected_heading_deg + 180) % 360 - 180)

  4. Flag as wrong_way if:
       delta > WRONG_WAY_THRESHOLD_DEG   # default: 120°
```

**Key parameters (all in `camera_config.json`):**

| Parameter                  | Default | Notes                                              |
|----------------------------|---------|----------------------------------------------------|
| `expected_heading_deg`     | —       | Required per zone. 0° = east, 90° = north, etc.   |
| `heading_tolerance_deg`    | 30°     | Acceptable deviation from expected heading         |
| `wrong_way_threshold_deg`  | 120°    | Angle at which a track is flagged wrong-way        |
| `min_track_frames`         | 10      | Minimum frames before heading is computed          |
| `heading_window_frames`    | 10      | Frames over which displacement is averaged         |

**Why these parameters:**
- `min_track_frames = 10` gates out vehicles that just entered the frame — too few points
  to compute a reliable heading vector.
- `heading_window_frames = 10` smooths over bounding-box jitter from DeepSORT. Computing
  heading from consecutive frames (T vs T-1) is too noisy. Displacement over 10 frames
  is stable.
- `wrong_way_threshold_deg = 120°` means the vehicle must be moving at least 60° past
  perpendicular to the expected flow — i.e., clearly opposing traffic, not just taking a
  slight diagonal path.

**Where the ML is:**
- YOLOv8 extracts per-frame spatial features (vehicle location and class) — this is ML.
- DeepSORT uses a Kalman filter + Hungarian algorithm to associate detections across frames
  into stable trajectories — this is ML.
- The heading rule interprets the trajectory output — this is the decision boundary,
  equivalent to a threshold on a softmax score. The ML work is in the layers beneath it.

This mirrors how every production traffic enforcement system works: the ML detects and
tracks, a rule interprets the result. The violation classification being rule-based does
not make the pipeline non-ML.

### 2.4 Multi-violation handling

A single tracked vehicle (`track_id`) can trigger multiple independent events in the same
run — e.g., `wrong_way` + `speeding` + `red_light_running`. Each rule emits its own row in
the `events` table. IEP2's clustering operates on events, not on vehicles, so correlated
violations at the same spatiotemporal point naturally cluster into the same hotspot. No
deduplication needed; no "combined class" needed.

Aggregate statistics like "N vehicles committed ≥2 violations in this run" are computed at
query time in IEP3 (single `GROUP BY track_id` query), not baked into the model.

---

## 3. Data sources (verified, with URLs)

### 3.1 RDD2022 — potholes + road cracks (primary dataset)

- **What.** 47,420 road images from 6 countries (Japan, India, Czech Republic, Norway,
  US, China), with ~55,000 labeled instances across 4 damage types (D00 longitudinal crack,
  D10 transverse crack, D20 alligator crack, D40 pothole).
- **Why this one.** It is the benchmark dataset used in peer-reviewed RDD research (CRDDC
  2022 challenge). Multi-country diversity means better generalization to dashcam footage.
- **URL.** `https://github.com/sekilab/RoadDamageDetector`
- **License.** Open (CC BY-style, cite the paper).
- **Format.** PascalVOC XML — requires one conversion script to YOLOv8 format.
- **Ready-made converter.** `https://github.com/oracl4/RoadDamageDetection` has a notebook
  `0_PrepareDatasetYOLOv8.ipynb` that converts PascalVOC → YOLOv8 and splits train/val.
- **Our class mapping.**
  - D00, D10, D20 → merged into `road_crack` (class ID 1)
  - D40 → `pothole` (class ID 0)
- **Recommended subset.** US + Japan subsets only (~20k images) — enough for training, less
  noise from country-specific road quirks.

### 3.2 Traffic light detection — Roboflow

- **What.** Several 2–8k-image datasets labeling traffic lights as red/yellow/green.
- **URL.** Search `https://universe.roboflow.com/` for "traffic light detection YOLOv8".
  The current best options (validate before download):
  - `traffic-light-detection-kmhxj` (~7k images)
  - `traffic-and-road-signs` (has light state + signs)
- **How we use it.** YOLO detects the light state. Red-light-running logic: if a tracked
  vehicle crosses a virtual stop-line polygon while the light is red → emit a
  `red_light_running` event. The virtual stop line is drawn on the video once, per-camera.

### 3.3 Self-labeled footage — illegal U-turn + shoulder lane

No clean public dataset exists for these two. The honest path:
- Extract **~100–150 frames** per class from your raw dashcam/CCTV footage.
- Label them in Roboflow's free tier (their annotator is very fast).
- Merge into the final dataset.
- This becomes a talking point for Dr. Ammar: **real, project-specific data collection**
  demonstrates initiative beyond off-the-shelf datasets.

**Labeling budget.** ~2 hours for both classes combined. Do not over-invest here.

---

## 4. What speeding actually is (no dataset needed)

Speeding is not a thing YOLO can see in a single frame. It is computed from how fast a
tracked object moves across pixels, converted to meters/second using a camera calibration
factor. The math:

```
speed_mps = (displacement_pixels × meter_per_pixel) × fps / n_frames
speed_kmh = speed_mps × 3.6
```

**Implementation.** Ultralytics ships `solutions.SpeedEstimator` out of the box:

```python
from ultralytics import solutions

estimator = solutions.SpeedEstimator(
    model="infraguard_v1.pt",
    fps=30,
    meter_per_pixel=0.05,   # calibrate per camera
    max_speed=180,          # outlier cap
)
```

**Calibration.** `meter_per_pixel` is measured from a known reference in the video
(e.g., a lane marking known to be 3 meters wide, divided by its pixel width). Document the
calibration value per camera/video in a `camera_config.json`.

**Threshold.** If `speed_kmh > 80` (configurable), emit a `speeding` event with the tracked
vehicle's bbox and the computed speed in the event metadata.

---

## 5. Final merged dataset

After collecting all sources:

```
data/
  train/
    images/
    labels/
  val/
    images/
    labels/
  test/
    images/
    labels/
  data.yaml
```

**`data.yaml`:**

```yaml
path: /content/drive/MyDrive/infraguard/data
train: train/images
val:   val/images
test:  test/images

names:
  0: pothole
  1: road_crack
  2: shoulder_lane
  3: traffic_light   # used by Layer 4 rule (red_light_running)
  4: normal          # optional negative class

nc: 5
```

> Note: `wrong_way`, `illegal_uturn`, `speeding`, and `red_light_running` are **not** in
> `data.yaml`. They are not YOLO classes — they are computed by the Layer 3 and Layer 4
> rules at inference time, using track_ids and (for red-light) the detected
> `traffic_light` state.

**Class remapping.** Each source dataset uses its own class IDs. A merge script
(`scripts/merge_datasets.py`) reads each dataset's `data.yaml`, remaps class IDs to the
unified scheme above, and copies images + rewritten label files into the merged tree.

**Target dataset size.** ~15–25k images after merging. Don't chase size — chase balance:
roughly comparable sample counts per class, not 20k potholes and 200 shoulder-lane.

**Split.** 70 / 20 / 10 (train / val / test). Use a fixed random seed in the merge script
for reproducibility.

---

## 6. Training plan

### 6.1 Environment

- **Platform.** Google Colab (free or Pro tier — Pro recommended for the final run).
- **GPU.** T4 is enough; A100 if Pro+ is available (cuts time by ~3x).
- **Framework.** Ultralytics YOLOv8 (`pip install ultralytics`).
- **Base weights.** `yolov8m.pt` (medium). Balances accuracy vs. inference speed on CPU
  for the IEP1 container.

### 6.2 Command

```bash
yolo detect train \
  data=data.yaml \
  model=yolov8m.pt \
  epochs=100 \
  imgsz=640 \
  batch=16 \
  patience=20 \
  project=infraguard \
  name=v1 \
  save=True \
  device=0
```

### 6.3 What to watch during training

- **mAP@0.5** on val set should climb past 0.5 by epoch 30, 0.6+ by epoch 60.
- Per-class mAP — if one class collapses (e.g., shoulder_lane stuck at 0.1), it means the
  labels are too few or inconsistent. Fix the data, re-train. Do not tune hyperparameters
  to rescue bad labels.
- Early-stopping `patience=20` — training will stop if val loss doesn't improve for 20
  epochs. This is fine.

### 6.4 Output

`runs/detect/v1/weights/best.pt` → rename to `infraguard_v1.pt` and save to Google Drive
immediately. Also upload to MLflow (the promotion logic already implemented in Phase 2).

---

## 7. Integrating the model into IEP1

The entire point of the Phase 2 stub-first design was that this is a drop-in replacement.
The API contract does not change.

### 7.1 File-level changes

```
iep1/
  app/
    main.py           # unchanged — FastAPI routes stay identical
    detector.py       # REPLACE stub with real YOLO + DeepSORT
    tracker.py        # NEW — DeepSORT wrapper
    violations.py     # NEW — per-class post-processing logic
    camera_config.json # NEW — expected_heading_deg, stop_lines per camera
  models/
    infraguard_v1.pt  # from training; loaded at container startup
  requirements.txt    # add: ultralytics, deep-sort-realtime
```

### 7.2 Flow inside `POST /process`

```
1. Load video from video_path
2. For each frame:
   a. YOLO inference → detections (pothole, road_crack, shoulder_lane, traffic_light)
   b. DeepSORT update → stable track_ids for vehicles
   c. Post-processing:
      - red_light_running: tracked vehicle + red light + crosses stop-line polygon
      - wrong_way: smoothed track heading vs. expected_heading_deg from camera_config
      - illegal_uturn: track describes a U-shape within N seconds
      - speeding: displacement × meter_per_pixel × fps
3. For each detected event:
   INSERT INTO events (run_id, frame_idx, timestamp, class_name,
                       confidence, bbox, track_id, latitude, longitude)
4. Return 200 OK with count of events emitted.
```

### 7.3 Graceful fallback (keep the stub alive)

Add an environment variable `IEP1_MODE = real | stub`. If `real` and the model file can't
be loaded (e.g., weights missing in dev), log a warning and fall back to the stub. This
keeps CI green even if the `.pt` file is not committed (which it shouldn't be — it's too
large for git, use DVC or a download step in the Dockerfile).

### 7.4 Docker hygiene

- Do **not** bake `infraguard_v1.pt` into the image. Mount it via volume in docker-compose,
  or pull from a signed URL at container startup.
- `ultralytics` pulls torch + torchvision which are large. Use `python:3.11-slim` and
  accept the image size increase (~2.5GB). Document this tradeoff in `docs/tradeoffs.md`.

### 7.5 CI stays on stub

Do not run real inference in CI. CI runs with `IEP1_MODE=stub`. Keep integration tests
fast and deterministic. Real-model validation happens in a separate workflow or manual
demo script.

---

## 8. 10-day timeline (from today)

> This is the concrete day-by-day plan. Adjust as reality bites.

| Day | Work |
|-----|------|
| 1   | Download RDD2022 (US + Japan subsets). Run PascalVOC → YOLOv8 conversion. Verify label correctness by visualizing 20 random bboxes. |
| 2   | Download traffic light dataset from Roboflow. Extract 100–150 frames from own footage for illegal_uturn + shoulder_lane. |
| 3   | Label self-captured frames in Roboflow. Write `scripts/merge_datasets.py`. Run merge, produce final `data.yaml`. Visualize 30 random samples from merged set. |
| 4   | Training run on Colab (100 epochs, yolov8m). Save `infraguard_v1.pt` to Drive. Log metrics to MLflow. |
| 5   | Integrate YOLO into `iep1/app/detector.py`. Wire DeepSORT tracker. Keep the stub fallback working. |
| 6   | Implement `violations.py`: red-light, wrong-way heading rule, illegal-uturn, speeding. Write `camera_config.json` with expected headings and calibration. Unit tests for each rule. |
| 7   | Run end-to-end on a real video locally. Verify events flow through to IEP2 → IEP3 → PDF. Fix whatever breaks. |
| 8   | Frontend dashboard polish (map + reports list). Verify Grafana shows real metrics. |
| 9   | Demo rehearsal. Walk through `readme_correction.md` rubric-by-rubric. Patch gaps. |
| 10  | Buffer. Something will break. Use this day. |

---

## 9. Risks and explicit tradeoffs

- **Risk: real YOLO is slow on CPU.** A 1-minute video at 30fps is 1800 frames; yolov8m on
  CPU is ~2 fps → 15 minutes per video. Acceptable for a demo, not production.
  **Mitigation.** Document this in `docs/tradeoffs.md`. Offer a "sampled mode" (1 frame per
  second) for long videos. GPU deployment is out of scope for this capstone.

- **Risk: self-labeled data is noisy.** 150 hand-labeled frames in one afternoon will have
  inconsistencies. **Mitigation.** Accept lower per-class mAP for shoulder_lane and
  illegal_uturn. Do not over-optimize. The integration story matters more than a 0.05
  mAP gain.

- **Risk: camera calibration (`meter_per_pixel`) is wrong.** Speed estimates will be off by
  whatever factor the calibration is off. **Mitigation.** Calibrate against a known lane
  marking in each video. Document the process in `camera_config.json`. Treat speed values
  as relative, not absolute.

- **Risk: wrong-way heading is misconfigured.** If `expected_heading_deg` is set wrong for
  a zone, all vehicles on that road will be flagged or none will. **Mitigation.** Validate
  the config by running on a known-clean clip (no wrong-way vehicles) and asserting zero
  wrong-way events. Document this validation step in the demo script.

- **Risk: integration breaks something downstream.** The whole stub-first design is
  supposed to prevent this. **Mitigation.** E2E test (already written) stays as the
  contract check. If it breaks, the real model broke the contract — revert to stub,
  re-check the output schema.

---

## 10. Definition of done

IEP1 is complete when, in order:

1. `infraguard_v1.pt` exists and has mAP@0.5 > 0.5 on val set.
2. `iep1/app/detector.py` loads the real model at startup with stub fallback.
3. `POST /process` on a real 30-second video produces ≥ 5 events across ≥ 2 classes,
   written to PostgreSQL.
4. The same run_id flows through IEP2 → IEP3 and produces a PDF naming real events.
5. Grafana shows request rate + inference latency for IEP1.
6. `docs/tradeoffs.md` documents the CPU-inference, calibration, self-label, and
   wrong-way heading risks.
7. `readme_correction.md` points at `iep1/app/detector.py` and this plan file as evidence
   of the model-integration rubric component.

---

## 11. Progress log

> Update this section as work proceeds. One line per session.

- 2026-04-18: Wrong-way detection approach finalized — pure YOLO+DeepSORT+heading rule,
  no separate classifier or labeled dataset. Roboflow wrong-way dataset dropped.
  Section 2.3 added with full detection logic and parameter table. Tradeoffs documented.