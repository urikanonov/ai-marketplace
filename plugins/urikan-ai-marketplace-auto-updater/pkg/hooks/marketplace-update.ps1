# urikan-ai-marketplace Auto-Update Hook
# Updates installed marketplace plugins on session start and exposes read-only health diagnostics.

param(
    [ValidateSet("copilot", "claude")]
    [string]$Agent = "copilot",
    [ValidateSet("update", "health")]
    [string]$Mode = "update"
)

$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"
$defaultThrottleHours = 24
$defaultCatalogCheckHours = 1
$maxCadenceHours = 87600
$envThrottleVar = "URIKAN_AI_MARKETPLACE_THROTTLE_HOURS"
$maxLogBytes = 262144
$maxLogArchives = 3

if ($Agent -eq "claude") {
    $agentHome = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
    $cli = "claude"
    $agentSuffix = ".claude"
} else {
    $agentHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME ".copilot" }
    $cli = "copilot"
    $agentSuffix = ""
}

$pluginData = Join-Path $agentHome "plugin-data"
$logFile = Join-Path $pluginData "$self.log"
$throttleFile = Join-Path $pluginData "$self$agentSuffix.last-run"
$catalogStampFile = Join-Path $pluginData "$self$agentSuffix.last-catalog-check"
$configFile = Join-Path $pluginData "$self.config.json"
$statusFile = Join-Path $pluginData "$self.status.json"
$lockFile = Join-Path $pluginData "$self.lock"
$packageRoot = Split-Path -Parent $PSScriptRoot

function Ensure-PluginData {
    if (-Not (Test-Path $pluginData)) {
        New-Item -ItemType Directory -Force -Path $pluginData | Out-Null
    }
}

function Rotate-UpdaterLog {
    try {
        if (-Not (Test-Path $logFile) -or (Get-Item $logFile).Length -lt $maxLogBytes) { return }
        for ($i = $maxLogArchives; $i -ge 1; $i--) {
            $source = if ($i -eq 1) { $logFile } else { "$logFile.$($i - 1)" }
            $destination = "$logFile.$i"
            if (Test-Path $source) { Move-Item -Path $source -Destination $destination -Force }
        }
    } catch { }
}

function Write-UpdaterLog($message, [switch]$NoRotate) {
    try {
        Ensure-PluginData
        if (-Not $NoRotate) { Rotate-UpdaterLog }
        "$(Get-Date -Format o)  [$Agent] $message" | Add-Content -Path $logFile -Encoding utf8
    } catch { }
}

