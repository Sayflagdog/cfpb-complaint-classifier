import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from cfpb_complaint_classifier.db.tasks import get_result
from cfpb_complaint_classifier.messaging import (
    BrokerUnavailableError,
    QueueOverloadedError,
    publish_task,
)
from cfpb_complaint_classifier.schemas import (
    TaskAccepted,
    TaskMessage,
    TaskRequest,
    TaskResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/api/v1/tasks",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_task(payload: TaskRequest, request: Request) -> TaskAccepted:
    settings = request.app.state.settings
    task = TaskMessage(**payload.model_dump())
    try:
        await publish_task(request.app.state.broker, settings, task)
    except (QueueOverloadedError, BrokerUnavailableError) as exc:
        logger.warning("Task publication failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue is unavailable; retry with the same task_id",
            headers={"Retry-After": str(settings.retry_after_seconds)},
        ) from None
    return TaskAccepted(task_id=task.task_id)


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResult)
async def read_task(task_id: UUID, request: Request) -> TaskResult:
    result = await get_result(request.app.state.db_engine, task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task is unknown or not completed")
    return result
