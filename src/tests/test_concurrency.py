import asyncio

import pytest

from candidate_service.db.database import database


@pytest.mark.asyncio
async def test_concurrent_create_same_operation(client):
    body = {
        "operationId": "concurrent-op",
        "amount": "100.00",
        "currency": "RUB",
        "description": "concurrency test",
    }
    responses = await asyncio.gather(
        *[client.post("/operations", json=body) for _ in range(16)]
    )

    statuses = {response.status_code for response in responses}
    assert statuses == {201, 409}
    assert sum(1 for response in responses if response.status_code == 201) == 1

    async with database.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM operations WHERE operation_id = $1",
            body["operationId"],
        )
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_submit_same_operation(client, mock_http):
    operation_id = "concurrent-submit"
    create_payload = {
        "operationId": operation_id,
        "amount": "250.00",
        "currency": "RUB",
        "description": "concurrent submit",
    }
    assert (await client.post("/operations", json=create_payload)).status_code == 201

    submit_responses = await asyncio.gather(
        *[client.post(f"/operations/{operation_id}/submit") for _ in range(20)]
    )

    statuses = {response.status_code for response in submit_responses}
    assert statuses == {200, 202}
    assert sum(1 for response in submit_responses if response.status_code == 202) == 1

    async with database.pool.acquire() as conn:
        scheduled_events = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM events
            WHERE operation_id = $1 AND event_type = 'SUBMIT_SCHEDULED'
            """,
            operation_id,
        )
    assert scheduled_events == 1

    assert (await client.get(f"/operations/{operation_id}")).json()["status"] == "PROCESSING"

    await asyncio.sleep(0.15)
    assert mock_http.post_calls
    assert all(
        call["headers"].get("Idempotency-Key") == operation_id
        for call in mock_http.post_calls
    )


@pytest.mark.asyncio
async def test_repeat_submit_after_processing_is_idempotent(client):
    operation_id = "repeat-submit"
    await client.post(
        "/operations",
        json={
            "operationId": operation_id,
            "amount": "100.00",
            "currency": "RUB",
            "description": "",
        },
    )

    assert (await client.post(f"/operations/{operation_id}/submit")).status_code == 202
    repeat = await client.post(f"/operations/{operation_id}/submit")
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "PROCESSING"

    async with database.pool.acquire() as conn:
        scheduled_events = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM events
            WHERE operation_id = $1 AND event_type = 'SUBMIT_SCHEDULED'
            """,
            operation_id,
        )
    assert scheduled_events == 1
