"""Unit tests for IEP2 POST /cluster endpoint.

asyncpg pool is mocked so no real Postgres is required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

_SAMPLE_EVENTS = [
    {
        "event_id": "evt-001",
        "timestamp": "2026-04-13T08:00:00Z",
        "location": {"lat": 33.8938, "lon": 35.5018},
        "violation_type": "red_light",
        "severity": "high",
    },
    {
        "event_id": "evt-002",
        "timestamp": "2026-04-13T08:05:30Z",
        "location": {"lat": 33.8941, "lon": 35.5022},
        "violation_type": "speeding",
        "severity": "medium",
    },
]


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


def test_cluster_returns_one_hotspot() -> None:
    """POST /cluster with two events should return one stub hotspot."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/cluster",
            json={"events": _SAMPLE_EVENTS, "run_id": "run-cluster-001"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run-cluster-001"
    assert len(data["hotspots"]) == 1

    hotspot = data["hotspots"][0]
    assert "hotspot_id" in hotspot
    assert "center" in hotspot
    assert "lat" in hotspot["center"]
    assert "lon" in hotspot["center"]
    assert "radius_meters" in hotspot
    assert "event_count" in hotspot
    assert "risk_score" in hotspot
    assert "dominant_violation" in hotspot


def test_cluster_event_count_matches_input() -> None:
    """Hotspot event_count should equal the number of input events."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/cluster",
            json={"events": _SAMPLE_EVENTS, "run_id": "run-count-test"},
        )

    assert response.json()["hotspots"][0]["event_count"] == len(_SAMPLE_EVENTS)


def test_cluster_empty_events() -> None:
    """POST /cluster with no events still returns a stub hotspot (fallback centroid)."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/cluster",
            json={"events": [], "run_id": "run-empty"},
        )

    assert response.status_code == 200
    assert len(response.json()["hotspots"]) == 1


def test_cluster_persists_to_db() -> None:
    """POST /cluster should call execute once per hotspot."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        response = client.post(
            "/cluster",
            json={"events": _SAMPLE_EVENTS, "run_id": "run-persist-cluster"},
        )

    assert response.status_code == 200
    conn = mock_pool.acquire.return_value
    assert conn.execute.call_count == 1  # one hotspot → one insert


def test_cluster_no_db() -> None:
    """POST /cluster succeeds (returns stub) even when DB pool is unavailable."""
    with patch.object(main, "_pool", None):
        response = client.post(
            "/cluster",
            json={"events": _SAMPLE_EVENTS, "run_id": "run-no-db"},
        )

    assert response.status_code == 200


def test_cluster_missing_run_id() -> None:
    """POST /cluster without run_id returns 422 validation error."""
    response = client.post("/cluster", json={"events": _SAMPLE_EVENTS})
    assert response.status_code == 422
