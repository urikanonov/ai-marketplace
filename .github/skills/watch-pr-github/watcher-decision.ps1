#!/usr/bin/env pwsh
# Pure decision logic for the watch-pr-github watcher.
#
# This file is the SINGLE SOURCE OF TRUTH for the watcher's safety-critical decision
# logic (sticky opt-out precedence, effective-permission merge gating, auto-merge
# cancellation, changes-requested handling, per-oid seen-key state transitions). It is
# dot-sourced by the runnable watcher (watch-pr-github.ps1) and exercised directly by the
# unit tests (tests/decision.Tests.ps1). It performs NO I/O and makes NO gh/network calls:
# every dependency (the PR-state snapshot, the seen-set, effective permission, and trust
# classification) is passed in, so a mocked snapshot fully determines the emitted EVENT.
#
# Keep it pwsh 7 / Windows PowerShell 5.1 compatible and Set-StrictMode -Version Latest
# clean, matching the auto-updater hook tests.

Set-StrictMode -Version Latest

# Reconcile the sticky -NoMerge opt-out. The persisted state carries a sticky noMerge flag
# so a "don't merge" survives relaunches that forget the switch (context compaction, a
# different agent taking over). -NoMerge sets it, -AllowMerge clears it, and -NoMerge takes
# PRECEDENCE if both are somehow passed (fail closed, deterministic). Returns the effective
# opt-out and the new sticky value plus whether it changed (so the caller can persist).
function Resolve-OptOut {
    param(
        [bool]$StickyNoMerge,
        [switch]$NoMerge,
        [switch]$AllowMerge
    )
    $sticky = $StickyNoMerge
    if ($NoMerge) { $sticky = $true }
    elseif ($AllowMerge) { $sticky = $false }
    return [pscustomobject]@{
        OptedOut = $sticky
        Sticky   = $sticky
        Changed  = ($sticky -ne $StickyNoMerge)
    }
}

# Parse a persisted watcher-state JSON string into its seen-set and sticky opt-out flag.
# Fail CLOSED: if the string is missing or cannot be parsed (corruption / an interrupted
# write), assume the opt-out (noMerge = $true) so a corrupt file can never silently
# re-enable merging.
function ConvertFrom-WatcherState {
    param([string]$Json)
    if (-not $Json -or -not $Json.Trim()) {
        return [pscustomobject]@{ Seen = @(); NoMerge = $false }
    }
    try {
        $s = $Json | ConvertFrom-Json
        return [pscustomobject]@{ Seen = @($s.seen); NoMerge = [bool]$s.noMerge }
    } catch {
        return [pscustomobject]@{ Seen = @(); NoMerge = $true }
    }
}

