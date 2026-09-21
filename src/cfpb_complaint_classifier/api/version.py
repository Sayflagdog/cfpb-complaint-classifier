from fastapi import APIRouter

from cfpb_complaint_classifier.core.version import get_application_version
from cfpb_complaint_classifier.schemas import VersionResponse

router = APIRouter()


@router.get("/api/v1/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(version=get_application_version())
