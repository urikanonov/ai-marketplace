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
    param($Snapshot, [string]$Viewer = 'me', [bool]$OptedOut = $false, [string[]]$Seen = @(), $Trust = $TrustAll, $Perm = $MaintainerPerm, [bool]$FeedbackAvailable = $true)
    return Get-WatcherDecision -Snapshot $Snapshot -Viewer $Viewer -OptedOut $OptedOut -Seen $Seen -IsTrusted $Trust -ResolveViewerPermission $Perm -FeedbackAvailable $FeedbackAvailable
}

Write-Host "== WPG-DECISION-01 merged/closed take precedence over everything =="
try {
    # Even a conflicting, failing, draft snapshot yields PR_MERGED when merged.
    $s = New-Snapshot -Merged $true -Mergeable 'CONFLICTING' -Rollup 'FAILURE' -IsDraft $true
    $dm = Invoke-Decision $s
    Assert-Eq 'EVENT=PR_MERGED' $dm.Event 'WPG-DECISION-01: merged wins'
    # A terminal event adds no seen key, so it is not persisted (Changed is false).
    Assert-True (-not $dm.Changed) 'WPG-DECISION-01: terminal event does not grow the seen-set'
    $s2 = New-Snapshot -State 'CLOSED' -Mergeable 'CONFLICTING'
    Assert-Eq 'EVENT=PR_CLOSED' (Invoke-Decision $s2).Event 'WPG-DECISION-01: closed wins'
} catch { $script:failures += "WPG-DECISION-01 threw: $_" }

