#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://localhost:8080}"
OPERATION_ID="${OPERATION_ID:-operation-1223}"
echo "=== 1. Health ==="
curl -s -w "\nHTTP %{http_code}\n" "${BASE_URL}/health"
echo
echo "=== 2. Create operation ==="
curl -s -w "\nHTTP %{http_code}\n" -X POST "${BASE_URL}/operations" \
  -H "Content-Type: application/json" \
  -d "{
    \"operationId\": \"${OPERATION_ID}\",
    \"amount\": \"1000.00\",
    \"currency\": \"RUB\",
    \"description\": \"Оплата заказа\"
  }"
echo
echo "=== 3. Submit (schedule send) ==="
curl -s -w "\nHTTP %{http_code}\n" -X POST "${BASE_URL}/operations/${OPERATION_ID}/submit"
echo
echo "=== Waiting for provider-simulator callback (adjust if needed) ==="
sleep 5
echo "=== 4. Operation status (after callback) ==="
curl -s "${BASE_URL}/operations/${OPERATION_ID}"
echo
echo "=== 5. Event history ==="
curl -s "${BASE_URL}/operations/${OPERATION_ID}/events"
echo