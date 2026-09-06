#!/usr/bin/env pwsh
# Cross-platform (pwsh) behavior tests for the auto-updater session-start hook.
# Runs the real hook script against an isolated temp COPILOT_HOME sandbox with a
# stubbed `copilot` command; performs no real updates and no network calls.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkgRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) "pkg"
$hookScript = Join-Path (Join-Path $pkgRoot "hooks") "marketplace-update.ps1"
$hooksJson = Join-Path $pkgRoot "hooks.json"
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $pkgRoot))
$marketplace = "urikan-ai-marketplace"
$self = "urikan-ai-marketplace-auto-updater"
$isWindowsPlatform = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT

$script:failures = @()
$script:passes = 0

function Assert-True($condition, $message) {
    if ($condition) { $script:passes++ } else { $script:failures += $message; Write-Host "  FAIL: $message" -ForegroundColor Red }
}

function New-Sandbox([string[]]$plugins, [switch]$IncludeSelf) {
    $root = Join-Path ([IO.Path]::GetTempPath()) ("upd-" + [Guid]::NewGuid().ToString("N"))
    $installed = Join-Path (Join-Path $root "installed-plugins") $marketplace
    New-Item -ItemType Directory -Force -Path $installed | Out-Null
    foreach ($p in $plugins) {
        $pluginRoot = Join-Path $installed $p
        New-Item -ItemType Directory -Force -Path $pluginRoot | Out-Null
        @{ name = $p; version = "1.0.0" } | ConvertTo-Json |
            Set-Content -Path (Join-Path $pluginRoot "plugin.json") -Encoding utf8
    }
    if ($IncludeSelf) {
        $selfRoot = Join-Path $installed $self
        New-Item -ItemType Directory -Force -Path $selfRoot | Out-Null
        @{ name = $self; version = "1.0.0" } | ConvertTo-Json |
            Set-Content -Path (Join-Path $selfRoot "plugin.json") -Encoding utf8
    }
    return $root
}

function Reset-Mock {
    $global:CopilotCalls = @()
    $global:CopilotCatalogCalls = @()
    $global:CopilotFailFor = $null
    $global:CopilotCatalogFails = $false
    $global:CopilotSelfUpdateVersion = $null
    $global:ObservedRunningStatus = $null
    Set-Item -Path Function:global:copilot -Value {
        $call = [string]::Join(" ", $args)
        if ($call -like "plugin marketplace update *") {
            $global:CopilotCatalogCalls += , $call
            $global:LASTEXITCODE = if ($global:CopilotCatalogFails) { 1 } else { 0 }
            Write-Output $(if ($global:CopilotCatalogFails) { "catalog failed" } else { "catalog updated" })
            return
        }
        $global:CopilotCalls += , $call
        $statusPath = Join-Path (Join-Path $env:COPILOT_HOME "plugin-data") "urikan-ai-marketplace-auto-updater.status.json"
        if (Test-Path $statusPath) {
            $global:ObservedRunningStatus = (Get-Content -Path $statusPath -Raw | ConvertFrom-Json).result
        }
        $target = ($args | Select-Object -Last 1)
        if ($global:CopilotFailFor -and $target -like "*$($global:CopilotFailFor)@*") {
            $global:LASTEXITCODE = 1
            Write-Output "simulated failure for $target"
        } else {
            $global:LASTEXITCODE = 0
            if ($global:CopilotSelfUpdateVersion -and $target -like "urikan-ai-marketplace-auto-updater@*") {
                $manifest = Join-Path (Join-Path (Join-Path (Join-Path $env:COPILOT_HOME "installed-plugins") "urikan-ai-marketplace") "urikan-ai-marketplace-auto-updater") "plugin.json"
                @{ name = "urikan-ai-marketplace-auto-updater"; version = $global:CopilotSelfUpdateVersion } |
                    ConvertTo-Json | Set-Content -Path $manifest -Encoding utf8
            }
            Write-Output "updated $target"
        }
    }
}

function Invoke-Hook([string]$copilotHome, [string]$mode = "update") {
    $savedPath = $env:PATH
    $savedHome = $env:COPILOT_HOME
    $savedCacheHome = $env:COPILOT_CACHE_HOME
    try {
        $env:PATH = ""              # keep the stub function authoritative; never hit a real copilot on PATH
        $env:COPILOT_HOME = $copilotHome
        $env:COPILOT_CACHE_HOME = Join-Path $copilotHome "copilot-cache"
        & $hookScript -Mode $mode
    } finally {
        $env:PATH = $savedPath
        if ($null -eq $savedHome) { Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_HOME = $savedHome }
        if ($null -eq $savedCacheHome) { Remove-Item Env:COPILOT_CACHE_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_CACHE_HOME = $savedCacheHome }
    }
}

function Get-Log([string]$copilotHome) {
    $log = Join-Path (Join-Path $copilotHome "plugin-data") "$self.log"
    if (Test-Path $log) { return (Get-Content -Path $log -Raw) } else { return "" }
}

function Get-Throttle([string]$copilotHome) {
    return Join-Path (Join-Path $copilotHome "plugin-data") "$self.last-run"
}

function Get-CatalogStamp([string]$copilotHome, [string]$agent = "copilot") {
    $suffix = if ($agent -eq "claude") { ".claude" } else { "" }
    return Join-Path (Join-Path $copilotHome "plugin-data") "$self$suffix.last-catalog-check"
}

function Get-StatusPath([string]$copilotHome) {
    return Join-Path (Join-Path $copilotHome "plugin-data") "$self.status.json"
}

function Get-LockPath([string]$copilotHome) {
    return Join-Path (Join-Path $copilotHome "plugin-data") "$self.lock"
}

function Set-Config([string]$copilotHome, $config) {
    $pd = Join-Path $copilotHome "plugin-data"
    New-Item -ItemType Directory -Force -Path $pd | Out-Null
    $path = Join-Path $pd "$self.config.json"
    if ($config -is [string]) { $config | Set-Content -Path $path -Encoding utf8 }
    else { ($config | ConvertTo-Json) | Set-Content -Path $path -Encoding utf8 }
}

function Set-CatalogPluginVersion([string]$copilotHome, [string]$plugin, [string]$version) {
    $root = Join-Path (Join-Path (Join-Path $copilotHome "plugins") $marketplace) $plugin
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    @{ name = $plugin; version = $version } | ConvertTo-Json |
        Set-Content -Path (Join-Path $root "plugin.json") -Encoding utf8
}

function Set-CopilotCachedMarketplaceVersion([string]$copilotHome, [string]$plugin, [string]$version) {
    $root = Join-Path (Join-Path (Join-Path $copilotHome "copilot-cache") "marketplaces") "fixture-marketplace"
    $manifestRoot = Join-Path (Join-Path $root ".github") "plugin"
    $source = Join-Path (Join-Path (Join-Path $root "plugins") $plugin) "pkg"
    New-Item -ItemType Directory -Force -Path $manifestRoot, $source | Out-Null
    @{
        name = $marketplace
        plugins = @(@{ name = $plugin; version = $version; source = "./plugins/$plugin/pkg" })
    } | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $manifestRoot "marketplace.json") -Encoding utf8
    @{ name = $plugin; version = $version } | ConvertTo-Json |
        Set-Content -Path (Join-Path $source "plugin.json") -Encoding utf8
}

function Set-Stamp([string]$copilotHome, [double]$hoursAgo) {
    $stamp = Get-Throttle $copilotHome
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stamp) | Out-Null
    ([datetimeoffset]::Now.AddHours(-$hoursAgo)).ToString("o") | Set-Content -Path $stamp -Encoding utf8
    Set-CatalogStamp $copilotHome $hoursAgo
}

function Set-CatalogStamp([string]$configHome, [double]$hoursAgo, [string]$agent = "copilot") {
    $stamp = Get-CatalogStamp $configHome $agent
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stamp) | Out-Null
    ([datetimeoffset]::Now.AddHours(-$hoursAgo)).ToString("o") | Set-Content -Path $stamp -Encoding utf8
}

# --- Claude-branch helpers (Agent=claude reads settings.json enabledPlugins under CLAUDE_CONFIG_DIR) ---

