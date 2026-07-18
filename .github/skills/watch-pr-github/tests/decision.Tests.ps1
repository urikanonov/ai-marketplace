#!/usr/bin/env pwsh
# Cross-platform (pwsh) unit tests for the watch-pr-github watcher's pure decision logic
# (watcher-decision.ps1). No gh calls, no network, no filesystem state: every test builds a
# mocked PR-state snapshot and asserts the emitted EVENT and the persisted seen-set. Trust
# and viewer permission are injected as scriptblocks so the safety-critical merge gating is
# fully deterministic.
#
# Feature ids are WPG-DECISION-NN (see ../SPEC.md). Run:
#   pwsh -NoProfile -File .github/skills/watch-pr-github/tests/decision.Tests.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path (Split-Path -Parent $here) 'watcher-decision.ps1')

$script:failures = @()
$script:passes = 0

function Assert-True($condition, $message) {
    if ($condition) { $script:passes++ } else { $script:failures += $message; Write-Host "  FAIL: $message" -ForegroundColor Red }
}

function Assert-Eq($expected, $actual, $message) {
    Assert-True ($expected -eq $actual) "$message (expected '$expected', got '$actual')"
}

# A merge-capable maintainer by default; individual tests override with -Perm / -Trust.
$MaintainerPerm = { 'admin' }
$NonMaintainerPerm = { 'read' }
$UnknownPerm = { 'unknown' }
$TrustAll = { param($login, $assoc) $true }
$TrustNone = { param($login, $assoc) $false }
# Trust only allowlisted Copilot logins and OWNER association (mirrors Is-Trusted).
$TrustCopilotOrOwner = {
    param($login, $assoc)
    if ($login -in @('copilot-pull-request-reviewer', 'Copilot')) { return $true }
    if ($assoc -eq 'OWNER') { return $true }
    return $false
}

function New-Snapshot {
    param(
        [bool]$Merged = $false,
        [string]$State = 'OPEN',
        [string]$Oid = 'abc123',
        [string]$Rollup = 'SUCCESS',
        [string]$Mergeable = 'MERGEABLE',
        [string]$MergeStateStatus = 'CLEAN',
        [string]$ReviewDecision = '',
        [bool]$AutoMergeEnabled = $false,
        [bool]$IsDraft = $false,
        [bool]$ViewerApproved = $false,
        [string[]]$FailedCheckIds = @(),
        [object[]]$Feedback = @()
    )
    return [pscustomobject]@{
        Merged           = $Merged
        State            = $State
        Oid              = $Oid
        Rollup           = $Rollup
        Mergeable        = $Mergeable
        MergeStateStatus = $MergeStateStatus
        ReviewDecision   = $ReviewDecision
        AutoMergeEnabled = $AutoMergeEnabled
        IsDraft          = $IsDraft
        ViewerApproved   = $ViewerApproved
        FailedCheckIds   = $FailedCheckIds
        Feedback         = $Feedback
    }
}

function Invoke-Decision {
    param($Snapshot, [string]$Viewer = 'me', [bool]$OptedOut = $false, [string[]]$Seen = @(), $Trust = $TrustAll, $Perm = $MaintainerPerm)
    return Get-WatcherDecision -Snapshot $Snapshot -Viewer $Viewer -OptedOut $OptedOut -Seen $Seen -IsTrusted $Trust -ResolveViewerPermission $Perm
}

Write-Host "== WPG-DECISION-01 merged/closed take precedence over everything =="
try {
    # Even a conflicting, failing, draft snapshot yields PR_MERGED when merged.
    $s = New-Snapshot -Merged $true -Mergeable 'CONFLICTING' -Rollup 'FAILURE' -IsDraft $true
    Assert-Eq 'EVENT=PR_MERGED' (Invoke-Decision $s).Event 'WPG-DECISION-01: merged wins'
    $s2 = New-Snapshot -State 'CLOSED' -Mergeable 'CONFLICTING'
    Assert-Eq 'EVENT=PR_CLOSED' (Invoke-Decision $s2).Event 'WPG-DECISION-01: closed wins'
} catch { $script:failures += "WPG-DECISION-01 threw: $_" }

