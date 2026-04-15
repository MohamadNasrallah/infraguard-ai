"""IEP2 — Hotspot Clustering Service.

Receives violation events, clusters them into spatial hotspots, and
persists the hotspots to PostgreSQL.

Endpoints:
  POST /cluster  → cluster events, write hotspots to DB, return hotspot list
  GET  /health   → liveness probe
"""

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from schemas import ClusterRequest, ClusterResponse, Hotspot

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
            print(f"[IEP2] DB pool warning: {exc}")
    yield
    if _pool is not None:
        await _pool.close()


app = FastAPI(title="IEP2 — Hotspot Clustering", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)


async def _persist_hotspots(run_id: str, hotspots: list[Hotspot]) -> None:
    """Write hotspot records to the hotspots table.

    Args:
        run_id: Pipeline run identifier for DB correlation.
        hotspots: List of hotspot objects to persist.
    """
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        for hotspot in hotspots:
            await conn.execute(
                """
                INSERT INTO hotspots
                    (id, run_id, hotspot_id, center_lat, center_lon,
                     radius_meters, event_count, risk_score, dominant_violation)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
                """,
                str(uuid.uuid4()),
                run_id,
                hotspot.hotspot_id,
                hotspot.center["lat"],
                hotspot.center["lon"],
                hotspot.radius_meters,
                hotspot.event_count,
                hotspot.risk_score,
                hotspot.dominant_violation,
            )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always returns 200 {"status": "ok"}."""
    return {"status": "ok"}


@app.post("/cluster", response_model=ClusterResponse)
async def cluster_events(body: ClusterRequest) -> Any:
    """Cluster violation events into spatial hotspots and persist them.

    Stub: produces one hotspot centred on the mean location of the input
    events.  Real ST-DBSCAN logic will be slotted in during Phase 4 without
    changing this API contract.

    Args:
        body: Contains events list and run_id.

    Returns:
        ClusterResponse with run_id and list of hotspots.
    """
    event_count = len(body.events) or 2

    # Compute a simple centroid if events are present; fallback to a
    # realistic Beirut-area coordinate for stub runs with no events.
    if body.events:
        avg_lat = sum(e.location["lat"] for e in body.events) / event_count
        avg_lon = sum(e.location["lon"] for e in body.events) / event_count
    else:
        avg_lat, avg_lon = 33.8939, 35.5020

    dominant = body.events[0].violation_type if body.events else "red_light"

    stub_hotspots = [
        Hotspot(
            hotspot_id=f"{body.run_id[:8]}-hs-001",
            center={"lat": avg_lat, "lon": avg_lon},
            radius_meters=50.0,
            event_count=event_count,
            risk_score=0.82,
            dominant_violation=dominant,
        )
    ]

    await _persist_hotspots(body.run_id, stub_hotspots)

    return ClusterResponse(run_id=body.run_id, hotspots=stub_hotspots)
