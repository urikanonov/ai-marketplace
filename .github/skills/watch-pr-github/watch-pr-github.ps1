#!/usr/bin/env pwsh
# Runnable watch-pr-github watcher. Polls a GitHub PR with `gh` and prints `EVENT=...` only
# when the agent must act. All the safety-critical DECISION logic lives in the committed,
# unit-tested pure module watcher-decision.ps1 (dot-sourced below); this file is only the I/O
# shell around it (gh queries, pagination, permission lookups, atomic state persistence), so
# the decision behavior is exercised by tests/decision.Tests.ps1 and never drifts from a
# hand-pasted copy.
#
# Use PowerShell 7 (`pwsh`), the cross-platform, repo-portable choice; Windows PowerShell 5.1
# (`powershell`) also runs it. Example:
#   pwsh -NoProfile -File .github/skills/watch-pr-github/watch-pr-github.ps1 -Owner o -Repo r -PrNumber 42
param(
    [Parameter(Mandatory)][string]$Owner,
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][int]$PrNumber,
    [int]$PollSeconds = 180,
    [int]$MaxIterations = 240,
    [string]$StateFile,
    # Set -NoMerge when the user opted out of autonomous completion ("don't merge", "let me
    # do the final merge"). It suppresses every merge-initiating event (READY_TO_MERGE /
    # USER_APPROVED), raises READY_HELD instead, and cancels any pre-existing auto-merge
    # (DISABLE_AUTO_MERGE). The opt-out is persisted STICKY in the state file, so it survives
    # relaunches even if the flag is later omitted. Default (unset) = drive to completion.
    [switch]$NoMerge,
    # Clears a previously persisted -NoMerge opt-out, re-enabling autonomous completion.
    [switch]$AllowMerge,
    # ONLY these exact logins are trusted as Copilot. A generic [bot] suffix is not enough.
    [string[]]$CopilotLogins = @('copilot-pull-request-reviewer', 'copilot-pull-request-reviewer[bot]', 'copilot-swe-agent', 'copilot-swe-agent[bot]', 'Copilot')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'watcher-decision.ps1')

if (-not $StateFile) {
    # Default to a PER-USER-PRIVATE state dir (LocalApplicationData: %LOCALAPPDATA% on
    # Windows, ~/.local/share or $XDG_DATA_HOME on Unix), NOT the shared OS temp dir. A
    # world-writable /tmp path would be a predictable, symlink-raceable target on a
    # multi-user host; a per-user dir keeps the sticky opt-out and the atomic .tmp write out
    # of another local user's reach. It is also outside the repo, so running never dirties it.
    # Guard the base path: on a minimal Unix/container with no HOME/XDG it can be empty, and
    # Join-Path with an empty base would yield a RELATIVE path created under the CWD (often the
    # repo) -- fall back to the OS temp dir so the state file never lands in the working tree.
    $stateBase = [Environment]::GetFolderPath('LocalApplicationData')
    if (-not $stateBase) { $stateBase = [IO.Path]::GetTempPath() }
    $stateDir = Join-Path $stateBase 'watch-pr-github'
    if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
    $StateFile = Join-Path $stateDir ".wpg-state-$Owner-$Repo-$PrNumber.json"
}

# State file carries the per-PR seen keys AND the sticky opt-out flag. Reads fail CLOSED on
# a corrupt/interrupted write (see ConvertFrom-WatcherState). Writes are atomic (temp + move).
$script:StateNoMerge = $false
function Load-Seen {
    if (Test-Path $StateFile) {
        $st = ConvertFrom-WatcherState -Json (Get-Content $StateFile -Raw)
        $script:StateNoMerge = [bool]$st.NoMerge
        return @($st.Seen)
    }
    return @()
}
function Save-Seen([object[]]$ids) {
    $tmp = "$StateFile.tmp"
    [pscustomobject]@{ seen = @($ids); noMerge = $script:StateNoMerge } | ConvertTo-Json -Depth 4 | Set-Content -Path $tmp -Encoding utf8
    Move-Item -Path $tmp -Destination $StateFile -Force
}