function Read-JsonFile($path) {
    if (-Not (Test-Path $path)) { return $null }
    try {
        return Get-Content -Path $path -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-ValidCadence([double]$value) {
    return $value -ge 0 -and $value -le $maxCadenceHours -and
        -not [double]::IsNaN($value) -and -not [double]::IsInfinity($value)
}

function Write-StatusAtomic($status) {
    $tempFile = "$statusFile.$([Guid]::NewGuid().ToString('N')).tmp"
    $backupFile = "$statusFile.$([Guid]::NewGuid().ToString('N')).bak"
    try {
        Ensure-PluginData
        $json = $status | ConvertTo-Json -Depth 8
        $utf8 = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($tempFile, $json, $utf8)
        if (Test-Path $statusFile) {
            [IO.File]::Replace($tempFile, $statusFile, $backupFile, $true)
        } else {
            [IO.File]::Move($tempFile, $statusFile)
        }
    } catch {
        Write-UpdaterLog "status write failed: $($_.Exception.Message)" -NoRotate
    } finally {
        if (Test-Path $tempFile) { Remove-Item -Path $tempFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $backupFile) { Remove-Item -Path $backupFile -Force -ErrorAction SilentlyContinue }
    }
}

function Get-ConfigNumber($config, $propertyName, [double]$defaultValue, [string]$environmentName = "", [switch]$NoLog) {
    $parsed = 0.0
    $numStyle = [Globalization.NumberStyles]::Float
    $invariant = [Globalization.CultureInfo]::InvariantCulture

    if ($environmentName) {
        $environmentValue = [Environment]::GetEnvironmentVariable($environmentName)
        if (-Not [string]::IsNullOrWhiteSpace($environmentValue)) {
            if ([double]::TryParse($environmentValue.Trim(), $numStyle, $invariant, [ref]$parsed) -and
                (Test-ValidCadence $parsed)) {
                return $parsed
            }
            if (-Not $NoLog) { Write-UpdaterLog "ignoring invalid $environmentName='$environmentValue'; using config/default." }
        }
    }

    if ($null -ne $config) {
        $property = $config.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            $value = $property.Value
            if ($value -is [bool]) {
                if (-Not $NoLog) { Write-UpdaterLog "ignoring invalid $propertyName in config; using default ${defaultValue}h." }
            } elseif ($value -is [ValueType]) {
                $number = [double]$value
                if (Test-ValidCadence $number) { return $number }
            } elseif ([double]::TryParse([string]$value, $numStyle, $invariant, [ref]$parsed) -and
                (Test-ValidCadence $parsed)) {
                return $parsed
            }
            if (-Not $NoLog) { Write-UpdaterLog "ignoring invalid $propertyName in config; using default ${defaultValue}h." }
        }
    }
    return $defaultValue
}

function Get-ConfiguredCadences([switch]$NoLog) {
    $config = $null
    if (Test-Path $configFile) {
        try {
            $config = Get-Content -Path $configFile -Raw | ConvertFrom-Json
        } catch {
            if (-Not $NoLog) { Write-UpdaterLog "could not parse config ${configFile}; using defaults: $($_.Exception.Message)" }
        }
    }
    return [ordered]@{
        throttleHours = Get-ConfigNumber $config "throttleHours" $defaultThrottleHours $envThrottleVar -NoLog:$NoLog
        catalogCheckHours = Get-ConfigNumber $config "catalogCheckHours" $defaultCatalogCheckHours -NoLog:$NoLog
    }
}

function Get-ClaudePluginStates {
    $settings = Join-Path $agentHome "settings.json"
    if (-Not (Test-Path $settings)) { return @() }
    try {
        $json = Get-Content -Path $settings -Raw | ConvertFrom-Json
    } catch {
        Write-UpdaterLog "could not parse settings.json; skipping: $($_.Exception.Message)"
        return @()
    }
    $enabled = $json.PSObject.Properties["enabledPlugins"]
    if ($null -eq $enabled -or $null -eq $enabled.Value) { return @() }
    $states = @()
    foreach ($property in $enabled.Value.PSObject.Properties) {
        if ($property.Name -like "*@$marketplace") {
            $states += [ordered]@{
                name = ($property.Name -replace "@$marketplace$", "")
                enabled = ($property.Value -eq $true)
            }
        }
    }
    return @($states | Sort-Object { $_.name })
}

function Get-InstalledPlugins {
    if ($Agent -eq "claude") {
        return @(Get-ClaudePluginStates | Where-Object { $_.enabled } | ForEach-Object { $_.name })
    }

    $installed = Join-Path (Join-Path $agentHome "installed-plugins") $marketplace
    if (-Not (Test-Path $installed)) { return @() }
    return @(Get-ChildItem -Path $installed -Directory | ForEach-Object { $_.Name } | Sort-Object -Unique)
}

function Get-ManifestVersion($root) {
    if ([string]::IsNullOrWhiteSpace($root)) { return $null }
    $manifestPaths = @(
        "plugin.json",
        (Join-Path ".claude-plugin" "plugin.json")
    )
    foreach ($relative in $manifestPaths) {
        $manifest = Join-Path $root $relative
        $json = Read-JsonFile $manifest
        if ($null -ne $json -and $null -ne $json.version) { return [string]$json.version }
    }
    return $null
}

function Get-SemVerParts([string]$version) {
    if ($version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$') {
        return $null
    }
    return @{
        core = @($Matches[1], $Matches[2], $Matches[3])
        prerelease = if ($Matches[4]) { @($Matches[4] -split '\.') } else { @() }
    }
}

function Compare-NumericIdentifier([string]$left, [string]$right) {
    if ($left.Length -ne $right.Length) {
        if ($left.Length -gt $right.Length) { return 1 }
        return -1
    }
    return [Math]::Sign([string]::CompareOrdinal($left, $right))
}

function Compare-SemVer([string]$left, [string]$right) {
    $leftParts = Get-SemVerParts $left
    $rightParts = Get-SemVerParts $right
    if ($null -eq $leftParts -or $null -eq $rightParts) {
        if ($null -eq $leftParts -and $null -eq $rightParts) {
            return [Math]::Sign([string]::CompareOrdinal($left, $right))
        }
        if ($null -ne $leftParts) { return 1 }
        return -1
    }
    for ($i = 0; $i -lt 3; $i++) {
        $comparison = Compare-NumericIdentifier $leftParts.core[$i] $rightParts.core[$i]
        if ($comparison -ne 0) { return $comparison }
    }
    if ($leftParts.prerelease.Count -eq 0 -or $rightParts.prerelease.Count -eq 0) {
        if ($leftParts.prerelease.Count -eq $rightParts.prerelease.Count) { return 0 }
        if ($leftParts.prerelease.Count -eq 0) { return 1 }
        return -1
    }
    $shared = [Math]::Min($leftParts.prerelease.Count, $rightParts.prerelease.Count)
    for ($i = 0; $i -lt $shared; $i++) {
        $leftNumeric = $leftParts.prerelease[$i] -match '^(0|[1-9]\d*)$'
        $rightNumeric = $rightParts.prerelease[$i] -match '^(0|[1-9]\d*)$'
        if ($leftNumeric -and $rightNumeric) {
            $comparison = Compare-NumericIdentifier $leftParts.prerelease[$i] $rightParts.prerelease[$i]
        } elseif ($leftNumeric -ne $rightNumeric) {
            $comparison = if ($leftNumeric) { -1 } else { 1 }
        } else {
            $comparison = [Math]::Sign([string]::CompareOrdinal($leftParts.prerelease[$i], $rightParts.prerelease[$i]))
        }
        if ($comparison -ne 0) { return $comparison }
    }
    return [Math]::Sign($leftParts.prerelease.Count - $rightParts.prerelease.Count)
}

function Get-VersionDirectoriesNewestFirst($root) {
    if (-Not (Test-Path $root)) { return @() }
    $directories = @(Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue)
    for ($i = 0; $i -lt $directories.Count; $i++) {
        for ($j = $i + 1; $j -lt $directories.Count; $j++) {
            if ((Compare-SemVer $directories[$j].Name $directories[$i].Name) -gt 0) {
                $swap = $directories[$i]
                $directories[$i] = $directories[$j]
                $directories[$j] = $swap
            }
        }
    }
    return $directories
}

function Get-CopilotCacheRoot {
    if (-Not [string]::IsNullOrWhiteSpace($env:COPILOT_CACHE_HOME)) {
        return [IO.Path]::GetFullPath($env:COPILOT_CACHE_HOME)
    }
    $platform = [Environment]::OSVersion.Platform
    $isMac = $platform -eq [PlatformID]::MacOSX -or
        ((Get-Variable -Name IsMacOS -ValueOnly -ErrorAction SilentlyContinue) -eq $true)
    if ($isMac) { return Join-Path (Join-Path (Join-Path $HOME "Library") "Caches") "copilot" }
    if ($platform -eq [PlatformID]::Win32NT) {
        $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME ".cache" }
        return Join-Path $base "copilot"
    }
    $base = if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { Join-Path $HOME ".cache" }
    return Join-Path $base "copilot"
}

