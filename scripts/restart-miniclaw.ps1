param(
    [string]$Workspace = '',
    [Nullable[int]]$ImageCalls = $null
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$startScript = Join-Path $PSScriptRoot 'miniclaw.ps1'
$baseUrl = 'http://127.0.0.1:9120'
$logFolder = Join-Path $projectRoot '.codex\verification\image-budget-2026-10-08'

function Read-ProjectBudget {
    $page = (Invoke-WebRequest -Uri ($baseUrl + '/studio/index.html') -UseBasicParsing).Content
    $match = [regex]::Match($page, 'window\.WORKSPACE_TOKEN\s*=\s*("(?:[^"\\]|\\.)*")')
    if (-not $match.Success) { throw 'Cannot read the local session token.' }
    $localHeaders = @{ 'X-Hermes-Session-Token' = ($match.Groups[1].Value | ConvertFrom-Json) }
    $budgetUrl = $baseUrl + '/api/workspaces/' + [uri]::EscapeDataString($Workspace) + '/budget'
    $budget = Invoke-RestMethod -Uri $budgetUrl -Headers $localHeaders
    return @{ Budget = $budget; Headers = $localHeaders; Url = $budgetUrl }
}

try {
    if ($null -ne $ImageCalls -and ($ImageCalls -lt 0 -or $ImageCalls -gt 1000)) {
        throw 'ImageCalls must be between 0 and 1000.'
    }
    if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $startScript)) {
        throw 'The miniclaw runtime or launcher is missing.'
    }
    # Validate the launcher dependencies before stopping a working process.
    . (Join-Path $PSScriptRoot 'runtime.ps1')
    $null = Get-MiniclawRuntime -ProjectRoot $projectRoot
    $status = Invoke-RestMethod -Uri ($baseUrl + '/api/status')
    if ($status.active_agents -or $status.active_sessions -or $status.gateway_busy) {
        throw 'There is active chat work. Wait for it to finish before restarting.'
    }
    $jobProbe = @'
import json,sqlite3,sys
from pathlib import Path
database=Path(sys.argv[1])/'.hermes'/'miniclaw.sqlite3'
with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
    active=sum(json.loads(row[0]).get('state') in ('queued','running','submitting')
        for table in ('canvas_jobs','studio_video_jobs','studio_video_renders')
        for row in db.execute('select data from '+table))
print(active)
'@
    $activeJobs = & $pythonPath -c $jobProbe $projectRoot
    if ($LASTEXITCODE -ne 0 -or $activeJobs -ne '0') {
        throw 'Generation tasks are active or their state cannot be read. Restart cancelled.'
    }
    $listener = @(Get-NetTCPConnection -LocalPort 9120 -State Listen)
    if ($listener.Count -ne 1) { throw 'Unexpected listener count on port 9120.' }
    $oldProcessId = $listener[0].OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $oldProcessId"
    if (-not $process.CommandLine.Contains((Join-Path $PSScriptRoot 'web_entry.py')) -or
        $process.CommandLine -notmatch 'dashboard.*--port 9120') {
        throw 'Port 9120 belongs to a different application. Restart cancelled.'
    }
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    Write-Host 'Restarting the local miniclaw backend...'
    Stop-Process -Id $oldProcessId
    $launcherShell = (Get-Process -Id $PID).Path
    $null = Start-Process -FilePath $launcherShell -ArgumentList @('-NoProfile', '-File', ('"' + $startScript + '"'), 'web', '-Port', '9120') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'manual-restart.stdout.log') -RedirectStandardError (Join-Path $logFolder 'manual-restart.stderr.log') -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $newListener = Get-NetTCPConnection -LocalPort 9120 -State Listen -ErrorAction Stop
            if ($newListener.OwningProcess -eq $oldProcessId) { continue }
            $null = Invoke-RestMethod -Uri ($baseUrl + '/api/status') -TimeoutSec 2
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) { throw "Startup did not complete. Check the logs in $logFolder" }
    if ($Workspace) {
        $connection = Read-ProjectBudget
        if ($connection.Budget.max_calls -ne 1000) { throw 'The new budget API was not loaded.' }
        if ($null -ne $ImageCalls) {
            $payload = @{ calls = [int]$ImageCalls } | ConvertTo-Json -Compress
            $null = Invoke-RestMethod -Uri $connection.Url -Method Post -Headers $connection.Headers -ContentType 'application/json' -Body $payload
            $verified = (Read-ProjectBudget).Budget
            if ($verified.limit -ne $ImageCalls) { throw 'The saved budget could not be verified.' }
            Write-Host "Budget saved: total $($verified.limit), reserved $($verified.reserved), remaining $($verified.remaining)."
        }
    }
    Write-Host 'Ready. Refresh the miniclaw page. No cloud generation was requested.'
} catch {
    Write-Host ('Restart failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
