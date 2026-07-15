<#
.SYNOPSIS
  v3 V3-2 app-side drop: commit verdict_transitions.json (+ the records snapshot) to the private
  archive rendezvous and push. Outbound-only — it never touches the durable archive or the VM
  read-API; a compromised app can at worst pollute the rendezvous (the VM validates before merging).

.DESCRIPTION
  SHIPS DARK. With no rendezvous configured (empty -Rendezvous, or a path that is not a git clone)
  this is a silent no-op (exit 0) — zero behavioural change until you create the private archive
  repo, clone it, and schedule this task. See operations/README "Durable archive (V3-2) deploy".

  The git credential (SSH deploy key) lives in this scheduled task's environment — never committed.

.EXAMPLE
  powershell -File scripts\archive_drop.ps1 -DataDir "%APPDATA%\ipo-advisor-desktop\engine-data" `
      -Rendezvous "C:\ipo-archive"
#>
param(
  [string]$DataDir = "",
  [string]$Rendezvous = ""
)
# NB: no global $ErrorActionPreference='Stop' — under it, git's normal stderr progress would raise a
# NativeCommandError even on a SUCCESSFUL push (PowerShell 5.1). Cmdlets that must not fail silently
# use -ErrorAction Stop individually; git success is checked via $LASTEXITCODE.

# --- Dark-ship guard: nothing configured -> do nothing, quietly. ---
if ([string]::IsNullOrWhiteSpace($Rendezvous) -or -not (Test-Path (Join-Path $Rendezvous ".git"))) {
  exit 0
}
$transitions = Join-Path $DataDir "verdict_transitions.json"
if ([string]::IsNullOrWhiteSpace($DataDir) -or -not (Test-Path $transitions)) {
  exit 0  # nothing to drop yet
}

# --- Stage the (reproducible-not-necessary) records snapshot alongside the history. ---
Copy-Item $transitions $Rendezvous -Force -ErrorAction Stop
$records = Join-Path $DataDir "ipo_records.parquet"
if (Test-Path $records) { Copy-Item $records $Rendezvous -Force -ErrorAction Stop }

# --- Commit only if something actually changed (no empty commits, no push noise), then push. ---
git -C $Rendezvous add -A
git -C $Rendezvous diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  $stamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
  git -C $Rendezvous commit -m "drop $stamp" | Out-Null
  git -C $Rendezvous push origin HEAD | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Error "archive drop: git push failed"; exit 1 }
}
exit 0
