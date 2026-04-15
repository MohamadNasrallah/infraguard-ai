"""IEP2 Pydantic schemas — hotspot clustering API contract.

These schemas are the stable contract between EEP and IEP2.
"""

from pydantic import BaseModel


class ViolationEvent(BaseModel):
    """A single traffic violation event (passed from IEP1)."""

    event_id: str
    timestamp: str
    location: dict[str, float]
    violation_type: str
    severity: str


class ClusterRequest(BaseModel):
    """Input for POST /cluster."""

    events: list[ViolationEvent]
    run_id: str


class Hotspot(BaseModel):
    """A spatial cluster of violation events."""

    hotspot_id: str
    center: dict[str, float]  # {"lat": float, "lon": float}
    radius_meters: float
    event_count: int
    risk_score: float
    dominant_violation: str


class ClusterResponse(BaseModel):
    """Output of POST /cluster."""

    run_id: str
    hotspots: list[Hotspot]
