import asyncio
from datetime import datetime, timezone

import pytest

from candidate_service.db.database import database


def _receipt_payload(operation_id: str, provider_payment_id: str) -> dict:
    return {
        "providerPaymentId": provider_payment_id,
        "operationId": operation_id,
        "result": "COMPLETED",
        "message": "Payment completed",
        "occurredAt": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_receipt_before_provider_response(client, mock_http):
    operation_id = "race-op"
    provider_payment_id = "race-provider-id"
    mock_http.delay_seconds = 0.4

    create = await client.post(
        "/operations",
        json={
            "operationId": operation_id,
            "amount": "100.00",
            "currency": "RUB",
            "description": "race",
        },
    )
    assert create.status_code == 201

    submit_task = asyncio.create_task(client.post(f"/operations/{operation_id}/submit"))

    await asyncio.sleep(0.05)

    receipt = await client.post(
        "/receipts",
        json=_receipt_payload(operation_id, provider_payment_id),
    )
    assert receipt.status_code == 204

    submit_response = await submit_task
    assert submit_response.status_code == 202

    await asyncio.sleep(0.5)

    state = await client.get(f"/operations/{operation_id}")
    assert state.status_code == 200
    body = state.json()
    assert body["status"] == "COMPLETED"
    assert body["providerPaymentId"] == provider_payment_id

    async with database.pool.acquire() as conn:
        receipt_events = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM events
            WHERE operation_id = $1 AND event_type = 'RECEIPT_PROCESSED'
            """,
            operation_id,
        )
    assert receipt_events == 1

    assert mock_http.post_calls
    assert all(
        call["headers"].get("Idempotency-Key") == operation_id
        for call in mock_http.post_calls
    )


@pytest.mark.asyncio
async def test_concurrent_duplicate_receipts(client):
    operation_id = "dup-receipt-op"
    provider_payment_id = "dup-provider-id"

    await client.post(
        "/operations",
        json={
            "operationId": operation_id,
            "amount": "100.00",
            "currency": "RUB",
            "description": "",
        },
    )

    async with database.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE operations
            SET status = 'PROCESSING', provider_payment_id = $2, updated_at = NOW()
            WHERE operation_id = $1
            """,
            operation_id,
            provider_payment_id,
        )

    payload = _receipt_payload(operation_id, provider_payment_id)
    responses = await asyncio.gather(
        *[client.post("/receipts", json=payload) for _ in range(10)]
    )
    assert all(response.status_code == 204 for response in responses)

    state = await client.get(f"/operations/{operation_id}")
    assert state.json()["status"] == "COMPLETED"

    async with database.pool.acquire() as conn:
        processed = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM events
            WHERE operation_id = $1 AND event_type = 'RECEIPT_PROCESSED'
            """,
            operation_id,
        )
    assert processed == 1
