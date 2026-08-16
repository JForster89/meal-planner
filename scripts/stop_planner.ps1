# Stops the meal planner started by start_planner.ps1.
#
# It runs under pythonw.exe with no console, so there's no window to close -
# this finds whatever is listening on the port and stops it.

$port = 5000
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if (-not $conns) {
    Write-Host "The meal planner isn't running."
    Start-Sleep -Seconds 2
    exit 0
}

# Note: $pid is a reserved automatic variable in PowerShell, hence $procId.
foreach ($procId in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    # Only ever stop a Python process, so a mistyped port can't kill something else.
    if ($proc -and $proc.ProcessName -match 'python') {
        Stop-Process -Id $procId -Force
        Write-Host "Stopped the meal planner (pid $procId)."
    } else {
        Write-Host "Port $port is used by '$($proc.ProcessName)', not the planner. Left alone."
    }
}

Start-Sleep -Seconds 2
