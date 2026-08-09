from fastapi import APIRouter, Depends, status, HTTPException
from asyncpg import Connection

from candidate_service.db.database import database

router = APIRouter()

@router.get("/health", status_code=status.HTTP_200_OK)
async def health(conn: Connection = Depends(database.get_connection)):
    try:
        await conn.fetchval("SELECT 1")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database error: {str(e)}")
    return {"status": "ok"}