Write-Host "== WPG-DECISION-02 MERGE_CONFLICT fires once per oid, on CONFLICTING or DIRTY =="
try {
    $s = New-Snapshot -Mergeable 'CONFLICTING' -MergeStateStatus 'DIRTY'
    $d = Invoke-Decision $s
    Assert-Eq 'EVENT=MERGE_CONFLICT' $d.Event 'WPG-DECISION-02: CONFLICTING emits'
    Assert-True ($d.Seen -contains 'conflict:abc123') 'WPG-DECISION-02: conflict key persisted'
    # Seen-guarded: same oid does not re-fire.
    $d2 = Invoke-Decision $s -Seen $d.Seen
    Assert-Eq $null $d2.Event 'WPG-DECISION-02: seen conflict does not re-fire'
    # DIRTY merge state also counts.
    $sd = New-Snapshot -MergeStateStatus 'DIRTY'
    Assert-Eq 'EVENT=MERGE_CONFLICT' (Invoke-Decision $sd).Event 'WPG-DECISION-02: DIRTY emits'
} catch { $script:failures += "WPG-DECISION-02 threw: $_" }

Write-Host "== WPG-DECISION-03 DISABLE_AUTO_MERGE cancels an interrupted / objectionable auto-merge (NOT seen-guarded) =="
try {
    # Opt-out with an active auto-merge -> cancel, and it re-emits even if a stale key exists.
    $s = New-Snapshot -AutoMergeEnabled $true
    $d = Invoke-Decision $s -OptedOut $true
    Assert-Eq 'EVENT=DISABLE_AUTO_MERGE reason=optout' $d.Event 'WPG-DECISION-03: optout cancels'
    $d2 = Invoke-Decision $s -OptedOut $true -Seen @('conflict:abc123', 'held:abc123', 'ready:abc123')
    Assert-Eq 'EVENT=DISABLE_AUTO_MERGE reason=optout' $d2.Event 'WPG-DECISION-03: re-emits (not seen-guarded)'
    # Changes-requested with an active auto-merge -> cancel over the objection.
    $sc = New-Snapshot -AutoMergeEnabled $true -ReviewDecision 'CHANGES_REQUESTED'
    Assert-Eq 'EVENT=DISABLE_AUTO_MERGE reason=changes' (Invoke-Decision $sc).Event 'WPG-DECISION-03: changes cancels'
} catch { $script:failures += "WPG-DECISION-03 threw: $_" }

Write-Host "== WPG-DECISION-04 CHECKS_FAILED keyed by failing run ids; a rerun re-fires =="
try {
    $s = New-Snapshot -Rollup 'FAILURE' -MergeStateStatus 'BLOCKED' -FailedCheckIds @('cr20', 'cr10')
    $d = Invoke-Decision $s
    Assert-Eq 'EVENT=CHECKS_FAILED oid=abc123 runs=cr10,cr20' $d.Event 'WPG-DECISION-04: sorted failing runs surfaced'
    Assert-True ($d.Seen -contains 'checks:abc123:cr10+cr20') 'WPG-DECISION-04: checks key persisted'
    # Same failing set does not re-fire.
    Assert-Eq $null (Invoke-Decision $s -Seen $d.Seen).Event 'WPG-DECISION-04: identical failure suppressed'
    # A rerun with new run ids re-fires.
    $s2 = New-Snapshot -Rollup 'FAILURE' -MergeStateStatus 'BLOCKED' -FailedCheckIds @('cr99')
    Assert-Eq 'EVENT=CHECKS_FAILED oid=abc123 runs=cr99' (Invoke-Decision $s2 -Seen $d.Seen).Event 'WPG-DECISION-04: rerun re-fires'
} catch { $script:failures += "WPG-DECISION-04 threw: $_" }