function Get-CopilotMarketplaceCacheDirectories {
    if ($Agent -ne "copilot") { return @() }
    $root = Join-Path (Get-CopilotCacheRoot) "marketplaces"
    if (-Not (Test-Path $root)) { return @() }
    $matches = @()
    foreach ($directory in @(Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue)) {
        $manifestPaths = @(
            (Join-Path (Join-Path (Join-Path $directory.FullName ".github") "plugin") "marketplace.json"),
            (Join-Path (Join-Path $directory.FullName ".claude-plugin") "marketplace.json")
        )
        foreach ($manifestPath in $manifestPaths) {
            $manifest = Read-JsonFile $manifestPath
            if ($null -ne $manifest -and $manifest.name -eq $marketplace) {
                $matches += $directory
                break
            }
        }
    }
    return @($matches)
}

function Get-CopilotCachedPluginRoots($plugin) {
    $roots = @()
    foreach ($directory in @(Get-CopilotMarketplaceCacheDirectories)) {
        $manifestPaths = @(
            (Join-Path (Join-Path (Join-Path $directory.FullName ".github") "plugin") "marketplace.json"),
            (Join-Path (Join-Path $directory.FullName ".claude-plugin") "marketplace.json")
        )
        foreach ($manifestPath in $manifestPaths) {
            $manifest = Read-JsonFile $manifestPath
            if ($null -eq $manifest -or $manifest.name -ne $marketplace) { continue }
            $entry = @($manifest.plugins | Where-Object { $_.name -eq $plugin } | Select-Object -First 1)
            if ($entry.Count -eq 0 -or [string]::IsNullOrWhiteSpace($entry[0].source)) { continue }
            $relative = ([string]$entry[0].source) -replace '^[.][\\/]', ''
            $roots += Join-Path $directory.FullName $relative
            break
        }
    }
    return @($roots)
}