function New-ClaudeSandbox([hashtable]$enabledPlugins) {
    $root = Join-Path ([IO.Path]::GetTempPath()) ("cl-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    (@{ enabledPlugins = $enabledPlugins } | ConvertTo-Json -Depth 5) |
        Set-Content -Path (Join-Path $root "settings.json") -Encoding utf8
    return $root
}

function Set-ClaudeCacheVersion([string]$claudeHome, [string]$plugin, [string]$version) {
    $root = Join-Path (Join-Path (Join-Path (Join-Path (Join-Path $claudeHome "plugins") "cache") $marketplace) $plugin) $version
    New-Item -ItemType Directory -Force -Path (Join-Path $root ".claude-plugin") | Out-Null
    @{ name = $plugin; version = $version } | ConvertTo-Json |
        Set-Content -Path (Join-Path (Join-Path $root ".claude-plugin") "plugin.json") -Encoding utf8
}

function Reset-ClaudeMock {
    $global:ClaudeCalls = @()
    $global:ClaudeCatalogCalls = @()
    $global:ClaudePopulateSelfVersionOn = $null
    $global:ClaudePopulatedSelfVersion = $null
    Set-Item -Path Function:global:claude -Value {
        $call = [string]::Join(" ", $args)
        if ($call -like "plugin marketplace update *") {
            $global:ClaudeCatalogCalls += , $call
            $global:LASTEXITCODE = 0
            Write-Output "catalog updated"
            return
        }
        $global:ClaudeCalls += , $call
        $target = ($args | Select-Object -Last 1)
        if ($global:ClaudePopulateSelfVersionOn -and
            $target -like "$($global:ClaudePopulateSelfVersionOn)@*" -and
            $global:ClaudePopulatedSelfVersion) {
            Set-ClaudeCacheVersion $env:CLAUDE_CONFIG_DIR $self $global:ClaudePopulatedSelfVersion
        }
        $global:LASTEXITCODE = 0
        Write-Output ("updated " + $target)
    }
}

function Invoke-ClaudeHook([string]$claudeHome, [string]$mode = "update") {
    $savedPath = $env:PATH
    $savedHome = $env:CLAUDE_CONFIG_DIR
    try {
        $env:PATH = ""
        $env:CLAUDE_CONFIG_DIR = $claudeHome
        & $hookScript -Agent claude -Mode $mode
    } finally {
        $env:PATH = $savedPath
        if ($null -eq $savedHome) { Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue } else { $env:CLAUDE_CONFIG_DIR = $savedHome }
    }
}

function Get-ClaudeLog([string]$claudeHome) {
    $log = Join-Path (Join-Path $claudeHome "plugin-data") "$self.log"
    if (Test-Path $log) { return (Get-Content -Path $log -Raw) } else { return "" }
}

# --- Helpers for functionally EXECUTING the real hooks.json command strings (UPD-06/07/15),
# instead of only pattern-matching their text, against an isolated temp sandbox. ---

# Resolves a real POSIX shell for these functional checks. On Windows this must be Git Bash (the
# same bash.exe Git for Windows ships, which is what a bash-type hook actually runs under on the
# windows-latest runner and under Claude Code on Windows) rather than an ambiguous `bash` on PATH:
# a plain `Get-Command bash` can resolve to WSL's bash.exe instead, which is a different OS layer
# with different path semantics and would not represent the real invocation.
function Get-FunctionalBashExe {
    if ($isWindowsPlatform) {
        $gitBash = "C:\Program Files\Git\bin\bash.exe"
        if (Test-Path $gitBash) { return $gitBash }
        return $null
    }
    $cmd = Get-Command bash -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# Writes a stub CLI under $root/bin (a Windows .cmd on Windows, a POSIX shell script elsewhere)
# that appends its invocation args to $logPath, then returns the bin directory to prepend to PATH.
# Used so a functional check can exercise the real "plugin update" call path without ever
# touching a real CLI, the network, or the user's real plugin/marketplace directories.
function New-StubCli([string]$root, [string]$name, [string]$logPath) {
    $bin = Join-Path $root "bin"
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    if ($isWindowsPlatform) {
        $path = Join-Path $bin "$name.cmd"
        @"
@echo off
echo %* >> "$logPath"
exit /b 0
"@ | Set-Content -Path $path -Encoding ascii
    } else {
        $path = Join-Path $bin $name
        @"
#!/bin/sh
echo "`$@" >> "$logPath"
exit 0
"@ | Set-Content -Path $path -Encoding ascii
        & chmod +x $path
    }
    return $bin
}

# Resolves the native filesystem path of a POSIX utility as $bashExe's own (unmodified) PATH sees
# it, translating a Git-Bash POSIX path (e.g. "/usr/bin/mkdir") to its native Windows path via
# cygpath so it can be copied with PowerShell's own Copy-Item. Returns $null if not found or if the
# name resolves to a shell builtin/function (no standalone file to copy - those need no PATH entry
# anyway, since builtins are always available regardless of PATH).
function Resolve-NativeUtilPath([string]$bashExe, [string]$name) {
    $posix = ((& $bashExe "-c" "command -v $name 2>/dev/null") -join "").Trim()
    if (-not $posix) { return $null }
    if ($isWindowsPlatform) {
        $native = ((& $bashExe "-c" "cygpath -w -- '$posix' 2>/dev/null") -join "").Trim()
        if ($native -and (Test-Path -LiteralPath $native -PathType Leaf)) { return $native }
        return $null
    }
    if (Test-Path -LiteralPath $posix -PathType Leaf) { return $posix }
    return $null
}

# Copies the specific external utilities the missing-pwsh branch needs (mkdir, date, printf, cat)
# into a fresh directory. Needed because Remove-PwshFromPath below may exclude a directory that
# happens to colocate pwsh with coreutils (e.g. Ubuntu's /usr/bin ships both), which would
# otherwise silently break the branch's own mkdir/date/printf calls, not just hide pwsh.
function New-PwshFreeUtilBin([string]$root, [string]$bashExe) {
    $dir = Join-Path $root "safebin"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($name in @("mkdir", "date", "printf", "cat")) {
        $native = Resolve-NativeUtilPath $bashExe $name
        if ($native) {
            $destName = if ($isWindowsPlatform) { Split-Path -Leaf $native } else { $name }
            Copy-Item -LiteralPath $native -Destination (Join-Path $dir $destName) -Force -ErrorAction SilentlyContinue
        }
    }
    return $dir
}

# Builds a PATH string with every directory that contains a real pwsh binary removed, so
# `command -v pwsh` genuinely fails inside the real if/then/else/fi dispatcher - proving the whole
# command takes the missing-pwsh branch on its own merits, rather than assuming its control flow by
# regex-extracting the else branch's text and running only that in isolation.
function Remove-PwshFromPath([string]$path) {
    $sep = [IO.Path]::PathSeparator
    $pwshNames = if ($isWindowsPlatform) { @("pwsh.exe", "pwsh.cmd", "pwsh.bat") } else { @("pwsh") }
    $dirs = ($path -split [regex]::Escape($sep)) | Where-Object { $_ }
    $kept = $dirs | Where-Object {
        $dir = $_
        -not ($pwshNames | Where-Object { Test-Path -LiteralPath (Join-Path $dir $_) -PathType Leaf })
    }
    return ($kept -join $sep)
}

function Invoke-FunctionalBashCommand([string]$bashExe, [string]$command) {
    $saved = $env:UPDATER_TEST_COMMAND
    try {
        $env:UPDATER_TEST_COMMAND = $command
        & $bashExe "-c" 'eval "$UPDATER_TEST_COMMAND"'
    } finally {
        if ($null -eq $saved) {
            Remove-Item Env:UPDATER_TEST_COMMAND -ErrorAction SilentlyContinue
        } else {
            $env:UPDATER_TEST_COMMAND = $saved
        }
    }
}

Write-Host "== UPD-01 managed-plugin enumeration keeps self out of the managed phase =="
try {
    Reset-Mock
    $home1 = New-Sandbox -plugins @("alpha") -IncludeSelf
    Invoke-Hook $home1
    Assert-True (($global:CopilotCalls -join "|") -like "*alpha@$marketplace*") "UPD-01: alpha should be updated"
    Assert-True ($global:CopilotCalls[0] -like "*alpha@$marketplace*") "UPD-01: self must not enter the managed-plugin phase"
    Remove-Item -Recurse -Force $home1
} catch { $script:failures += "UPD-01 threw: $_" }

Write-Host "== UPD-02 missing CLI skip + log =="
try {
    Remove-Item Function:copilot -ErrorAction SilentlyContinue
    $home2 = New-Sandbox -plugins @("alpha")
    Invoke-Hook $home2
    Assert-True ((Get-Log $home2) -like "*copilot CLI not found*") "UPD-02: missing CLI must be logged"
    Assert-True (-not (Test-Path (Get-Throttle $home2))) "UPD-02: no throttle stamp when CLI is missing"
    Remove-Item -Recurse -Force $home2
} catch { $script:failures += "UPD-02 threw: $_" }

Write-Host "== UPD-03 per-plugin failure isolation =="
try {
    Reset-Mock
    $global:CopilotFailFor = "beta"
    $home3 = New-Sandbox -plugins @("alpha", "beta", "gamma")
    Invoke-Hook $home3
    Assert-True ($global:CopilotCalls.Count -eq 3) "UPD-03: all three plugins attempted despite one failing"
    Assert-True ((Get-Log $home3) -like "*update failed for beta*") "UPD-03: failing plugin logged"
    Remove-Item -Recurse -Force $home3
} catch { $script:failures += "UPD-03 threw: $_" }

Write-Host "== UPD-04 COPILOT_HOME fallback to HOME/.copilot =="
try {
    Reset-Mock
    $fakeHome = Join-Path ([IO.Path]::GetTempPath()) ("uh-" + [Guid]::NewGuid().ToString("N"))
    $installed = Join-Path (Join-Path (Join-Path $fakeHome ".copilot") "installed-plugins") $marketplace
    New-Item -ItemType Directory -Force -Path (Join-Path $installed "alpha") | Out-Null
    $savedHomeVar = $HOME
    $savedCopilotHome = $env:COPILOT_HOME
    $savedPath = $env:PATH
    try {
        Set-Variable -Name HOME -Value $fakeHome -Force -Scope Global
        Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue
        $env:PATH = ""
        & $hookScript
    } finally {
        Set-Variable -Name HOME -Value $savedHomeVar -Force -Scope Global
        $env:PATH = $savedPath
        if ($null -ne $savedCopilotHome) { $env:COPILOT_HOME = $savedCopilotHome }
    }
    Assert-True (($global:CopilotCalls -join "|") -like "*alpha@$marketplace*") "UPD-04: fallback home resolved and alpha updated"
    Assert-True (Test-Path (Join-Path (Join-Path $fakeHome ".copilot") "plugin-data")) "UPD-04: plugin-data created under HOME/.copilot"
    Remove-Item -Recurse -Force $fakeHome
} catch { $script:failures += "UPD-04 threw: $_" }

Write-Host "== UPD-05 deterministic sorted log order =="
try {
    Reset-Mock
    $home5 = New-Sandbox -plugins @("zed", "alpha", "mid")
    Invoke-Hook $home5
    $targets = $global:CopilotCalls | ForEach-Object { ($_ -split " ")[-1] }
    Assert-True (($targets -join ",") -eq "alpha@$marketplace,mid@$marketplace,zed@$marketplace") "UPD-05: plugins processed in sorted order (got $($targets -join ','))"
    Remove-Item -Recurse -Force $home5
} catch { $script:failures += "UPD-05 threw: $_" }

Write-Host "== UPD-06 ExecutionPolicy-bypass invocation in hooks.json =="
try {
    $hooks = Get-Content -Path $hooksJson -Raw | ConvertFrom-Json
    $ps = $hooks.hooks.sessionStart[0].powershell
    Assert-True ($ps -match "-ExecutionPolicy\s+Bypass") "UPD-06: powershell field bypasses ExecutionPolicy"
    Assert-True ($ps -match "-File\s+\./hooks/marketplace-update\.ps1") "UPD-06: powershell field invokes the script via -File"
    Assert-True ($ps -match "-NoProfile") "UPD-06: powershell field uses -NoProfile"

    # Functional check: actually spawn the unmodified "powershell ..." command line from
    # hooks.json (its relative -File path resolves via the working directory, exactly as the CLI
    # runs it from the plugin root) under real Windows PowerShell 5.1, against a sandbox
    # COPILOT_HOME with one installed plugin and a stubbed `copilot` CLI. This proves the real
    # quoting, -File path resolution, and end-to-end behavior, not just the command text.
    if ($isWindowsPlatform -and (Get-Command powershell -ErrorAction SilentlyContinue)) {
        $home6 = Join-Path ([IO.Path]::GetTempPath()) ("upd06-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path (Join-Path (Join-Path $home6 "installed-plugins") "$marketplace\alpha") | Out-Null
        $stubLog6 = Join-Path $home6 "stub-calls.log"
        $bin6 = New-StubCli $home6 "copilot" $stubLog6
        $savedPath6 = $env:PATH
        $savedHome6 = $env:COPILOT_HOME
        try {
            $env:PATH = "$bin6;$savedPath6"
            $env:COPILOT_HOME = $home6
            $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $ps) -WorkingDirectory $pkgRoot -NoNewWindow -Wait -PassThru
            Assert-True ($proc.ExitCode -eq 0) "UPD-06: the real powershell command line exits cleanly under Windows PowerShell 5.1"
        } finally {
            $env:PATH = $savedPath6
            if ($null -eq $savedHome6) { Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_HOME = $savedHome6 }
        }
        Assert-True ((Test-Path $stubLog6) -and ((Get-Content -Raw $stubLog6) -like "*plugin update alpha@$marketplace*")) "UPD-06: the real command resolves the sandbox and updates the installed plugin"
        Assert-True ((Get-Log $home6) -like "*pass complete: 1 plugin(s) checked*") "UPD-06: the real command completes the pass and logs it"
        Remove-Item -Recurse -Force $home6
    } else {
        Write-Host "  (Windows PowerShell unavailable; structural checks only)"
    }
} catch { $script:failures += "UPD-06 threw: $_" }

Write-Host "== UPD-07 missing-pwsh log signal in bash field =="
try {
    $hooks = Get-Content -Path $hooksJson -Raw | ConvertFrom-Json
    $bash = $hooks.hooks.sessionStart[0].bash
    Assert-True ($bash -like "*command -v pwsh*") "UPD-07: bash field probes for pwsh"
    Assert-True ($bash -like "*plugin-data*" -and $bash -like "*$self.log*") "UPD-07: bash field targets the plugin-data log"
    Assert-True ($bash -like "*not found on PATH*") "UPD-07: bash field logs a discoverable skip note"
    # Functional check of the WHOLE if/then/else/fi dispatcher (not a regex-extracted branch):
    # run the real, unmodified $bash string itself under a real POSIX shell (bash on Linux, Git
    # Bash on Windows - see Get-FunctionalBashExe), in a sandbox PATH where the real pwsh binary
    # has been genuinely removed (not merely a fabricated snippet standing in for it), so a
    # malformed conditional, wrong probe, or quoting/control-flow regression in the full command
    # would surface here - proving the missing-pwsh path is taken on its own merits.
    $bashExe = Get-FunctionalBashExe
    if ($bashExe) {
        $home7 = Join-Path ([IO.Path]::GetTempPath()) ("b7-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $home7 | Out-Null
        $safeBin7 = New-PwshFreeUtilBin $home7 $bashExe
        $savedPath7 = $env:PATH
        $prev = $env:COPILOT_HOME
        try {
            $env:PATH = "$safeBin7$([IO.Path]::PathSeparator)$(Remove-PwshFromPath $savedPath7)"
            $probe7 = ((& $bashExe "-c" "command -v pwsh 2>/dev/null") -join "").Trim()
            Assert-True ([string]::IsNullOrEmpty($probe7)) "UPD-07: sandbox PATH genuinely lacks pwsh (precondition for the missing-pwsh branch)"
            $env:COPILOT_HOME = $home7
            Invoke-FunctionalBashCommand $bashExe $bash | Out-Null
        } finally {
            $env:PATH = $savedPath7
            if ($null -eq $prev) { Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_HOME = $prev }
        }
        $logPath = Join-Path (Join-Path $home7 "plugin-data") "$self.log"
        Assert-True ((Test-Path $logPath) -and ((Get-Content -Raw $logPath) -like "*not found on PATH*")) "UPD-07: the real if/then/else/fi dispatcher (run whole, not just its else branch) takes the missing-pwsh path and writes the skip note"
        Remove-Item -Recurse -Force $home7
    } else {
        Write-Host "  (bash unavailable; structural checks only)"
    }
} catch { $script:failures += "UPD-07 threw: $_" }

Write-Host "== UPD-08 last-run throttle =="
try {
    Reset-Mock
    $home8 = New-Sandbox -plugins @("alpha")
    $stamp = Get-Throttle $home8
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stamp) | Out-Null
    ([datetimeoffset]::Now).ToString("o") | Set-Content -Path $stamp -Encoding utf8
    Set-CatalogStamp $home8 0
    Invoke-Hook $home8
    Assert-True ($global:CopilotCalls.Count -eq 0) "UPD-08: recent stamp throttles the whole pass"
    Assert-True ((Get-Log $home8) -like "*skipping auto-update*") "UPD-08: throttle is logged"

    Reset-Mock
    $home8b = New-Sandbox -plugins @("alpha")
    $stampB = Get-Throttle $home8b
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stampB) | Out-Null
    ([datetimeoffset]::Now.AddHours(-48)).ToString("o") | Set-Content -Path $stampB -Encoding utf8
    Invoke-Hook $home8b
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-08: a stale stamp lets the pass run"
    $written = [datetimeoffset]::Parse((Get-Content -Raw $stampB).Trim())
    Assert-True ((([datetimeoffset]::Now - $written).TotalMinutes) -lt 5) "UPD-08: the pass refreshes the stamp"

    # The default cadence is 24h: with no config a 22h-old pass is still throttled (it would run
    # under the previous 20h default).
    Reset-Mock
    $home8c = New-Sandbox -plugins @("alpha")
    Set-Stamp $home8c 22
    Set-CatalogStamp $home8c 0
    Invoke-Hook $home8c
    Assert-True ($global:CopilotCalls.Count -eq 0) "UPD-08: the default cadence is 24h (a 22h-old pass is throttled)"
    Remove-Item -Recurse -Force $home8, $home8b, $home8c
} catch { $script:failures += "UPD-08 threw: $_" }

Write-Host "== UPD-09 Claude enumerates enabledPlugins and keeps self for the final phase =="
try {
    Reset-ClaudeMock
    $c9 = New-ClaudeSandbox @{ "commentable-html@$marketplace" = $true; "$self@$marketplace" = $true }
    Invoke-ClaudeHook $c9
    Assert-True (($global:ClaudeCalls -join "|") -like "*commentable-html@$marketplace*") "UPD-09: commentable-html updated under Claude"
    Assert-True ($global:ClaudeCalls[-1] -like "*$self@$marketplace*") "UPD-09: self is retained for the final Claude update phase"
    Assert-True ($global:ClaudeCalls.Count -eq 2) "UPD-09: Claude updates the managed plugin and then the updater"
    Remove-Item -Recurse -Force $c9
} catch { $script:failures += "UPD-09 threw: $_" }

Write-Host "== UPD-10 Claude skips disabled and other-marketplace plugins =="
try {
    Reset-ClaudeMock
    $c10 = New-ClaudeSandbox @{ "commentable-html@$marketplace" = $true; "beta@$marketplace" = $false; "other@some-other-marketplace" = $true }
    Invoke-ClaudeHook $c10
    $joined = ($global:ClaudeCalls -join "|")
    Assert-True ($joined -like "*commentable-html@$marketplace*") "UPD-10: enabled marketplace plugin updated"
    Assert-True (-not ($joined -like "*beta@*")) "UPD-10: disabled plugin skipped"
    Assert-True (-not ($joined -like "*other@*")) "UPD-10: other-marketplace plugin skipped"
    Assert-True ($global:ClaudeCalls.Count -eq 1) "UPD-10: exactly one update"
    Remove-Item -Recurse -Force $c10
} catch { $script:failures += "UPD-10 threw: $_" }

Write-Host "== UPD-11 Claude SessionStart hook config =="
try {
    $claudeHooks = Join-Path (Join-Path $pkgRoot "hooks") "hooks.json"
    Assert-True (Test-Path $claudeHooks) "UPD-11: Claude hooks/hooks.json ships"
    $ch = Get-Content -Path $claudeHooks -Raw | ConvertFrom-Json
    Assert-True ($null -ne $ch.hooks.SessionStart) "UPD-11: Claude hooks declares a SessionStart event"
    $raw = Get-Content -Path $claudeHooks -Raw
    Assert-True ($raw -like "*-Agent*claude*") "UPD-11: Claude hook invokes the shared script with -Agent claude"
    Assert-True ($raw -like "*`${CLAUDE_PLUGIN_ROOT}*") "UPD-11: Claude hook uses the CLAUDE_PLUGIN_ROOT placeholder"
    Assert-True ($raw -like "*marketplace-update.ps1*") "UPD-11: Claude hook runs the shared marketplace-update.ps1"
} catch { $script:failures += "UPD-11 threw: $_" }

Write-Host "== UPD-12 on-demand manual-update skill =="
try {
    $skillMd = Join-Path (Join-Path (Join-Path $pkgRoot "skills") "marketplace-update") "SKILL.md"
    Assert-True (Test-Path $skillMd) "UPD-12: marketplace-update SKILL.md ships"
    $skill = Get-Content -Path $skillMd -Raw
    Assert-True ($skill -match "(?m)^name:\s*marketplace-update\s*$") "UPD-12: SKILL.md front matter name is marketplace-update"
    Assert-True ($skill -match "(?m)^description:\s*\S") "UPD-12: SKILL.md front matter has a non-empty description"
    Assert-True ($skill -like "*update cmh*") "UPD-12: skill triggers on the 'update cmh' phrasing"
    Assert-True ($skill -like "*plugin update*") "UPD-12: skill instructs running the plugin update command"
} catch { $script:failures += "UPD-12 threw: $_" }

Write-Host "== UPD-13 Claude throttle and empty/missing config are no-ops =="
try {
    Reset-ClaudeMock
    $c13 = New-ClaudeSandbox @{ "commentable-html@$marketplace" = $true }
    $stamp = Join-Path (Join-Path $c13 "plugin-data") "$self.claude.last-run"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stamp) | Out-Null
    ([datetimeoffset]::Now).ToString("o") | Set-Content -Path $stamp -Encoding utf8
    Set-CatalogStamp $c13 0 "claude"
    Invoke-ClaudeHook $c13
    Assert-True ($global:ClaudeCalls.Count -eq 0) "UPD-13: recent Claude stamp throttles the pass"
    Assert-True ((Get-ClaudeLog $c13) -like "*skipping auto-update*") "UPD-13: Claude throttle is logged"
    Remove-Item -Recurse -Force $c13

    Reset-ClaudeMock
    $c13b = New-ClaudeSandbox @{ "other@some-other-marketplace" = $true }
    Invoke-ClaudeHook $c13b
    Assert-True ($global:ClaudeCalls.Count -eq 0) "UPD-13: no enabled marketplace plugins is a clean no-op"
    Remove-Item -Recurse -Force $c13b
} catch { $script:failures += "UPD-13 threw: $_" }