# Effective repo permission per login. A SUCCESSFUL lookup returns admin|maintain|write|
# triage|read|none and is cached; a login that could not be confirmed returns 'unknown' and
# is NOT cached, and on a -Fresh failure any stale cached value is EVICTED. Pass -Fresh to
# bypass the cache for the safety-critical merge-capability check.
$permCache = @{}
function Get-EffectivePermission($login, [switch]$Fresh) {
    if (-not $login) { return 'none' }
    if (-not $Fresh -and $permCache.ContainsKey($login)) { return $permCache[$login] }
    try {
        $r = gh api "repos/$Owner/$Repo/collaborators/$login/permission" 2>$null | ConvertFrom-Json
        if ($r -and $r.permission) { $permCache[$login] = $r.permission; return $r.permission }
    } catch { }
    if ($Fresh -and $permCache.ContainsKey($login)) { $permCache.Remove($login) | Out-Null }
    return 'unknown'
}
# Trust = an exact allowlisted Copilot login, OR a human with effective admin/maintain/write.
# Fail closed: association (MEMBER/COLLABORATOR) and a generic [bot] suffix are NOT sufficient.
# The rule itself lives in the unit-tested pure module (Test-CommenterTrusted); this wrapper
# only injects the live gh-backed permission lookup.
function Test-Trusted($login, $assoc) {
    return Test-CommenterTrusted -Login $login -Assoc $assoc -CopilotLogins $CopilotLogins `
        -PermissionResolver { param($l) Get-EffectivePermission $l }
}

# Page through a PR sub-connection (reviewThreads | comments | reviews) via graphql cursors.
function Get-AllNodes($field, $inner) {
    $nodes = @(); $cursor = $null
    do {
        $after = if ($cursor) { ", after: `"$cursor`"" } else { '' }
        $q = "query(`$o:String!,`$r:String!,`$n:Int!){ repository(owner:`$o,name:`$r){ pullRequest(number:`$n){ $field(first:100$after){ pageInfo{ hasNextPage endCursor } nodes{ $inner } } } } }"
        $conn = (gh api graphql -f query=$q -f o=$Owner -f r=$Repo -F n=$PrNumber | ConvertFrom-Json).data.repository.pullRequest.$field
        $nodes += $conn.nodes
        $cursor = if ($conn.pageInfo.hasNextPage) { $conn.pageInfo.endCursor } else { $null }
    } while ($cursor)
    return , $nodes
}

$stateQuery = @'
query($owner:String!,$repo:String!,$num:Int!){
  viewer{ login }
  repository(owner:$owner,name:$repo){
    pullRequest(number:$num){
      state merged isDraft mergeable mergeStateStatus reviewDecision author{ login }
      autoMergeRequest{ enabledAt }
      commits(last:1){ nodes{ commit{ oid statusCheckRollup{ state
        contexts(first:100){ pageInfo{ hasNextPage endCursor } nodes{
          __typename
          ... on CheckRun{ databaseId conclusion }
          ... on StatusContext{ context state createdAt }
        } } } } } }
    }
  }
}
'@

# Page through the last commit's statusCheckRollup contexts beyond the first 100 that the
# state query already fetched. The rollup embeds only the first page, so a failing context past
# position 100 would otherwise be invisible; this fetches the remaining pages (starting at the
# state query's endCursor) and returns their nodes to append. Returns @() when there is no more.
# $ExpectedOid guards a cross-poll race: if a new commit lands between the state query and this
# call, the cursor would target a different commit's contexts, so bail rather than mix pages.
function Get-RollupContexts([string]$After, [string]$ExpectedOid) {
    $nodes = @(); $cursor = $After
    $q = @'
query($owner:String!,$repo:String!,$num:Int!,$after:String!){
  repository(owner:$owner,name:$repo){ pullRequest(number:$num){ commits(last:1){ nodes{ commit{ oid statusCheckRollup{
    contexts(first:100, after:$after){ pageInfo{ hasNextPage endCursor } nodes{
      __typename
      ... on CheckRun{ databaseId conclusion }
      ... on StatusContext{ context state createdAt }
    } } } } } } } }
}
'@
    while ($cursor) {
        $cnodes = (gh api graphql -f query=$q -f owner=$Owner -f repo=$Repo -F num=$PrNumber -f after=$cursor | ConvertFrom-Json).data.repository.pullRequest.commits.nodes
        $c = if ($cnodes) { $cnodes[0].commit } else { $null }
        if (-not $c) { break }
        if ($ExpectedOid -and $c.oid -ne $ExpectedOid) { break }
        $conn = $c.statusCheckRollup.contexts
        if (-not $conn) { break }
        $nodes += $conn.nodes
        $cursor = if ($conn.pageInfo.hasNextPage) { $conn.pageInfo.endCursor } else { $null }
    }
    return @($nodes)
}