Write-Host "== WPG-DECISION-05 NEW_COMMENTS classifies trusted vs untrusted and filters non-Copilot bots =="
try {
    $fb = @(
        [pscustomobject]@{ Kind = 'thread'; Key = 'thread:t1:1'; Login = 'octocat'; Assoc = 'NONE' },
        [pscustomobject]@{ Kind = 'review'; Key = 'review:2'; Login = 'Copilot'; Assoc = 'NONE' },
        [pscustomobject]@{ Kind = 'issue'; Key = 'issue:3'; Login = 'owner'; Assoc = 'OWNER' },
        [pscustomobject]@{ Kind = 'issue'; Key = 'issue:4'; Login = 'dependabot[bot]'; Assoc = 'NONE' }
    )
    $s = New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fb
    $d = Invoke-Decision $s -Trust $TrustCopilotOrOwner
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[review:2,issue:3] untrusted=[thread:t1:1]' $d.Event 'WPG-DECISION-05: trust split + bot filter'
    Assert-True ($d.Seen -notcontains 'issue:4') 'WPG-DECISION-05: non-Copilot bot issue comment skipped'
    # A [bot] on a review thread (not issue/review kind) is NOT skipped.
    $fb2 = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t9:9'; Login = 'some[bot]'; Assoc = 'NONE' })
    $d2 = Invoke-Decision (New-Snapshot -Feedback $fb2) -Trust $TrustNone
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t9:9]' $d2.Event 'WPG-DECISION-05: thread bot not skipped'
    # Already-seen feedback does not re-fire.
    Assert-Eq $null (Invoke-Decision $s -Seen $d.Seen -Trust $TrustCopilotOrOwner).Event 'WPG-DECISION-05: seen comments suppressed'
} catch { $script:failures += "WPG-DECISION-05 threw: $_" }

Write-Host "== WPG-DECISION-06 USER_APPROVED only for a merge-capable actor, honoring the merge guards =="
try {
    $s = New-Snapshot -ViewerApproved $true
    Assert-Eq 'EVENT=USER_APPROVED login=me' (Invoke-Decision $s -Perm $MaintainerPerm).Event 'WPG-DECISION-06: maintainer approval enables auto-merge'
    # Non-maintainer approval must NOT enable auto-merge (falls through to readiness).
    Assert-Eq 'EVENT=AWAITING_MAINTAINER_MERGE mergeState=CLEAN' (Invoke-Decision $s -Perm $NonMaintainerPerm).Event 'WPG-DECISION-06: non-maintainer approval does not merge'
    # Opt-out suppresses USER_APPROVED (falls through to READY_HELD).
    Assert-Eq 'EVENT=READY_HELD mergeState=CLEAN' (Invoke-Decision $s -OptedOut $true).Event 'WPG-DECISION-06: opt-out suppresses approval-merge'
    # Changes-requested suppresses USER_APPROVED.
    $sc = New-Snapshot -ViewerApproved $true -ReviewDecision 'CHANGES_REQUESTED'
    Assert-Eq 'EVENT=CHANGES_REQUESTED' (Invoke-Decision $sc).Event 'WPG-DECISION-06: changes-requested suppresses approval-merge'
} catch { $script:failures += "WPG-DECISION-06 threw: $_" }

Write-Host "== WPG-DECISION-07 DRAFT_HELD once per oid, and a draft never merges =="
try {
    $s = New-Snapshot -IsDraft $true
    $d = Invoke-Decision $s
    Assert-Eq 'EVENT=DRAFT_HELD' $d.Event 'WPG-DECISION-07: draft surfaced'
    Assert-Eq $null (Invoke-Decision $s -Seen $d.Seen).Event 'WPG-DECISION-07: draft held once per oid'
} catch { $script:failures += "WPG-DECISION-07 threw: $_" }

Write-Host "== WPG-DECISION-08 BRANCH_BEHIND when the base advanced =="
try {
    $s = New-Snapshot -MergeStateStatus 'BEHIND'
    $d = Invoke-Decision $s
    Assert-Eq 'EVENT=BRANCH_BEHIND' $d.Event 'WPG-DECISION-08: behind surfaced'
    Assert-Eq $null (Invoke-Decision $s -Seen $d.Seen).Event 'WPG-DECISION-08: behind once per oid'
} catch { $script:failures += "WPG-DECISION-08 threw: $_" }

