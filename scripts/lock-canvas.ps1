# Resolve optional canvas dependencies against the pinned Hermes environment.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'runtime.ps1')
$canvasRuntime = Get-MiniclawRuntime -ProjectRoot $projectRoot
$canvasConstraints = Join-Path $projectRoot '.codex\verification\canvas-upstream-constraints.txt'
New-Item -ItemType Directory -Path (Split-Path -Parent $canvasConstraints) -Force | Out-Null
& $canvasRuntime.uv export --project (Join-Path $projectRoot 'hermes-agent') --frozen --extra web --extra dev --no-default-groups --no-emit-project --no-hashes -o $canvasConstraints --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cannot export pinned Hermes constraints' }
& $canvasRuntime.uv pip compile (Join-Path $projectRoot 'canvas-requirements.in') --python (Join-Path $projectRoot '.venv\Scripts\python.exe') --constraint $canvasConstraints -o (Join-Path $projectRoot 'canvas-requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'Canvas dependency locking failed' }
