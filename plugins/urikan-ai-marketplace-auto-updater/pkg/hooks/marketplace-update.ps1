# urikan-ai-marketplace Auto-Update Hook
# Runs on session start to update installed plugins from the urikan-ai-marketplace.
# Non-blocking by design: failures are caught and logged, never surfaced to the session.

$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"

# Respect COPILOT_HOME, fall back to ~/.copilot.
$copilotHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }

# Use the nested 2-arg Join-Path form; the 3-arg form is not supported on Windows PowerShell 5.1.
$installed = Join-Path (Join-Path $copilotHome "installed-plugins") $marketplace
$pluginData = Join-Path $copilotHome "plugin-data"
$logFile = Join-Path $pluginData "$self.log"
$throttleFile = Join-Path $pluginData "$self.last-run"

# Skip the whole update pass when the previous pass ran within this many hours.
$throttleHours = 20

function Write-UpdaterLog($message) {
    try {
        $logDir = Split-Path -Parent $logFile
        if (-Not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        "$(Get-Date -Format o)  $message" | Add-Content -Path $logFile -Encoding utf8
    } catch { }
}

try {
    if (-Not (Test-Path $installed)) { return }

    # Last-run throttle: a corrupt or unreadable stamp must never block updates.
    try {
        if (Test-Path $throttleFile) {
            $raw = (Get-Content -Path $throttleFile -Raw).Trim()
            $last = [datetimeoffset]::Parse($raw, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
            $elapsedHours = ([datetimeoffset]::Now - $last).TotalHours
            if ($elapsedHours -ge 0 -and $elapsedHours -lt $throttleHours) {
                Write-UpdaterLog ("skipping auto-update; last run {0:0.0}h ago (throttle {1}h)." -f $elapsedHours, $throttleHours)
                return
            }
        }
    } catch {
        Write-UpdaterLog "throttle check failed; proceeding: $($_.Exception.Message)"
    }

    if (-Not (Get-Command copilot -ErrorAction SilentlyContinue)) {
        Write-UpdaterLog "copilot CLI not found on PATH; skipping auto-update."
        return
    }

    # Sort by name so the log order is deterministic across platforms.
    Get-ChildItem -Path $installed -Directory |
        Sort-Object Name |
        Where-Object { $_.Name -ne $self } |
        ForEach-Object {
            $plugin = $_.Name
            try {
                $output = copilot plugin update "$plugin@$marketplace" 2>&1
                if ($LASTEXITCODE -ne 0) {
                    Write-UpdaterLog "update failed for $plugin (exit $LASTEXITCODE): $output"
                }
            } catch {
                Write-UpdaterLog "update errored for $plugin : $($_.Exception.Message)"
            }
        }

    # Record the pass so the next session can throttle. Failure here is non-fatal.
    try {
        if (-Not (Test-Path $pluginData)) { New-Item -ItemType Directory -Force -Path $pluginData | Out-Null }
        ([datetimeoffset]::Now).ToString('o') | Set-Content -Path $throttleFile -Encoding utf8
    } catch { }
} catch {
    Write-UpdaterLog "auto-update aborted: $($_.Exception.Message)"
}
