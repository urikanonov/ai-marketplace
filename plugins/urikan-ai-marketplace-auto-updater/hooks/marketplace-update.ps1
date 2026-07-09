# urikan-ai-marketplace Auto-Update Hook
# Runs on session start to update installed plugins from the urikan-ai-marketplace.
# Non-blocking by design: failures are caught and logged, never surfaced to the session.

$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"

# Respect COPILOT_HOME, fall back to ~/.copilot.
$copilotHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }

# Use the nested 2-arg Join-Path form; the 3-arg form is not supported on Windows PowerShell 5.1.
$installed = Join-Path (Join-Path $copilotHome "installed-plugins") $marketplace
$logFile = Join-Path (Join-Path $copilotHome "plugin-data") "$self.log"

function Write-UpdaterLog($message) {
    try {
        $logDir = Split-Path -Parent $logFile
        if (-Not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        "$(Get-Date -Format o)  $message" | Add-Content -Path $logFile -Encoding utf8
    } catch { }
}

try {
    if (-Not (Test-Path $installed)) { return }
    if (-Not (Get-Command copilot -ErrorAction SilentlyContinue)) {
        Write-UpdaterLog "copilot CLI not found on PATH; skipping auto-update."
        return
    }

    Get-ChildItem -Path $installed -Directory |
        Where-Object { $_.Name -ne $self } |
        ForEach-Object {
            try { copilot plugin update "$($_.Name)@$marketplace" 2>&1 | Out-Null }
            catch { Write-UpdaterLog "update failed for $($_.Name): $($_.Exception.Message)" }
        }
} catch {
    Write-UpdaterLog "auto-update aborted: $($_.Exception.Message)"
}
