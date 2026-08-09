# Payment Service (candidate-service)
## Описание
Сервис проводит платёжную операцию через внешний `provider-simulator` по HTTP, сохраняет состояние в постоянном хранилище и завершает операцию только по callback-квитанции. Повторы submit, конкурентные запросы, потерянные ответы провайдера и перезапуск процесса не должны приводить к созданию второго платежа для одной операции.
## Стек
- Python 3.14
- FastAPI, Uvicorn
- PostgreSQL (asyncpg)
- HTTP-клиент: httpx
- Docker, Docker Compose
- provider-simulator: `ghcr.io/fintech-dev-lab/internship-provider-simulator:v0.2.0`
- structlog, prometheus-client (метрики на `/metrics`)
## Запуск
1. Клонируйте репозиторий и перейдите в корень проекта.
```bash
git clone <repo-url>
cd payment-service
```
2. Запустите стек:
```bash
docker compose up --build
Дождитесь готовности:

candidate-service слушает порт 8080 на хосте;
provider-simulator — порт 8081;
PostgreSQL используется для персистентности (данные сохраняются в Docker volume).

Проверка готовности:

curl -s http://localhost:8080/health
Ожидается HTTP 200.

Переменные окружения (задаются в docker-compose.yml):

PROVIDER_URL=http://provider-simulator:8081
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/payments_db

Остановка:

docker compose down
Данные операций сохраняются, если не удалять volumes (docker compose down без -v).

Сквозной сценарий
Callback на финальный статус (COMPLETED / REJECTED) отправляет provider-simulator на POST http://candidate-service:8080/receipts. Шаг «Проверить статус» выполняйте после того, как callback обработан (обычно несколько секунд после submit).

1. Health
curl -s -w "\nHTTP %{http_code}\n" http://localhost:8080/health
2. Создать операцию
curl -s -w "\nHTTP %{http_code}\n" -X POST http://localhost:8080/operations \
  -H "Content-Type: application/json" \
  -d '{
    "operationId": "operation-123",
    "amount": "1000.00",
    "currency": "RUB",
    "description": "Оплата заказа"
  }'
Ожидается HTTP 201, в теле "status": "CREATED".

3. Отправить операцию (намерение отправки)
curl -s -w "\nHTTP %{http_code}\n" -X POST http://localhost:8080/operations/operation-123/submit
Первый вызов: HTTP 202, "status": "PROCESSING". Повторный submit той же операции: HTTP 200, без нового намерения.

4. Проверить статус после callback
curl -s http://localhost:8080/operations/operation-123
После callback от симулятора ожидается "status": "COMPLETED" или "REJECTED" и заполненный providerPaymentId.

5. История событий
curl -s http://localhost:8080/operations/operation-123/events
Ожидается массив событий с монотонно растущим eventId, включая CREATED, переход в PROCESSING и обработку квитанции.

Альтернатива: автоматический прогон — scripts/demo.sh - Запуск после поднятого compose
Запуск - ./scripts/demo.sh

Архитектура
Модуль	Назначение
candidate_service/main.py
Точка входа FastAPI, lifespan: подключение к БД, HTTP-клиент, startup recovery для PROCESSING, фоновый outbox worker для повторной отправки
candidate_service/routes/
HTTP API: /health, /operations, /submit, /receipts, /events
candidate_service/services/candidate_service.py
Бизнес-логика: создание операции, атомарный submit, вызов провайдера с Idempotency-Key / X-Correlation-ID, обработка квитанций
candidate_service/models/operations.py
SQL-операции с операциями и событиями
candidate_service/db/database.py
Пул asyncpg, инициализация схемы
candidate_service/schemas/schemas.py
Контракты запросов и ответов API
Состояния: CREATED → PROCESSING (после submit) → COMPLETED / REJECTED (только callback).

Тесты
Локально нужен PostgreSQL для тестовой БД (URL задаётся в фикстурах или через переменную окружения, например TEST_DATABASE_URL).

Из корня проекта (с установленными dev-зависимостями через uv):

uv sync --dev
uv run pytest src/tests -v
Покрытие тестами: тесты конкурентности (test_concurrency.py) и восстановления (test_recovery.py), сценарии с квитанцией до ответа провайдера (test_receipt_race.py).

Дополнительно
Метрики: GET http://localhost:8080/metrics
Перезапуск только candidate-service во время PROCESSING: docker compose restart candidate-service — отправка должна продолжиться с тем же idempotency key.
```

---
## `scripts/demo.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://localhost:8080}"
OPERATION_ID="${OPERATION_ID:-operation-123}"
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
```

---

## `scripts/git-bash-demo.sh` - для проверки через Git Bash

```bash
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
```
---

## `scripts/demo.ps1` - для проверки через Power Shell

```bash
param(
    [string]$BASE_URL = "http://localhost:8080",
    [string]$OPERATION_ID = "operation-124"
)

function Invoke-Api {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        [string]$Body = $null
    )

    try {
        $params = @{
            Uri             = $Uri
            Method          = $Method
            ContentType     = "application/json; charset=utf-8"
            UseBasicParsing = $true
        }
        if ($Body) {
            $params.Body = $Body
        }

        $response = Invoke-WebRequest @params
        Write-Host $response.Content
        Write-Host "HTTP $($response.StatusCode)"
    }
    catch {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $reader.BaseStream.Position = 0
            $reader.DiscardBufferedData()
            Write-Host $reader.ReadToEnd()
            Write-Host "HTTP $status" -ForegroundColor Red
        }
        else {
            Write-Host $_.Exception.Message -ForegroundColor Red
        }
    }
}

Write-Host "=== 1. Health ==="
Invoke-Api -Uri "$BASE_URL/health"
Write-Host ""

Write-Host "=== 2. Create operation ==="
$body = @{
    operationId = $OPERATION_ID
    amount      = "1000.00"
    currency    = "RUB"
    description = "Order payment"
} | ConvertTo-Json -Compress
Invoke-Api -Uri "$BASE_URL/operations" -Method "POST" -Body $body
Write-Host ""

Write-Host "=== 3. Submit ==="
Invoke-Api -Uri "$BASE_URL/operations/$OPERATION_ID/submit" -Method "POST"
Write-Host ""

Write-Host "Waiting 5 seconds for provider-simulator callback..."
Start-Sleep -Seconds 5

Write-Host "=== 4. Status ==="
Invoke-Api -Uri "$BASE_URL/operations/$OPERATION_ID"
Write-Host ""

Write-Host "=== 5. Events ==="
Invoke-Api -Uri "$BASE_URL/operations/$OPERATION_ID/events"
Write-Host ""

Write-Host "Done." -ForegroundColor Green
Read-Host "Press Enter to exit"
```