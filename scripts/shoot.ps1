param([string]$Name = 'shot', [string]$Path = '/projects', [int]$Width = 1440, [int]$Height = 900, [int]$Wait = 6000)
# Headless Chrome screenshot of the local miniclaw UI, used for before/after comparisons in docs/redesign-log.md.
$out = Join-Path (Split-Path -Parent $PSScriptRoot) ".codex\redesign"
New-Item -ItemType Directory -Path $out -Force | Out-Null
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$file = Join-Path $out "$Name-$Width.png"
& $chrome --headless=new --disable-gpu --hide-scrollbars "--window-size=$Width,$Height" "--virtual-time-budget=$Wait" "--screenshot=$file" "http://127.0.0.1:9120$Path" 2>$null | Out-Null
Write-Output $file
