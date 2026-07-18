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

if (-not $StateFile) { $StateFile = Join-Path ([IO.Path]::GetTempPath()) ".wpg-state-$Owner-$Repo-$PrNumber.json" }

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
function Test-Trusted($login, $assoc) {
    if ($CopilotLogins -contains $login) { return $true }
    if ($login -and $login.EndsWith('[bot]')) { return $false }
    if ($assoc -eq 'OWNER') { return $true }
    $p = Get-EffectivePermission $login
    return ($p -eq 'admin' -or $p -eq 'maintain' -or $p -eq 'write')
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
        contexts(first:100){ nodes{
          __typename
          ... on CheckRun{ databaseId conclusion }
          ... on StatusContext{ context state }
        } } } } } }
    }
  }
}
'@

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
        $commit = $pr.commits.nodes[0].commit
        $oid = $commit.oid
        $rollup = $commit.statusCheckRollup.state

        # Only fetch feedback connections when the PR is still open (a merged/closed PR short-
        # circuits in the decision anyway).
        $feedback = @()
        $viewerApproved = $false
        if (-not $pr.merged -and $pr.state -ne 'CLOSED') {
            $threads = Get-AllNodes 'reviewThreads' 'id isResolved comments(last:1){ nodes{ databaseId author{ login } authorAssociation } }'
            $issueComments = Get-AllNodes 'comments' 'databaseId author{ login } authorAssociation'
            $reviews = Get-AllNodes 'reviews' 'databaseId state body author{ login } authorAssociation'
            foreach ($t in $threads) {
                if ($t.isResolved) { continue }
                $c = $t.comments.nodes[0]; if (-not $c) { continue }
                $feedback += [pscustomobject]@{ Kind = 'thread'; Key = "thread:$($t.id):$($c.databaseId)"; Login = $c.author.login; Assoc = $c.authorAssociation }
            }
            foreach ($c in $issueComments) {
                $feedback += [pscustomobject]@{ Kind = 'issue'; Key = "issue:$($c.databaseId)"; Login = $c.author.login; Assoc = $c.authorAssociation }
            }
            foreach ($r in $reviews) {
                if (-not $r.body -or -not $r.body.Trim()) { continue }
                if ($r.state -notin @('COMMENTED', 'CHANGES_REQUESTED', 'APPROVED', 'DISMISSED')) { continue }
                $feedback += [pscustomobject]@{ Kind = 'review'; Key = "review:$($r.databaseId)"; Login = $r.author.login; Assoc = $r.authorAssociation }
            }
            $viewerApproved = [bool]($reviews | Where-Object { $_.author.login -eq $viewer -and $_.state -eq 'APPROVED' })
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
            FailedCheckIds   = (Get-FailedCheckIds -Contexts $commit.statusCheckRollup.contexts.nodes)
            Feedback         = $feedback
        }

        $isTrusted = { param($login, $assoc) Test-Trusted $login $assoc }
        $resolveViewerPerm = { Get-EffectivePermission $viewer -Fresh }

        $decision = Get-WatcherDecision -Snapshot $snapshot -Viewer $viewer -OptedOut $optedOut -Seen $seen `
            -IsTrusted $isTrusted -ResolveViewerPermission $resolveViewerPerm -CopilotLogins $CopilotLogins

        if ($decision.Event) {
            Save-Seen $decision.Seen
            Write-Output $decision.Event
            exit 0
        }

        Write-Host "[$(Get-Date -Format o)] poll $i ok: state=$($pr.state) merge=$($pr.mergeable)/$($pr.mergeStateStatus) review=$($pr.reviewDecision) checks=$rollup"
    } catch { Write-Host "[$(Get-Date -Format o)] poll $i error: $($_.Exception.Message)" }
    Start-Sleep -Seconds $PollSeconds
}
Write-Output 'EVENT=WATCH_TIMEOUT'; exit 0
