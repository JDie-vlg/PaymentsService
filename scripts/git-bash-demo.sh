#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
OPERATION_ID="${OPERATION_ID:-operation-123}"

echo "=== 1. Health ==="
curl -sS -w "\nHTTP %{http_code}\n" "${BASE_URL}/health"
echo

echo "=== 2. Create operation ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "${BASE_URL}/operations" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @- <<EOF
{"operationId":"${OPERATION_ID}","amount":"1000.00","currency":"RUB","description":"Order payment"}
EOF
echo

echo "=== 3. Submit ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "${BASE_URL}/operations/${OPERATION_ID}/submit"
echo

echo "Waiting 5 seconds for provider-simulator callback..."
sleep 5

echo "=== 4. Status ==="
curl -sS -w "\nHTTP %{http_code}\n" "${BASE_URL}/operations/${OPERATION_ID}"
echo

echo "=== 5. Events ==="
curl -sS -w "\nHTTP %{http_code}\n" "${BASE_URL}/operations/${OPERATION_ID}/events"
echo
