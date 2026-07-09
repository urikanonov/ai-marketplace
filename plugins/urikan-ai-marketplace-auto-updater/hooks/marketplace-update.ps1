# urikan-ai-marketplace Auto-Update Hook
# Runs on session start to check for plugin updates from the urikan-ai-marketplace.
# Errors are silently suppressed: intentional to never block session startup.

$ErrorActionPreference = "SilentlyContinue"
$marketplace = "urikan-ai-marketplace"

# Respect COPILOT_HOME, fall back to ~/.copilot
$copilotHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }
$dir = Join-Path $copilotHome "installed-plugins" $marketplace

if (-Not (Test-Path $dir)) { return }

Get-ChildItem -Path $dir -Directory |
    Where-Object { $_.Name -ne "urikan-ai-marketplace-auto-updater" } |
    ForEach-Object { copilot plugin update "$($_.Name)@$marketplace" 2>$null }

return
