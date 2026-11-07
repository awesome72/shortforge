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
# 웹 UI(Next.js 16)는 Node 20.9 이상이 필요하다. 낮으면 npm 빌드가 알 수 없는 오류로 멈춘다
$nodeVersion = [version]((node --version) -replace "^v", "")
if ($nodeVersion -lt [version]"20.9.0") {
    Write-Host "✗ Node.js $nodeVersion 은(는) 너무 오래됐다 — winget upgrade OpenJS.NodeJS.LTS" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Write-Host "• .env를 만들었다 — YOUTUBE_API_KEY, GEMINI_API_KEY 두 개를 채운다" -ForegroundColor Yellow
}

Write-Host "• 백엔드 의존성 (uv sync --locked)"
# CI와 같은 잠금 파일 그대로 설치한다 (잠금 파일과 다른 버전이 깔리지 않게)
Push-Location "$Root\backend"; uv sync --locked; if ($LASTEXITCODE) { exit 1 }; Pop-Location

Write-Host "• 웹 UI 의존성·빌드 (npm ci, npm run build)"
Push-Location "$Root\frontend"
npm ci; if ($LASTEXITCODE) { exit 1 }
npm run build; if ($LASTEXITCODE) { exit 1 }
Pop-Location

Write-Host "• 환경 점검"
Push-Location "$Root\backend"; uv run python ..\scripts\doctor.py; $ok = $LASTEXITCODE; Pop-Location
if ($ok) {
    Write-Host "점검에 실패한 항목이 있다. 키가 비어 있다면 start.bat으로 시작해 화면의 '설정 (API 키)'에서 넣는다." -ForegroundColor Yellow
} else {
    Write-Host "설치 완료 — start.bat으로 시작한다." -ForegroundColor Green
}
