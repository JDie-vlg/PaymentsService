import asyncpg
import logging
import urllib.parse

from candidate_service.config import Settings


class Postgres:

    def __init__(self, database_url: str):
        self._pool: asyncpg.Pool | None = None
        self._database_url: str = database_url

    async def _ensure_database_exists(self) -> None:

        parsed = urllib.parse.urlparse(self._database_url)

        system_url = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            "/postgres",
            parsed.params,
            parsed.query,
            parsed.fragment
        ))

        conn = await asyncpg.connect(system_url)
        try:
            db_name = parsed.path.lstrip("/")

            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                db_name
            )
            if not exists:

                await conn.execute(f'CREATE DATABASE "{db_name}"')
                logging.info(f"Database '{db_name}' created")
            else:
                logging.info(f"Database '{db_name}' already exists")
        finally:
            await conn.close()

    async def connect(self) -> None:
        await self._ensure_database_exists()

        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=10,
            command_timeout=10,
        )
        logging.info("Connection pool created")

    async def disconnect(self) -> None:

        if self._pool:
            await self._pool.close()
            self._pool = None
            logging.info("Connection pool closed")

    async def init_schema(self) -> None:

        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")

        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id          TEXT PRIMARY KEY,
                    amount                TEXT NOT NULL,
                    currency              TEXT NOT NULL DEFAULT 'RUB',
                    description           TEXT NOT NULL DEFAULT '',
                    status                TEXT NOT NULL DEFAULT 'CREATED',
                    provider_payment_id   TEXT,
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id        SERIAL PRIMARY KEY,
                    operation_id    TEXT NOT NULL REFERENCES operations(operation_id),
                    event_type      TEXT NOT NULL,
                    from_status     TEXT,
                    to_status       TEXT NOT NULL,
                    message         TEXT,
                    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_operation
                ON events(operation_id)
            """)
            logging.info("Database schema initialized")


    async def get_connection(self):
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self._pool.acquire() as conn:
            yield conn


    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Pool not initialized")
        return self._pool


settings = Settings()
database = Postgres(settings.database_url)
