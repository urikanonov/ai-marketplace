# Non-blocking SessionStart extractor launcher for commentable-html (Copilot on Windows).
#
# Invoked by pkg/hooks.json as `powershell ... -File hooks\session-extract.ps1 -Version <v>`. Using
# a -File script (not an inline -Command) avoids any early $-expansion by an outer shell, and
# $PSScriptRoot resolves the plugin paths absolutely regardless of the working directory.
#
# Fast path: if the version marker exists as a FILE, exit immediately (no Python spawn); a directory
# that happens to share the marker name is NOT treated as done (matches run()'s isfile check), so a
# tampered/crash-landed marker directory cannot permanently suppress extraction. Otherwise find a
# WORKING Python - skipping the Microsoft Store `python3.exe` alias stub, which exits non-zero - and
# run the extractor isolated (-I). Always exits 0 so a failure never blocks session start.
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = 'SilentlyContinue'
$skill = Join-Path (Split-Path -Parent $PSScriptRoot) 'skills\commentable-html'
if (Test-Path (Join-Path $skill ".skill-resources-$Version.ok") -PathType Leaf) { exit 0 }
$py = $null
foreach ($c in 'python', 'python3', 'py') {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { continue }
  if ($cmd.Source -like '*\WindowsApps\*') { continue }
  & $cmd.Source -I -c 'pass' 2>$null
  if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; break }
}
if ($py) {
  & $py -I (Join-Path $PSScriptRoot 'extract_resources.py') --version $Version --agent copilot *> $null
}
exit 0
