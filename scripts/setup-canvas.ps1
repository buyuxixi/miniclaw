$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'runtime.ps1')
$canvasRuntime = Get-MiniclawRuntime -ProjectRoot $projectRoot
$canvasListeners = Get-NetTCPConnection -LocalPort 9120 -State Listen -ErrorAction SilentlyContinue
foreach ($canvasListener in $canvasListeners) {
    $canvasProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($canvasListener.OwningProcess)"
    if ($canvasProcess.CommandLine -like '*miniclaw*web_entry.py*') { throw 'Stop the local miniclaw service before installing Python dependencies; Windows locks loaded extension files.' }
}
& $canvasRuntime.uv pip install --python (Join-Path $projectRoot '.venv\Scripts\python.exe') -r (Join-Path $projectRoot 'canvas-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Local SAM dependency installation failed' }
Write-Host 'Local SAM dependencies installed. Prepare model weights from the image workspace.'
