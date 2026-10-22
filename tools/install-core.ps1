# T003R1 core dependency install (background, observable, single run).
# Scope: install requirements-dev.in only. No Chromium download, no database creation,
# no gateway/system changes. ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less
# .ps1 as ANSI and would break on non-ASCII bytes.
[CmdletBinding()]
param(
    [string]$TaskRoot = 'D:\Users\28369\Desktop\AgentWorkspace',
    [int]$OverallTimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'

$logDir    = Join-Path $TaskRoot 'tasks\logs'
$reportDir = Join-Path $TaskRoot 'tasks\reports'
foreach ($d in @($logDir, $reportDir)) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

$stdoutLog  = Join-Path $logDir 'T003-core.log'
$stderrLog  = Join-Path $logDir 'T003-core.err.log'
$journalLog = Join-Path $logDir 'T003-core.ps1.log'
$freezeErr  = Join-Path $logDir 'T003-core.freeze.err.log'
$reportJson = Join-Path $reportDir 'install-core.json'

$uv       = 'C:\Users\28369\.local\bin\uv.exe'
$venvPy   = Join-Path $TaskRoot '.venv\Scripts\python.exe'
$reqFile  = Join-Path $TaskRoot 'requirements-dev.in'
$lockFile = Join-Path $TaskRoot 'requirements-dev.lock'

$startedAt  = (Get-Date).ToString('o')
$wrapperPid = $PID
$childPid   = $null
$exitCode   = $null
$status     = 'FAILED'
$note       = ''
$lockCreated = $false

# Journal goes to its own file: uv holds T003-core.log exclusively while running.
function Write-Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date).ToString('HH:mm:ss'), $msg
    Add-Content -LiteralPath $journalLog -Value $line -Encoding UTF8
}

function Write-Report {
    $obj = [ordered]@{
        task                    = 'T003R1'
        status                  = $script:status
        started_at              = $script:startedAt
        finished_at             = (Get-Date).ToString('o')
        wrapper_pid             = $script:wrapperPid
        process_id              = $script:childPid
        exit_code               = $script:exitCode
        overall_timeout_seconds = $OverallTimeoutSeconds
        python                  = $venvPy
        requirements            = $reqFile
        lock_file               = $(if ($script:lockCreated) { $lockFile } else { $null })
        stdout_log              = $stdoutLog
        stderr_log              = $stderrLog
        index                   = 'https://pypi.org/simple'
        http_timeout            = 30
        http_retries            = 1
        mysqlclient             = 'wheel-only (--only-binary mysqlclient)'
        chromium_downloaded     = $false
        database_created        = $false
        note                    = $script:note
    }
    $json = $obj | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($reportJson, $json, (New-Object System.Text.UTF8Encoding($false)))
}

# Startup marker first, so a later crash still leaves a trace.
Write-Log ('T003R1 install-core start; wrapper_pid={0}; overall_timeout={1}s' -f $wrapperPid, $OverallTimeoutSeconds)
$preLines = @()

try {
    # In-process UTF-8 only; global environment untouched.
    $env:PYTHONUTF8       = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUNBUFFERED = '1'
    $env:UV_HTTP_TIMEOUT  = '30'
    $env:UV_HTTP_RETRIES  = '1'

    foreach ($p in @($uv, $venvPy, $reqFile)) {
        if (-not (Test-Path -LiteralPath $p)) { throw "missing required path: $p" }
    }

    $preLines += ('[{0}] uv: {1}' -f (Get-Date).ToString('HH:mm:ss'), ((& $uv --version 2>&1) -join ' '))
    $preLines += ('[{0}] python: {1}' -f (Get-Date).ToString('HH:mm:ss'), $venvPy)
    # uv 0.12.10: no --timeout / --retries CLI flags; UV_HTTP_* env vars used instead.
    $argList = @(
        'pip', 'install',
        '--python', $venvPy,
        '-r', $reqFile,
        '--default-index', 'https://pypi.org/simple',
        '--only-binary', 'mysqlclient',
        '--no-cache'
    )
    $preLines += ('[{0}] cmd: {1} {2}' -f (Get-Date).ToString('HH:mm:ss'), $uv, ($argList -join ' '))

    # uv owns T003-core.log / .err.log exclusively, so the journal keeps the prelude.
    $preLines | ForEach-Object { Write-Log $_ }
    $p = Start-Process -FilePath $uv -ArgumentList $argList -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    $childPid = $p.Id
    Write-Log "uv child pid=$childPid"

    $timeoutMs = $OverallTimeoutSeconds * 1000
    if (-not $p.WaitForExit($timeoutMs)) {
        & taskkill /T /F /PID $childPid 2>&1 | Out-Null
        $status = 'TIMEOUT'
        $exitCode = -1
        $note = "exceeded overall timeout ${OverallTimeoutSeconds}s; process tree killed"
        Write-Log "TIMEOUT: $note"
    }
    else {
        $p.Refresh()
        $exitCode = $p.ExitCode
        if ($exitCode -eq 0) {
            $status = 'SUCCESS'
            Write-Log 'uv install exit=0; freezing lock'
            $freeze = & $uv pip freeze --python $venvPy 2> $freezeErr
            if ($LASTEXITCODE -eq 0) {
                [System.IO.File]::WriteAllText($lockFile, (($freeze -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
                $lockCreated = $true
                $note = 'core deps installed; lock frozen; chromium not downloaded; no database created'
                Write-Log "lock written: $lockFile"
            }
            else {
                $status = 'PARTIAL'
                $note = "install ok but uv pip freeze failed exit=$LASTEXITCODE"
                Write-Log "WARN: $note"
            }
        }
        else {
            $status = 'FAILED'
            $note = "uv install failed with exit code $exitCode; see stderr log"
            Write-Log "FAILED: $note"
        }
    }
}
catch {
    $status = 'FAILED'
    if ($null -eq $exitCode) { $exitCode = -1 }
    $note = "installer error: $($_.Exception.Message)"
    Write-Log "ERROR: $note"
}
finally {
    Write-Report
    Write-Log "report written: $reportJson (status=$status exit=$exitCode)"
}
