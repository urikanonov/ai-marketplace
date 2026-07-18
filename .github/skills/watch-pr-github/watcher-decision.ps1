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
# Fail CLOSED: any content that is missing, empty/whitespace, or unparseable (corruption /
# an interrupted write) assumes the opt-out (noMerge = $true) so a corrupt or truncated
# state file can never silently re-enable merging. NOTE: this is a contract about state
# CONTENT; the ABSENCE of a state file (a genuine first run) is handled by the caller
# (Load-Seen returns an empty seen-set and leaves the opt-out unset) and never reaches here.
function ConvertFrom-WatcherState {
    param([string]$Json)
    if (-not $Json -or -not $Json.Trim()) {
        return [pscustomobject]@{ Seen = @(); NoMerge = $true }
    }
    try {
        $s = $Json | ConvertFrom-Json
        # Fail CLOSED per field: a missing or null noMerge assumes the opt-out ($true), and a
        # missing or null seen is an empty set. Read via PSObject.Properties so a missing
        # property is StrictMode-safe (a bare $s.noMerge would throw under StrictMode). This
        # keeps a partial/legacy/tampered state object (e.g. {"noMerge":null}) from silently
        # re-enabling merging.
        $noMergeProp = $s.PSObject.Properties['noMerge']
        $noMerge = if ($noMergeProp -and $null -ne $noMergeProp.Value) { [bool]$noMergeProp.Value } else { $true }
        $seenProp = $s.PSObject.Properties['seen']
        $seenVal = if ($seenProp -and $null -ne $seenProp.Value) { @($seenProp.Value) } else { @() }
        return [pscustomobject]@{ Seen = $seenVal; NoMerge = $noMerge }
    } catch {
        return [pscustomobject]@{ Seen = @(); NoMerge = $true }
    }
}

# Classify a commenter as trusted or not. Trust = an exact allowlisted Copilot login, OR a
# human with effective admin/maintain/write permission. Fail closed: a generic [bot] suffix
# and a MEMBER/COLLABORATOR association are NOT sufficient. Pure: the effective-permission
# lookup is injected as $PermissionResolver (login -> permission string) so this
# security-critical rule -- in particular the [bot] fail-closed guard, which the readiness
# path relies on because Get-WatcherDecision does NOT pre-filter [bot] authors on review
# threads -- is unit-testable without any gh call.
function Test-CommenterTrusted {
    param(
        [AllowEmptyString()][AllowNull()][string]$Login,
        [AllowEmptyString()][AllowNull()][string]$Assoc,
        [Parameter(Mandatory)][scriptblock]$PermissionResolver,
        [string[]]$CopilotLogins = @('copilot-pull-request-reviewer', 'copilot-pull-request-reviewer[bot]', 'copilot-swe-agent', 'copilot-swe-agent[bot]', 'Copilot')
    )
    if ($CopilotLogins -contains $Login) { return $true }
    if ($Login -and $Login.EndsWith('[bot]')) { return $false }
    if ($Assoc -eq 'OWNER') { return $true }
    $p = & $PermissionResolver $Login
    return ($p -eq 'admin' -or $p -eq 'maintain' -or $p -eq 'write')
}

# Decide whether the viewer's OWN review currently APPROVES the PR, based on their LATEST
# meaningful review. $Reviews is a list of @{ Login; State; Order }; Order is a monotonic
# sort key (the review's numeric databaseId, assigned at creation) so "latest" is decided by
# an explicit sort, NOT by relying on the order the gh reviews connection happened to return
# (that connection takes no orderBy and its ordering is not a documented contract). Only
# APPROVED / CHANGES_REQUESTED / DISMISSED change a reviewer's standing state (a later
# COMMENTED review does not revoke a standing approval, mirroring GitHub), so the answer is
# whether the viewer's last such review is APPROVED. This prevents a stale earlier APPROVED
# from counting after the viewer later requested changes or dismissed their own review.
function Test-ViewerApproved {
    param(
        [AllowEmptyCollection()][object[]]$Reviews = @(),
        [AllowEmptyString()][AllowNull()][string]$Viewer
    )
    if (-not $Viewer) { return $false }
    $meaningful = @($Reviews | Where-Object {
            $_ -and $_.Login -eq $Viewer -and $_.State -in @('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED')
        })
    if ($meaningful.Count -eq 0) { return $false }
    # Fail CLOSED if any ordering key is missing: without a reliable recency key we cannot tell
    # which of the viewer's reviews is the latest, and a null Order sorts BEFORE numeric keys,
    # which could let a stale earlier APPROVED win. databaseId is present for every real review,
    # so this never trips in practice; it just refuses to risk a false approval on bad data.
    if (@($meaningful | Where-Object { $null -eq $_.Order }).Count -gt 0) { return $false }
    $sorted = @($meaningful | Sort-Object -Property Order)
    return ($sorted[-1].State -eq 'APPROVED')
}

