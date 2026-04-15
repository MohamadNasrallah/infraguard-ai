"""Unit tests for IEP1 POST /process endpoint.

asyncpg pool is mocked so no real Postgres is required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def _make_mock_conn() -> MagicMock:
    """Return a mock asyncpg connection with async context manager support."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    return conn


def _make_mock_pool() -> MagicMock:
    """Return a mock asyncpg pool."""
    conn = _make_mock_conn()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool


def test_health() -> None:
    """Health endpoint must always return 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_returns_two_events() -> None:
    """POST /process should return exactly two stub events with correct schema."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/process",
            json={"video_path": "test_video.mp4", "run_id": "run-test-001"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run-test-001"
    assert len(data["events"]) == 2

    for event in data["events"]:
        assert "event_id" in event
        assert "timestamp" in event
        assert "location" in event
        assert "lat" in event["location"]
        assert "lon" in event["location"]
        assert "violation_type" in event
        assert "severity" in event


def test_process_persists_to_db() -> None:
    """POST /process should call pool.acquire().execute() for each event."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/process",
            json={"video_path": "video.mp4", "run_id": "run-persist-test"},
        )

    assert response.status_code == 200
    conn = mock_pool.acquire.return_value
    # Two events → two execute calls
    assert conn.execute.call_count == 2


def test_process_no_db() -> None:
    """POST /process succeeds (returns stub) even when DB pool is unavailable."""
    with patch.object(main, "_pool", None):
        response = client.post(
            "/process",
            json={"video_path": "video.mp4", "run_id": "run-no-db"},
        )

    assert response.status_code == 200
    assert len(response.json()["events"]) == 2


def test_process_missing_run_id() -> None:
    """POST /process without run_id returns 422 validation error."""
    response = client.post("/process", json={"video_path": "video.mp4"})
    assert response.status_code == 422
