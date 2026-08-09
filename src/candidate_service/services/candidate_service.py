import asyncio
import logging
import random
import structlog
from datetime import datetime, timezone

from httpx import (AsyncClient, ConnectError, HTTPStatusError,
                   NetworkError, ReadTimeout, WriteTimeout, TimeoutException, HTTPError)

from asyncpg import Connection, UniqueViolationError

from candidate_service.db.database import database
from candidate_service.config import Settings
from candidate_service.schemas.schemas import CreateOperationRequest, OperationResponse, ReceiptRequest, EventResponse
from candidate_service.models.operations import (insert_operation, insert_event, update_operation, get_operation,
                                                     get_operation_status, get_events_by_operation,
                                                     update_operation_provider_id, transition_to_processing
                                                     )
from candidate_service.metrics import PROCESSING_OPS, RETRY_TOTAL, PROVIDER_RESPONSES

logger = structlog.get_logger()

class ConflictError(Exception):
    """Операция с таким operationId уже существует."""
    pass


class NotFoundError(Exception):
    """Операция с таким operationId не найдена."""
    pass


class ProviderIdMismatchError(Exception):
    """providerPaymentId не совпадает с сохранённым."""
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

_FINAL_STATUSES = frozenset({"COMPLETED", "REJECTED"})


class OperationsService:

    @staticmethod
    async def create_operation(conn: Connection, req: CreateOperationRequest) -> OperationResponse:

        now = _now_utc()

        async with conn.transaction():
            try:
                row = await insert_operation(
                    conn,
                    req.operationId,
                    req.amount,
                    req.currency,
                    req.description,
                    now,
                )

            except UniqueViolationError:
                raise ConflictError("OperationId already exists")

            await insert_event(
                conn,
                req.operationId,
                'CREATED',
                None,
                'CREATED',
                'Operation created',
                now,
            )

            return OperationResponse(
                operationId=row['operation_id'],
                amount=row['amount'],
                currency=row['currency'],
                description=row['description'],
                status=row['status'],
                providerPaymentId=row['provider_payment_id'],
            )

    @staticmethod
    async def plan_submit(conn: Connection, operation_id: str) -> tuple[OperationResponse, bool]:

        row = await get_operation(conn, operation_id)
        if not row:
            raise NotFoundError("Operation not found")

        if row["status"] != "CREATED":
            return OperationsService._to_response(row), False

        now = _now_utc()

        async with conn.transaction():
            updated = await transition_to_processing(conn, operation_id)
            if not updated:
                current = await get_operation(conn, operation_id)
                return OperationsService._to_response(current), False

            await insert_event(
                conn,
                operation_id,
                'SUBMIT_SCHEDULED',
                'CREATED',
                'PROCESSING',
                'Submit scheduled by client',
                now,
            )

        return OperationsService._to_response(updated), True


    @staticmethod
    def _to_response(row) -> OperationResponse:
        return OperationResponse(
            operationId=row["operation_id"],
            amount=row["amount"],
            currency=row["currency"],
            description=row["description"],
            status=row["status"],
            providerPaymentId=row["provider_payment_id"],
        )

    @staticmethod
    async def execute_submit_to_provider(operation_id: str) -> None:

        from candidate_service.main import app
        client: AsyncClient = app.state.http

        settings = Settings()
        max_retries = 3
        base_delay = 1.0

        log = logger.bind(operation_id=operation_id)

        async with database.pool.acquire() as conn:
            row = await get_operation(conn, operation_id)
            if not row or row['status'] != 'PROCESSING':
                log.info("skip_not_processing", status=row['status'] if row else None)
                return

            amount = row['amount']
            currency = row['currency']
            log = log.bind(provider_payment_id=row['provider_payment_id'])

            for attempt in range(1, max_retries + 1):
                log = log.bind(attempt=attempt)

                try:
                    async with database.pool.acquire() as conn:
                        fresh = await get_operation(conn, operation_id)
                        if not fresh or fresh['status'] in _FINAL_STATUSES:
                            log.info("already_final", status=fresh["status"] if fresh else None)
                            return

                        response = await client.post(
                            f"{settings.PROVIDER_URL}/payments",
                            json={
                                "operationId": operation_id,
                                "amount": amount,
                                "currency": currency,
                            },
                            headers={
                                "Content-Type": "application/json",
                                "Idempotency-Key": operation_id,
                                "X-Correlation-ID": operation_id,
                            },
                            timeout=10.0,
                        )

                        if response.status_code == 503:
                            response.raise_for_status()

                        if response.status_code != 202:
                            PROVIDER_RESPONSES.labels(status=str(response.status_code)).inc()
                            log.error('provider_http_error', status_code=response.status_code)
                            async with conn.transaction():
                                await insert_event(
                                    conn,
                                    operation_id,
                                    'PROVIDER_HTTP_ERROR',
                                    'PROCESSING',
                                    'PROCESSING',
                                    f'Unexpected HTTP {response.status_code}',
                                    _now_utc(),
                                )

                            if response.status_code >= 500 and attempt < max_retries:
                                delay = base_delay * ( 2 ** (attempt-1))
                                jitter = random.uniform(0, delay*0.5)
                                await asyncio.sleep(delay + jitter)
                                continue
                            return

                        data = response.json()
                        provider_payment_id = data.get('providerPaymentId')
                        provider_status = data.get('status')

                        if provider_status != 'ACCEPTED':
                            async with conn.transaction():
                                await insert_event(
                                    conn,
                                    operation_id,
                                    'PROVIDER_UNEXPECTED_STATUS',
                                    'PROCESSING',
                                    'PROCESSING',
                                    f"Expected ACCEPTED, got {provider_status}",
                                    _now_utc(),
                                )
                            log.warning("provider_unexpected_status", provider_status=provider_status)
                            return

                        PROVIDER_RESPONSES.labels(status=provider_status).inc()

                        async with conn.transaction():
                            current = await get_operation(conn, operation_id)
                            if current["status"] in _FINAL_STATUSES:
                                await insert_event(
                                    conn,
                                    operation_id,
                                    'PROVIDER_LATE_202',
                                    current['status'],
                                    current['status'],
                                    f"Late 202 with providerPaymentId={provider_payment_id}",
                                    _now_utc(),
                                )
                                log.info("late_202_ignored", current_status=current['status'])
                                return

                            if provider_payment_id:
                                await update_operation_provider_id(conn, operation_id, provider_payment_id)
                                log = log.bind(provider_payment_id=provider_payment_id)

                            await insert_event(
                                conn,
                                operation_id,
                                'PROVIDER_ACCEPTED',
                                'PROCESSING',
                                'PROCESSING',
                                f"Provider 202: providerPaymentId={provider_payment_id}, status={provider_status}",
                                _now_utc(),
                            )
                        log.info("provider_accepted")
                        return

                except (ConnectionError, ReadTimeout, WriteTimeout, NetworkError, TimeoutException) as e:
                    RETRY_TOTAL.labels(operation_id=operation_id).inc()
                    log.warning("network_error", error_type=type(e).__name__, message=str(e))

                    if attempt < max_retries:
                        delay = base_delay * ( 2 ** ( attempt - 1))
                        jitter = random.uniform(0, delay * 0.5)
                        log.info("backoff_retry", delay=delay, jitter=jitter)
                        await asyncio.sleep(delay + jitter)
                        continue

                    async with database.pool.acquire() as conn:
                        await insert_event(
                            conn,
                            operation_id,
                            'PROVIDER_NETWORK_ERROR',
                            'PROCESSING',
                            'PROCESSING',
                            f"All {max_retries} attempts failed: {e}",
                            _now_utc()
                        )

                    log.error("retries_exhausted_network")
                    return

                except HTTPStatusError as e:
                    if e.response.status_code == 503:
                        RETRY_TOTAL.labels(operation_id=operation_id).inc()
                        log.warning("provider_503")

                        if attempt < max_retries:
                            delay = base_delay * ( 2 ** ( attempt - 1))
                            jitter = random.uniform(0, delay * 0.5)
                            await asyncio.sleep(delay + jitter)
                            continue

                        async with database.pool.acquire() as conn:
                            await insert_event(
                                conn,
                                operation_id,
                                'PROVIDER_503_EXHAUSTED',
                                'PROCESSING',
                                'PROCESSING',
                                f"503 after {max_retries} attempts",
                                _now_utc()
                            )
                        log.error("retries_exhausted_503")
                        return

                    PROVIDER_RESPONSES.labels(status=str(e.response.status_code)).inc()
                    log.error("provider_http_error", status_code=e.response.status_code)
                    async with database.pool.acquire() as conn:
                        await insert_event(
                            conn,
                            operation_id,
                            'PROVIDER_HTTP_ERROR',
                            'PROCESSING',
                            'PROCESSING',
                            f"HTTP {e.response.status_code}: {e}",
                            _now_utc()
                        )
                    return

                except Exception as e:
                    log.exception("unexpected_error")
                    async with database.pool.acquire() as conn:
                        await insert_event(
                            conn,
                            operation_id,
                            'PROVIDER_FATAL',
                            'PROCESSING',
                            'PROCESSING',
                            str(e),
                            _now_utc()
                        )
                    return

    @staticmethod
    async def get_operation_status(conn: Connection, operation_id: str) -> OperationResponse:

        row = await get_operation(conn, operation_id)
        if not row:
            raise NotFoundError("Operation not found")
        return OperationResponse(
            operationId=row['operation_id'],
            amount=row['amount'],
            currency=row['currency'],
            description=row['description'],
            status=row['status'],
            providerPaymentId=row['provider_payment_id'],
        )


    @staticmethod
    async def get_history_events(conn: Connection, operation_id: str) -> list[EventResponse]:
        row = await get_operation(conn, operation_id)
        if not row:
            raise NotFoundError("Operation not found")

        records = await get_events_by_operation(conn, operation_id)

        return [
            EventResponse(
                eventId=r["event_id"],
                type=r["event_type"],
                fromStatus=r["from_status"],
                toStatus=r["to_status"],
                message=r["message"],
                occurredAt=r["occurred_at"],
            )
            for r in records
        ]


