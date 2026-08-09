from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from httpx import AsyncClient
from starlette.responses import JSONResponse

from candidate_service.schemas.schemas import CreateOperationRequest
from candidate_service.db.database import database
from candidate_service.services.candidate_service import ConflictError, NotFoundError, OperationsService

router = APIRouter()

@router.post("/operations", status_code=status.HTTP_201_CREATED)
async def create_operation(
        req: CreateOperationRequest,
        conn=Depends(database.get_connection)):
    try:
        return await OperationsService.create_operation(conn, req)
    except ConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Operation already exists")


@router.post("/operations/{operation_id}/submit")
async def submit_operation(
        operation_id: str,
        background_tasks: BackgroundTasks,
        conn=Depends(database.get_connection),
    ):

    try:
        result, scheduled = await OperationsService.plan_submit(conn, operation_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")

    if scheduled:
        background_tasks.add_task(
            OperationsService.execute_submit_to_provider,
            operation_id,
        )

        return JSONResponse(content=result.model_dump(),
                            status_code=status.HTTP_202_ACCEPTED)

    return JSONResponse(content=result.model_dump(),
                        status_code=status.HTTP_200_OK)

@router.get("/operations/{operation_id}")
async def get_operation(
        operation_id: str,
        conn=Depends(database.get_connection),
):
    try:
        return await OperationsService.get_operation_status(conn, operation_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")

@router.get("/operations/{operation_id}/events")
async def get_operation_events(
        operation_id: str,
        conn=Depends(database.get_connection),
):
    try:
        return await OperationsService.get_history_events(conn, operation_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")