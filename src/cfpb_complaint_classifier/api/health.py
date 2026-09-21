from fastapi import APIRouter, Request, Response, status

from cfpb_complaint_classifier.schemas import (
    HealthReport,
    LivenessResponse,
    ReportStatus,
)
from cfpb_complaint_classifier.services.health import build_health_report

router = APIRouter()


@router.get("/healthz", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get("/api/v1/health", response_model=HealthReport)
async def health(request: Request, response: Response) -> HealthReport:
    report = await build_health_report(request.app.state.db_engine)
    if report.status is ReportStatus.degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
