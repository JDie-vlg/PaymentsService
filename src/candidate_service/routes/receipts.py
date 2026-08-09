from fastapi import APIRouter, Depends, HTTPException, status

from candidate_service.schemas.schemas import ReceiptRequest
from candidate_service.db.database import database
from candidate_service.services.candidate_service import NotFoundError, ConflictError, ReceiptsService, ProviderIdMismatchError

router = APIRouter()

@router.post("/receipts", status_code=status.HTTP_204_NO_CONTENT)
async def receive_receipt(
        req: ReceiptRequest,
        conn=Depends(database.get_connection),
):
    try:
        await ReceiptsService.process_receipt(conn, req)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")
    except ProviderIdMismatchError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))