Write-Host "== WPG-DECISION-02 MERGE_CONFLICT fires once per oid, on CONFLICTING or DIRTY =="
try {
    $s = New-Snapshot -Mergeable 'CONFLICTING' -MergeStateStatus 'DIRTY'
    $d = Invoke-Decision $s
    Assert-Eq 'EVENT=MERGE_CONFLICT' $d.Event 'WPG-DECISION-02: CONFLICTING emits'
    Assert-True ($d.Seen -contains 'conflict:abc123') 'WPG-DECISION-02: conflict key persisted'
    Assert-True $d.Changed 'WPG-DECISION-02: conflict grows the seen-set (persisted)'
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
    # When BOTH opt-out and changes-requested hold, opt-out is the reported reason (precedence).
    $sb = New-Snapshot -AutoMergeEnabled $true -ReviewDecision 'CHANGES_REQUESTED'
    Assert-Eq 'EVENT=DISABLE_AUTO_MERGE reason=optout' (Invoke-Decision $sb -OptedOut $true).Event 'WPG-DECISION-03: optout reason beats changes'
    # DISABLE_AUTO_MERGE adds no seen key, so it is not persisted (Changed is false).
    Assert-True (-not $d.Changed) 'WPG-DECISION-03: cancel event does not grow the seen-set'
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
    # A custom -CopilotLogins list is honored: a [bot] in the list is NOT filtered on an issue.
    $fb3 = @([pscustomobject]@{ Kind = 'issue'; Key = 'issue:7'; Login = 'my-bot[bot]'; Assoc = 'NONE' })
    $d3 = Get-WatcherDecision -Snapshot (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fb3) -Viewer 'me' -Seen @() -IsTrusted $TrustNone -ResolveViewerPermission $MaintainerPerm -CopilotLogins @('my-bot[bot]')
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[issue:7]' $d3.Event 'WPG-DECISION-05: custom CopilotLogins keeps an allowlisted bot'
    # A duplicate feedback key (e.g. a pagination cursor shift returning the same node twice)
    # is added only once, not duplicated into the emitted event.
    $fbDup = @(
        [pscustomobject]@{ Kind = 'issue'; Key = 'issue:9'; Login = 'octocat'; Assoc = 'NONE' },
        [pscustomobject]@{ Kind = 'issue'; Key = 'issue:9'; Login = 'octocat'; Assoc = 'NONE' }
    )
    $dDup = Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbDup) -Trust $TrustNone
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[issue:9]' $dDup.Event 'WPG-DECISION-05: duplicate feedback key de-duplicated'
    Assert-True $dDup.Changed 'WPG-DECISION-05: NEW_COMMENTS grows the seen-set'
    # Ordering: unseen feedback takes precedence over USER_APPROVED and readiness, even for a
    # merge-capable viewer who approved -- NEW_COMMENTS wins and no approved:/ready: key is added.
    $fbA = @([pscustomobject]@{ Kind = 'issue'; Key = 'issue:11'; Login = 'octocat'; Assoc = 'NONE' })
    $dA = Invoke-Decision (New-Snapshot -ViewerApproved $true -Feedback $fbA) -Trust $TrustNone -Perm $MaintainerPerm
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[issue:11]' $dA.Event 'WPG-DECISION-05: NEW_COMMENTS beats USER_APPROVED/readiness'
    Assert-True ($dA.Seen -notcontains 'approved:abc123' -and $dA.Seen -notcontains 'ready:abc123') 'WPG-DECISION-05: no approval/ready key while comments are unseen'
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
    # A DRAFT approved by the viewer must NOT fire USER_APPROVED; it surfaces DRAFT_HELD and
    # records no approved: key (the guard is `-not $p.IsDraft`).
    $sd = New-Snapshot -ViewerApproved $true -IsDraft $true
    $dd = Invoke-Decision $sd -Perm $MaintainerPerm
    Assert-Eq 'EVENT=DRAFT_HELD' $dd.Event 'WPG-DECISION-06: draft suppresses approval-merge'
    Assert-True ($dd.Seen -notcontains 'approved:abc123') 'WPG-DECISION-06: draft records no approved key'
    # Once approved:$oid is seen, USER_APPROVED does not re-nudge and falls through to readiness.
    Assert-Eq 'EVENT=READY_TO_MERGE mergeState=CLEAN' (Invoke-Decision $s -Seen @('approved:abc123') -Perm $MaintainerPerm).Event 'WPG-DECISION-06: approved seen-guard falls through to READY'
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
    # The SAME re-probe guard protects the USER_APPROVED path: a viewer-approved snapshot with
    # 'unknown' perm emits nothing and records no key, then promotes to USER_APPROVED once the
    # lookup succeeds (a regression that fired approval-merge on a transient failure is caught).
    $sa = New-Snapshot -ViewerApproved $true
    $da = Invoke-Decision $sa -Perm $UnknownPerm
    Assert-Eq $null $da.Event 'WPG-DECISION-13: unknown perm emits no USER_APPROVED'
    Assert-True ($da.Seen -notcontains 'approved:abc123' -and $da.Seen -notcontains 'ready:abc123' -and $da.Seen -notcontains 'await:abc123') 'WPG-DECISION-13: unknown records no approval/ready/await key'
    Assert-Eq 'EVENT=USER_APPROVED login=me' (Invoke-Decision $sa -Seen $da.Seen -Perm $MaintainerPerm).Event 'WPG-DECISION-13: approval re-probed to USER_APPROVED'
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
    # Empty / whitespace state content -> fail CLOSED (an existing but truncated/blank state
    # file is corruption; the genuine no-file first-run case is handled by the caller, not here).
    Assert-True (ConvertFrom-WatcherState -Json '').NoMerge 'WPG-DECISION-16: empty content fails closed'
    Assert-True (ConvertFrom-WatcherState -Json "  `n ").NoMerge 'WPG-DECISION-16: whitespace content fails closed'
    Assert-Eq 0 @((ConvertFrom-WatcherState -Json '').Seen).Count 'WPG-DECISION-16: empty state has no seen keys'
    # Valid state round-trips seen + noMerge.
    $ok = ConvertFrom-WatcherState -Json '{"seen":["ready:x"],"noMerge":true}'
    Assert-True ($ok.NoMerge -and ($ok.Seen -contains 'ready:x')) 'WPG-DECISION-16: valid state parsed'
    # A valid state that is NOT opted out round-trips noMerge=false.
    Assert-True (-not (ConvertFrom-WatcherState -Json '{"seen":[],"noMerge":false}').NoMerge) 'WPG-DECISION-16: valid non-opted-out state parsed'
    # Partial / tampered state fails CLOSED per field: a null or missing noMerge assumes the
    # opt-out, and a null or missing seen is an empty set (never a set with a null element).
    Assert-True (ConvertFrom-WatcherState -Json '{"seen":["ready:x"],"noMerge":null}').NoMerge 'WPG-DECISION-16: null noMerge fails closed'
    Assert-True (ConvertFrom-WatcherState -Json '{"seen":["ready:x"]}').NoMerge 'WPG-DECISION-16: missing noMerge fails closed'
    $ns = ConvertFrom-WatcherState -Json '{"seen":null,"noMerge":false}'
    Assert-Eq 0 @($ns.Seen).Count 'WPG-DECISION-16: null seen -> empty set'
    Assert-Eq 0 @((ConvertFrom-WatcherState -Json '{"noMerge":true}').Seen).Count 'WPG-DECISION-16: missing seen -> empty set'
} catch { $script:failures += "WPG-DECISION-16 threw: $_" }

