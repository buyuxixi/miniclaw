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
$clarificationPatch = Join-Path $projectRoot 'patches\hermes-chat-clarification-v1.patch'
$recoveryPatch = Join-Path $projectRoot 'patches\hermes-chat-recovery-v2.patch'
$tracePatch = Join-Path $projectRoot 'patches\hermes-chat-trace-v3.patch'
& git -C $sourceRoot apply --reverse --check $tracePatch 2>$null
$traceInstalled = $LASTEXITCODE -eq 0
if (-not $traceInstalled) {
& git -C $sourceRoot apply --reverse --check $recoveryPatch 2>$null
$recoveryInstalled = $LASTEXITCODE -eq 0
if (-not $recoveryInstalled) {
    & git -C $sourceRoot apply --reverse --check $clarificationPatch 2>$null
    if ($LASTEXITCODE -ne 0) {
        & git -C $sourceRoot apply --check $clarificationPatch
        if ($LASTEXITCODE -ne 0) { throw 'Hermes clarification compatibility patch conflicts with local changes; no files were replaced.' }
        & git -C $sourceRoot apply $clarificationPatch
        if ($LASTEXITCODE -ne 0) { throw 'Could not apply Hermes clarification compatibility patch' }
    }
    & git -C $sourceRoot apply --check $recoveryPatch
    if ($LASTEXITCODE -ne 0) { throw 'Hermes recovery compatibility patch conflicts with local changes; no files were replaced.' }
    & git -C $sourceRoot apply $recoveryPatch
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply Hermes recovery compatibility patch' }
}

    & git -C $sourceRoot apply --check $tracePatch
    if ($LASTEXITCODE -ne 0) { throw 'Hermes trace compatibility patch conflicts with local changes; no files were replaced.' }
    & git -C $sourceRoot apply $tracePatch
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply Hermes trace compatibility patch' }
}

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

& $runtime.uv pip install --python (Join-Path $projectRoot '.venv\Scripts\python.exe') -r (Join-Path $projectRoot 'document-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Attachment parser dependency installation failed' }

Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $runtime.node $runtime.npm_cli ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
} finally { Pop-Location }
& (Join-Path $PSScriptRoot 'miniclaw.ps1') prepare
Write-Host 'Dependencies and missing local configuration are ready. Set your local Key, then run build and web.'
