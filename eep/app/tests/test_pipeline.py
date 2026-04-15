"""Unit tests for EEP pipeline endpoints.

DB pool and IEP HTTP calls are mocked so no real Postgres or IEP services
are required.  Integration behaviour (real DB + services) is covered by
the GitHub Actions integration workflow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import db
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_pool() -> MagicMock:
    """Return a mock asyncpg pool whose execute/fetchrow/fetch are AsyncMocks."""
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=None)
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])
    return pool


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health() -> None:
    """Health endpoint must always return 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /run
# ---------------------------------------------------------------------------


def test_run_pipeline_success() -> None:
    """POST /run should call IEP1→IEP2→IEP3 and return run_id + pdf_url."""
    mock_pool = _make_mock_pool()

    with (
        patch.object(db, "_pool", mock_pool),
        patch(
            "main.call_iep1",
            new=AsyncMock(
                return_value=[
                    {
                        "event_id": "evt-001",
                        "timestamp": "2026-04-13T08:00:00Z",
                        "location": {"lat": 33.89, "lon": 35.50},
                        "violation_type": "red_light",
                        "severity": "high",
                    }
                ]
            ),
        ),
        patch(
            "main.call_iep2",
            new=AsyncMock(
                return_value=[
                    {
                        "hotspot_id": "hs-001",
                        "center": {"lat": 33.89, "lon": 35.50},
                        "radius_meters": 50.0,
                        "event_count": 1,
                        "risk_score": 0.8,
                        "dominant_violation": "red_light",
                    }
                ]
            ),
        ),
        patch(
            "main.call_iep3",
            new=AsyncMock(return_value="https://reports.infraguard.local/report.pdf"),
        ),
    ):
        response = client.post("/run", json={"video_path": "test_video.mp4"})

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["pdf_url"] == "https://reports.infraguard.local/report.pdf"


def test_run_pipeline_iep1_failure() -> None:
    """POST /run returns 502 when IEP1 fails after retries."""
    from orchestrator import PipelineStepError

    mock_pool = _make_mock_pool()

    with (
        patch.object(db, "_pool", mock_pool),
        patch(
            "main.call_iep1",
            new=AsyncMock(side_effect=PipelineStepError("IEP1", RuntimeError("down"))),
        ),
    ):
        response = client.post("/run", json={"video_path": "test_video.mp4"})

    assert response.status_code == 502
    assert "IEP1" in response.json()["detail"]


def test_run_pipeline_no_db() -> None:
    """POST /run succeeds even when the DB pool is not available (degraded mode)."""
    with (
        patch.object(db, "_pool", None),
        patch(
            "main.call_iep1",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "main.call_iep2",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "main.call_iep3",
            new=AsyncMock(return_value="https://reports.infraguard.local/no-db.pdf"),
        ),
    ):
        response = client.post("/run", json={"video_path": "test_video.mp4"})

    assert response.status_code == 200
    assert "run_id" in response.json()


# ---------------------------------------------------------------------------
# GET /status/{run_id}
# ---------------------------------------------------------------------------


def test_get_status_not_found() -> None:
    """GET /status returns 404 for unknown run_id."""
    mock_pool = _make_mock_pool()
    mock_pool.fetchrow = AsyncMock(return_value=None)

    with patch.object(db, "_pool", mock_pool):
        response = client.get("/status/nonexistent-run-id")

    assert response.status_code == 404


def test_get_status_found() -> None:
    """GET /status returns run details when run_id exists."""
    from datetime import datetime, timezone

    mock_pool = _make_mock_pool()
    mock_pool.fetchrow = AsyncMock(
        return_value={
            "id": "run-abc",
            "status": "DONE",
            "video_path": "test.mp4",
            "started_at": datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 4, 15, 8, 1, 0, tzinfo=timezone.utc),
            "pdf_url": "https://reports.infraguard.local/r.pdf",
        }
    )

    with patch.object(db, "_pool", mock_pool):
        response = client.get("/status/run-abc")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DONE"
    assert data["run_id"] == "run-abc"


# ---------------------------------------------------------------------------
# GET /reports
# ---------------------------------------------------------------------------


def test_list_reports_empty() -> None:
    """GET /reports returns an empty list when no reports exist."""
    mock_pool = _make_mock_pool()
    mock_pool.fetch = AsyncMock(return_value=[])

    with patch.object(db, "_pool", mock_pool):
        response = client.get("/reports")

    assert response.status_code == 200
    assert response.json() == []


def test_list_reports_with_data() -> None:
    """GET /reports returns report entries sorted by created_at."""
    from datetime import datetime, timezone

    mock_pool = _make_mock_pool()
    mock_pool.fetch = AsyncMock(
        return_value=[
            {
                "run_id": "run-xyz",
                "pdf_url": "https://reports.infraguard.local/r.pdf",
                "created_at": datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone.utc),
            }
        ]
    )

    with patch.object(db, "_pool", mock_pool):
        response = client.get("/reports")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "run-xyz"
    assert "pdf_url" in data[0]


def test_get_status_no_db() -> None:
    """GET /status returns 503 when DB pool is unavailable."""
    with patch.object(db, "_pool", None):
        response = client.get("/status/any-id")
    assert response.status_code == 503


@pytest.mark.parametrize("endpoint", ["/reports"])
def test_reports_no_db(endpoint: str) -> None:
    """Endpoints requiring DB return 503 when pool is unavailable."""
    with patch.object(db, "_pool", None):
        response = client.get(endpoint)
    assert response.status_code == 503
