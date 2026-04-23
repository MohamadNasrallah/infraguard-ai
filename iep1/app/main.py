"""IEP1 — Violation Detection Service.

Accepts a video path, produces structured ViolationEvent records, and
persists them to PostgreSQL.

Endpoints:
  POST /process  → detect violations, write events to DB, return events list
  GET  /health   → liveness probe
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from schemas import ProcessRequest, ProcessResponse, ViolationEvent

log = logging.getLogger(__name__)

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Open the asyncpg pool on startup and close it on shutdown."""
    global _pool
    if DATABASE_URL:
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        except Exception as exc:  # noqa: BLE001
            print(f"[IEP1] DB pool warning: {exc}")
    yield
    if _pool is not None:
        await _pool.close()


app = FastAPI(title="IEP1 — Violation Detection", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)


async def _persist_events(run_id: str, events: list[ViolationEvent]) -> None:
    """Write violation events to the events table.

    Args:
        run_id: Pipeline run identifier for DB correlation.
        events: List of detected violation events to persist.
    """
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        for event in events:
            await conn.execute(
                """
                INSERT INTO events
                    (id, run_id, event_id, ts, lat, lon, violation_type, severity,
                     camera_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
                """,
                str(uuid.uuid4()),
                run_id,
                event.event_id,
                datetime.fromisoformat(
                    event.timestamp.replace("Z", "+00:00")
                ),
                event.location["lat"],
                event.location["lon"],
                event.violation_type,
                event.severity,
                event.camera_id,
            )


def _conf_to_severity(conf: float) -> str:
    if conf >= 0.85:
        return "high"
    if conf >= 0.65:
        return "medium"
    return "low"


async def _run_real_pipeline(
    video_path: str,
    run_id: str,
    camera_config_path: str,
    pool: asyncpg.Pool | None,
) -> list[ViolationEvent]:
    """Lazy-import pipeline, run inference, batch-insert to DB, return events.

    Raises on any failure so the caller can fall back to stub.
    """
    try:
        import pipeline as _pipeline  # noqa: PLC0415 — intentional lazy import
    except ImportError as exc:
        log.warning(
            "[IEP1] pipeline import failed (%s) — caller will fall back to stub.", exc
        )
        raise

    raw_events = list(_pipeline.process_video(video_path, camera_config_path, run_id))

    violation_events: list[ViolationEvent] = [
        ViolationEvent(
            event_id=(
                f"{run_id[:8]}-f{ev['frame_idx']:06d}"
                f"-t{ev.get('track_id') or 'x'}"
            ),
            timestamp=datetime.fromtimestamp(
                float(ev["timestamp"]), tz=timezone.utc
            ).isoformat(),
            location={
                "lat": ev.get("latitude") or 0.0,
                "lon": ev.get("longitude") or 0.0,
            },
            violation_type=ev["class_name"],
            severity=_conf_to_severity(float(ev.get("confidence", 0.5))),
            camera_id=ev.get("camera_id"),
        )
        for ev in raw_events
    ]

    if pool is not None and violation_events:
        rows = [
            (
                str(uuid.uuid4()),
                run_id,
                ev.event_id,
                datetime.fromisoformat(ev.timestamp),
                ev.location["lat"],
                ev.location["lon"],
                ev.violation_type,
                ev.severity,
                ev.camera_id,
            )
            for ev in violation_events
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO events
                    (id, run_id, event_id, ts, lat, lon, violation_type, severity,
                     camera_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )

    return violation_events


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always returns 200 {"status": "ok"}."""
    return {"status": "ok"}


@app.post("/process", response_model=ProcessResponse)
async def process_video(body: ProcessRequest) -> Any:
    """Detect violations in a video and persist them to PostgreSQL.

    Stub (default): returns two realistic fake ViolationEvent objects.
    Real (IEP1_MODE=real): calls pipeline.process_video() with lazy imports;
    falls back to stub on any failure so the service never returns 500.

    Args:
        body: Contains video_path and run_id.

    Returns:
        ProcessResponse with run_id and list of violation events.
    """
    mode = os.getenv("IEP1_MODE", "stub").lower()
    if mode not in {"stub", "real"}:
        log.warning("[IEP1] Unknown IEP1_MODE=%s — falling back to stub.", mode)
        mode = "stub"

    if mode == "real":
        camera_config = os.getenv(
            "IEP1_CAMERA_CONFIG", "/app/configs/camera_config.json"
        )
        try:
            events = await _run_real_pipeline(
                body.video_path, body.run_id, camera_config, _pool
            )
            return ProcessResponse(run_id=body.run_id, events=events)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "[IEP1] Real pipeline failed (%s) — falling back to stub.", exc
            )

    stub_events = [
        ViolationEvent(
            event_id=f"{body.run_id[:8]}-evt-001",
            timestamp="2026-04-13T08:00:00Z",
            location={"lat": 33.8938, "lon": 35.5018},
            violation_type="red_light",
            severity="high",
        ),
        ViolationEvent(
            event_id=f"{body.run_id[:8]}-evt-002",
            timestamp="2026-04-13T08:05:30Z",
            location={"lat": 33.8941, "lon": 35.5022},
            violation_type="speeding",
            severity="medium",
        ),
    ]

    await _persist_events(body.run_id, stub_events)

    return ProcessResponse(run_id=body.run_id, events=stub_events)
