from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST


PROCESSING_OPS = Gauge(
    "payment_processing_operations",
    "Number of operations currently in PROCESSING status",
)

RETRY_TOTAL = Counter(
    "payment_retry_attempts_total",
    "Total retry attempts to provider",
    ["operation_id"],
)

PROVIDER_RESPONSES = Counter(
    "payment_provider_responses_total",
    "Provider responses by status",
    ["status"],
)

async def metrics_endpoint():
    from starlette.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )