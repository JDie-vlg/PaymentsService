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