# Normalize raw gh review nodes (each with author{ login }, state, databaseId) into the
# ordered @{ Login; State; Order } shape Test-ViewerApproved expects. Tolerant of a null node
# (a nullable connection entry, which would otherwise throw under StrictMode and strand the
# poll) and a null author (a deleted account -> Login $null, never matched as the viewer).
# Pure, so the projection is unit-testable rather than living only in the untested I/O shell.
function ConvertTo-ReviewStates {
    param([AllowEmptyCollection()][AllowNull()][object[]]$RawReviews = @())
    $out = @()
    foreach ($r in @($RawReviews)) {
        if (-not $r) { continue }
        $login = if ($r.author) { $r.author.login } else { $null }
        $out += [pscustomobject]@{ Login = $login; State = $r.state; Order = $r.databaseId }
    }
    return @($out)
}

# Normalize a timestamp to a stable, culture-invariant UTC ISO string, so a key built from it is
# identical across runtimes. ConvertFrom-Json yields a [datetime] on pwsh 7 but a raw ISO string on
# Windows PowerShell 5.1, and a [datetime]'s default ToString is culture/timezone-dependent -- either
# would make the same status produce different keys. A null/blank value yields '' (a stable no-op).
function ConvertTo-CanonicalTimestamp($Value) {
    if ($null -eq $Value) { return '' }
    $invariant = [System.Globalization.CultureInfo]::InvariantCulture
    if ($Value -is [datetime]) {
        return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', $invariant)
    }
    $s = [string]$Value
    if (-not $s.Trim()) { return '' }
    $dt = [datetime]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    if ([datetime]::TryParse($s, $invariant, $styles, [ref]$dt)) {
        return $dt.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', $invariant)
    }
    return $s
}

