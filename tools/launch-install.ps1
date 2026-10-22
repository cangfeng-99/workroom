# 一次性启动器：以隐藏窗口分离启动 install-core.ps1，并立刻返回 PID
param(
    [string]$TaskRoot = 'D:\Users\28369\Desktop\AgentWorkspace'
)
$ErrorActionPreference = 'Stop'
$script = Join-Path $TaskRoot 'tools\install-core.ps1'
$launchJson = Join-Path $TaskRoot 'tasks\reports\install-core.launch.json'

$p = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$script) `
        -WorkingDirectory $TaskRoot -WindowStyle Hidden -PassThru

$obj = [ordered]@{
    task = 'T003R1'
    launcher_at = (Get-Date).ToString('o')
    spawned_pid = $p.Id
    script = $script
    window_style = 'Hidden'
}
$dir = Split-Path -Parent $launchJson
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
[System.IO.File]::WriteAllText($launchJson, ($obj | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
Write-Output "spawned_pid=$($p.Id)"
