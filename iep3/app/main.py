"""IEP3 — Report Generation Service.

Receives hotspots and events, loads a versioned LLM prompt, generates a PDF
safety report, and persists the report reference to PostgreSQL.

Endpoints:
  POST /generate  → generate report, write to DB, return pdf_url
  GET  /health    → liveness probe
"""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException

from prompt_manager import load_prompt
from schemas import GenerateRequest, GenerateResponse

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
            print(f"[IEP3] DB pool warning: {exc}")
    yield
    if _pool is not None:
        await _pool.close()


app = FastAPI(title="IEP3 — Report Generation", lifespan=lifespan)


async def _persist_report(run_id: str, pdf_url: str) -> None:
    """Write the report record to the reports table.

    Args:
        run_id: Pipeline run identifier for DB correlation.
        pdf_url: URL of the generated PDF report.
    """
    if _pool is None:
        return
    await _pool.execute(
        """
        INSERT INTO reports (id, run_id, pdf_url, created_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        """,
        str(uuid.uuid4()),
        run_id,
        pdf_url,
        datetime.now(timezone.utc),
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always returns 200 {"status": "ok"}."""
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
async def generate_report(body: GenerateRequest) -> Any:
    """Generate a PDF safety report from hotspots and events.

    Loads the active versioned prompt via prompt_manager, then:
    Stub: returns a deterministic fake pdf_url based on run_id.
    Real LLM call + ReportLab PDF rendering will be slotted in during
    Phase 4 without changing this API contract.

    Args:
        body: Contains hotspots, events, and run_id.

    Returns:
        GenerateResponse with pdf_url.

    Raises:
        HTTPException 500: If the prompt file for the configured version
                           cannot be found.
    """
    try:
        _prompt = load_prompt()  # validates prompt file exists; used in Phase 4
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    hotspot_count = len(body.hotspots)
    event_count = len(body.events)
    pdf_url = (
        f"https://reports.infraguard.local/runs/{body.run_id}"
        f"/report_{hotspot_count}hs_{event_count}ev.pdf"
    )

    await _persist_report(body.run_id, pdf_url)

    return GenerateResponse(pdf_url=pdf_url)
