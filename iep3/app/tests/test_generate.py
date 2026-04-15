"""Unit tests for IEP3 POST /generate endpoint.

asyncpg pool is mocked so no real Postgres is required.
The prompt file is read from the real iep3/prompts/ directory.
"""

from unittest.mock import AsyncMock, patch

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

_SAMPLE_HOTSPOTS = [
    {
        "hotspot_id": "hs-001",
        "center": {"lat": 33.8939, "lon": 35.5020},
        "radius_meters": 50.0,
        "event_count": 2,
        "risk_score": 0.82,
        "dominant_violation": "red_light",
    }
]

_SAMPLE_EVENTS = [
    {
        "event_id": "evt-001",
        "timestamp": "2026-04-13T08:00:00Z",
        "location": {"lat": 33.8938, "lon": 35.5018},
        "violation_type": "red_light",
        "severity": "high",
    }
]


def _make_mock_pool():  # type: ignore[return]
    """Return a mock asyncpg pool with an AsyncMock execute."""
    from unittest.mock import MagicMock

    pool = MagicMock()
    pool.execute = AsyncMock(return_value=None)
    return pool


def test_health() -> None:
    """Health endpoint must always return 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_returns_pdf_url() -> None:
    """POST /generate should return a non-empty pdf_url."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/generate",
            json={
                "hotspots": _SAMPLE_HOTSPOTS,
                "events": _SAMPLE_EVENTS,
                "run_id": "run-gen-001",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "pdf_url" in data
    assert data["pdf_url"]


def test_generate_pdf_url_contains_run_id() -> None:
    """pdf_url should embed the run_id for traceability."""
    mock_pool = _make_mock_pool()
    run_id = "run-traceability-test"

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/generate",
            json={
                "hotspots": _SAMPLE_HOTSPOTS,
                "events": _SAMPLE_EVENTS,
                "run_id": run_id,
            },
        )

    assert run_id in response.json()["pdf_url"]


def test_generate_persists_to_db() -> None:
    """POST /generate should call pool.execute() to write the report."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/generate",
            json={
                "hotspots": _SAMPLE_HOTSPOTS,
                "events": _SAMPLE_EVENTS,
                "run_id": "run-persist-gen",
            },
        )

    assert response.status_code == 200
    mock_pool.execute.assert_called_once()


def test_generate_no_db() -> None:
    """POST /generate succeeds even when DB pool is unavailable."""
    with patch.object(main, "_pool", None):
        response = client.post(
            "/generate",
            json={
                "hotspots": _SAMPLE_HOTSPOTS,
                "events": _SAMPLE_EVENTS,
                "run_id": "run-no-db-gen",
            },
        )

    assert response.status_code == 200
    assert "pdf_url" in response.json()


def test_generate_missing_run_id() -> None:
    """POST /generate without run_id returns 422 validation error."""
    response = client.post(
        "/generate",
        json={"hotspots": _SAMPLE_HOTSPOTS, "events": _SAMPLE_EVENTS},
    )
    assert response.status_code == 422


def test_generate_prompt_not_found() -> None:
    """POST /generate returns 500 if the prompt file is missing."""
    with (
        patch.object(main, "_pool", None),
        patch("main.load_prompt", side_effect=FileNotFoundError("missing")),
    ):
        response = client.post(
            "/generate",
            json={
                "hotspots": _SAMPLE_HOTSPOTS,
                "events": _SAMPLE_EVENTS,
                "run_id": "run-bad-prompt",
            },
        )

    assert response.status_code == 500