Write-Host "== WPG-DECISION-09 CHANGES_REQUESTED surfaces (never silently merges over an objection) =="
try {
    $s = New-Snapshot -ReviewDecision 'CHANGES_REQUESTED'
    Assert-Eq 'EVENT=CHANGES_REQUESTED' (Invoke-Decision $s).Event 'WPG-DECISION-09: changes-requested surfaced'
} catch { $script:failures += "WPG-DECISION-09 threw: $_" }

Write-Host "== WPG-DECISION-10 READY_HELD when the user opted out of the merge =="
try {
    $s = New-Snapshot
    $d = Invoke-Decision $s -OptedOut $true
    Assert-Eq 'EVENT=READY_HELD mergeState=CLEAN' $d.Event 'WPG-DECISION-10: opt-out holds at readiness'
    # UNSTABLE also holds.
    $su = New-Snapshot -MergeStateStatus 'UNSTABLE'
    Assert-Eq 'EVENT=READY_HELD mergeState=UNSTABLE' (Invoke-Decision $su -OptedOut $true).Event 'WPG-DECISION-10: opt-out holds on UNSTABLE too'
} catch { $script:failures += "WPG-DECISION-10 threw: $_" }

Write-Host "== WPG-DECISION-11 READY_TO_MERGE for a maintainer; UNSTABLE is ready too =="
try {
    Assert-Eq 'EVENT=READY_TO_MERGE mergeState=CLEAN' (Invoke-Decision (New-Snapshot) -Perm $MaintainerPerm).Event 'WPG-DECISION-11: CLEAN ready'
    # UNSTABLE (only a non-required check not green) is ready.
    Assert-Eq 'EVENT=READY_TO_MERGE mergeState=UNSTABLE' (Invoke-Decision (New-Snapshot -MergeStateStatus 'UNSTABLE') -Perm $MaintainerPerm).Event 'WPG-DECISION-11: UNSTABLE ready'
    # Once ready:$oid is seen, it does not re-fire.
    $d = Invoke-Decision (New-Snapshot) -Perm $MaintainerPerm
    Assert-Eq $null (Invoke-Decision (New-Snapshot) -Seen $d.Seen -Perm $MaintainerPerm).Event 'WPG-DECISION-11: ready once per oid'
} catch { $script:failures += "WPG-DECISION-11 threw: $_" }

Write-Host "== WPG-DECISION-12 a non-maintainer NEVER merges: AWAITING_MAINTAINER_MERGE, once =="
try {
    $d = Invoke-Decision (New-Snapshot) -Perm $NonMaintainerPerm
    Assert-Eq 'EVENT=AWAITING_MAINTAINER_MERGE mergeState=CLEAN' $d.Event 'WPG-DECISION-12: non-maintainer awaits'
    Assert-True ($d.Event -ne 'EVENT=READY_TO_MERGE mergeState=CLEAN') 'WPG-DECISION-12: never READY for non-maintainer'
    Assert-Eq $null (Invoke-Decision (New-Snapshot) -Seen $d.Seen -Perm $NonMaintainerPerm).Event 'WPG-DECISION-12: awaits once per oid'
} catch { $script:failures += "WPG-DECISION-12 threw: $_" }

Write-Host "== WPG-DECISION-13 transient-permission failure re-probes rather than demoting =="
try {
    # 'unknown' (a transiently failed lookup) emits nothing and does NOT record a key.
    $d = Invoke-Decision (New-Snapshot) -Perm $UnknownPerm
    Assert-Eq $null $d.Event 'WPG-DECISION-13: unknown perm emits nothing'
    Assert-True ($d.Seen -notcontains 'await:abc123' -and $d.Seen -notcontains 'ready:abc123') 'WPG-DECISION-13: unknown records no ready/await key'
    # Next poll, once the lookup succeeds as write+, it is promoted to READY.
    Assert-Eq 'EVENT=READY_TO_MERGE mergeState=CLEAN' (Invoke-Decision (New-Snapshot) -Seen $d.Seen -Perm $MaintainerPerm).Event 'WPG-DECISION-13: re-probed to READY'
} catch { $script:failures += "WPG-DECISION-13 threw: $_" }

