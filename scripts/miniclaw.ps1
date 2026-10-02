param(
    [ValidateSet('prepare', 'web', 'dashboard', 'chat', 'build', 'build-upstream', 'test')]
    [string]$Action = 'web',
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'hermes-agent'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'runtime.ps1')
$runtimeConfig = Get-MiniclawRuntime -ProjectRoot $projectRoot
foreach ($requiredPath in @($pythonPath, $runtimeConfig.node)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Runtime missing: $requiredPath. Run .\scripts\setup.ps1 first." }
}
$env:PATH = (Split-Path -Parent $runtimeConfig.node) + ';' + (Join-Path $projectRoot '.venv\Scripts') + ';' + (Split-Path -Parent $runtimeConfig.uv) + ';' + $env:PATH
$env:HERMES_HOME = Join-Path $projectRoot '.hermes'
$env:HERMES_PYTHON = $pythonPath
$env:PYTHONUTF8 = '1'
if ($Port -eq 0) { $Port = if ($Action -eq 'dashboard') { 9119 } else { 9120 } }
Push-Location $sourceRoot
try {
    if ($Action -eq 'prepare') {
        & $pythonPath (Join-Path $PSScriptRoot 'prepare.py')
        if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed' }
        $pluginsRoot = Join-Path $env:HERMES_HOME 'plugins'
        New-Item -ItemType Directory -Path $pluginsRoot -Force | Out-Null
        $pluginLink = Join-Path $pluginsRoot 'miniclaw-files'
        $pluginSource = Join-Path $projectRoot 'plugins\miniclaw-files'
        if (-not (Test-Path -LiteralPath $pluginLink)) {
            New-Item -ItemType Junction -Path $pluginLink -Target $pluginSource | Out-Null
        } elseif ((Get-Item -LiteralPath $pluginLink).Target -notcontains $pluginSource) {
            throw "Existing plugin path differs: $pluginLink"
        }
    } elseif ($Action -eq 'build') {
        Set-Location (Join-Path $projectRoot 'frontend')
        & $runtimeConfig.node $runtimeConfig.npm_cli run build
    } elseif ($Action -eq 'build-upstream') {
        & $runtimeConfig.node $runtimeConfig.npm_cli run build --workspace web
        if ($LASTEXITCODE -ne 0) { throw 'Web build failed' }
        & $runtimeConfig.node $runtimeConfig.npm_cli run build --workspace ui-tui
    } elseif ($Action -eq 'test') {
        & $pythonPath (Join-Path $PSScriptRoot 'verify_offline.py')
        if ($LASTEXITCODE -ne 0) { throw 'Offline checks failed' }
        Set-Location (Join-Path $projectRoot 'frontend')
        & $runtimeConfig.node $runtimeConfig.npm_cli test
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $env:HERMES_HOME 'config.yaml'))) { throw 'Run .\scripts\miniclaw.ps1 prepare first' }
        Set-Location (Join-Path $projectRoot 'workspace')
        $toolsetPin = & $pythonPath (Join-Path $PSScriptRoot 'read_toolset_pin.py')
        if ($LASTEXITCODE -ne 0 -or $toolsetPin -isnot [string] -or $toolsetPin -notmatch '^[\w.:-]+(,[\w.:-]+)*$') { throw 'Invalid tool selection; backend was not started' }
        $env:HERMES_TUI_TOOLSETS = $toolsetPin.Trim()
        if ($Action -eq 'chat') {
            & $pythonPath -m hermes_cli.main chat
        } else {
            if ($Action -eq 'web') {
                $env:HERMES_WEB_DIST = Join-Path $projectRoot 'frontend\dist'
                if (-not (Test-Path -LiteralPath (Join-Path $env:HERMES_WEB_DIST 'index.html'))) { throw 'Run .\scripts\miniclaw.ps1 build first' }
            } else {
                Remove-Item Env:HERMES_WEB_DIST -ErrorAction SilentlyContinue
            }
            & $pythonPath -m hermes_cli.main dashboard --host 127.0.0.1 --port $Port --no-open --skip-build --isolated
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "miniclaw $Action failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
