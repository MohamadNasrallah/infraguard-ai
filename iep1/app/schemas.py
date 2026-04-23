"""IEP1 Pydantic schemas — violation detection API contract.

These schemas are the stable contract between EEP and IEP1.
Do not change field names or types once deployed — create a versioned
endpoint instead and document the decision in docs/tradeoffs.md.
"""

from typing import Optional

from pydantic import BaseModel


class ProcessRequest(BaseModel):
    """Input for POST /process."""

    video_path: str
    run_id: str


class ViolationEvent(BaseModel):
    """A single detected traffic violation event."""

    event_id: str
    timestamp: str  # ISO 8601
    location: dict[str, float]  # {"lat": float, "lon": float}
    violation_type: str
    severity: str  # "low" | "medium" | "high"
    camera_id: Optional[str] = None  # populated by real pipeline; NULL in stub mode


class ProcessResponse(BaseModel):
    """Output of POST /process."""

    run_id: str
    events: list[ViolationEvent]
