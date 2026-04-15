"""EEP — External Entry Point.

Orchestrates the full InfraGuard pipeline:
  POST /run        → trigger pipeline (IEP1 → IEP2 → IEP3), persist run record
  GET  /status/{run_id} → check pipeline run status from DB
  GET  /reports    → list completed reports from DB
  GET  /health     → liveness probe
"""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import db
from orchestrator import PipelineStepError, call_iep1, call_iep2, call_iep3

IEP1_URL = os.getenv("IEP1_URL", "http://localhost:8002")
IEP2_URL = os.getenv("IEP2_URL", "http://localhost:8003")
IEP3_URL = os.getenv("IEP3_URL", "http://localhost:8004")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_migrations() -> None:
    """Apply any pending Alembic migrations synchronously.

    Called once during application startup before the asyncpg pool is opened.
    Uses psycopg2 (sync driver) via SQLAlchemy, which is the standard Alembic
    approach.  The DATABASE_URL env var is picked up inside env.py.
    """
    cfg_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
    alembic_cfg = AlembicConfig(cfg_path)
    alembic_command.upgrade(alembic_cfg, "head")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Run migrations and open the DB pool on startup; close it on shutdown."""
    if db.DATABASE_URL:
        try:
            _run_migrations()
        except Exception as exc:  # noqa: BLE001
            # Log but do not crash — allows the service to start in degraded
            # mode during local dev without a running Postgres instance.
            print(f"[EEP] Migration warning: {exc}")
        try:
            await db.init_pool()
        except Exception as exc:  # noqa: BLE001
            print(f"[EEP] DB pool warning: {exc}")
    yield
    await db.close_pool()


app = FastAPI(title="EEP — InfraGuard Orchestrator", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Request body for POST /run."""

    video_path: str = "default.mp4"


class RunResponse(BaseModel):
    """Response body for POST /run."""

    run_id: str
    pdf_url: str


class RunStatus(BaseModel):
    """Response body for GET /status/{run_id}."""

    run_id: str
    status: str
    video_path: str
    started_at: str
    completed_at: str | None
    pdf_url: str | None


class ReportEntry(BaseModel):
    """Single entry in GET /reports response."""

    run_id: str
    pdf_url: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always returns 200 {"status": "ok"}."""
    return {"status": "ok"}


@app.post("/run", response_model=RunResponse)
async def run_pipeline(body: RunRequest) -> Any:
    """Trigger the full pipeline: IEP1 → IEP2 → IEP3.

    1. Inserts a pipeline_run row with status=RUNNING.
    2. Calls IEP1 (violation detection), IEP2 (clustering), IEP3 (report).
    3. On success: updates status to DONE, stores pdf_url, inserts reports row.
    4. On failure: updates status to FAILED and returns 502.
    """
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    pool = None
    try:
        pool = db.get_pool()
    except RuntimeError:
        # No DB available (e.g. local dev without Postgres).
        pass

    if pool is not None:
        await pool.execute(
            """
            INSERT INTO pipeline_runs (id, status, video_path, started_at)
            VALUES ($1, 'RUNNING', $2, $3)
            """,
            run_id,
            body.video_path,
            now,
        )

    try:
        async with httpx.AsyncClient() as client:
            events = await call_iep1(client, IEP1_URL, run_id, body.video_path)
            hotspots = await call_iep2(client, IEP2_URL, run_id, events)
            pdf_url = await call_iep3(client, IEP3_URL, run_id, hotspots, events)
    except PipelineStepError as exc:
        if pool is not None:
            await pool.execute(
                """
                UPDATE pipeline_runs
                SET status = 'FAILED', completed_at = $1
                WHERE id = $2
                """,
                datetime.now(timezone.utc),
                run_id,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    completed_at = datetime.now(timezone.utc)

    if pool is not None:
        await pool.execute(
            """
            UPDATE pipeline_runs
            SET status = 'DONE', completed_at = $1, pdf_url = $2
            WHERE id = $3
            """,
            completed_at,
            pdf_url,
            run_id,
        )
        await pool.execute(
            """
            INSERT INTO reports (id, run_id, pdf_url, created_at)
            VALUES ($1, $2, $3, $4)
            """,
            str(uuid.uuid4()),
            run_id,
            pdf_url,
            completed_at,
        )

    return RunResponse(run_id=run_id, pdf_url=pdf_url)


@app.get("/status/{run_id}", response_model=RunStatus)
async def get_status(run_id: str) -> Any:
    """Return the current status of a pipeline run.

    Args:
        run_id: UUID of the pipeline run.

    Raises:
        HTTPException 503: DB pool not available.
        HTTPException 404: run_id not found.
    """
    try:
        pool = db.get_pool()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DB unavailable") from exc

    row = await pool.fetchrow(
        "SELECT id, status, video_path, started_at, completed_at, pdf_url "
        "FROM pipeline_runs WHERE id = $1",
        run_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")

    return RunStatus(
        run_id=row["id"],
        status=row["status"],
        video_path=row["video_path"],
        started_at=row["started_at"].isoformat(),
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
        pdf_url=row["pdf_url"],
    )


@app.get("/reports", response_model=list[ReportEntry])
async def list_reports() -> Any:
    """Return all completed reports ordered by most recent first.

    Raises:
        HTTPException 503: DB pool not available.
    """
    try:
        pool = db.get_pool()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DB unavailable") from exc

    rows = await pool.fetch(
        "SELECT run_id, pdf_url, created_at FROM reports ORDER BY created_at DESC"
    )
    return [
        ReportEntry(
            run_id=row["run_id"],
            pdf_url=row["pdf_url"],
            created_at=row["created_at"].isoformat(),
        )
        for row in rows
    ]
