"""Golden tests for IEP3 report generation.

Uses a fixed, deterministic input to assert:
  1. load_prompt("v1") returns a string containing all required section headers.
  2. POST /generate with a fixed payload returns 200 and a pdf_url containing
     the supplied run_id.
"""
import sys
import os

# Ensure iep3/app is on the path so we can import prompt_manager and main.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from prompt_manager import load_prompt

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXED_RUN_ID = "golden-test-001"

_FIXED_HOTSPOTS = [
    {
        "hotspot_id": "hs-golden-001",
        "center": {"lat": 33.8939, "lon": 35.5020},
        "radius_meters": 50.0,
        "event_count": 1,
        "risk_score": 0.82,
        "dominant_violation": "red_light",
    }
]

_FIXED_EVENTS = [
    {
        "event_id": "evt-golden-001",
        "timestamp": "2026-04-13T08:00:00Z",
        "location": {"lat": 33.8939, "lon": 35.5020},
        "violation_type": "red_light",
        "severity": "high",
    }
]


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


def test_prompt_v1_contains_executive_summary() -> None:
    """load_prompt("v1") must include the Executive Summary heading."""
    prompt = load_prompt("v1")
    assert "Executive Summary" in prompt


def test_prompt_v1_contains_hotspot_analysis() -> None:
    """load_prompt("v1") must include the Hotspot Analysis heading."""
    prompt = load_prompt("v1")
    assert "Hotspot Analysis" in prompt


def test_prompt_v1_contains_recommendations() -> None:
    """load_prompt("v1") must include the Recommendations heading."""
    prompt = load_prompt("v1")
    assert "Recommendations" in prompt


# ---------------------------------------------------------------------------
# Endpoint golden test
# ---------------------------------------------------------------------------


def test_generate_golden_payload() -> None:
    """POST /generate with fixed payload returns 200 and pdf_url with run_id."""
    mock_pool = _make_mock_pool()

    with patch.object(main, "_pool", mock_pool):
        client = TestClient(main.app)
        response = client.post(
            "/generate",
            json={
                "hotspots": _FIXED_HOTSPOTS,
                "events": _FIXED_EVENTS,
                "run_id": _FIXED_RUN_ID,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "pdf_url" in data
    assert _FIXED_RUN_ID in data["pdf_url"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pool():
    from unittest.mock import MagicMock
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=None)
    return pool
