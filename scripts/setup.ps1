param([string]$PythonVersion = '3.12')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'hermes-agent'
. (Join-Path $PSScriptRoot 'runtime.ps1')
$runtime = Get-MiniclawRuntime -ProjectRoot $projectRoot

if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
& git -C $projectRoot submodule update --init --recursive --depth 1
if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize Hermes submodule' }
$upstream = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'UPSTREAM.json') | ConvertFrom-Json
$actualCommit = & git -C $sourceRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualCommit.Trim() -ne $upstream.commit) {
    throw 'Hermes commit differs from UPSTREAM.json; refusing to install a different harness.'
}

# Keep Python dependencies in the outer project; do not alter the global Python.
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    & $runtime.uv sync --project $sourceRoot --python $PythonVersion --frozen --extra web --extra dev --no-default-groups
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
} finally {
    if ($null -eq $previousEnvironment) {
        Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    } else { $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment }
}

Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $runtime.node $runtime.npm_cli ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
} finally { Pop-Location }
& (Join-Path $PSScriptRoot 'miniclaw.ps1') prepare
Write-Host 'Dependencies and missing local configuration are ready. Set your local Key, then run build and web.'