Write-Host "== WPG-DECISION-14 an active auto-merge suppresses readiness events =="
try {
    # With auto-merge enabled and no opt-out / objection, no readiness event fires.
    Assert-Eq $null (Invoke-Decision (New-Snapshot -AutoMergeEnabled $true)).Event 'WPG-DECISION-14: auto-merge suppresses readiness'
} catch { $script:failures += "WPG-DECISION-14 threw: $_" }

Write-Host "== WPG-DECISION-15 Resolve-OptOut: -NoMerge wins, sticky persists, -AllowMerge clears =="
try {
    # -NoMerge sets the sticky opt-out.
    Assert-True (Resolve-OptOut -StickyNoMerge $false -NoMerge).OptedOut 'WPG-DECISION-15: -NoMerge sets opt-out'
    # Sticky persists with neither switch.
    Assert-True (Resolve-OptOut -StickyNoMerge $true).OptedOut 'WPG-DECISION-15: sticky persists'
    # -AllowMerge clears it.
    Assert-True (-not (Resolve-OptOut -StickyNoMerge $true -AllowMerge).OptedOut) 'WPG-DECISION-15: -AllowMerge clears'
    # Conflicting switches: -NoMerge takes precedence (fail closed).
    Assert-True (Resolve-OptOut -StickyNoMerge $false -NoMerge -AllowMerge).OptedOut 'WPG-DECISION-15: -NoMerge beats -AllowMerge'
    # Changed flag reflects a transition only.
    Assert-True (Resolve-OptOut -StickyNoMerge $false -NoMerge).Changed 'WPG-DECISION-15: change detected'
    Assert-True (-not (Resolve-OptOut -StickyNoMerge $true -NoMerge).Changed) 'WPG-DECISION-15: no change when already set'
} catch { $script:failures += "WPG-DECISION-15 threw: $_" }

Write-Host "== WPG-DECISION-16 ConvertFrom-WatcherState fails CLOSED on a corrupt state file =="
try {
    # Corrupt JSON -> opt-out assumed so a corrupt file can never silently re-enable merging.
    Assert-True (ConvertFrom-WatcherState -Json '{ this is not json').NoMerge 'WPG-DECISION-16: corrupt -> fail closed to opt-out'
    # Empty / missing -> no opt-out, empty seen.
    $empty = ConvertFrom-WatcherState -Json ''
    Assert-True (-not $empty.NoMerge) 'WPG-DECISION-16: empty state is not opted out'
    Assert-Eq 0 @($empty.Seen).Count 'WPG-DECISION-16: empty state has no seen keys'
    # Valid state round-trips seen + noMerge.
    $ok = ConvertFrom-WatcherState -Json '{"seen":["ready:x"],"noMerge":true}'
    Assert-True ($ok.NoMerge -and ($ok.Seen -contains 'ready:x')) 'WPG-DECISION-16: valid state parsed'
} catch { $script:failures += "WPG-DECISION-16 threw: $_" }

Write-Host "== WPG-DECISION-17 Get-FailedCheckIds maps and sorts CheckRun / StatusContext failures =="
try {
    $contexts = @(
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 20; conclusion = 'FAILURE' },
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 5; conclusion = 'SUCCESS' },
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 7; conclusion = 'TIMED_OUT' },
        [pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/pending'; state = 'PENDING' },
        [pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/broken'; state = 'ERROR' }
    )
    $ids = Get-FailedCheckIds -Contexts $contexts
    Assert-Eq 'cr20,cr7,scci/broken' ($ids -join ',') 'WPG-DECISION-17: only failures, sorted; passing/pending excluded'
} catch { $script:failures += "WPG-DECISION-17 threw: $_" }

Write-Host ""
if ($script:failures.Count -gt 0) {
    Write-Host "FAILED ($($script:failures.Count) assertion(s), $script:passes passed):" -ForegroundColor Red
    $script:failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "OK: all $script:passes assertions passed." -ForegroundColor Green
exit 0