Write-Host "== WPG-DECISION-17 Get-FailedCheckIds maps and sorts CheckRun / StatusContext failures =="
try {
    $contexts = @(
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 20; conclusion = 'FAILURE' },
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 5; conclusion = 'SUCCESS' },
        [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 7; conclusion = 'TIMED_OUT' },
        [pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/pending'; state = 'PENDING'; createdAt = '2026-01-01T00:00:00Z' },
        [pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/broken'; state = 'ERROR'; createdAt = '2026-01-01T00:00:00Z' }
    )
    $ids = Get-FailedCheckIds -Contexts $contexts
    # A StatusContext is keyed by its context name AND its createdAt (so a repost re-fires).
    Assert-Eq 'cr20,cr7,scci/broken@2026-01-01T00:00:00Z' ($ids -join ',') 'WPG-DECISION-17: only failures, sorted; passing/pending excluded; StatusContext keyed with createdAt'
    # Null / empty inputs (a PR with no checks) yield an empty list, not a StrictMode throw.
    Assert-Eq 0 @(Get-FailedCheckIds -Contexts @()).Count 'WPG-DECISION-17: empty contexts -> empty'
    Assert-Eq 0 @(Get-FailedCheckIds -Contexts $null).Count 'WPG-DECISION-17: null contexts -> empty'
    Assert-Eq 'cr8' ((Get-FailedCheckIds -Contexts @($null, [pscustomobject]@{ __typename = 'CheckRun'; databaseId = 8; conclusion = 'FAILURE' })) -join ',') 'WPG-DECISION-17: null context entry skipped'
    # A StatusContext with a missing or null createdAt degrades to name-only keying (sc<ctx>@) and
    # does NOT throw under StrictMode (createdAt is read via PSObject.Properties).
    Assert-Eq 'scci/x@' ((Get-FailedCheckIds -Contexts @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/x'; state = 'FAILURE' })) -join ',') 'WPG-DECISION-17: missing createdAt degrades to name-only key'
    Assert-Eq 'scci/y@' ((Get-FailedCheckIds -Contexts @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/y'; state = 'ERROR'; createdAt = $null })) -join ',') 'WPG-DECISION-17: null createdAt degrades to name-only key'
    # createdAt is canonicalized, so a [datetime] (pwsh 7 ConvertFrom-Json) and the equivalent ISO
    # string (Windows PowerShell 5.1) produce the SAME key.
    $asString = (Get-FailedCheckIds -Contexts @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/z'; state = 'FAILURE'; createdAt = '2026-03-04T05:06:07Z' })) -join ','
    $asDate = (Get-FailedCheckIds -Contexts @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/z'; state = 'FAILURE'; createdAt = ([datetime]::new(2026, 3, 4, 5, 6, 7, [System.DateTimeKind]::Utc)) })) -join ','
    Assert-Eq 'scci/z@2026-03-04T05:06:07Z' $asString 'WPG-DECISION-17: ISO-string createdAt canonicalized'
    Assert-Eq $asString $asDate 'WPG-DECISION-17: datetime and ISO-string createdAt yield the same key'
} catch { $script:failures += "WPG-DECISION-17 threw: $_" }

Write-Host "== WPG-DECISION-22 a StatusContext re-failure (fail -> pass -> fail) re-fires CHECKS_FAILED =="
try {
    $oid = 'abc123'
    # First failure of a legacy status.
    $c1 = @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/legacy'; state = 'FAILURE'; createdAt = '2026-01-01T10:00:00Z' })
    $s1 = New-Snapshot -Rollup 'FAILURE' -MergeStateStatus 'BLOCKED' -FailedCheckIds (Get-FailedCheckIds -Contexts $c1)
    $d1 = Invoke-Decision $s1
    Assert-Eq "EVENT=CHECKS_FAILED oid=$oid runs=scci/legacy@2026-01-01T10:00:00Z" $d1.Event 'WPG-DECISION-22: first StatusContext failure fires'
    # The SAME failure (same createdAt) does not re-fire.
    Assert-Eq $null (Invoke-Decision $s1 -Seen $d1.Seen).Event 'WPG-DECISION-22: unchanged StatusContext failure suppressed'
    # After a pass then a new failure, the reposted status has a NEW createdAt -> new key -> re-fires.
    $c2 = @([pscustomobject]@{ __typename = 'StatusContext'; context = 'ci/legacy'; state = 'FAILURE'; createdAt = '2026-01-01T12:00:00Z' })
    $s2 = New-Snapshot -Rollup 'FAILURE' -MergeStateStatus 'BLOCKED' -FailedCheckIds (Get-FailedCheckIds -Contexts $c2)
    Assert-Eq "EVENT=CHECKS_FAILED oid=$oid runs=scci/legacy@2026-01-01T12:00:00Z" (Invoke-Decision $s2 -Seen $d1.Seen).Event 'WPG-DECISION-22: re-failure with new createdAt re-fires'
} catch { $script:failures += "WPG-DECISION-22 threw: $_" }

Write-Host "== WPG-DECISION-23 a review thread is trusted only if ALL participants are trusted (least-privileged) =="
try {
    # Trust only OWNER association (a stand-in for a confirmed maintainer).
    $trustOwner = { param($login, $assoc) $assoc -eq 'OWNER' }
    # A thread whose participants are all trusted -> trusted.
    $fbAll = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t1:9'; Login = 'maint'; Assoc = 'OWNER'; Participants = @(
                [pscustomobject]@{ Login = 'maint'; Assoc = 'OWNER' },
                [pscustomobject]@{ Login = 'maint2'; Assoc = 'OWNER' }) })
    $dAll = Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbAll) -Trust $trustOwner
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[thread:t1:9] untrusted=[]' $dAll.Event 'WPG-DECISION-23: all-trusted thread is trusted'
    # A thread where the LATEST comment is a trusted maintainer but an EARLIER participant is
    # external must be classified UNtrusted (least-privileged), so the external comment is vetted.
    $fbMixed = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t2:9'; Login = 'maint'; Assoc = 'OWNER'; Participants = @(
                [pscustomobject]@{ Login = 'ext'; Assoc = 'NONE' },
                [pscustomobject]@{ Login = 'maint'; Assoc = 'OWNER' }) })
    $dMixed = Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbMixed) -Trust $trustOwner
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t2:9]' $dMixed.Event 'WPG-DECISION-23: an external participant makes the thread untrusted'
    # Issue/review items (no Participants) still classify by their single author (backward compatible).
    $fbIssue = @([pscustomobject]@{ Kind = 'issue'; Key = 'issue:5'; Login = 'maint'; Assoc = 'OWNER' })
    $dIssue = Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbIssue) -Trust $trustOwner
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[issue:5] untrusted=[]' $dIssue.Event 'WPG-DECISION-23: single-author item still classifies by its author'
    # A thread whose only participant is external is untrusted.
    $fbExt = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t3:9'; Login = 'ext'; Assoc = 'NONE'; Participants = @([pscustomobject]@{ Login = 'ext'; Assoc = 'NONE' }) })
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t3:9]' (Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbExt) -Trust $trustOwner).Event 'WPG-DECISION-23: sole external participant is untrusted'
    # A null-author participant (deleted account) makes the thread untrusted (fail closed).
    $fbNull = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t4:9'; Login = 'maint'; Assoc = 'OWNER'; Participants = @(
                [pscustomobject]@{ Login = $null; Assoc = 'NONE' },
                [pscustomobject]@{ Login = 'maint'; Assoc = 'OWNER' }) })
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t4:9]' (Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbNull) -Trust $trustOwner).Event 'WPG-DECISION-23: null-author participant makes the thread untrusted'
    # A TRUNCATED thread (more comments than were fetched) fails closed to untrusted even if every
    # fetched participant is trusted, because an older untrusted participant might be unseen.
    $fbTrunc = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t5:9'; Login = 'maint'; Assoc = 'OWNER'; ParticipantsTruncated = $true; Participants = @(
                [pscustomobject]@{ Login = 'maint'; Assoc = 'OWNER' }) })
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t5:9]' (Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbTrunc) -Trust $trustOwner).Event 'WPG-DECISION-23: truncated participant window fails closed to untrusted'
    # A present-but-EMPTY Participants list fails closed to untrusted (never silently trusted).
    $fbEmpty = @([pscustomobject]@{ Kind = 'thread'; Key = 'thread:t6:9'; Login = 'maint'; Assoc = 'OWNER'; Participants = @() })
    Assert-Eq 'EVENT=NEW_COMMENTS trusted=[] untrusted=[thread:t6:9]' (Invoke-Decision (New-Snapshot -MergeStateStatus 'BLOCKED' -Feedback $fbEmpty) -Trust $trustOwner).Event 'WPG-DECISION-23: empty participant list fails closed to untrusted'
} catch { $script:failures += "WPG-DECISION-23 threw: $_" }

