function Get-MiniclawRuntime {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $localPath = Join-Path $ProjectRoot 'runtime.local.json'
    $local = if (Test-Path -LiteralPath $localPath) {
        Get-Content -Raw -LiteralPath $localPath | ConvertFrom-Json
    } else { $null }

    $nodePath = if ($local -and $local.node) { $local.node } else {
        (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    }
    $uvPath = if ($local -and $local.uv) { $local.uv } else {
        (Get-Command uv.exe -ErrorAction SilentlyContinue).Source
    }
    $npmCli = if ($local -and $local.npm_cli) { $local.npm_cli } else {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($npmCommand) {
            Join-Path (Split-Path -Parent $npmCommand.Source) 'node_modules\npm\bin\npm-cli.js'
        }
    }
    foreach ($entry in @(
        @{ Name = 'Node.js'; Path = $nodePath },
        @{ Name = 'npm CLI'; Path = $npmCli },
        @{ Name = 'uv'; Path = $uvPath }
    )) {
        if (-not $entry.Path -or -not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) {
            throw "Missing $($entry.Name). Install the README prerequisites or configure runtime.local.json."
        }
    }
    $nodeVersion = & $nodePath -p 'process.versions.node'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot run Node.js' }
    if ([version]$nodeVersion -lt [version]'22.12.0') {
        throw "Node.js $nodeVersion is unsupported; use Node.js 22.12+ or 24 LTS."
    }
    [pscustomobject]@{ node = $nodePath; npm_cli = $npmCli; uv = $uvPath }
}
