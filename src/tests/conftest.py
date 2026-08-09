import asyncio
import os

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/payments_db",
    ),
)

from candidate_service.db.database import database  # noqa: E402
from candidate_service.main import app, lifespan  # noqa: E402


class MockHttpClient:

    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.delay_seconds: float = 0.0
        self.responses: list[httpx.Response] | None = None
        self._response_index = 0

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.post_calls.append({"url": url, **kwargs})
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)

        if self.responses is not None:
            response = self.responses[min(self._response_index, len(self.responses) - 1)]
            self._response_index += 1
            return response

        operation_id = kwargs.get("json", {}).get("operationId", "unknown")
        return httpx.Response(
            202,
            json={
                "providerPaymentId": f"provider-{operation_id}",
                "status": "ACCEPTED",
            },
        )

    async def aclose(self) -> None:
        return None


async def _truncate_operations() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE events RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE TABLE operations CASCADE")


@pytest.fixture
async def mock_http() -> MockHttpClient:
    return MockHttpClient()


@pytest.fixture
async def client(mock_http: MockHttpClient):
    import candidate_service.main as main_module

    async def noop_recovery() -> None:
        return None

    async def silent_outbox(stop_event: asyncio.Event) -> None:
        await stop_event.wait()

    original_recovery = main_module.startup_recovery
    original_outbox = main_module.outbox_worker
    main_module.startup_recovery = noop_recovery
    main_module.outbox_worker = silent_outbox

    try:
        async with lifespan(app):
            app.state.http = mock_http
            await _truncate_operations()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

            await _truncate_operations()
    finally:
        main_module.startup_recovery = original_recovery
        main_module.outbox_worker = original_outbox


@pytest.fixture
async def db_session(mock_http: MockHttpClient):

    import candidate_service.main as main_module

    async def noop_recovery() -> None:
        return None

    async def silent_outbox(stop_event: asyncio.Event) -> None:
        await stop_event.wait()

    original_recovery = main_module.startup_recovery
    original_outbox = main_module.outbox_worker
    main_module.startup_recovery = noop_recovery
    main_module.outbox_worker = silent_outbox

    try:
        async with lifespan(app):
            app.state.http = mock_http
            await _truncate_operations()
            yield
            await _truncate_operations()
    finally:
        main_module.startup_recovery = original_recovery
        main_module.outbox_worker = original_outbox