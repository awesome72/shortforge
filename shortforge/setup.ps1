# ShortForge 최초 설치 (Windows). setup.bat을 더블클릭하거나 PowerShell에서 실행한다.
# 필요한 것: Python 3.11+, uv, Node.js 20.9+, FFmpeg. 없으면 설치 방법을 안내하고 멈춘다.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Need($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\$name.exe"
        if (Test-Path $winget) { return }
        Write-Host "✗ $name 이(가) 없다 — $hint" -ForegroundColor Red
        exit 1
    }
}

Write-Host "== ShortForge 설치 ==" -ForegroundColor Cyan
Need "uv" "winget install astral-sh.uv"
Need "node" "winget install OpenJS.NodeJS.LTS"
Need "npm" "Node.js와 함께 설치된다"
Need "ffmpeg" "winget install Gyan.FFmpeg"

if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Write-Host "• .env를 만들었다 — YOUTUBE_API_KEY, GEMINI_API_KEY 두 개를 채운다" -ForegroundColor Yellow
}

Write-Host "• 백엔드 의존성 (uv sync)"
Push-Location "$Root\backend"; uv sync; if ($LASTEXITCODE) { exit 1 }; Pop-Location

Write-Host "• 웹 UI 의존성·빌드 (npm ci, npm run build)"
Push-Location "$Root\frontend"
npm ci; if ($LASTEXITCODE) { exit 1 }
npm run build; if ($LASTEXITCODE) { exit 1 }
Pop-Location

Write-Host "• 환경 점검"
Push-Location "$Root\backend"; uv run python ..\scripts\doctor.py; $ok = $LASTEXITCODE; Pop-Location
if ($ok) {
    Write-Host "점검에 실패한 항목이 있다. .env의 키를 채운 뒤 다시 실행하거나 start.bat으로 시작한다." -ForegroundColor Yellow
} else {
    Write-Host "설치 완료 — start.bat으로 시작한다." -ForegroundColor Green
}