Write-Host "== UPD-14 Claude plugin.json does not redundantly reference the standard hooks file =="
try {
    $claudePj = Join-Path (Join-Path $pkgRoot ".claude-plugin") "plugin.json"
    Assert-True (Test-Path $claudePj) "UPD-14: .claude-plugin/plugin.json ships"
    $pj = Get-Content -Path $claudePj -Raw | ConvertFrom-Json
    $hooksField = $pj.PSObject.Properties['hooks']
    # Claude Code auto-loads the standard hooks/hooks.json; a manifest reference to it causes a
    # "Duplicate hooks file detected" load failure at install time. The field must be absent (or
    # not point at that standard location).
    $refsStandard = ($null -ne $hooksField) -and ($hooksField.Value -match 'hooks/hooks\.json')
    Assert-True (-not $refsStandard) "UPD-14: Claude plugin.json must not reference the auto-loaded ./hooks/hooks.json"
    Assert-True (Test-Path (Join-Path (Join-Path $pkgRoot "hooks") "hooks.json")) "UPD-14: the standard hooks/hooks.json still ships for auto-load"
} catch { $script:failures += "UPD-14 threw: $_" }

Write-Host "== UPD-15 Claude SessionStart hook is a single per-platform bash dispatcher (no cross-platform spawn failure) =="
try {
    $claudeHooks = Join-Path (Join-Path $pkgRoot "hooks") "hooks.json"
    $ch = Get-Content -Path $claudeHooks -Raw | ConvertFrom-Json
    $handlers = @($ch.hooks.SessionStart[0].hooks)
    # Exactly one handler: Claude runs every handler in a matched group, so a second exec-form
    # `powershell` handler would spawn-fail on macOS/Linux (no `powershell` binary) and surface a
    # `hook error` notice. A single bash handler that dispatches by uname avoids that entirely.
    Assert-True ($handlers.Count -eq 1) "UPD-15: exactly one SessionStart handler (no second handler to spawn-fail cross-platform)"
    $h = $handlers[0]
    Assert-True ($h.shell -eq "bash") "UPD-15: the single handler is a bash handler"
    Assert-True ($null -eq ($handlers | Where-Object { $_.command -eq "powershell" })) "UPD-15: no exec-form powershell handler (would spawn-fail on macOS/Linux)"
    Assert-True (($h.command -match "MINGW") -and ($h.command -match "MSYS") -and ($h.command -match "CYGWIN")) "UPD-15: handler branches on uname for Windows (MINGW/MSYS/CYGWIN)"
    Assert-True ($h.command -match "pwsh") "UPD-15: handler runs pwsh on macOS/Linux"
    Assert-True ($h.command -match "powershell") "UPD-15: handler runs Windows PowerShell on Windows"

    # Functional check: actually execute the real dispatcher command under a real POSIX shell
    # (bash on Linux, Git Bash on Windows), with CLAUDE_PLUGIN_ROOT/CLAUDE_CONFIG_DIR pointed at a
    # sandbox and a stub `claude` CLI on PATH, so the real uname dispatch, the CLAUDE_PLUGIN_ROOT
    # placeholder substitution into the -File path, and the CLAUDE_CONFIG_DIR path resolution are
    # all proven end to end - not just matched as text.
    $bashExe15 = Get-FunctionalBashExe
    if ($bashExe15) {
        $home15 = Join-Path ([IO.Path]::GetTempPath()) ("upd15-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $home15 | Out-Null
        (@{ enabledPlugins = @{ "commentable-html@$marketplace" = $true } } | ConvertTo-Json -Depth 5) |
            Set-Content -Path (Join-Path $home15 "settings.json") -Encoding utf8
        $stubLog15 = Join-Path $home15 "stub-calls.log"
        $bin15 = New-StubCli $home15 "claude" $stubLog15
        $savedPath15 = $env:PATH
        $savedRoot15 = $env:CLAUDE_PLUGIN_ROOT
        $savedConfig15 = $env:CLAUDE_CONFIG_DIR
        try {
            # Use the platform's real PATH separator (";" on Windows, ":" on Linux/macOS) - the
            # dispatcher runs under a real POSIX shell/pwsh which splits PATH on ":" on non-Windows,
            # so a hardcoded ";" here would silently hide the stub CLI from command resolution.
            $env:PATH = "$bin15$([IO.Path]::PathSeparator)$savedPath15"
            $env:CLAUDE_PLUGIN_ROOT = $pkgRoot
            $env:CLAUDE_CONFIG_DIR = $home15
            Invoke-FunctionalBashCommand $bashExe15 $h.command | Out-Null
            Assert-True ($LASTEXITCODE -eq 0) "UPD-15: the real dispatcher command exits cleanly"
        } finally {
            $env:PATH = $savedPath15
            if ($null -eq $savedRoot15) { Remove-Item Env:CLAUDE_PLUGIN_ROOT -ErrorAction SilentlyContinue } else { $env:CLAUDE_PLUGIN_ROOT = $savedRoot15 }
            if ($null -eq $savedConfig15) { Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue } else { $env:CLAUDE_CONFIG_DIR = $savedConfig15 }
        }
        Assert-True ((Test-Path $stubLog15) -and ((Get-Content -Raw $stubLog15) -like "*plugin update commentable-html@$marketplace*")) "UPD-15: the real dispatcher resolves CLAUDE_PLUGIN_ROOT and updates the sandboxed plugin"
        Assert-True ((Get-ClaudeLog $home15) -like "*pass complete: 1 plugin(s) checked*") "UPD-15: the real dispatcher resolves CLAUDE_CONFIG_DIR and completes the pass"
        Remove-Item -Recurse -Force $home15
    } else {
        Write-Host "  (no functional POSIX shell available; structural checks only)"
    }
} catch { $script:failures += "UPD-15 threw: $_" }

Write-Host "== UPD-16 The update script logs a completed pass =="
try {
    $ps1 = Join-Path (Join-Path $pkgRoot "hooks") "marketplace-update.ps1"
    $body = Get-Content -Path $ps1 -Raw
    Assert-True ($body -match "pass complete") "UPD-16: a completed pass is written to the log (not only failures/skips)"
} catch { $script:failures += "UPD-16 threw: $_" }

Write-Host "== UPD-17 persistent, update-safe throttle cadence (config file + env override) =="
try {
    # A user-set cadence lives in plugin-data/<self>.config.json, which is OUTSIDE the shipped
    # installed-plugins subtree a plugin update replaces, so the cadence survives updates.
    $ps1 = Join-Path (Join-Path $pkgRoot "hooks") "marketplace-update.ps1"
    $body = Get-Content -Path $ps1 -Raw
    Assert-True ($body -match "\.config\.json") "UPD-17: throttle is read from a persistent config file"
    Assert-True ($body -match "plugin-data") "UPD-17: the config file lives under plugin-data (survives plugin updates)"

    # Config throttleHours = 0 means no throttle: a recent stamp still lets the pass run every session.
    Reset-Mock
    $h17a = New-Sandbox -plugins @("alpha")
    Set-Config $h17a @{ throttleHours = 0 }
    Set-Stamp $h17a 0.1
    Invoke-Hook $h17a
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-17: throttleHours=0 disables the throttle (runs on every session)"

    # A larger custom throttle skips a pass a recent-ish stamp would otherwise allow at the default.
    Reset-Mock
    $h17b = New-Sandbox -plugins @("alpha")
    Set-Config $h17b @{ throttleHours = 100 }
    Set-Stamp $h17b 48
    Set-CatalogStamp $h17b 0.1
    Invoke-Hook $h17b
    Assert-True ($global:CopilotCalls.Count -eq 0) "UPD-17: a custom throttleHours=100 throttles a 48h-old stamp"
    Assert-True ((Get-Log $h17b) -like "*skipping auto-update*") "UPD-17: the custom-throttle skip is logged"

    # The env override wins over the config file.
    Reset-Mock
    $h17c = New-Sandbox -plugins @("alpha")
    Set-Config $h17c @{ throttleHours = 100 }
    Set-Stamp $h17c 0.1
    $savedEnv = $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS
    try {
        $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS = "0"
        Invoke-Hook $h17c
    } finally {
        if ($null -eq $savedEnv) { Remove-Item Env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS -ErrorAction SilentlyContinue } else { $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS = $savedEnv }
    }
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-17: the env override beats the config file"

    Reset-Mock
    $h17e = New-Sandbox -plugins @("alpha")
    Set-Stamp $h17e 0.1
    $savedInfiniteEnv = $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS
    try {
        $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS = "Infinity"
        Invoke-Hook $h17e
    } finally {
        if ($null -eq $savedInfiniteEnv) { Remove-Item Env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS -ErrorAction SilentlyContinue } else { $env:URIKAN_AI_MARKETPLACE_THROTTLE_HOURS = $savedInfiniteEnv }
    }
    $status17e = Get-Content -Path (Get-StatusPath $h17e) -Raw | ConvertFrom-Json
    Assert-True ($status17e.result -eq "throttled") "UPD-17: non-finite cadence is rejected and falls back to the default"
    Assert-True ((Get-Log $h17e) -like "*ignoring invalid URIKAN_AI_MARKETPLACE_THROTTLE_HOURS*") "UPD-17: rejected non-finite cadence is logged"

    Reset-Mock
    $h17f = New-Sandbox -plugins @("alpha")
    Set-Config $h17f @{ throttleHours = $true }
    Set-Stamp $h17f 2
    Set-CatalogStamp $h17f 0.1
    Invoke-Hook $h17f
    $status17f = Get-Content -Path (Get-StatusPath $h17f) -Raw | ConvertFrom-Json
    Assert-True ($status17f.result -eq "throttled") "UPD-17: Boolean cadence is rejected instead of being coerced to one hour"

    Reset-Mock
    $h17g = New-Sandbox -plugins @("alpha")
    Set-Config $h17g @{ throttleHours = 1e300 }
    Set-Stamp $h17g 2
    Set-CatalogStamp $h17g 0.1
    Invoke-Hook $h17g
    $status17g = Get-Content -Path (Get-StatusPath $h17g) -Raw | ConvertFrom-Json
    Assert-True ($status17g.result -eq "throttled") "UPD-17: cadence that can overflow date arithmetic is rejected"

    # A corrupt config never breaks the hook; it falls back to the 20h default.
    Reset-Mock
    $h17d = New-Sandbox -plugins @("alpha")
    Set-Config $h17d "this is not json {"
    Set-Stamp $h17d 48
    Invoke-Hook $h17d
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-17: a corrupt config falls back to the default and still runs a due pass"

    Remove-Item -Recurse -Force $h17a, $h17b, $h17c, $h17d, $h17e, $h17f, $h17g
} catch { $script:failures += "UPD-17 threw: $_" }

Write-Host "== UPD-18 the skill can set the cadence in free text =="
try {
    $skillMd = Join-Path (Join-Path (Join-Path $pkgRoot "skills") "marketplace-update") "SKILL.md"
    $skill = Get-Content -Path $skillMd -Raw
    Assert-True ($skill -match "(?i)set (the )?(update )?(cadence|frequency)") "UPD-18: skill documents setting the update cadence/frequency"
    Assert-True ($skill -like "*every session*") "UPD-18: skill handles the 'every session' phrasing"
    Assert-True ($skill -like "*$self.config.json*") "UPD-18: skill writes the persistent config file"
    Assert-True ($skill -match "throttleHours") "UPD-18: skill sets the throttleHours key"
} catch { $script:failures += "UPD-18 threw: $_" }

Write-Host "== UPD-19 the skill offers a four-way cadence choice with a 24h default =="
try {
    $skillMd = Join-Path (Join-Path (Join-Path $pkgRoot "skills") "marketplace-update") "SKILL.md"
    $skill = Get-Content -Path $skillMd -Raw
    # When the user asks to change the schedule WITHOUT naming a value (e.g. "change update
    # schedule"), the agent presents the same four-way choice, with 24h as the default.
    Assert-True ($skill -match "(?i)change update (schedule|cadence|frequency)") "UPD-19: skill triggers on 'change update schedule/cadence/frequency'"
    Assert-True ($skill -match "(?i)each session") "UPD-19: skill offers the 'each session' choice"
    Assert-True ($skill -match "(?i)every 1 hour") "UPD-19: skill offers the 'every 1 hour' choice"
    Assert-True ($skill -match "(?i)every 24 hours") "UPD-19: skill offers the 'every 24 hours' choice"
    Assert-True ($skill -match "(?i)custom") "UPD-19: skill offers a custom interval"
    Assert-True ($skill -match "(?im)24 hours.*default") "UPD-19: 24 hours is presented as the default"
} catch { $script:failures += "UPD-19 threw: $_" }

Write-Host "== UPD-20 shipped package includes the canonical MIT license =="
try {
    $license = Join-Path $pkgRoot "LICENSE"
    $canonicalLicense = Join-Path $repoRoot "LICENSE"
    Assert-True (Test-Path $license) "UPD-20: LICENSE ships in the package root"
    if (Test-Path $license) {
        $actual = [IO.File]::ReadAllBytes($license)
        $expected = [IO.File]::ReadAllBytes($canonicalLicense)
        Assert-True ([Linq.Enumerable]::SequenceEqual($actual, $expected)) "UPD-20: shipped LICENSE matches the canonical MIT text"
    }
} catch { $script:failures += "UPD-20 threw: $_" }

Write-Host "== UPD-21 failed update does not write the success throttle stamp =="
try {
    # A pass where one plugin fails must NOT write the stamp so the next session retries.
    Reset-Mock
    $global:CopilotFailFor = "beta"
    $h21 = New-Sandbox -plugins @("alpha", "beta", "gamma")
    Invoke-Hook $h21
    Assert-True (-not (Test-Path (Get-Throttle $h21))) "UPD-21: throttle stamp must NOT be written after a failed update"
    Assert-True ((Get-Log $h21) -like "*update failed for beta*") "UPD-21: the failure is still logged"
    Remove-Item -Recurse -Force $h21

    # Thrown-exception path (catch branch ~line 153): assert stamp is also NOT written
    # when a plugin update throws instead of returning a nonzero exit code.
    Reset-Mock
    $h21t = New-Sandbox -plugins @("alpha", "beta", "gamma")
    Set-Item -Path Function:global:copilot -Value {
        $global:CopilotCalls += , ([string]::Join(" ", $args))
        $target = ($args | Select-Object -Last 1)
        if ($target -like "*beta@*") { throw "simulated throw for $target" }
        $global:LASTEXITCODE = 0
        Write-Output "updated $target"
    }
    Invoke-Hook $h21t
    Assert-True (-not (Test-Path (Get-Throttle $h21t))) "UPD-21: throttle stamp must NOT be written when an update throws"
    Remove-Item -Recurse -Force $h21t

    # A fully successful pass MUST still write the stamp (regression guard).
    $global:CopilotFailFor = $null
    Reset-Mock
    $h21b = New-Sandbox -plugins @("alpha", "beta")
    Invoke-Hook $h21b
    Assert-True (Test-Path (Get-Throttle $h21b)) "UPD-21: throttle stamp IS written after an all-success pass"
    Remove-Item -Recurse -Force $h21b
} catch { $script:failures += "UPD-21 threw: $_" }

Write-Host "== UPD-22 updater self-update runs last and records restart state =="
try {
    Reset-Mock
    $global:CopilotSelfUpdateVersion = "2.0.0"
    $h22 = New-Sandbox -plugins @("alpha", "beta") -IncludeSelf
    Invoke-Hook $h22
    $targets22 = $global:CopilotCalls | ForEach-Object { ($_ -split " ")[-1] }
    Assert-True (($targets22 -join ",") -eq "alpha@$marketplace,beta@$marketplace,$self@$marketplace") "UPD-22: self-update runs once after every managed plugin"
    $status22 = Get-Content -Path (Get-StatusPath $h22) -Raw | ConvertFrom-Json
    Assert-True ($status22.restartRequired -eq $true) "UPD-22: a successful self-update records restartRequired"
    Assert-True ($status22.plugins[-1].name -eq $self) "UPD-22: the final structured outcome belongs to the updater"
    Remove-Item -Recurse -Force $h22

    Reset-Mock
    $global:CopilotFailFor = $self
    $h22b = New-Sandbox -plugins @("alpha") -IncludeSelf
    Invoke-Hook $h22b
    $status22b = Get-Content -Path (Get-StatusPath $h22b) -Raw | ConvertFrom-Json
    Assert-True ($status22b.managedResult -eq "success") "UPD-22: managed-plugin success is preserved when self-update fails"
    Assert-True ($status22b.selfUpdateResult -eq "failed") "UPD-22: self-update failure is recorded separately"
    Remove-Item -Recurse -Force $h22b

    Reset-ClaudeMock
    $global:ClaudePopulateSelfVersionOn = "alpha"
    $global:ClaudePopulatedSelfVersion = "2.0.0"
    $c22 = New-ClaudeSandbox @{
        "alpha@$marketplace" = $true
        "$self@$marketplace" = $true
    }
    Set-ClaudeCacheVersion $c22 "alpha" "1.0.0"
    $activeVersion22c = (Get-Content -Path (Join-Path $pkgRoot "plugin.json") -Raw | ConvertFrom-Json).version
    Set-ClaudeCacheVersion $c22 $self $activeVersion22c
    Invoke-ClaudeHook $c22
    $status22c = Get-Content -Path (Get-StatusPath $c22) -Raw | ConvertFrom-Json
    $selfOutcome22c = @($status22c.plugins | Where-Object { $_.name -eq $self })[0]
    Assert-True ($selfOutcome22c.beforeVersion -eq $activeVersion22c) "UPD-22: Claude self-update compares against the running package, not a newly populated cache entry"
    Assert-True ($status22c.restartRequired -eq $true) "UPD-22: Claude records restartRequired when N+1 entered the cache before the self-update phase"
    Remove-Item -Recurse -Force $c22
} catch { $script:failures += "UPD-22 threw: $_" }

Write-Host "== UPD-23 structured status is atomic and tracks attempts separately from success =="
try {
    Reset-Mock
    $h23 = New-Sandbox -plugins @("alpha", "beta")
    Invoke-Hook $h23
    $firstStatus23 = Get-Content -Path (Get-StatusPath $h23) -Raw | ConvertFrom-Json
    $firstSuccess23 = $firstStatus23.lastSuccess
    Set-Config $h23 @{ throttleHours = 0; catalogCheckHours = 1 }
    Reset-Mock
    $global:CopilotFailFor = "beta"
    Invoke-Hook $h23
    $statusPath23 = Get-StatusPath $h23
    $status23 = Get-Content -Path $statusPath23 -Raw | ConvertFrom-Json
    Assert-True ($status23.schemaVersion -eq 1) "UPD-23: status declares schemaVersion 1"
    Assert-True (-not [string]::IsNullOrWhiteSpace($status23.lastAttempt)) "UPD-23: status records lastAttempt"
    Assert-True ($global:ObservedRunningStatus -eq "running") "UPD-23: the running attempt is persisted before an external plugin operation"
    Assert-True ($status23.lastSuccess -eq $firstSuccess23) "UPD-23: failed pass preserves rather than advances lastSuccess"
    Assert-True ($status23.result -eq "partial") "UPD-23: mixed outcomes produce a partial result (got $($status23.result))"
    Assert-True (-not (Test-Path "$statusPath23.tmp")) "UPD-23: no fixed temporary status file remains after atomic replacement"
    Get-Content -Path $statusPath23 -Raw | ConvertFrom-Json | Out-Null
    Remove-Item -Recurse -Force $h23

    Reset-Mock
    $h23b = New-Sandbox -plugins @("alpha") -IncludeSelf
    Invoke-Hook $h23b
    $previousSuccess23b = (Get-Content -Path (Get-StatusPath $h23b) -Raw | ConvertFrom-Json).lastSuccess
    $throttle23b = Get-Throttle $h23b
    Remove-Item -Path $throttle23b -Force
    New-Item -ItemType Directory -Path $throttle23b | Out-Null
    Set-Config $h23b @{ throttleHours = 0; catalogCheckHours = 1 }
    Reset-Mock
    $global:CopilotSelfUpdateVersion = "2.0.0"
    Invoke-Hook $h23b
    $status23b = Get-Content -Path (Get-StatusPath $h23b) -Raw | ConvertFrom-Json
    Assert-True ($status23b.result -eq "failed") "UPD-23: an uncaught pass failure records a failed result (got $($status23b.result))"
    Assert-True ($status23b.lastSuccess -eq $previousSuccess23b) "UPD-23: outer failure handling preserves the previous lastSuccess (got $($status23b.lastSuccess))"
    Assert-True (@($status23b.plugins).Count -eq 2) "UPD-23: outer failure handling preserves accumulated plugin outcomes"
    Assert-True ($status23b.managedResult -eq "success" -and $status23b.selfUpdateResult -eq "updated") "UPD-23: outer failure handling preserves managed and self-update results"
    Assert-True ($status23b.restartRequired -eq $true) "UPD-23: outer failure handling preserves a completed self-update restart requirement"
    Assert-True ($null -ne $status23b.catalog) "UPD-23: outer failure handling preserves the catalog snapshot"
    Remove-Item -Recurse -Force $h23b
} catch { $script:failures += "UPD-23 threw: $_" }

Write-Host "== UPD-24 catalog checks use an independent one-hour cadence and bypass install throttle =="
try {
    Reset-Mock
    $h24 = New-Sandbox -plugins @("alpha")
    Set-CatalogPluginVersion $h24 "alpha" "2.0.0"
    Set-Config $h24 @{ throttleHours = 24; catalogCheckHours = 1 }
    Set-Stamp $h24 0.1
    Set-CatalogStamp $h24 2
    Invoke-Hook $h24
    Assert-True ($global:CopilotCatalogCalls.Count -eq 1) "UPD-24: a due catalog refresh runs independently of the install throttle"
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-24: a successful due catalog refresh processes plugin updates immediately"
    $status24 = Get-Content -Path (Get-StatusPath $h24) -Raw | ConvertFrom-Json
    Assert-True ($status24.catalog.checkHours -eq 1) "UPD-24: status records the configured catalog-check cadence"
    Assert-True (-not [string]::IsNullOrWhiteSpace($status24.catalog.lastChecked)) "UPD-24: status records the successful catalog refresh"
    Assert-True (-not [string]::IsNullOrWhiteSpace($status24.catalog.revision)) "UPD-24: status records a deterministic catalog revision"
    Assert-True ($status24.plugins[0].targetVersion -eq "2.0.0") "UPD-24: plugin outcomes report the current marketplace target version"
    Remove-Item -Recurse -Force $h24

    Reset-Mock
    $h24b = New-Sandbox -plugins @("alpha")
    Set-Config $h24b @{ throttleHours = 24; catalogCheckHours = 1 }
    Set-Stamp $h24b 0.1
    Set-CatalogStamp $h24b 2
    $global:CopilotFailFor = "alpha"
    Invoke-Hook $h24b
    $failedStatus24b = Get-Content -Path (Get-StatusPath $h24b) -Raw | ConvertFrom-Json
    $retryAt24b = [datetimeoffset]::Parse($failedStatus24b.nextEligiblePass)
    Assert-True ($retryAt24b -le [datetimeoffset]::Now.AddMinutes(1)) "UPD-24: failed pass reports immediate next-session eligibility"
    Reset-Mock
    Invoke-Hook $h24b
    Assert-True ($global:CopilotCatalogCalls.Count -eq 0) "UPD-24: retry does not need another catalog refresh"
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-24: a failed catalog-triggered pass retries on the next session despite both cadences"
    Remove-Item -Recurse -Force $h24b

    Reset-Mock
    $global:CopilotCatalogFails = $true
    $h24c = New-Sandbox -plugins @("alpha")
    Set-Stamp $h24c 0.1
    Remove-Item -Path (Get-CatalogStamp $h24c) -Force
    Invoke-Hook $h24c
    $failedCatalogStatus24c = Get-Content -Path (Get-StatusPath $h24c) -Raw | ConvertFrom-Json
    Assert-True ($failedCatalogStatus24c.result -eq "failed") "UPD-24: failed catalog refresh is recorded when install checks are throttled"
    Assert-True ([datetimeoffset]::Parse($failedCatalogStatus24c.nextEligiblePass) -le [datetimeoffset]::Now.AddMinutes(1)) "UPD-24: failed catalog refresh reports immediate eligibility"
    Remove-Item -Recurse -Force $h24c
} catch { $script:failures += "UPD-24 threw: $_" }

Write-Host "== UPD-25 every plugin has a normalized structured outcome =="
try {
    Reset-Mock
    $global:CopilotFailFor = "beta"
    $h25 = New-Sandbox -plugins @("alpha", "beta")
    Invoke-Hook $h25
    $status25 = Get-Content -Path (Get-StatusPath $h25) -Raw | ConvertFrom-Json
    Assert-True (@($status25.plugins).Count -eq 2) "UPD-25: status contains one outcome per managed plugin"
    $alpha25 = @($status25.plugins | Where-Object { $_.name -eq "alpha" })[0]
    $beta25 = @($status25.plugins | Where-Object { $_.name -eq "beta" })[0]
    Assert-True ($alpha25.result -in @("updated", "already-current", "completed")) "UPD-25: successful plugin has a normalized success outcome"
    Assert-True ($beta25.result -eq "failed" -and $beta25.errorCategory -eq "cli-exit") "UPD-25: failed plugin has a normalized error category"
    Assert-True ($alpha25.durationMs -ge 0 -and $beta25.durationMs -ge 0) "UPD-25: every plugin outcome records duration"
    Remove-Item -Recurse -Force $h25
} catch { $script:failures += "UPD-25 threw: $_" }

Write-Host "== UPD-26 an exclusive cross-process lock prevents overlapping passes =="
try {
    Reset-Mock
    $h26 = New-Sandbox -plugins @("alpha")
    $lockPath26 = Get-LockPath $h26
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lockPath26) | Out-Null
    $held26 = [IO.File]::Open($lockPath26, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try { Invoke-Hook $h26 } finally { $held26.Dispose() }
    Assert-True ($global:CopilotCalls.Count -eq 0) "UPD-26: a second pass performs no plugin updates while the lock is held"
    Assert-True ((Get-Log $h26) -like "*another pass is running*") "UPD-26: lock contention is logged with an explicit outcome"
    Remove-Item -Recurse -Force $h26

    Reset-Mock
    $h26b = New-Sandbox -plugins @("alpha")
    New-Item -ItemType Directory -Force -Path (Get-LockPath $h26b) | Out-Null
    Invoke-Hook $h26b
    Assert-True ((Get-Log $h26b) -like "*lock unavailable*") "UPD-26: non-contention lock errors are not mislabeled as another pass"
    Remove-Item -Recurse -Force $h26b
} catch { $script:failures += "UPD-26 threw: $_" }

Write-Host "== UPD-27 updater logs rotate at a bounded size =="
try {
    Reset-Mock
    $h27 = New-Sandbox -plugins @("alpha")
    $logPath27 = Join-Path (Join-Path $h27 "plugin-data") "$self.log"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath27) | Out-Null
    [IO.File]::WriteAllText($logPath27, ("x" * 300000))
    Invoke-Hook $h27
    Assert-True (Test-Path "$logPath27.1") "UPD-27: oversized current log is rotated to .1"
    Assert-True ((Get-Item $logPath27).Length -lt 300000) "UPD-27: a fresh bounded current log is created"
    Assert-True (-not (Test-Path "$logPath27.4")) "UPD-27: rotation retains no more than three archives"
    Remove-Item -Recurse -Force $h27
} catch { $script:failures += "UPD-27 threw: $_" }

