from enum import StrEnum

from pydantic import BaseModel


class HealthStatus(StrEnum):
    healthy = "healthy"
    unavailable = "unavailable"


class ReportStatus(StrEnum):
    healthy = "healthy"
    degraded = "degraded"


class LivenessResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    version: str


class ComponentHealth(BaseModel):
    status: HealthStatus
    version: str | None = None
    response_time_ms: float


class HealthReport(BaseModel):
    status: ReportStatus
    components: dict[str, ComponentHealth]