function Test-PluginInstalled($plugin) {
    if ($Agent -eq "copilot") {
        return Test-Path (Join-Path (Join-Path (Join-Path $agentHome "installed-plugins") $marketplace) $plugin)
    }
    $cacheRoot = Join-Path (Join-Path (Join-Path (Join-Path $agentHome "plugins") "cache") $marketplace) $plugin
    return Test-Path $cacheRoot
}

function Get-InstalledVersion($plugin) {
    if ($Agent -eq "copilot") {
        $root = Join-Path (Join-Path (Join-Path $agentHome "installed-plugins") $marketplace) $plugin
        return Get-ManifestVersion $root
    }

    $cacheRoot = Join-Path (Join-Path (Join-Path $agentHome "plugins") "cache") $marketplace
    $pluginRoot = Join-Path $cacheRoot $plugin
    if (-Not (Test-Path $pluginRoot)) { return $null }
    $versions = @(Get-VersionDirectoriesNewestFirst $pluginRoot)
    foreach ($version in $versions) {
        $found = Get-ManifestVersion $version.FullName
        if ($found) { return $found }
    }
    return Get-ManifestVersion $pluginRoot
}

function Get-MarketplaceVersion($plugin) {
    $roots = @()
    if ($Agent -eq "copilot") {
        $roots += @(Get-CopilotCachedPluginRoots $plugin)
    }
    $roots += @(
        (Join-Path (Join-Path (Join-Path $agentHome "plugins") $marketplace) $plugin),
        (Join-Path (Join-Path (Join-Path (Join-Path $agentHome "plugins") "marketplaces") $marketplace) $plugin)
    )
    foreach ($root in $roots) {
        $version = Get-ManifestVersion $root
        if ($version) { return $version }
    }

    $cacheRoot = Join-Path (Join-Path (Join-Path (Join-Path $agentHome "plugins") "cache") $marketplace) $plugin
    if (Test-Path $cacheRoot) {
        $versions = @(Get-VersionDirectoriesNewestFirst $cacheRoot)
        foreach ($versionDir in $versions) {
            $version = Get-ManifestVersion $versionDir.FullName
            if ($version) { return $version }
        }
    }
    return $null
}