class ReceiptsService:

    @staticmethod
    async def process_receipt(conn: Connection, req: ReceiptRequest) -> None:

        log = logger.bind(
            operation_id=req.operationId,
            provider_payment_id=req.providerPaymentId,
        )

        async with conn.transaction():
            row = await get_operation(conn, req.operationId)
            if not row:
                raise NotFoundError("Operation not found")

            db_provider_id = row['provider_payment_id']
            if db_provider_id is None:
                await update_operation_provider_id(
                    conn, req.operationId, req.providerPaymentId
                )
                log.info("provider_id_linked")

            elif db_provider_id != req.providerPaymentId:
                log.error("provider_id_mismatch", exprected=db_provider_id, got=req.providerPaymentId)
                raise ProviderIdMismatchError(
                    f"Provider payment id {db_provider_id} does not match, got {req.providerPaymentId}"
                )

            current_status = row['status']

            if current_status == req.result:
                log.info("duplicate_receipts")
                return

            if current_status in _FINAL_STATUSES:
                await insert_event(
                    conn,
                    req.operationId,
                    "RECEIPT_IGNORED",
                    current_status,
                    current_status,
                    f"Late receipts ignored result={req.result}, message={req.message}",
                    req.occurredAt,
                )
                log.info("late_receipts_ignored", current_status=current_status, rejected_result=req.result)
                return

            await update_operation(conn, req.operationId, req.providerPaymentId, req.result)
            await insert_event(
                conn,
                req.operationId,
                "RECEIPT_PROCESSED",
                current_status,
                req.result,
                req.message or f"Receipt processed: {req.result}",
                req.occurredAt,
            )
            log.info("receipts_processed", from_status=current_status, to_status=req.result)