Write-Host "== UPD-28 health mode explains state without updating plugins =="
try {
    Reset-Mock
    $h28 = New-Sandbox -plugins @("alpha") -IncludeSelf
    Invoke-Hook $h28
    Reset-Mock
    $health28 = @(Invoke-Hook $h28 "health") -join [Environment]::NewLine
    $healthJson28 = $health28 | ConvertFrom-Json
    Assert-True ($global:CopilotCalls.Count -eq 0 -and $global:CopilotCatalogCalls.Count -eq 0) "UPD-28: health mode performs no CLI update operations"
    Assert-True ($healthJson28.agent -eq "copilot") "UPD-28: health output identifies the current agent"
    Assert-True (-not [string]::IsNullOrWhiteSpace($healthJson28.activeUpdaterVersion)) "UPD-28: health output reports the active updater version"
    Assert-True ($null -ne $healthJson28.plugins) "UPD-28: health output reports managed plugin state"
    Assert-True ($null -ne $healthJson28.lastAttempt -and $null -ne $healthJson28.nextEligiblePass) "UPD-28: health output reports attempt and eligibility timing"
    $skill28 = Get-Content -Path (Join-Path (Join-Path (Join-Path $pkgRoot "skills") "marketplace-update") "SKILL.md") -Raw
    Assert-True ($skill28 -match "(?i)check updater health") "UPD-28: the bundled skill triggers on updater-health requests"
    Assert-True ($skill28 -match "(?i)-Mode health") "UPD-28: the bundled skill invokes the read-only health mode"
    $activated28 = Get-Content -Path (Get-StatusPath $h28) -Raw | ConvertFrom-Json
    $activated28.restartRequired = $true
    $activeVersion28 = (Get-Content -Path (Join-Path $pkgRoot "plugin.json") -Raw | ConvertFrom-Json).version
    $activated28.plugins += [pscustomobject]@{ name = $self; finalVersion = $activeVersion28 }
    $activated28 | ConvertTo-Json -Depth 8 | Set-Content -Path (Get-StatusPath $h28) -Encoding utf8
    $activatedHealth28 = @(Invoke-Hook $h28 "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($activatedHealth28.restartRequired -eq $false) "UPD-28: health clears restartRequired after the updated package becomes active"

    $interrupted28 = $activatedHealth28
    $interrupted28.result = "running"
    $interrupted28.reason = "Update pass started."
    $interrupted28 | ConvertTo-Json -Depth 8 | Set-Content -Path (Get-StatusPath $h28) -Encoding utf8
    $interruptedHealth28 = @(Invoke-Hook $h28 "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($interruptedHealth28.result -eq "interrupted") "UPD-28: an abandoned running state is reported as interrupted"
    Assert-True ($interruptedHealth28.remediation -match "(?i)retry") "UPD-28: interrupted health includes a retry remediation"

    $heldLock28 = [IO.File]::Open((Get-LockPath $h28), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $activeHealth28 = @(Invoke-Hook $h28 "health") -join [Environment]::NewLine | ConvertFrom-Json
    } finally {
        $heldLock28.Dispose()
    }
    Assert-True ($activeHealth28.result -eq "running") "UPD-28: a locked running state remains active rather than interrupted"
    Assert-True ($activeHealth28.remediation -match "(?i)wait") "UPD-28: an active running state tells the user to wait"
    Remove-Item -Recurse -Force $h28

    Reset-Mock
    $h28b = New-Sandbox -plugins @()
    $pluginData28b = Join-Path $h28b "plugin-data"
    $null = @(Invoke-Hook $h28b "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True (-not (Test-Path $pluginData28b)) "UPD-28: read-only health does not create plugin-data or a lock file"
    Remove-Item -Recurse -Force $h28b

    Reset-Mock
    $h28f = New-Sandbox -plugins @("alpha")
    Set-Stamp $h28f 0.1
    Remove-Item -Path (Get-CatalogStamp $h28f) -Force
    $health28f = @(Invoke-Hook $h28f "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ([datetimeoffset]::Parse($health28f.nextEligiblePass) -le [datetimeoffset]::Now.AddMinutes(1)) "UPD-28: a missing cadence stamp reports immediate eligibility"
    Remove-Item -Recurse -Force $h28f

    Reset-Mock
    $h28g = New-Sandbox -plugins @("alpha")
    Set-Config $h28g "{ invalid json"
    $config28g = Join-Path (Join-Path $h28g "plugin-data") "$self.config.json"
    $beforeConfig28g = Get-Content -Path $config28g -Raw
    $null = @(Invoke-Hook $h28g "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True (-not (Test-Path (Join-Path (Join-Path $h28g "plugin-data") "$self.log"))) "UPD-28: malformed config does not make read-only health write a log"
    Assert-True ((Get-Content -Path $config28g -Raw) -eq $beforeConfig28g) "UPD-28: read-only health does not modify malformed config"
    Remove-Item -Recurse -Force $h28g

    Reset-Mock
    $h28e = New-Sandbox -plugins @() -IncludeSelf
    $lockPath28e = Get-LockPath $h28e
    New-Item -ItemType Directory -Force -Path $lockPath28e | Out-Null
    $health28e = @(Invoke-Hook $h28e "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($health28e.lockState -eq "unavailable") "UPD-28: non-contention lock errors are distinguished from an active pass"
    Assert-True ($health28e.remediation -match "(?i)permissions|lock") "UPD-28: lock errors include actionable remediation"
    Remove-Item -Recurse -Force $h28e

    Reset-Mock
    $h28c = New-Sandbox -plugins @()
    Set-Stamp $h28c 0.1
    Invoke-Hook $h28c
    $status28c = Get-Content -Path (Get-StatusPath $h28c) -Raw | ConvertFrom-Json
    Assert-True ([datetimeoffset]::Parse($status28c.nextEligiblePass) -le [datetimeoffset]::Now.AddMinutes(1)) "UPD-28: no-plugins outcome is immediately eligible for retry"
    Remove-Item -Recurse -Force $h28c

    Reset-Mock
    $h28d = New-Sandbox -plugins @("alpha")
    Set-Stamp $h28d 0.1
    Remove-Item Function:copilot -ErrorAction SilentlyContinue
    Invoke-Hook $h28d
    $status28d = Get-Content -Path (Get-StatusPath $h28d) -Raw | ConvertFrom-Json
    Assert-True ($status28d.result -eq "missing-cli") "UPD-28: missing CLI is recorded"
    Assert-True ([datetimeoffset]::Parse($status28d.nextEligiblePass) -le [datetimeoffset]::Now.AddMinutes(1)) "UPD-28: missing-cli outcome is immediately eligible for retry"
    Remove-Item -Recurse -Force $h28d

    Reset-ClaudeMock
    $c28 = New-ClaudeSandbox @{ "$self@$marketplace" = $false }
    Set-ClaudeCacheVersion $c28 $self "1.9.0"
    Set-ClaudeCacheVersion $c28 $self "1.10.0"
    $healthClaude28 = @(Invoke-ClaudeHook $c28 "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($healthClaude28.installed -eq $true -and $healthClaude28.enabled -eq $false) "UPD-28: Claude health distinguishes installed-but-disabled from missing"
    Assert-True ($healthClaude28.marketplaceUpdaterVersion -eq "1.10.0") "UPD-28: Claude cache versions are selected semantically, not lexically"
    Assert-True ($healthClaude28.remediation -match "(?i)enable") "UPD-28: disabled updater health includes an enable remediation"
    Remove-Item -Recurse -Force $c28

    Reset-ClaudeMock
    $c28b = New-ClaudeSandbox @{ "$self@$marketplace" = $false }
    Set-ClaudeCacheVersion $c28b $self "1.10.0-beta.10"
    Set-ClaudeCacheVersion $c28b $self "1.10.0-beta.2"
    $healthClaude28b = @(Invoke-ClaudeHook $c28b "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($healthClaude28b.marketplaceUpdaterVersion -eq "1.10.0-beta.10") "UPD-28: Claude prerelease cache versions follow SemVer precedence"
    Remove-Item -Recurse -Force $c28b

    Reset-Mock
    $h28h = New-Sandbox -plugins @("alpha") -IncludeSelf
    Set-CopilotCachedMarketplaceVersion $h28h $self "2.0.0"
    $health28h = @(Invoke-Hook $h28h "health") -join [Environment]::NewLine | ConvertFrom-Json
    Assert-True ($health28h.marketplaceUpdaterVersion -eq "2.0.0") "UPD-28: Copilot health resolves the refreshed platform marketplace cache"
    Assert-True (-not [string]::IsNullOrWhiteSpace($health28h.catalog.revision)) "UPD-28: Copilot catalog revision includes the platform marketplace cache"
    Remove-Item -Recurse -Force $h28h

    $hookBody28 = Get-Content -Path $hookScript -Raw
    Assert-True ($hookBody28 -notmatch '\.claude-plugin\\plugin\.json') "UPD-28: Claude manifest lookup does not embed a Windows-only path separator"
} catch { $script:failures += "UPD-28 threw: $_" }

Write-Host "== UPD-29 real CLI lifecycle suite is wired into both platform jobs =="
try {
    $lifecycleScript29 = Join-Path $here "real_cli_lifecycle.py"
    $workflow29 = Get-Content -Path (Join-Path (Join-Path (Join-Path $repoRoot ".github") "workflows") "pwsh-tests.yml") -Raw
    Assert-True (Test-Path $lifecycleScript29) "UPD-29: the hermetic real-CLI lifecycle harness exists"
    Assert-True ($workflow29 -match 'python plugins/urikan-ai-marketplace-auto-updater/dev/tests/real_cli_lifecycle\.py') "UPD-29: the required cross-platform job runs the real-CLI lifecycle harness"
    Assert-True ($workflow29 -match '@github/copilot@1\.0\.83') "UPD-29: CI pins the Copilot CLI used by the lifecycle harness"
    Assert-True ($workflow29 -match '@anthropic-ai/claude-code@2\.1\.251') "UPD-29: CI pins the Claude CLI used by the lifecycle harness"
} catch { $script:failures += "UPD-29 threw: $_" }

Remove-Item Function:copilot -ErrorAction SilentlyContinue
Remove-Item Function:claude -ErrorAction SilentlyContinue

Write-Host ""
if ($script:failures.Count -gt 0) {
    Write-Host "FAILED ($($script:failures.Count) assertion(s), $script:passes passed):" -ForegroundColor Red
    $script:failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "OK: all $script:passes assertions passed." -ForegroundColor Green
exit 0
