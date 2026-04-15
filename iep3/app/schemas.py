"""IEP3 Pydantic schemas — report generation API contract.

These schemas are the stable contract between EEP and IEP3.
"""

from pydantic import BaseModel


class ViolationEvent(BaseModel):
    """A single traffic violation event (passed from IEP1 via EEP)."""

    event_id: str
    timestamp: str
    location: dict[str, float]
    violation_type: str
    severity: str


class Hotspot(BaseModel):
    """A spatial cluster of violation events (passed from IEP2 via EEP)."""

    hotspot_id: str
    center: dict[str, float]
    radius_meters: float
    event_count: int
    risk_score: float
    dominant_violation: str


class GenerateRequest(BaseModel):
    """Input for POST /generate."""

    hotspots: list[Hotspot]
    events: list[ViolationEvent]
    run_id: str


class GenerateResponse(BaseModel):
    """Output of POST /generate."""

    pdf_url: str
