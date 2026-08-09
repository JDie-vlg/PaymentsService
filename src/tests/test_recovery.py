import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from candidate_service.db.database import database
from candidate_service.main import startup_recovery
from candidate_service.services.candidate_service import OperationsService


@pytest.mark.asyncio
async def test_startup_recovery_resumes_processing(db_session):
    operation_id = "recovery-op"

    async with database.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO operations (
                operation_id, amount, currency, description, status, created_at, updated_at
            )
            VALUES ($1, '100.00', 'RUB', '', 'PROCESSING', NOW(), NOW())
            """,
            operation_id,
        )

    with patch.object(
        OperationsService,
        "execute_submit_to_provider",
        new_callable=AsyncMock,
    ) as mock_submit:
        await startup_recovery()
        await asyncio.sleep(0.05)

        mock_submit.assert_awaited_once_with(operation_id)


@pytest.mark.asyncio
async def test_startup_recovery_no_processing_operations(db_session):
    with patch.object(
        OperationsService,
        "execute_submit_to_provider",
        new_callable=AsyncMock,
    ) as mock_submit:
        await startup_recovery()
        await asyncio.sleep(0.05)
        mock_submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_recovery_resumes_all_processing(db_session):
    ids = ["recovery-a", "recovery-b", "recovery-c"]

    async with database.pool.acquire() as conn:
        for operation_id in ids:
            await conn.execute(
                """
                INSERT INTO operations (
                    operation_id, amount, currency, description, status, created_at, updated_at
                )
                VALUES ($1, '10.00', 'RUB', '', 'PROCESSING', NOW(), NOW())
                """,
                operation_id,
            )

    with patch.object(
        OperationsService,
        "execute_submit_to_provider",
        new_callable=AsyncMock,
    ) as mock_submit:
        await startup_recovery()
        await asyncio.sleep(0.05)

        assert mock_submit.await_count == len(ids)
        resumed_ids = {call.args[0] for call in mock_submit.await_args_list}
        assert resumed_ids == set(ids)