function Get-CatalogRevision {
    $roots = @()
    if ($Agent -eq "copilot") {
        $roots += @(Get-CopilotMarketplaceCacheDirectories | ForEach-Object { $_.FullName })
    }
    $roots += @(
        (Join-Path (Join-Path $agentHome "plugins") $marketplace),
        (Join-Path (Join-Path (Join-Path $agentHome "plugins") "marketplaces") $marketplace),
        (Join-Path (Join-Path (Join-Path $agentHome "plugins") "cache") $marketplace)
    )
    $entries = @()
    foreach ($root in $roots) {
        if (-Not (Test-Path $root)) { continue }
        foreach ($manifest in @(Get-ChildItem -Path $root -Filter "plugin.json" -File -Recurse -ErrorAction SilentlyContinue)) {
            $json = Read-JsonFile $manifest.FullName
            if ($null -ne $json -and $null -ne $json.name -and $null -ne $json.version) {
                $entries += "$($json.name):$($json.version)"
            }
        }
    }
    $normalized = (@($entries | Sort-Object -Unique) -join "`n")
    if ([string]::IsNullOrWhiteSpace($normalized)) { return $null }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-ActiveUpdaterVersion {
    return Get-ManifestVersion $packageRoot
}

function Read-Timestamp($path) {
    if (-Not (Test-Path $path)) { return $null }
    try {
        $raw = (Get-Content -Path $path -Raw).Trim()
        return [datetimeoffset]::Parse(
            $raw,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    } catch {
        return $null
    }
}

function Test-IsDue($path, [double]$hours) {
    if ($hours -eq 0) { return $true }
    $last = Read-Timestamp $path
    if ($null -eq $last) { return $true }
    $elapsed = ([datetimeoffset]::Now - $last).TotalHours
    return $elapsed -lt 0 -or $elapsed -ge $hours
}

function Write-Timestamp($path, [datetimeoffset]$time) {
    Ensure-PluginData
    $time.ToString("o") | Set-Content -Path $path -Encoding utf8
}

function Get-NextEligiblePass($lastSuccess, $lastCatalogCheck, $cadences) {
    if ($null -eq $lastSuccess -or $null -eq $lastCatalogCheck) {
        return ([datetimeoffset]::Now).ToString("o")
    }
    $next = @()
    if ($null -ne $lastSuccess) { $next += $lastSuccess.AddHours($cadences.throttleHours) }
    if ($null -ne $lastCatalogCheck) { $next += $lastCatalogCheck.AddHours($cadences.catalogCheckHours) }
    if ($next.Count -eq 0) { return ([datetimeoffset]::Now).ToString("o") }
    return ($next | Sort-Object | Select-Object -First 1).ToString("o")
}

function Get-HealthReport {
    $saved = Read-JsonFile $statusFile
    $cadences = Get-ConfiguredCadences -NoLog
    $lastSuccess = Read-Timestamp $throttleFile
    $lastCatalogCheck = Read-Timestamp $catalogStampFile
    $plugins = @()
    if ($Agent -eq "claude") {
        $states = @(Get-ClaudePluginStates)
        $names = @($states | ForEach-Object { $_.name })
        $cacheRoot = Join-Path (Join-Path (Join-Path $agentHome "plugins") "cache") $marketplace
        if (Test-Path $cacheRoot) {
            $names += @(Get-ChildItem -Path $cacheRoot -Directory -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Name })
        }
        foreach ($plugin in @($names | Sort-Object -Unique)) {
            $configured = @($states | Where-Object { $_.name -eq $plugin } | Select-Object -First 1)
            $plugins += [ordered]@{
                name = $plugin
                installedVersion = Get-InstalledVersion $plugin
                marketplaceVersion = Get-MarketplaceVersion $plugin
                installed = Test-PluginInstalled $plugin
                enabled = ($configured.Count -gt 0 -and $configured[0].enabled)
            }
        }
    } else {
        foreach ($plugin in @(Get-InstalledPlugins)) {
            $plugins += [ordered]@{
                name = $plugin
                installedVersion = Get-InstalledVersion $plugin
                marketplaceVersion = Get-MarketplaceVersion $plugin
                installed = $true
                enabled = $true
            }
        }
    }

    $lockState = "available"
    $lockError = $null
    $probe = $null
    try {
        if (Test-Path $lockFile) {
            $probe = [IO.File]::Open($lockFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        }
    } catch [IO.IOException] {
        $lockState = "another-pass-running"
    } catch {
        $lockState = "unavailable"
        $lockError = $_.Exception.Message
    } finally {
        if ($null -ne $probe) { $probe.Dispose() }
    }

    $result = if ($null -ne $saved -and $null -ne $saved.result) { $saved.result } else { "never-run" }
    $reason = if ($null -ne $saved -and $null -ne $saved.reason) { $saved.reason } else { "No update status has been recorded yet." }
    if ($result -eq "running" -and $lockState -eq "available") {
        $result = "interrupted"
        $reason = "The previous update process ended before it recorded a final outcome."
    }
    $lastAttempt = if ($null -ne $saved) { $saved.lastAttempt } else { $null }
    $restartRequired = if ($null -ne $saved) { [bool]$saved.restartRequired } else { $false }
    $activeUpdaterVersion = if ($null -ne $saved -and $null -ne $saved.activeUpdaterVersion) {
        [string]$saved.activeUpdaterVersion
    } else {
        Get-ActiveUpdaterVersion
    }
    if ($restartRequired -and $activeUpdaterVersion -and $null -ne $saved -and $null -ne $saved.plugins) {
        $savedSelf = @($saved.plugins | Where-Object { $_.name -eq $self } | Select-Object -Last 1)
        if ($savedSelf.Count -gt 0 -and $savedSelf[0].finalVersion -eq $activeUpdaterVersion) {
            $restartRequired = $false
        }
    }
    $marketplaceUpdaterVersion = Get-MarketplaceVersion $self
    $selfState = @($plugins | Where-Object { $_.name -eq $self } | Select-Object -First 1)
    $installed = $selfState.Count -gt 0 -and $selfState[0].installed
    $enabled = $selfState.Count -gt 0 -and $selfState[0].enabled
    $remediation = if ($lockState -eq "unavailable") {
        "Check plugin-data permissions and the updater lock path."
    } elseif (-Not $installed) {
        "Install $self@$marketplace for the current agent."
    } elseif (-Not $enabled) {
        "Enable $self@$marketplace for the current agent."
    } else {
        switch ($result) {
            "running" { "Wait for the active update pass to finish, then check health again." }
            "never-run" { "Start a new agent session or run an on-demand update." }
            "missing-cli" { "Put the current agent CLI on PATH, then retry." }
            "partial" { "Review the per-plugin failures and retry the update." }
            "failed" { "Review the updater log and retry the update." }
            "interrupted" { "Retry the update; the previous process was interrupted." }
            default { if ($restartRequired) { "Restart the agent to activate the updated updater." } else { "No action required." } }
        }
    }

    return [ordered]@{
        schemaVersion = 1
        agent = $Agent
        installed = $installed
        enabled = $enabled
        activeUpdaterVersion = $activeUpdaterVersion
        marketplaceUpdaterVersion = $marketplaceUpdaterVersion
        lastAttempt = $lastAttempt
        lastSuccess = if ($null -ne $lastSuccess) { $lastSuccess.ToString("o") } else { $null }
        nextEligiblePass = if ($result -in @("partial", "failed", "interrupted", "missing-cli", "no-plugins")) {
            ([datetimeoffset]::Now).ToString("o")
        } else {
            Get-NextEligiblePass $lastSuccess $lastCatalogCheck $cadences
        }
        result = $result
        reason = $reason
        restartRequired = $restartRequired
        lockState = $lockState
        lockError = $lockError
        throttleHours = $cadences.throttleHours
        catalog = [ordered]@{
            checkHours = $cadences.catalogCheckHours
            lastChecked = if ($null -ne $lastCatalogCheck) { $lastCatalogCheck.ToString("o") } else { $null }
            revision = Get-CatalogRevision
        }
        plugins = @($plugins)
        statusPath = $statusFile
        logPath = $logFile
        remediation = $remediation
    }
}

if ($Mode -eq "health") {
    try {
        Get-HealthReport | ConvertTo-Json -Depth 8
    } catch {
        [ordered]@{
            schemaVersion = 1
            agent = $Agent
            result = "failed"
            reason = "Health inspection failed: $($_.Exception.Message)"
            remediation = "Review the updater log and configuration."
        } | ConvertTo-Json -Depth 4
    }
    return
}

$lockHandle = $null
$lastSuccess = $null
$previous = $null
$state = $null
try {
    Ensure-PluginData
    try {
        $lockHandle = [IO.File]::Open($lockFile, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        Write-UpdaterLog "another pass is running; skipping this session." -NoRotate
        return
    } catch {
        Write-UpdaterLog "lock unavailable; skipping this session: $($_.Exception.Message)" -NoRotate
        return
    }

    Rotate-UpdaterLog
    $now = [datetimeoffset]::Now
    $previous = Read-JsonFile $statusFile
    $cadences = Get-ConfiguredCadences
    $lastSuccess = Read-Timestamp $throttleFile
    $lastCatalogCheck = Read-Timestamp $catalogStampFile
    $plugins = @(Get-InstalledPlugins)
    $managedPlugins = @($plugins | Where-Object { $_ -ne $self } | Sort-Object -Unique)
    $selfInstalled = @($plugins | Where-Object { $_ -eq $self }).Count -gt 0
    $state = [ordered]@{
        schemaVersion = 1
        agent = $Agent
        activeUpdaterVersion = Get-ActiveUpdaterVersion
        marketplaceUpdaterVersion = Get-MarketplaceVersion $self
        lastAttempt = $now.ToString("o")
        lastSuccess = if ($null -ne $lastSuccess) { $lastSuccess.ToString("o") } else { $null }
        nextEligiblePass = $null
        result = "running"
        reason = "Update pass started."
        restartRequired = $false
        managedResult = "not-run"
        selfUpdateResult = if ($selfInstalled) { "not-run" } else { "not-installed" }
        catalog = [ordered]@{
            checkHours = $cadences.catalogCheckHours
            lastChecked = if ($null -ne $lastCatalogCheck) { $lastCatalogCheck.ToString("o") } else { $null }
            result = "not-due"
            revision = Get-CatalogRevision
        }
        plugins = @()
    }
    Write-StatusAtomic $state

    if ($plugins.Count -eq 0) {
        $state.result = "no-plugins"
        $state.reason = "No enabled plugins from $marketplace were found."
        $state.nextEligiblePass = $now.ToString("o")
        Write-UpdaterLog "no managed plugins are installed or enabled; nothing to update."
        Write-StatusAtomic $state
        return
    }

    if (-Not (Get-Command $cli -ErrorAction SilentlyContinue)) {
        $state.result = "missing-cli"
        $state.reason = "$cli CLI not found on PATH."
        $state.nextEligiblePass = $now.ToString("o")
        Write-UpdaterLog "$cli CLI not found on PATH; skipping auto-update."
        Write-StatusAtomic $state
        return
    }

    $catalogDue = Test-IsDue $catalogStampFile $cadences.catalogCheckHours
    $catalogRefreshed = $false
    $catalogFailed = $false
    if ($catalogDue) {
        try {
            $null = & $cli plugin marketplace update $marketplace 2>&1
            if ($LASTEXITCODE -eq 0) {
                $catalogRefreshed = $true
                $lastCatalogCheck = [datetimeoffset]::Now
                Write-Timestamp $catalogStampFile $lastCatalogCheck
                $state.catalog.lastChecked = $lastCatalogCheck.ToString("o")
                $state.catalog.result = "refreshed"
                $state.catalog.revision = Get-CatalogRevision
                $state.marketplaceUpdaterVersion = Get-MarketplaceVersion $self
                Write-UpdaterLog "marketplace catalog refreshed."
            } else {
                $catalogFailed = $true
                $state.catalog.result = "failed"
                Write-UpdaterLog "marketplace catalog refresh failed (exit $LASTEXITCODE)."
            }
        } catch {
            $catalogFailed = $true
            $state.catalog.result = "failed"
            Write-UpdaterLog "marketplace catalog refresh errored: $($_.Exception.Message)"
        }
    }

    $installDue = Test-IsDue $throttleFile $cadences.throttleHours
    $previousNeedsRetry = $null -ne $previous -and
        $previous.result -in @("partial", "failed", "running", "missing-cli", "no-plugins")
    if (-Not $installDue -and -Not $catalogRefreshed -and -Not $previousNeedsRetry) {
        $state.result = if ($catalogFailed) { "failed" } else { "throttled" }
        $state.reason = if ($catalogFailed) {
            "Catalog refresh failed while the plugin-install pass was throttled."
        } else {
            "Plugin-install and catalog-check cadences are not due."
        }
        $state.nextEligiblePass = if ($catalogFailed) {
            $now.ToString("o")
        } else {
            Get-NextEligiblePass $lastSuccess $lastCatalogCheck $cadences
        }
        Write-UpdaterLog ("skipping auto-update; install throttle {0}h and catalog check {1}h are not due." -f $cadences.throttleHours, $cadences.catalogCheckHours)
        Write-StatusAtomic $state
        return
    }

    $anyFailed = $catalogFailed
    $orderedPlugins = @($managedPlugins)
    if ($selfInstalled) { $orderedPlugins += $self }
    foreach ($plugin in $orderedPlugins) {
        $beforeVersion = if ($plugin -eq $self -and $state.activeUpdaterVersion) {
            [string]$state.activeUpdaterVersion
        } else {
            Get-InstalledVersion $plugin
        }
        $targetVersion = Get-MarketplaceVersion $plugin
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $exitCode = $null
        $errorCategory = $null
        $result = "completed"
        try {
            $null = & $cli plugin update "$plugin@$marketplace" 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $result = "failed"
                $errorCategory = "cli-exit"
                $anyFailed = $true
                Write-UpdaterLog "update failed for $plugin (exit $exitCode)."
            }
        } catch {
            $result = "failed"
            $errorCategory = "exception"
            $anyFailed = $true
            Write-UpdaterLog "update errored for $plugin ($errorCategory)."
        } finally {
            $timer.Stop()
        }

        $finalVersion = Get-InstalledVersion $plugin
        if ($result -ne "failed" -and $beforeVersion -and $finalVersion) {
            $result = if ($beforeVersion -eq $finalVersion) { "already-current" } else { "updated" }
        }
        $pluginRestartRequired = $plugin -eq $self -and $result -in @("updated", "completed")
        if ($pluginRestartRequired) {
            $state.restartRequired = $true
        }
        $state.plugins += [ordered]@{
            name = $plugin
            beforeVersion = $beforeVersion
            targetVersion = $targetVersion
            finalVersion = $finalVersion
            result = $result
            durationMs = [long]$timer.ElapsedMilliseconds
            exitCode = $exitCode
            errorCategory = $errorCategory
            restartRequired = $pluginRestartRequired
        }
        Write-UpdaterLog ("plugin {0}: result={1}; before={2}; target={3}; final={4}; durationMs={5}; restartRequired={6}." -f
            $plugin, $result, $beforeVersion, $targetVersion, $finalVersion, $timer.ElapsedMilliseconds,
            $pluginRestartRequired)
    }

    $completed = [datetimeoffset]::Now
    $managedFailures = @($state.plugins | Where-Object { $_.name -ne $self -and $_.result -eq "failed" }).Count
    $state.managedResult = if ($managedPlugins.Count -eq 0) {
        "no-managed-plugins"
    } elseif ($managedFailures -eq 0) {
        "success"
    } else {
        "failed"
    }
    if ($selfInstalled) {
        $selfOutcome = @($state.plugins | Where-Object { $_.name -eq $self } | Select-Object -Last 1)
        $state.selfUpdateResult = if ($selfOutcome.Count -eq 0) { "not-run" } else { $selfOutcome[0].result }
    }
    if (-Not $anyFailed) {
        Write-Timestamp $throttleFile $completed
        $lastSuccess = $completed
        $state.lastSuccess = $completed.ToString("o")
        $state.result = "success"
        $state.reason = "All plugin operations completed successfully."
    } else {
        $successCount = @($state.plugins | Where-Object { $_.result -ne "failed" }).Count
        $state.result = if ($successCount -gt 0) { "partial" } else { "failed" }
        $state.reason = "One or more catalog or plugin operations failed; the next session will retry."
    }
    $state.nextEligiblePass = if ($anyFailed) {
        $completed.ToString("o")
    } else {
        Get-NextEligiblePass $lastSuccess $lastCatalogCheck $cadences
    }
    Write-UpdaterLog ("auto-update pass complete: {0} plugin(s) checked; result={1}; restartRequired={2}." -f
        $orderedPlugins.Count, $state.result, $state.restartRequired)
    Write-StatusAtomic $state
} catch {
    Write-UpdaterLog "auto-update aborted: $($_.Exception.Message)"
    try {
        $preservedLastSuccess = if ($null -ne $lastSuccess) {
            $lastSuccess.ToString("o")
        } elseif ($null -ne $previous -and $null -ne $previous.lastSuccess) {
            ([datetimeoffset]$previous.lastSuccess).ToString("o")
        } else {
            $null
        }
        if ($null -ne $state) {
            $failedState = $state
            $failedState.lastSuccess = $preservedLastSuccess
            $failedState.nextEligiblePass = ([datetimeoffset]::Now).ToString("o")
            $failedState.result = "failed"
            $failedState.reason = "Auto-update aborted."
        } else {
            $failedState = [ordered]@{
                schemaVersion = 1
                agent = $Agent
                activeUpdaterVersion = Get-ActiveUpdaterVersion
                marketplaceUpdaterVersion = Get-MarketplaceVersion $self
                lastAttempt = ([datetimeoffset]::Now).ToString("o")
                lastSuccess = $preservedLastSuccess
                nextEligiblePass = ([datetimeoffset]::Now).ToString("o")
                result = "failed"
                reason = "Auto-update aborted."
                restartRequired = $false
                managedResult = "not-run"
                selfUpdateResult = "not-run"
                catalog = $null
                plugins = @()
            }
        }
        Write-StatusAtomic $failedState
    } catch { }
} finally {
    if ($null -ne $lockHandle) { $lockHandle.Dispose() }
}
