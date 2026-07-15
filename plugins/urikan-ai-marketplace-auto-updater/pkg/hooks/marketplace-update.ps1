# urikan-ai-marketplace Auto-Update Hook
# Runs on session start to update installed plugins from the urikan-ai-marketplace.
# Non-blocking by design: failures are caught and logged, never surfaced to the session.
#
# Works for both agents via -Agent: `copilot` (default) reads ~/.copilot and runs `copilot plugin
# update`; `claude` reads ~/.claude/settings.json enabledPlugins and runs `claude plugin update`.

param(
    [ValidateSet("copilot", "claude")]
    [string]$Agent = "copilot"
)

$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"

# Skip the whole update pass when the previous pass ran within this many hours.
$throttleHours = 20

# Per-agent config: the CLI binary, the config-home dir, and how installed marketplace plugins are
# enumerated. Copilot lists installed-plugins/<marketplace>/<plugin> dirs; Claude reads the
# enabledPlugins map in settings.json. Each agent logs and throttles under its own config home so a
# Copilot pass and a Claude pass never interfere.
if ($Agent -eq "claude") {
    $agentHome = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
    $cli = "claude"
    $throttleName = "$self.claude.last-run"
} else {
    $agentHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }
    $cli = "copilot"
    $throttleName = "$self.last-run"
}

# Use the nested 2-arg Join-Path form; the 3-arg form is not supported on Windows PowerShell 5.1.
$pluginData = Join-Path $agentHome "plugin-data"
$logFile = Join-Path $pluginData "$self.log"
$throttleFile = Join-Path $pluginData $throttleName

function Write-UpdaterLog($message) {
    try {
        $logDir = Split-Path -Parent $logFile
        if (-Not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        "$(Get-Date -Format o)  [$Agent] $message" | Add-Content -Path $logFile -Encoding utf8
    } catch { }
}

# The installed urikan-ai-marketplace plugins for this agent, excluding self, name-sorted so the log
# order is deterministic across platforms.
function Get-InstalledPlugins {
    if ($Agent -eq "claude") {
        $settings = Join-Path $agentHome "settings.json"
        if (-Not (Test-Path $settings)) { return @() }
        try {
            $json = Get-Content -Path $settings -Raw | ConvertFrom-Json
        } catch {
            Write-UpdaterLog "could not parse settings.json; skipping: $($_.Exception.Message)"
            return @()
        }
        $enabled = $json.PSObject.Properties['enabledPlugins']
        if ($null -eq $enabled -or $null -eq $enabled.Value) { return @() }
        $names = @()
        foreach ($prop in $enabled.Value.PSObject.Properties) {
            if ($prop.Value -eq $true -and $prop.Name -like "*@$marketplace") {
                $names += ($prop.Name -replace "@$marketplace$", "")
            }
        }
        return @($names | Where-Object { $_ -ne $self } | Sort-Object -Unique)
    } else {
        $installed = Join-Path (Join-Path $agentHome "installed-plugins") $marketplace
        if (-Not (Test-Path $installed)) { return @() }
        return @(Get-ChildItem -Path $installed -Directory |
            Sort-Object Name |
            Where-Object { $_.Name -ne $self } |
            ForEach-Object { $_.Name })
    }
}

try {
    $plugins = Get-InstalledPlugins
    if (@($plugins).Count -eq 0) { return }

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

    if (-Not (Get-Command $cli -ErrorAction SilentlyContinue)) {
        Write-UpdaterLog "$cli CLI not found on PATH; skipping auto-update."
        return
    }

    foreach ($plugin in @($plugins)) {
        try {
            $output = & $cli plugin update "$plugin@$marketplace" 2>&1
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
