import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(strict=True, min_length=1, max_length=20000)
    task_id: UUID = Field(default_factory=uuid4)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            raise ValueError("Text must contain non-whitespace characters")
        return normalized


class TaskMessage(TaskRequest):
    task_id: UUID = Field(...)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskAccepted(BaseModel):
    task_id: UUID


class TaskResult(BaseModel):
    task_id: UUID
    category: str
    model_name: str
    model_version: str
    created_at: AwareDatetime
    started_at: AwareDatetime
    completed_at: AwareDatetime


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
