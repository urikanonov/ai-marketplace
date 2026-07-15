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
} catch { $script:failures += "UPD-06 threw: $_" }

Write-Host "== UPD-07 missing-pwsh log signal in bash field =="
try {
    $hooks = Get-Content -Path $hooksJson -Raw | ConvertFrom-Json
    $bash = $hooks.hooks.sessionStart[0].bash
    Assert-True ($bash -like "*command -v pwsh*") "UPD-07: bash field probes for pwsh"
    Assert-True ($bash -like "*plugin-data*" -and $bash -like "*$self.log*") "UPD-07: bash field targets the plugin-data log"
    Assert-True ($bash -like "*not found on PATH*") "UPD-07: bash field logs a discoverable skip note"
    # Functional check of the else (missing-pwsh) branch on POSIX shells, where this field
    # actually runs. On Windows the powershell field is used instead, and git-bash mangles
    # Windows paths, so the structural checks above stand in there.
    $bashExe = Get-Command bash -ErrorAction SilentlyContinue
    if ($bashExe -and -not $IsWindows) {
        $elseBranch = $null
        if ($bash -match "else\s+(.*);\s*fi\s*$") { $elseBranch = $Matches[1] }
        if ($elseBranch) {
            $home7 = Join-Path ([IO.Path]::GetTempPath()) ("b7-" + [Guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Force -Path $home7 | Out-Null
            $prev = $env:COPILOT_HOME
            try {
                $env:COPILOT_HOME = $home7
                & $bashExe.Source "-c" $elseBranch | Out-Null
            } finally {
                if ($null -eq $prev) { Remove-Item Env:COPILOT_HOME -ErrorAction SilentlyContinue } else { $env:COPILOT_HOME = $prev }
            }
            $logPath = Join-Path (Join-Path $home7 "plugin-data") "$self.log"
            Assert-True ((Test-Path $logPath) -and ((Get-Content -Raw $logPath) -like "*not found on PATH*")) "UPD-07: else branch writes the skip note to the log"
            Remove-Item -Recurse -Force $home7
        } else {
            Write-Host "  (could not isolate else branch; structural checks only)"
        }
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
    Remove-Item -Recurse -Force $home8, $home8b
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
} catch { $script:failures += "UPD-15 threw: $_" }

Write-Host "== UPD-16 The update script logs a completed pass =="
try {
    $ps1 = Join-Path (Join-Path $pkgRoot "hooks") "marketplace-update.ps1"
    $body = Get-Content -Path $ps1 -Raw
    Assert-True ($body -match "pass complete") "UPD-16: a completed pass is written to the log (not only failures/skips)"
} catch { $script:failures += "UPD-16 threw: $_" }

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
