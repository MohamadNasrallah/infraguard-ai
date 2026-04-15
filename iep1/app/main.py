"""IEP1 — Violation Detection Service.

Accepts a video path, produces structured ViolationEvent records, and
persists them to PostgreSQL.

Endpoints:
  POST /process  → detect violations, write events to DB, return events list
  GET  /health   → liveness probe
"""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from schemas import ProcessRequest, ProcessResponse, ViolationEvent

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
                    (id, run_id, event_id, ts, lat, lon, violation_type, severity)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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
            )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always returns 200 {"status": "ok"}."""
    return {"status": "ok"}


@app.post("/process", response_model=ProcessResponse)
async def process_video(body: ProcessRequest) -> Any:
    """Detect violations in a video and persist them to PostgreSQL.

    Stub: returns two realistic fake ViolationEvent objects.
    Real YOLO + DeepSORT logic will be slotted in during Phase 4 without
    changing this API contract.

    Args:
        body: Contains video_path and run_id.

    Returns:
        ProcessResponse with run_id and list of violation events.
    """
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
