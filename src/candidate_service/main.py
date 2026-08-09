import httpx
import uvicorn
import logging
import asyncio

from fastapi import FastAPI
from contextlib import asynccontextmanager

from candidate_service.db.database import database, settings
from candidate_service.routes import operations_router, health_router, receipts_router
from candidate_service.services.candidate_service import OperationsService
from candidate_service.logging_config import configure_logging
from candidate_service.metrics import metrics_endpoint, PROCESSING_OPS

logger = logging.getLogger(__name__)
configure_logging()


async def startup_recovery():

    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                    SELECT operation_id
                    FROM operations
                    WHERE status = 'PROCESSING'
                """
            )

        if not rows:
            logger.info("Recovery: no PROCESSING operations")
            return

        logger.info(f"Recovery: resuming {len(rows)} operations")

        for row in rows:
            asyncio.create_task(OperationsService.execute_submit_to_provider(row['operation_id']))

    except Exception as e:
        logger.exception(f"Recovery failed: {e}")


async def outbox_worker(stop_event: asyncio.Event):

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30.0)
            break
        except asyncio.TimeoutError:
            pass

        try:
            async with database.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                        SELECT operation_id
                        FROM operations
                        WHERE status = 'PROCESSING'
                    """
                )
                PROCESSING_OPS.set(len(rows))

            for row in rows:
                op_id = row['operation_id']
                logger.info(f"Outbox: retrying {op_id}")
                await OperationsService.execute_submit_to_provider(op_id)
        except Exception:
            logger.exception(f"Outbox worker error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Payment Service")

    await database.connect()
    logger.info("Connected to database")
    await database.init_schema()
    logger.info("Init schema")

    app.state.http = httpx.AsyncClient(timeout=settings.SERVER_TIMEOUT)
    logger.info("HTTP client created")

    await startup_recovery()

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(outbox_worker(stop_event))

    try:
        yield
    finally:
        logger.info("Shutdown")
        stop_event.set()

        try:
            await asyncio.wait_for(worker_task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Outbox worker did not finish in time, cancelling")
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        await app.state.http.aclose()
        logging.info("HTTP client closed")

        await database.disconnect()
        logger.info("Disconnected from database")


app = FastAPI(title="Payment Service", lifespan=lifespan)

app.include_router(operations_router)
app.include_router(health_router)
app.include_router(receipts_router)

@app.get("/metrics")
async def metrics():
    return await metrics_endpoint()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)