# Reduce a status-check rollup's context nodes to the sorted identities of the runs that
# are currently FAILING. Keying a CHECKS_FAILED event by these identities means a rerun
# (new run ids) re-fires while a repeated identical failure does not suppress it forever.
function Get-FailedCheckIds {
    param([object[]]$Contexts)
    $ids = @()
    foreach ($ctx in @($Contexts)) {
        if ($null -eq $ctx) { continue }
        if ($ctx.__typename -eq 'CheckRun' -and $ctx.conclusion -in @('FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'ACTION_REQUIRED')) {
            $ids += "cr$($ctx.databaseId)"
        } elseif ($ctx.__typename -eq 'StatusContext' -and $ctx.state -in @('FAILURE', 'ERROR')) {
            # Key a legacy commit-status by its context name AND its createdAt. Unlike a
            # CheckRun (whose databaseId changes on a rerun), a StatusContext keeps the same
            # context name across reposts, so keying by name alone would never re-fire after a
            # fail -> pass -> fail transition on the same commit; the reposted status carries a
            # new createdAt, so including it (canonicalized so the key is runtime-stable) makes
            # the re-failure a new key that re-fires. A missing/null createdAt degrades safely to
            # name-only keying (the old behavior), read via PSObject.Properties so it never throws.
            $caProp = $ctx.PSObject.Properties['createdAt']
            $ca = if ($caProp) { ConvertTo-CanonicalTimestamp $caProp.Value } else { '' }
            $ids += "sc$($ctx.context)@$ca"
        }
    }
    # Return the failing-run identities, sorted. NOTE: a PowerShell function return unrolls a
    # collection through the pipeline (empty -> nothing, one element -> a scalar, many -> an
    # array), so callers normalize with @(...) before use; the [string[]] cast just keeps the
    # element type stable. A leading-comma wrapper (`,@(...)`) is deliberately NOT used because
    # it would turn an empty result into a one-element array holding an empty array.
    return [string[]]@($ids | Sort-Object)
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
#   (admin|maintain|write|triage|none|read|unknown); 'unknown' means the lookup could not
#   be confirmed (transient failure) and must be re-probed next poll, not demoted.
# $FeedbackAvailable: $false when the caller could NOT fetch the review threads / comments /
#   reviews this poll (a transient API failure). The pre-feedback events (terminal, conflict,
#   auto-merge cancellation, failing checks) still fire, but everything from NEW_COMMENTS
#   onward -- including USER_APPROVED, DRAFT_HELD, and merge readiness -- is SUPPRESSED, so the
#   watcher never advances or merges a PR on a poll where an unseen review comment might exist
#   (fail CLOSED, matching the original loop, which aborted the whole poll on a feedback error).
function Get-WatcherDecision {
    param(
        [Parameter(Mandatory)][object]$Snapshot,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Viewer,
        [bool]$OptedOut,
        [AllowEmptyCollection()][string[]]$Seen = @(),
        [Parameter(Mandatory)][scriptblock]$IsTrusted,
        [Parameter(Mandatory)][scriptblock]$ResolveViewerPermission,
        [bool]$FeedbackAvailable = $true,
        [string[]]$CopilotLogins = @('copilot-pull-request-reviewer', 'copilot-pull-request-reviewer[bot]', 'copilot-swe-agent', 'copilot-swe-agent[bot]', 'Copilot')
    )

    $seen = @($Seen)
    $p = $Snapshot
    $oid = $p.Oid

    function New-Decision($evt, [string[]]$newSeen) {
        # $evt is deliberately untyped so a $null (no-event) is preserved, not coerced to ''.
        # Changed reports whether the seen-set grew (a key was added), so the caller persists
        # only real state changes -- terminal and the un-seen-guarded DISABLE_AUTO_MERGE leave
        # it unchanged. The seen-set is append-only, so a count delta is a sound "changed" test.
        return [pscustomobject]@{ Event = $evt; Seen = @($newSeen); Changed = (@($newSeen).Count -ne @($Seen).Count) }
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

    # Fail CLOSED when this poll's feedback could not be fetched: the pre-feedback events above
    # (terminal, conflict, auto-merge cancellation, failing checks) have already had their say
    # and do not depend on feedback, but NEW_COMMENTS and everything after it (USER_APPROVED,
    # DRAFT_HELD, and merge readiness) must NOT run, because an unseen review comment or an
    # informal objection might exist. Returning no event keeps the watcher polling until the
    # feedback fetch recovers, so it never advances or merges a PR on degraded feedback.
    if (-not $FeedbackAvailable) { return New-Decision $null $seen }

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
        if ($seen -contains $f.Key -or $add -contains $f.Key) { continue }
        $add += $f.Key
        # Trust classification is LEAST-PRIVILEGED: an item is trusted only if EVERY participant
        # is trusted. A review thread carries a Participants list (all its comment authors), so an
        # external comment ANYWHERE in an otherwise maintainer-led thread (or vice versa) still
        # marks the thread untrusted and gets vetted, rather than being judged by only the latest
        # comment's author. An issue comment or review body has a single author (no Participants),
        # so it is classified by that author.
        $pp = $f.PSObject.Properties['Participants']
        if ($pp) { $participants = @($pp.Value) }
        else { $participants = @([pscustomobject]@{ Login = $f.Login; Assoc = $f.Assoc }) }
        # Fail CLOSED when the participant set cannot be confirmed complete: a truncated window (a
        # thread with more comments than were fetched, ParticipantsTruncated) or an empty set means
        # an untrusted participant might be unseen, so treat the item as untrusted (vet it).
        $truncProp = $f.PSObject.Properties['ParticipantsTruncated']
        if (($truncProp -and $truncProp.Value) -or $participants.Count -eq 0) {
            $itemTrusted = $false
        } else {
            $itemTrusted = $true
            foreach ($person in $participants) {
                if (-not (& $IsTrusted $person.Login $person.Assoc)) { $itemTrusted = $false; break }
            }
        }
        if ($itemTrusted) { $trusted += $f.Key } else { $untrusted += $f.Key }
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
