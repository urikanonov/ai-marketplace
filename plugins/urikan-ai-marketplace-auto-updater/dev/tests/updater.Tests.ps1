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

$script:failures = @()
$script:passes = 0

function Assert-True($condition, $message) {
    if ($condition) { $script:passes++ } else { $script:failures += $message; Write-Host "  FAIL: $message" -ForegroundColor Red }
}

function New-Sandbox([string[]]$plugins, [switch]$IncludeSelf) {
    $root = Join-Path ([IO.Path]::GetTempPath()) ("upd-" + [Guid]::NewGuid().ToString("N"))
    $installed = Join-Path (Join-Path $root "installed-plugins") $marketplace
    New-Item -ItemType Directory -Force -Path $installed | Out-Null
    foreach ($p in $plugins) { New-Item -ItemType Directory -Force -Path (Join-Path $installed $p) | Out-Null }
    if ($IncludeSelf) { New-Item -ItemType Directory -Force -Path (Join-Path $installed $self) | Out-Null }
    return $root
}

function Reset-Mock {
    $global:CopilotCalls = @()
    $global:CopilotFailFor = $null
    Set-Item -Path Function:global:copilot -Value {
        $global:CopilotCalls += , ([string]::Join(" ", $args))
        $target = ($args | Select-Object -Last 1)
        if ($global:CopilotFailFor -and $target -like "*$($global:CopilotFailFor)@*") {
            $global:LASTEXITCODE = 1
            Write-Output "simulated failure for $target"
        } else {
            $global:LASTEXITCODE = 0
            Write-Output "updated $target"
        }
    }
}

function Invoke-Hook([string]$copilotHome) {
    $savedPath = $env:PATH
    $savedHome = $env:COPILOT_HOME
    try {
        $env:PATH = ""              # keep the stub function authoritative; never hit a real copilot on PATH
        $env:COPILOT_HOME = $copilotHome
        & $hookScript
    } finally {
        $env:PATH = $savedPath
        if ($null -eq $savedHome) { Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_HOME = $savedHome }
    }
}

function Get-Log([string]$copilotHome) {
    $log = Join-Path (Join-Path $copilotHome "plugin-data") "$self.log"
    if (Test-Path $log) { return (Get-Content -Path $log -Raw) } else { return "" }
}

function Get-Throttle([string]$copilotHome) {
    return Join-Path (Join-Path $copilotHome "plugin-data") "$self.last-run"
}

function Set-Config([string]$copilotHome, $config) {
    $pd = Join-Path $copilotHome "plugin-data"
    New-Item -ItemType Directory -Force -Path $pd | Out-Null
    $path = Join-Path $pd "$self.config.json"
    if ($config -is [string]) { $config | Set-Content -Path $path -Encoding utf8 }
    else { ($config | ConvertTo-Json) | Set-Content -Path $path -Encoding utf8 }
}

function Set-Stamp([string]$copilotHome, [double]$hoursAgo) {
    $stamp = Get-Throttle $copilotHome
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

function Reset-ClaudeMock {
    $global:ClaudeCalls = @()
    Set-Item -Path Function:global:claude -Value {
        $global:ClaudeCalls += , ([string]::Join(" ", $args))
        $global:LASTEXITCODE = 0
        Write-Output ("updated " + ($args | Select-Object -Last 1))
    }
}

function Invoke-ClaudeHook([string]$claudeHome) {
    $savedPath = $env:PATH
    $savedHome = $env:CLAUDE_CONFIG_DIR
    try {
        $env:PATH = ""
        $env:CLAUDE_CONFIG_DIR = $claudeHome
        & $hookScript -Agent claude
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
    if ($IsWindows) {
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
    if ($IsWindows) {
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
    if ($IsWindows) {
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
            $destName = if ($IsWindows) { Split-Path -Leaf $native } else { $name }
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
    $pwshNames = if ($IsWindows) { @("pwsh.exe", "pwsh.cmd", "pwsh.bat") } else { @("pwsh") }
    $dirs = ($path -split [regex]::Escape($sep)) | Where-Object { $_ }
    $kept = $dirs | Where-Object {
        $dir = $_
        -not ($pwshNames | Where-Object { Test-Path -LiteralPath (Join-Path $dir $_) -PathType Leaf })
    }
    return ($kept -join $sep)
}

Write-Host "== UPD-01 self-exclusion =="
try {
    Reset-Mock
    $home1 = New-Sandbox -plugins @("alpha") -IncludeSelf
    Invoke-Hook $home1
    Assert-True (($global:CopilotCalls -join "|") -like "*alpha@$marketplace*") "UPD-01: alpha should be updated"
    Assert-True (-not (($global:CopilotCalls -join "|") -like "*$self@*")) "UPD-01: self must not be updated"
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
    if ($IsWindows -and (Get-Command powershell -ErrorAction SilentlyContinue)) {
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
            & $bashExe "-c" $bash | Out-Null
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
    Invoke-Hook $home8c
    Assert-True ($global:CopilotCalls.Count -eq 0) "UPD-08: the default cadence is 24h (a 22h-old pass is throttled)"
    Remove-Item -Recurse -Force $home8, $home8b, $home8c
} catch { $script:failures += "UPD-08 threw: $_" }

Write-Host "== UPD-09 Claude enumerates enabledPlugins and excludes self =="
try {
    Reset-ClaudeMock
    $c9 = New-ClaudeSandbox @{ "commentable-html@$marketplace" = $true; "$self@$marketplace" = $true }
    Invoke-ClaudeHook $c9
    Assert-True (($global:ClaudeCalls -join "|") -like "*commentable-html@$marketplace*") "UPD-09: commentable-html updated under Claude"
    Assert-True (-not (($global:ClaudeCalls -join "|") -like "*$self@*")) "UPD-09: self excluded under Claude"
    Assert-True ($global:ClaudeCalls.Count -eq 1) "UPD-09: exactly one Claude update (self skipped)"
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
            & $bashExe15 "-c" $h.command | Out-Null
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

    # A corrupt config never breaks the hook; it falls back to the 20h default.
    Reset-Mock
    $h17d = New-Sandbox -plugins @("alpha")
    Set-Config $h17d "this is not json {"
    Set-Stamp $h17d 48
    Invoke-Hook $h17d
    Assert-True ($global:CopilotCalls.Count -eq 1) "UPD-17: a corrupt config falls back to the default and still runs a due pass"

    Remove-Item -Recurse -Force $h17a, $h17b, $h17c, $h17d
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