# Reduce a status-check rollup's context nodes to the sorted identities of the runs that
# are currently FAILING. Keying a CHECKS_FAILED event by these identities means a rerun
# (new run ids) re-fires while a repeated identical failure does not suppress it forever.
function Get-FailedCheckIds {
    param([object[]]$Contexts)
    $ids = @()
    foreach ($ctx in @($Contexts)) {
        if ($ctx.__typename -eq 'CheckRun' -and $ctx.conclusion -in @('FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'ACTION_REQUIRED')) {
            $ids += "cr$($ctx.databaseId)"
        } elseif ($ctx.__typename -eq 'StatusContext' -and $ctx.state -in @('FAILURE', 'ERROR')) {
            $ids += "sc$($ctx.context)"
        }
    }
    return , @($ids | Sort-Object)
}

# The core decision. Given a normalized PR-state snapshot, the current seen-set, the
# effective opt-out, and injected resolvers for trust and viewer permission, return the
# single EVENT to emit (or $null to keep polling) plus the seen-set to persist. The
# ORDERING and the guards here are the safety-critical part -- they mirror the watcher loop
# in SKILL.md exactly, so the two never drift.
#
# $Snapshot fields (all required; construct fully so StrictMode is happy):
#   Merged [bool], State [string], Oid [string], Rollup [string],
#   Mergeable [string], MergeStateStatus [string], ReviewDecision [string],
#   AutoMergeEnabled [bool], IsDraft [bool], ViewerApproved [bool],
#   FailedCheckIds [string[]], Feedback [array of @{ Kind; Key; Login; Assoc }]
#     Kind is 'thread' | 'issue' | 'review'.
#
# $IsTrusted: scriptblock (login, assoc) -> [bool].
# $ResolveViewerPermission: scriptblock () -> permission string
#   (admin|maintain|write|triage|read|none|unknown); 'unknown' means the lookup could not
#   be confirmed (transient failure) and must be re-probed next poll, not demoted.
function Get-WatcherDecision {
    param(
        [Parameter(Mandatory)][object]$Snapshot,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Viewer,
        [bool]$OptedOut,
        [AllowEmptyCollection()][string[]]$Seen = @(),
        [Parameter(Mandatory)][scriptblock]$IsTrusted,
        [Parameter(Mandatory)][scriptblock]$ResolveViewerPermission,
        [string[]]$CopilotLogins = @('copilot-pull-request-reviewer', 'copilot-pull-request-reviewer[bot]', 'copilot-swe-agent', 'copilot-swe-agent[bot]', 'Copilot')
    )

    $seen = @($Seen)
    $p = $Snapshot
    $oid = $p.Oid

    function New-Decision($evt, [string[]]$newSeen) {
        # $evt is deliberately untyped so a $null (no-event) is preserved, not coerced to ''.
        return [pscustomobject]@{ Event = $evt; Seen = @($newSeen) }
    }

    # Terminal states first: a merged or closed PR ends the loop.
    if ($p.Merged) { return New-Decision 'EVENT=PR_MERGED' $seen }
    if ($p.State -eq 'CLOSED') { return New-Decision 'EVENT=PR_CLOSED' $seen }

    # A conflicting / dirty merge state must be resolved before anything else can land.
    if ($p.Mergeable -eq 'CONFLICTING' -or $p.MergeStateStatus -eq 'DIRTY') {
        $mk = "conflict:$oid"
        if ($seen -notcontains $mk) { return New-Decision 'EVENT=MERGE_CONFLICT' (@($seen) + $mk) }
    }

    # Cancel an ACTIVE auto-merge when it must not proceed: the user opted out, OR a
    # reviewer requested changes (which, with native required approvals = 0, would otherwise
    # merge over the objection because the readiness block below is skipped while auto-merge
    # is set). Deliberately NOT seen-guarded: it re-emits every poll until the API reports
    # auto-merge is off, so an interrupted handling turn or a later re-enable can never let a
    # merge slip past the opt-out / objection.
    if ($p.AutoMergeEnabled -and ($OptedOut -or $p.ReviewDecision -eq 'CHANGES_REQUESTED')) {
        $reason = if ($OptedOut) { 'optout' } else { 'changes' }
        return New-Decision "EVENT=DISABLE_AUTO_MERGE reason=$reason" $seen
    }

    # Failing required/any checks. Keyed by the identities of the currently-failing runs.
    if ($p.Rollup -in @('FAILURE', 'ERROR')) {
        $failedIds = @($p.FailedCheckIds | Sort-Object)
        $ck = "checks:$oid`:" + ($failedIds -join '+')
        if ($seen -notcontains $ck) {
            return New-Decision "EVENT=CHECKS_FAILED oid=$oid runs=$($failedIds -join ',')" (@($seen) + $ck)
        }
    }

    # Fully-paginated actionable feedback: unresolved review threads, non-bot issue
    # comments, and top-level review bodies. Classify each unseen item as trusted (an
    # allowlisted Copilot login or a confirmed maintainer) or untrusted (everyone else, to
    # be vetted before acting).
    $trusted = @(); $untrusted = @(); $add = @()
    foreach ($f in @($p.Feedback)) {
        # Bot filter: issue comments and reviews from a generic [bot] that is not an
        # allowlisted Copilot login are noise and skipped; review threads are not skipped.
        if ($f.Kind -in @('issue', 'review') -and $f.Login -and $f.Login.EndsWith('[bot]') -and ($CopilotLogins -notcontains $f.Login)) {
            continue
        }
        if ($seen -contains $f.Key) { continue }
        $add += $f.Key
        if (& $IsTrusted $f.Login $f.Assoc) { $trusted += $f.Key } else { $untrusted += $f.Key }
    }
    if ($add.Count -gt 0) {
        $evt = "EVENT=NEW_COMMENTS trusted=[{0}] untrusted=[{1}]" -f ($trusted -join ','), ($untrusted -join ',')
        return New-Decision $evt (@($seen) + $add)
    }

    # The authenticated user explicitly approved: proactively enable auto-merge so it lands
    # when the rest passes -- but ONLY if the actor can merge, the user did not opt out, the
    # PR is not a draft, and no changes-requested review is outstanding (the same guards as
    # READY_TO_MERGE, so USER_APPROVED cannot smuggle an unwanted merge past them). The
    # permission lookup is skipped once the per-oid key has fired.
    if ($p.ViewerApproved -and -not $p.AutoMergeEnabled -and -not $OptedOut -and -not $p.IsDraft -and $p.ReviewDecision -ne 'CHANGES_REQUESTED') {
        $uk = "approved:$oid"
        if ($seen -notcontains $uk -and ((& $ResolveViewerPermission) -in @('admin', 'maintain', 'write'))) {
            return New-Decision "EVENT=USER_APPROVED login=$Viewer" (@($seen) + $uk)
        }
    }

    # A draft PR cannot merge; surface it once per head commit so the session is not left
    # polling a draft forever.
    if ($p.IsDraft) {
        $dk = "draft:$oid"
        if ($seen -notcontains $dk) { return New-Decision 'EVENT=DRAFT_HELD' (@($seen) + $dk) }
    }

    # Merge readiness. CLEAN means every gate passes; UNSTABLE means only a NON-required
    # check is failing/pending/skipped (this repo's pages deploy/notify jobs skip on PRs, so
    # a ready maintainer PR sits at UNSTABLE). BOTH mean every REQUIRED gate is satisfied, so
    # both are "ready". BEHIND means the base advanced and the branch must be updated first.
    if (-not $p.AutoMergeEnabled -and -not $p.IsDraft) {
        if ($p.MergeStateStatus -eq 'BEHIND') {
            $bk = "behind:$oid"
            if ($seen -notcontains $bk) { return New-Decision 'EVENT=BRANCH_BEHIND' (@($seen) + $bk) }
        } elseif ($p.MergeStateStatus -eq 'CLEAN' -or $p.MergeStateStatus -eq 'UNSTABLE') {
            if ($p.ReviewDecision -eq 'CHANGES_REQUESTED') {
                $ck2 = "changes:$oid"
                if ($seen -notcontains $ck2) { return New-Decision 'EVENT=CHANGES_REQUESTED' (@($seen) + $ck2) }
            } elseif ($OptedOut) {
                $hk = "held:$oid"
                if ($seen -notcontains $hk) { return New-Decision "EVENT=READY_HELD mergeState=$($p.MergeStateStatus)" (@($seen) + $hk) }
            } elseif (-not ($seen -contains "ready:$oid")) {
                # Only a merge-capable actor may complete the merge; a non-maintainer reports
                # readiness once and waits. 'unknown' (a transiently failed lookup) emits
                # nothing and retries next poll, a confirmed non-maintainer emits AWAITING
                # once, and write+ emits READY. The ready:$oid guard keeps a maintainer whose
                # lookup transiently failed re-probed rather than permanently stranded.
                $perm = & $ResolveViewerPermission
                if ($perm -in @('admin', 'maintain', 'write')) {
                    return New-Decision "EVENT=READY_TO_MERGE mergeState=$($p.MergeStateStatus)" (@($seen) + "ready:$oid")
                } elseif ($perm -ne 'unknown' -and ($seen -notcontains "await:$oid")) {
                    return New-Decision "EVENT=AWAITING_MAINTAINER_MERGE mergeState=$($p.MergeStateStatus)" (@($seen) + "await:$oid")
                }
            }
        }
    }

    # Nothing actionable this poll.
    return New-Decision $null $seen
}