for ($i = 0; $i -lt $MaxIterations; $i++) {
    try {
        $seen = Load-Seen
        # Reconcile the sticky opt-out (pure Resolve-OptOut): -NoMerge sets it, -AllowMerge
        # clears it, -NoMerge wins if both are passed, and once set it persists across
        # relaunches. Persist only on a change.
        $opt = Resolve-OptOut -StickyNoMerge $script:StateNoMerge -NoMerge:$NoMerge -AllowMerge:$AllowMerge
        if ($opt.Changed) { $script:StateNoMerge = $opt.Sticky; Save-Seen $seen }
        $optedOut = $opt.OptedOut

        $resp = (gh api graphql -f query=$stateQuery -f owner=$Owner -f repo=$Repo -F num=$PrNumber | ConvertFrom-Json)
        $viewer = $resp.data.viewer.login
        $pr = $resp.data.repository.pullRequest
        # Nullable GraphQL fields: a PR always has a commit, but statusCheckRollup is null for
        # a commit with no checks, and a list can carry a null node. Guard every dereference so
        # a missing rollup/commit yields an empty rollup rather than throwing under StrictMode
        # (which would strand the poll in the catch and retry to timeout without ever emitting
        # a terminal/readiness event).
        $commitNode = if ($pr.commits.nodes) { $pr.commits.nodes[0] } else { $null }
        $commit = if ($commitNode) { $commitNode.commit } else { $null }
        $oid = if ($commit) { $commit.oid } else { '' }
        $rollupObj = if ($commit) { $commit.statusCheckRollup } else { $null }
        $rollup = if ($rollupObj) { $rollupObj.state } else { $null }
        $rollupContexts = if ($rollupObj -and $rollupObj.contexts) { @($rollupObj.contexts.nodes) } else { @() }
        # If the rollup has more than the first 100 contexts, page the rest so a failing context
        # beyond position 100 is not missed (it would otherwise leave the CHECKS_FAILED key
        # incomplete). Non-fatal: on a pagination error, keep the first page.
        if ($rollupObj -and $rollupObj.contexts -and $rollupObj.contexts.pageInfo -and $rollupObj.contexts.pageInfo.hasNextPage) {
            try { $rollupContexts += @(Get-RollupContexts -After $rollupObj.contexts.pageInfo.endCursor -ExpectedOid $oid) }
            catch { Write-Host "[$(Get-Date -Format o)] poll $i rollup-contexts pagination failed (using first page): $($_.Exception.Message)" }
        }

        # Fetch the feedback connections when the PR is still open (a merged/closed PR short-
        # circuits in the decision anyway). NON-FATAL: if any pagination call fails, mark the
        # feedback DEGRADED and fall back to empty. The decision then still emits an earlier
        # terminal/conflict/auto-merge/checks event (which do not depend on feedback), but the
        # $FeedbackAvailable=$false flag makes it SUPPRESS NEW_COMMENTS and everything after it
        # (USER_APPROVED / readiness), so a transient feedback error can never advance or merge
        # a PR past an unseen review comment. It retries next poll.
        $feedback = @()
        $viewerApproved = $false
        $feedbackAvailable = $true
        if (-not $pr.merged -and $pr.state -ne 'CLOSED') {
            try {
                $threads = Get-AllNodes 'reviewThreads' 'id isResolved comments(last:100){ pageInfo{ hasPreviousPage } nodes{ databaseId author{ login } authorAssociation } }'
                $issueComments = Get-AllNodes 'comments' 'databaseId author{ login } authorAssociation'
                $reviews = Get-AllNodes 'reviews' 'databaseId state body author{ login } authorAssociation'
                foreach ($t in $threads) {
                    if (-not $t -or $t.isResolved) { continue }
                    $tcomments = if ($t.comments -and $t.comments.nodes) { @($t.comments.nodes | Where-Object { $_ }) } else { @() }
                    if ($tcomments.Count -eq 0) { continue }
                    # Key on the LATEST comment id so a new reply re-surfaces the thread, but
                    # collect ALL participants so trust is judged least-privileged (any external
                    # participant makes the whole thread untrusted, not just the last commenter).
                    # If the thread has more comments than the fetched window (hasPreviousPage),
                    # the participant set is incomplete -> mark it truncated so the decision fails
                    # closed (treats the thread as untrusted) rather than trusting a partial set.
                    $latest = $tcomments[-1]
                    $participants = @($tcomments | ForEach-Object {
                            $pl = if ($_.author) { $_.author.login } else { $null }
                            [pscustomobject]@{ Login = $pl; Assoc = $_.authorAssociation }
                        })
                    $truncated = if ($t.comments.pageInfo) { [bool]$t.comments.pageInfo.hasPreviousPage } else { $false }
                    $latestLogin = if ($latest.author) { $latest.author.login } else { $null }
                    $feedback += [pscustomobject]@{ Kind = 'thread'; Key = "thread:$($t.id):$($latest.databaseId)"; Login = $latestLogin; Assoc = $latest.authorAssociation; Participants = $participants; ParticipantsTruncated = $truncated }
                }
                foreach ($c in $issueComments) {
                    if (-not $c) { continue }
                    $login = if ($c.author) { $c.author.login } else { $null }
                    $feedback += [pscustomobject]@{ Kind = 'issue'; Key = "issue:$($c.databaseId)"; Login = $login; Assoc = $c.authorAssociation }
                }
                foreach ($r in $reviews) {
                    if (-not $r -or -not $r.body -or -not $r.body.Trim()) { continue }
                    if ($r.state -notin @('COMMENTED', 'CHANGES_REQUESTED', 'APPROVED', 'DISMISSED')) { continue }
                    $login = if ($r.author) { $r.author.login } else { $null }
                    $feedback += [pscustomobject]@{ Kind = 'review'; Key = "review:$($r.databaseId)"; Login = $login; Assoc = $r.authorAssociation }
                }
                $viewerApproved = Test-ViewerApproved -Viewer $viewer -Reviews (ConvertTo-ReviewStates -RawReviews $reviews)
            } catch {
                Write-Host "[$(Get-Date -Format o)] poll $i feedback fetch failed (holding merge/readiness this poll, will retry): $($_.Exception.Message)"
                $feedback = @(); $viewerApproved = $false; $feedbackAvailable = $false
            }
        }

        $snapshot = [pscustomobject]@{
            Merged           = [bool]$pr.merged
            State            = $pr.state
            Oid              = $oid
            Rollup           = $rollup
            Mergeable        = $pr.mergeable
            MergeStateStatus = $pr.mergeStateStatus
            ReviewDecision   = $pr.reviewDecision
            AutoMergeEnabled = [bool]$pr.autoMergeRequest
            IsDraft          = [bool]$pr.isDraft
            ViewerApproved   = $viewerApproved
            FailedCheckIds   = @(Get-FailedCheckIds -Contexts $rollupContexts)
            Feedback         = $feedback
        }

        $isTrusted = { param($login, $assoc) Test-Trusted $login $assoc }
        $resolveViewerPerm = { Get-EffectivePermission $viewer -Fresh }

        $decision = Get-WatcherDecision -Snapshot $snapshot -Viewer $viewer -OptedOut $optedOut -Seen $seen `
            -IsTrusted $isTrusted -ResolveViewerPermission $resolveViewerPerm -FeedbackAvailable $feedbackAvailable `
            -CopilotLogins $CopilotLogins

        if ($decision.Event) {
            # Persist only when the decision actually added a seen key. Terminal
            # (PR_MERGED/PR_CLOSED) and the deliberately un-seen-guarded DISABLE_AUTO_MERGE
            # leave the seen-set unchanged and are not persisted, matching the original loop.
            if ($decision.Changed) { Save-Seen $decision.Seen }
            Write-Output $decision.Event
            exit 0
        }

        Write-Host "[$(Get-Date -Format o)] poll $i ok: state=$($pr.state) merge=$($pr.mergeable)/$($pr.mergeStateStatus) review=$($pr.reviewDecision) checks=$rollup"
    } catch { Write-Host "[$(Get-Date -Format o)] poll $i error: $($_.Exception.Message)" }
    Start-Sleep -Seconds $PollSeconds
}
Write-Output 'EVENT=WATCH_TIMEOUT'; exit 0
