# ShortForge 실행 (Windows). API(127.0.0.1:8000)와 웹 UI(127.0.0.1:3000)를 띄우고 브라우저를 연다.
# 창을 닫거나 Ctrl+C를 누르면 둘 다 멈춘다. 먼저 setup.bat을 한 번 실행해야 한다.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

if (-not (Test-Path "$Root\frontend\.next\BUILD_ID")) {
    Write-Host "웹 UI 빌드가 없다 — setup.bat을 먼저 실행한다." -ForegroundColor Red
    exit 1
}
foreach ($port in 8000, 3000) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "포트 $port 를 이미 쓰고 있다 — 이전에 띄운 ShortForge를 먼저 닫는다." -ForegroundColor Red
        exit 1
    }
}

# API와 웹 UI 모두 이 PC에서만 접속되게 127.0.0.1에 묶는다 (인증 없는 로컬 앱)
$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$Root\backend" `
    -FilePath "uv" -ArgumentList "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"
$web = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$Root\frontend" `
    -FilePath "npm.cmd" -ArgumentList "run", "start", "--", "-H", "127.0.0.1", "-p", "3000"

try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 1 | Out-Null
            Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3000" -TimeoutSec 1 | Out-Null
            $ready = $true; break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "30초 안에 서버가 뜨지 않았다" }
    Write-Host "ShortForge 실행 중 — http://127.0.0.1:3000 (끝내려면 Ctrl+C)" -ForegroundColor Green
    Start-Process "http://127.0.0.1:3000"
    Wait-Process -Id $api.Id
} finally {
    foreach ($p in $api, $web) {
        if ($p -and -not $p.HasExited) {
            # npm은 node 자식 프로세스를 띄우므로 프로세스 트리째 끝낸다
            taskkill /PID $p.Id /T /F | Out-Null
        }
    }
}
