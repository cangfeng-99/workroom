# Enter-Dev.ps1 - prepare the CURRENT PowerShell process only.
# ASCII-only on purpose (Windows PowerShell 5.1 encoding safety).
# No system PATH changes, no services, no network.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $Root 'AGENTS.md'))) {
    Write-Host "[FAIL] Workspace root not recognized: $Root" -ForegroundColor Red
    exit 1
}

$candidates = @(
    (Join-Path $Root '.venv\Scripts'),
    'C:\Users\28369\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin',
    'C:\Users\28369\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback',
    'C:\Users\28369\.local\bin'
)

$added = @()
foreach ($p in $candidates) {
    if (Test-Path -LiteralPath $p) {
        $env:PATH = $p + ';' + $env:PATH
        $added += $p
    }
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:VIRTUAL_ENV = Join-Path $Root '.venv'
Set-Location -LiteralPath $Root

Write-Host "AgentWorkspace dev shell" -ForegroundColor Cyan
Write-Host "  root : $Root"
foreach ($p in $added) { Write-Host "  path+: $p" -ForegroundColor DarkGray }
Write-Host ("  python: " + ((& python --version) 2>&1))
Write-Host ("  node  : " + ((& node --version) 2>&1))
Write-Host ("  pnpm  : " + ((& pnpm --version) 2>&1))
Write-Host "This changed only the current process. Nothing was installed or started." -ForegroundColor DarkGray
