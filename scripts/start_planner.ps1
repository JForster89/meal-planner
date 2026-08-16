# Launcher for the desktop shortcut.
#
# Starts the meal planner if it isn't already running, waits for it to answer,
# then opens the browser.
#
# Startup takes a few seconds with no window to look at, which invites an
# impatient second click. A mutex makes that harmless: while one launcher is
# still working, another exits immediately rather than opening a second tab.
# A deliberate click later - once the first has finished and released the
# mutex - still opens the app, which is what you'd want.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$port = 5000
$url  = "http://127.0.0.1:$port/"
$py   = Join-Path $root 'venv\Scripts\pythonw.exe'

function Test-Listening {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# Session-local, so it needs no elevation.
$mutex = New-Object System.Threading.Mutex($false, 'MealPlannerLauncher')
if (-not $mutex.WaitOne(0)) {
    # Another launcher is mid-flight; it will open the browser when ready.
    exit 0
}

try {
    if (-not (Test-Path $py)) {
        Write-Host "Virtual environment missing at $root\venv"
        Write-Host "Run:  python -m venv venv"
        Write-Host "      venv\Scripts\pip install -r requirements-dev.txt"
        Read-Host "Press Enter to close"
        exit 1
    }

    if (-not (Test-Listening)) {
        # pythonw.exe runs without a console, so nothing lingers on screen.
        Start-Process -FilePath $py -ArgumentList (Join-Path $root 'app.py') `
                      -WorkingDirectory $root -WindowStyle Hidden

        $deadline = (Get-Date).AddSeconds(25)
        while (-not (Test-Listening) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 400
        }

        if (-not (Test-Listening)) {
            Write-Host "The planner did not start within 25 seconds."
            Write-Host "To see the error, run:"
            Write-Host "  $root\venv\Scripts\python.exe $root\app.py"
            Read-Host "Press Enter to close"
            exit 1
        }
    }

    Start-Process $url
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