Write-Host "== WPG-DECISION-24 ConvertTo-CanonicalTimestamp normalizes datetimes and strings to a stable key =="
try {
    $inv = '2026-03-04T05:06:07Z'
    Assert-Eq $inv (ConvertTo-CanonicalTimestamp '2026-03-04T05:06:07Z') 'WPG-DECISION-24: ISO string round-trips'
    Assert-Eq $inv (ConvertTo-CanonicalTimestamp ([datetime]::new(2026, 3, 4, 5, 6, 7, [System.DateTimeKind]::Utc))) 'WPG-DECISION-24: UTC datetime canonicalized'
    # A non-UTC datetime is converted to UTC so the key is timezone-stable.
    $local = [datetime]::new(2026, 3, 4, 5, 6, 7, [System.DateTimeKind]::Utc).ToLocalTime()
    Assert-Eq $inv (ConvertTo-CanonicalTimestamp $local) 'WPG-DECISION-24: local datetime converted to UTC'
    # Null / blank -> '' (a stable no-op).
    Assert-Eq '' (ConvertTo-CanonicalTimestamp $null) 'WPG-DECISION-24: null -> empty'
    Assert-Eq '' (ConvertTo-CanonicalTimestamp '   ') 'WPG-DECISION-24: blank -> empty'
} catch { $script:failures += "WPG-DECISION-24 threw: $_" }

