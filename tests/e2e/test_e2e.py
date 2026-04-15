"""End-to-end test for the InfraGuard pipeline.

Hits the live EEP /run endpoint, polls /status until completion, and asserts
the final status is "completed".

Run with:
    pytest tests/e2e/ -m e2e

Excluded from the normal test run (no -m flag) by the pytest.mark.e2e marker.
"""
import os
import time

import pytest
import requests

EEP_URL = os.getenv("EEP_URL", "http://localhost:8000")

pytestmark = pytest.mark.e2e


@pytest.mark.e2e
def test_full_pipeline_run() -> None:
    """POST /run → poll /status → assert completed."""
    # Trigger a pipeline run
    response = requests.post(
        f"{EEP_URL}/run",
        json={"video_path": "data/sample_video.mp4"},
        timeout=30,
    )
    assert response.status_code == 200, (
        f"POST /run returned {response.status_code}: {response.text}"
    )

    data = response.json()
    assert "run_id" in data, f"Response missing run_id: {data}"
    run_id = data["run_id"]

    # Poll /status until completed or failed
    final_status = None
    for _ in range(10):
        time.sleep(2)
        status_response = requests.get(
            f"{EEP_URL}/status/{run_id}",
            timeout=10,
        )
        if status_response.status_code == 200:
            status_data = status_response.json()
            current_status = status_data.get("status", "").lower()
            if current_status in ("completed", "done", "failed"):
                final_status = current_status
                break

    assert final_status in ("completed", "done"), (
        f"Pipeline run did not complete successfully. Final status: {final_status!r}"
    )
