"""Pipeline orchestrator — sequences IEP1 → IEP2 → IEP3 with retry + circuit-breaker.

Each IEP call is wrapped with tenacity:
  - 3 attempts total
  - Exponential back-off: 1 s → 2 s → 4 s (capped at 10 s)

If all retries are exhausted, PipelineStepError is raised.  The caller
(EEP /run handler) catches it, marks the pipeline_run as FAILED in
PostgreSQL, and returns a structured 502 error to the client.
"""

import httpx
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
)


class PipelineStepError(Exception):
    """Raised when an IEP call fails after all retry attempts."""

    def __init__(self, step: str, cause: Exception) -> None:
        """Record which pipeline step failed and the underlying cause."""
        self.step = step
        self.cause = cause
        super().__init__(f"{step} failed after retries: {cause}")


def _make_retry_decorator():  # type: ignore[return]
    """Return a tenacity retry decorator with the standard IEP policy."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )


async def call_iep1(
    client: httpx.AsyncClient,
    iep1_url: str,
    run_id: str,
    video_path: str,
) -> list[dict]:
    """Call IEP1 /process with retry logic.

    Args:
        client: Shared AsyncClient instance.
        iep1_url: Base URL of the IEP1 service.
        run_id: Pipeline run identifier to correlate DB records.
        video_path: Path to the video file to process.

    Returns:
        List of violation event dicts returned by IEP1.

    Raises:
        PipelineStepError: If IEP1 fails after all retry attempts.
    """

    @_make_retry_decorator()
    async def _attempt() -> list[dict]:
        r = await client.post(
            f"{iep1_url}/process",
            json={"video_path": video_path, "run_id": run_id},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("events", [])

    try:
        return await _attempt()
    except (RetryError, Exception) as exc:
        raise PipelineStepError("IEP1", exc) from exc


async def call_iep2(
    client: httpx.AsyncClient,
    iep2_url: str,
    run_id: str,
    events: list[dict],
) -> list[dict]:
    """Call IEP2 /cluster with retry logic.

    Args:
        client: Shared AsyncClient instance.
        iep2_url: Base URL of the IEP2 service.
        run_id: Pipeline run identifier.
        events: Violation events returned by IEP1.

    Returns:
        List of hotspot dicts returned by IEP2.

    Raises:
        PipelineStepError: If IEP2 fails after all retry attempts.
    """

    @_make_retry_decorator()
    async def _attempt() -> list[dict]:
        r = await client.post(
            f"{iep2_url}/cluster",
            json={"events": events, "run_id": run_id},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("hotspots", [])

    try:
        return await _attempt()
    except (RetryError, Exception) as exc:
        raise PipelineStepError("IEP2", exc) from exc


async def call_iep3(
    client: httpx.AsyncClient,
    iep3_url: str,
    run_id: str,
    hotspots: list[dict],
    events: list[dict],
) -> str:
    """Call IEP3 /generate with retry logic.

    Args:
        client: Shared AsyncClient instance.
        iep3_url: Base URL of the IEP3 service.
        run_id: Pipeline run identifier.
        hotspots: Hotspot dicts returned by IEP2.
        events: Violation events from IEP1 (used for full-context report).

    Returns:
        PDF URL string returned by IEP3.

    Raises:
        PipelineStepError: If IEP3 fails after all retry attempts.
    """

    @_make_retry_decorator()
    async def _attempt() -> str:
        r = await client.post(
            f"{iep3_url}/generate",
            json={"hotspots": hotspots, "events": events, "run_id": run_id},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("pdf_url", "")

    try:
        return await _attempt()
    except (RetryError, Exception) as exc:
        raise PipelineStepError("IEP3", exc) from exc