Write-Host "== WPG-DECISION-18 Test-CommenterTrusted fails closed on bots and unprivileged accounts =="
try {
    $writePerm = { param($l) 'write' }
    $readPerm = { param($l) 'read' }
    $unknownPerm = { param($l) 'unknown' }
    # An allowlisted Copilot login is trusted (including its [bot] form) without a perm lookup.
    Assert-True (Test-CommenterTrusted -Login 'copilot-pull-request-reviewer' -Assoc 'NONE' -PermissionResolver $readPerm) 'WPG-DECISION-18: allowlisted Copilot trusted'
    Assert-True (Test-CommenterTrusted -Login 'copilot-swe-agent[bot]' -Assoc 'NONE' -PermissionResolver $readPerm) 'WPG-DECISION-18: allowlisted Copilot [bot] trusted'
    # A generic [bot] is NEVER trusted, even with a MEMBER association and write permission.
    Assert-True (-not (Test-CommenterTrusted -Login 'random[bot]' -Assoc 'MEMBER' -PermissionResolver $writePerm)) 'WPG-DECISION-18: generic bot fails closed even with write perm'
    # OWNER association is trusted.
    Assert-True (Test-CommenterTrusted -Login 'owner' -Assoc 'OWNER' -PermissionResolver $readPerm) 'WPG-DECISION-18: OWNER trusted'
    # A human with write+ permission is trusted; read is not; unknown is not.
    Assert-True (Test-CommenterTrusted -Login 'maint' -Assoc 'MEMBER' -PermissionResolver $writePerm) 'WPG-DECISION-18: write perm trusted'
    Assert-True (-not (Test-CommenterTrusted -Login 'reader' -Assoc 'COLLABORATOR' -PermissionResolver $readPerm)) 'WPG-DECISION-18: read perm not trusted'
    Assert-True (-not (Test-CommenterTrusted -Login 'nope' -Assoc 'NONE' -PermissionResolver $unknownPerm)) 'WPG-DECISION-18: unknown perm not trusted'
    # A custom -CopilotLogins list is honored.
    Assert-True (Test-CommenterTrusted -Login 'my-bot[bot]' -Assoc 'NONE' -PermissionResolver $readPerm -CopilotLogins @('my-bot[bot]')) 'WPG-DECISION-18: custom allowlist honored'
} catch { $script:failures += "WPG-DECISION-18 threw: $_" }

