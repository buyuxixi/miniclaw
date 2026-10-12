param(
    [string]$Checkpoint = 'D:/model/laya-business-advisory/round-07-formal-seven',
    [string]$Python = 'D:/model/laya-runtime/.venv/Scripts/python.exe',
    [int]$Port = 8771
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gates = Join-Path $projectRoot 'config/laya/round07-joint-gates.json'
foreach ($layaRequired in @($Python, $Checkpoint, $gates)) {
    if (-not (Test-Path -LiteralPath $layaRequired)) { throw "Laya runtime missing: $layaRequired" }
}
$env:PYTHONUTF8 = '1'
& $Python (Join-Path $PSScriptRoot 'serve_laya_formal.py') --checkpoint $Checkpoint --gates $gates --port $Port
if ($LASTEXITCODE -ne 0) { throw "Laya startup failed with exit code $LASTEXITCODE" }
