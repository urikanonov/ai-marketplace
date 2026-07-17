# urikan-ai-marketplace Auto-Update Hook
# Runs on session start to update installed plugins from the urikan-ai-marketplace.
# Non-blocking by design: failures are caught and logged, never surfaced to the session.
#
# Works for both agents via -Agent: `copilot` (default) reads ~/.copilot and runs `copilot plugin
# update`; `claude` reads ~/.claude/settings.json enabledPlugins and runs `claude plugin update`.

param(
    [ValidateSet("copilot", "claude")]
    [string]$Agent = "copilot",
    # Persist a new update cadence and exit without running any updates. Accepts session|1h|24h or a
    # custom "<N>h" / "<N>" (N > 0 hours). The session-start hook reads it as the throttle interval.
    [string]$SetCadence,
    # Print the current (or default) cadence and exit without running any updates.
    [switch]$ShowCadence
)

$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"

# Default update cadence, in hours, when no cadence has been configured (see Get-CadenceHours).
$defaultCadenceHours = 24

# Per-agent config: the CLI binary, the config-home dir, and how installed marketplace plugins are
# enumerated. Copilot lists installed-plugins/<marketplace>/<plugin> dirs; Claude reads the
# enabledPlugins map in settings.json. Each agent logs and throttles under its own config home so a
# Copilot pass and a Claude pass never interfere.
if ($Agent -eq "claude") {
    $agentHome = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
    $cli = "claude"
    $throttleName = "$self.claude.last-run"
    $cadenceName = "$self.claude.cadence"
} else {
    $agentHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }
    $cli = "copilot"
    $throttleName = "$self.last-run"
    $cadenceName = "$self.cadence"
}

# Use the nested 2-arg Join-Path form; the 3-arg form is not supported on Windows PowerShell 5.1.
$pluginData = Join-Path $agentHome "plugin-data"
$logFile = Join-Path $pluginData "$self.log"
$throttleFile = Join-Path $pluginData $throttleName
$cadenceFile = Join-Path $pluginData $cadenceName

function Write-UpdaterLog($message) {
    try {
        $logDir = Split-Path -Parent $logFile
        if (-Not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        "$(Get-Date -Format o)  [$Agent] $message" | Add-Content -Path $logFile -Encoding utf8
    } catch { }
}

# Normalize a friendly cadence token to @{ cadence = <label>; hours = <double> }, or $null if invalid.
# session/each-session -> 0h (every session); hourly/1h -> 1h; daily/24h -> 24h; a bare/suffixed number
# (e.g. "6", "6h", "0.5h") is a custom interval in hours (must be > 0). 0 maps to "session".
function ConvertTo-CadenceSetting($value) {
    if ($null -eq $value) { return $null }
    $v = ("$value").Trim().ToLowerInvariant()
    $norm = ($v -replace '[\s_]+', '-')
    if ($norm -match '^(session|each-session|every-session|per-session|0|0h)$') { return @{ cadence = "session"; hours = [double]0 } }
    if ($norm -match '^(hourly|1|1h|1-hour|1-hours|every-1-hour|every-hour)$') { return @{ cadence = "1h"; hours = [double]1 } }
    if ($norm -match '^(daily|24|24h|24-hour|24-hours|every-24-hour|every-24-hours|every-day)$') { return @{ cadence = "24h"; hours = [double]24 } }
    $m = [regex]::Match($v, '^([0-9]+(?:\.[0-9]+)?)\s*h?$')
    if ($m.Success) {
        $hours = [double]::Parse($m.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
        if ($hours -gt 0) {
            $label = if ($hours -eq [math]::Floor($hours)) { "$([int]$hours)h" } else { "${hours}h" }
            return @{ cadence = $label; hours = $hours }
        }
    }
    return $null
}

# The configured throttle interval in hours; falls back to the default when unset or unreadable.
# A corrupt cadence file must never block updates, so any parse error uses the default.
function Get-CadenceHours {
    if (-Not (Test-Path $cadenceFile)) { return [double]$defaultCadenceHours }
    try {
        $raw = (Get-Content -Path $cadenceFile -Raw).Trim()
        if (-not $raw) { return [double]$defaultCadenceHours }
        $obj = $raw | ConvertFrom-Json
        if ($null -eq $obj.hours) { return [double]$defaultCadenceHours }
        $h = [double]$obj.hours
        if ($h -lt 0) { return [double]$defaultCadenceHours }
        return $h
    } catch {
        Write-UpdaterLog "cadence file unreadable; using default ${defaultCadenceHours}h: $($_.Exception.Message)"
        return [double]$defaultCadenceHours
    }
}

function Set-Cadence($value) {
    $setting = ConvertTo-CadenceSetting $value
    if ($null -eq $setting) {
        Write-Output "invalid cadence '$value'. Use: session | 1h | 24h | <N>h (custom interval, N > 0)."
        Write-UpdaterLog "set-cadence rejected invalid value '$value'."
        return
    }
    try {
        if (-Not (Test-Path $pluginData)) { New-Item -ItemType Directory -Force -Path $pluginData | Out-Null }
        ([ordered]@{ cadence = $setting.cadence; hours = $setting.hours } | ConvertTo-Json -Compress) |
            Set-Content -Path $cadenceFile -Encoding utf8
        $desc = if ($setting.hours -le 0) { "each session" } else { "every $($setting.hours) hour(s)" }
        Write-Output "urikan-ai-marketplace auto-update cadence set to $($setting.cadence) ($desc) for $Agent."
        Write-UpdaterLog "cadence set to $($setting.cadence) (hours=$($setting.hours))."
    } catch {
        Write-Output "failed to write cadence: $($_.Exception.Message)"
        Write-UpdaterLog "set-cadence write failed: $($_.Exception.Message)"
    }
}

function Show-Cadence {
    if (Test-Path $cadenceFile) {
        try {
            $obj = (Get-Content -Path $cadenceFile -Raw).Trim() | ConvertFrom-Json
            Write-Output ("cadence={0}; hours={1}; agent={2}; source=configured" -f $obj.cadence, $obj.hours, $Agent)
            return
        } catch { }
    }
    Write-Output ("cadence=${defaultCadenceHours}h; hours=$defaultCadenceHours; agent=$Agent; source=default")
}

# Cadence management modes: persist or print the cadence and exit without touching any plugin.
if ($PSBoundParameters.ContainsKey('SetCadence')) { Set-Cadence $SetCadence; return }
if ($ShowCadence) { Show-Cadence; return }

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

    # Last-run throttle: a corrupt or unreadable stamp must never block updates. The interval is the
    # user-configured cadence (default 24h); a cadence of 0 hours ("each session") disables it.
    $throttleHours = Get-CadenceHours
    try {
        if ($throttleHours -gt 0 -and (Test-Path $throttleFile)) {
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

    Write-UpdaterLog ("auto-update pass complete: {0} plugin(s) checked." -f @($plugins).Count)

    # Record the pass so the next session can throttle. Failure here is non-fatal.
    try {
        if (-Not (Test-Path $pluginData)) { New-Item -ItemType Directory -Force -Path $pluginData | Out-Null }
        ([datetimeoffset]::Now).ToString('o') | Set-Content -Path $throttleFile -Encoding utf8
    } catch { }
} catch {
    Write-UpdaterLog "auto-update aborted: $($_.Exception.Message)"
}