Write-Host "== WPG-DECISION-19 feedback-unavailable holds NEW_COMMENTS onward (fail closed), pre-feedback events still fire =="
try {
    # When this poll's feedback could not be fetched, an otherwise-ready PR must NOT advance:
    # no USER_APPROVED, no readiness, no DRAFT_HELD -- the watcher holds and retries.
    Assert-Eq $null (Invoke-Decision (New-Snapshot) -Perm $MaintainerPerm -FeedbackAvailable $false).Event 'WPG-DECISION-19: no READY when feedback unavailable'
    Assert-Eq $null (Invoke-Decision (New-Snapshot -ViewerApproved $true) -Perm $MaintainerPerm -FeedbackAvailable $false).Event 'WPG-DECISION-19: no USER_APPROVED when feedback unavailable'
    Assert-Eq $null (Invoke-Decision (New-Snapshot -IsDraft $true) -FeedbackAvailable $false).Event 'WPG-DECISION-19: no DRAFT_HELD when feedback unavailable'
    Assert-Eq $null (Invoke-Decision (New-Snapshot -MergeStateStatus 'BEHIND') -FeedbackAvailable $false).Event 'WPG-DECISION-19: no BRANCH_BEHIND when feedback unavailable'
    # But the pre-feedback events (terminal, conflict, auto-merge cancel, failing checks) still
    # fire even when feedback is unavailable -- they do not depend on it.
    Assert-Eq 'EVENT=PR_MERGED' (Invoke-Decision (New-Snapshot -Merged $true) -FeedbackAvailable $false).Event 'WPG-DECISION-19: terminal still fires'
    Assert-Eq 'EVENT=MERGE_CONFLICT' (Invoke-Decision (New-Snapshot -MergeStateStatus 'DIRTY') -FeedbackAvailable $false).Event 'WPG-DECISION-19: conflict still fires'
    Assert-Eq 'EVENT=DISABLE_AUTO_MERGE reason=optout' (Invoke-Decision (New-Snapshot -AutoMergeEnabled $true) -OptedOut $true -FeedbackAvailable $false).Event 'WPG-DECISION-19: auto-merge cancel still fires'
    Assert-Eq 'EVENT=CHECKS_FAILED oid=abc123 runs=cr1' (Invoke-Decision (New-Snapshot -Rollup 'FAILURE' -FailedCheckIds @('cr1')) -FeedbackAvailable $false).Event 'WPG-DECISION-19: failing checks still fire'
} catch { $script:failures += "WPG-DECISION-19 threw: $_" }

