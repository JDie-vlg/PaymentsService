from asyncpg import Connection, Record
from datetime import datetime


async def insert_operation(conn: Connection, operation_id: str, amount: str, currency: str, description: str, iso: datetime) -> Record:
    return await conn.fetchrow(
        """
        INSERT INTO operations (operation_id, amount, currency, description, status, created_at, updated_at)
        VALUES ($1, $2, $3, $4, 'CREATED', $5, $5)
        RETURNING operation_id, amount, currency, description, status, provider_payment_id
        """,
        operation_id,
        amount,
        currency,
        description,
        iso,
    )

async def insert_event(conn: Connection, operation_id: str, event_type: str, from_status: str | None, to_status: str, message: str, iso: datetime) -> None:
    await conn.execute(
        """
        INSERT INTO events (operation_id, event_type, from_status, to_status, message, occurred_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        operation_id, event_type, from_status, to_status, message, iso,
    )


async def update_operation(conn: Connection, operation_id: str, provider_payment_id: str | None, status: str) -> Record | None:

    if provider_payment_id is None:
        return await conn.fetchrow(
            """
                UPDATE operations
                SET status = $1, provider_payment_id = COALESCE(provider_payment_id, $2), updated_at = NOW()
                WHERE operation_id = $3
                RETURNING operation_id, amount, currency, description, status, provider_payment_id
            """,
            status, provider_payment_id, operation_id,
        )

    return await conn.fetchrow(
        """
        UPDATE operations 
        SET status = $1, updated_at = NOW()
        WHERE operation_id = $2
        RETURNING operation_id, amount, currency, description, status, provider_payment_id
        """,
        status, operation_id,
    )

async def transition_to_processing(conn: Connection, operation_id: str) -> Record | None:
    return await conn.fetchrow(
        """
            UPDATE operations
            SET status = 'PROCESSING', updated_at = NOW()
            WHERE operation_id = $1 AND status = 'CREATED'
            RETURNING operation_id, amount, currency, description, status, provider_payment_id
        """,
        operation_id,
    )

async def update_operation_provider_id(conn: Connection, operation_id: str, provider_payment_id: str) -> Record:
    return await conn.fetchrow(
        """
        UPDATE operations
        SET provider_payment_id = $1, updated_at = NOW()
        WHERE operation_id = $2
        RETURNING operation_id, amount, currency, description, status, provider_payment_id
        """,
        provider_payment_id, operation_id,
    )

async def get_operation(conn: Connection, operation_id: str) -> Record | None:
    return await conn.fetchrow(
        """
        SELECT operation_id, amount, currency, description, status, provider_payment_id
        FROM operations
        WHERE operation_id = $1
        """,
        operation_id,
    )


async def get_operation_status(conn: Connection, operation_id: str) -> Record:
    return await conn.fetchrow(
        """
        SELECT status
        FROM operations
        WHERE operation_id = $1
        """,
        operation_id,
    )

async def get_events_by_operation(conn: Connection, operation_id: str) -> list[Record]:
    return await conn.fetch(
        """
            SELECT event_id, event_type, from_status, to_status, message, occurred_at
            FROM events
            WHERE operation_id = $1
            ORDER BY event_id ASC
        """,
        operation_id,
    )