Write-Host "== WPG-DECISION-20 Test-ViewerApproved reflects the viewer's LATEST review state =="
try {
    # Reviews are passed oldest -> newest as @{ Login; State }.
    $me = 'me'
    # Viewer approved and nothing since -> approved.
    Assert-True (Test-ViewerApproved -Reviews @([pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 1 }) -Viewer $me) 'WPG-DECISION-20: lone approval counts'
    # Viewer approved then later requested changes -> NOT approved (the bug #407 fixes: any-historical-APPROVED was wrong).
    Assert-True (-not (Test-ViewerApproved -Reviews @(
                [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 1 },
                [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = 2 }) -Viewer $me)) 'WPG-DECISION-20: later changes-requested overrides the approval'
    # Viewer approved then dismissed their own review -> NOT approved.
    Assert-True (-not (Test-ViewerApproved -Reviews @(
                [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 1 },
                [pscustomobject]@{ Login = 'me'; State = 'DISMISSED'; Order = 2 }) -Viewer $me)) 'WPG-DECISION-20: later dismissal overrides the approval'
    # A later COMMENTED review does NOT supersede a standing approval (only APPROVED/CHANGES_REQUESTED/DISMISSED count).
    Assert-True (Test-ViewerApproved -Reviews @(
            [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 1 },
            [pscustomobject]@{ Login = 'me'; State = 'COMMENTED'; Order = 2 }) -Viewer $me) 'WPG-DECISION-20: a later COMMENTED review does not revoke approval'
    # Only OTHER users approved -> viewer not approved.
    Assert-True (-not (Test-ViewerApproved -Reviews @([pscustomobject]@{ Login = 'someone'; State = 'APPROVED'; Order = 1 }) -Viewer $me)) 'WPG-DECISION-20: another user approving does not count'
    # Viewer requested changes then approved -> approved (latest wins the other way too).
    Assert-True (Test-ViewerApproved -Reviews @(
            [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = 1 },
            [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 2 }) -Viewer $me) 'WPG-DECISION-20: latest approval after changes counts'
    # No reviews / empty viewer -> not approved.
    Assert-True (-not (Test-ViewerApproved -Reviews @() -Viewer $me)) 'WPG-DECISION-20: no reviews -> not approved'
    Assert-True (-not (Test-ViewerApproved -Reviews @([pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 1 }) -Viewer '')) 'WPG-DECISION-20: empty viewer -> not approved'
    # A viewer whose ONLY review is COMMENTED is not approved (COMMENTED is not a meaningful state).
    Assert-True (-not (Test-ViewerApproved -Reviews @([pscustomobject]@{ Login = 'me'; State = 'COMMENTED'; Order = 1 }) -Viewer $me)) 'WPG-DECISION-20: sole COMMENTED review is not approved'
    # A null-Login review (deleted author) is never attributed to the viewer.
    Assert-True (-not (Test-ViewerApproved -Reviews @(
                [pscustomobject]@{ Login = $null; State = 'APPROVED'; Order = 1 },
                [pscustomobject]@{ Login = 'me'; State = 'COMMENTED'; Order = 2 }) -Viewer $me)) 'WPG-DECISION-20: null-login review is skipped'
    # Another user's review interleaved between the viewer's own reviews is ignored.
    Assert-True (Test-ViewerApproved -Reviews @(
            [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = 1 },
            [pscustomobject]@{ Login = 'other'; State = 'CHANGES_REQUESTED'; Order = 2 },
            [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 3 }) -Viewer $me) 'WPG-DECISION-20: interleaved other-user review ignored'
    # "Latest" is decided by Order, not array position: an APPROVED with a higher Order that
    # appears FIRST in the array still wins over an earlier-ordered CHANGES_REQUESTED.
    Assert-True (Test-ViewerApproved -Reviews @(
            [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 9 },
            [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = 4 }) -Viewer $me) 'WPG-DECISION-20: higher Order approval wins regardless of array position'
    # And the reverse: a higher-Order CHANGES_REQUESTED beats an earlier-ordered APPROVED.
    Assert-True (-not (Test-ViewerApproved -Reviews @(
                [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = 9 },
                [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 4 }) -Viewer $me)) 'WPG-DECISION-20: higher Order changes-requested wins regardless of array position'
    # Fail CLOSED on a missing ordering key: a null-Order CHANGES_REQUESTED alongside a numeric
    # APPROVED must NOT report approved (a null Order would otherwise sort first and let the
    # stale APPROVED win). Without a reliable recency key, do not risk a false approval.
    Assert-True (-not (Test-ViewerApproved -Reviews @(
                [pscustomobject]@{ Login = 'me'; State = 'APPROVED'; Order = 4 },
                [pscustomobject]@{ Login = 'me'; State = 'CHANGES_REQUESTED'; Order = $null }) -Viewer $me)) 'WPG-DECISION-20: null Order fails closed'
} catch { $script:failures += "WPG-DECISION-20 threw: $_" }

Write-Host "== WPG-DECISION-21 ConvertTo-ReviewStates normalizes gh review nodes and tolerates nulls =="
try {
    # gh-shaped nodes (author{login}, state, databaseId) -> ordered @{ Login; State; Order }.
    $raw = @(
        [pscustomobject]@{ author = [pscustomobject]@{ login = 'me' }; state = 'APPROVED'; databaseId = 5 },
        $null,
        [pscustomobject]@{ author = $null; state = 'COMMENTED'; databaseId = 6 }
    )
    $states = ConvertTo-ReviewStates -RawReviews $raw
    Assert-Eq 2 @($states).Count 'WPG-DECISION-21: null node skipped'
    Assert-Eq 'me' $states[0].Login 'WPG-DECISION-21: author login mapped'
    Assert-Eq 'APPROVED' $states[0].State 'WPG-DECISION-21: state mapped'
    Assert-Eq 5 $states[0].Order 'WPG-DECISION-21: databaseId mapped to Order'
    Assert-True ($null -eq $states[1].Login) 'WPG-DECISION-21: null author -> null Login'
    # Empty / null input -> empty list, no throw.
    Assert-Eq 0 @(ConvertTo-ReviewStates -RawReviews @()).Count 'WPG-DECISION-21: empty input -> empty'
    Assert-Eq 0 @(ConvertTo-ReviewStates -RawReviews $null).Count 'WPG-DECISION-21: null input -> empty'
    # Round-trips into Test-ViewerApproved: a normalized withdrawn approval is not approved.
    $rt = ConvertTo-ReviewStates -RawReviews @(
        [pscustomobject]@{ author = [pscustomobject]@{ login = 'me' }; state = 'APPROVED'; databaseId = 1 },
        [pscustomobject]@{ author = [pscustomobject]@{ login = 'me' }; state = 'CHANGES_REQUESTED'; databaseId = 2 }
    )
    Assert-True (-not (Test-ViewerApproved -Reviews $rt -Viewer 'me')) 'WPG-DECISION-21: normalized withdrawn approval is not approved'
} catch { $script:failures += "WPG-DECISION-21 threw: $_" }

Write-Host ""
if ($script:failures.Count -gt 0) {
    Write-Host "FAILED ($($script:failures.Count) assertion(s), $script:passes passed):" -ForegroundColor Red
    $script:failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "OK: all $script:passes assertions passed." -ForegroundColor Green
exit 0
