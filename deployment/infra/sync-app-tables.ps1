#Requires -Version 7
<#
.SYNOPSIS
  Back up the app's tables from the remote pmsonline (read-only) and restore them into the local Docker pmsonline.

.DESCRIPTION
  Runs pg_dump / pg_restore in a throwaway postgres:18.6 container on the compose network, so no local
  Postgres client is needed. Backups go to deployment/infra/postgres/.sync/<yyyyMMddTHHmm> (gitignored).

  Credentials: remote = REMOTE_PG_DSN (else PG_DSN) in backend/.env, or $env:SYNC_REMOTE_DSN; local = PG_USER / PG_PASSWORD / PG_DB
  in deployment/infra/.env. They reach the container only as environment variables.
  If deployment/infra/.env has PMSONLINE_RO_PASSWORD, a local read-only role pmsonline_ro is (re)created with
  SELECT on the restored tables, mirroring the remote.

  The remote role is read-only; nothing is ever written there. Locally, the selected tables are DROPPED and replaced.

.EXAMPLE
  ./sync-app-tables.ps1                          # backup + restore the 9 app tables (asks before replacing)
.EXAMPLE
  ./sync-app-tables.ps1 -Mode backup             # dump only
.EXAMPLE
  ./sync-app-tables.ps1 -Mode restore -Yes       # restore the newest backup again, no remote access
.EXAMPLE
  ./sync-app-tables.ps1 -Tables board,device_uptime -Yes   # small subset, e.g. to test
#>
[CmdletBinding()]
param(
  [ValidateSet('full', 'backup', 'restore')]
  [string]$Mode = 'full',

  # Tables read by backend/app/queries. onu_pon_1d (ml input, 133 GB) is deliberately not included.
  [string[]]$Tables = @('device', 'intf', 'intf_rev', 'device_uptime', 'ponport', 'ponport_rev', 'board', 'odn_onu', 'ticket'),

  # Backup to restore in -Mode restore (directory name under postgres/.sync). Default: the newest one.
  [string]$From,

  [ValidateRange(1, 16)]
  [int]$Jobs = 4,

  # Number of backups to keep in postgres/.sync after a new backup.
  [ValidateRange(1, 100)]
  [int]$Keep = 3,

  # Replace the local tables without asking.
  [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$Image = 'postgres:18.6'
$Infra = $PSScriptRoot
$Repo = Resolve-Path (Join-Path $Infra '../..')
$SyncDir = Join-Path $Infra 'postgres/.sync'
$StampRe = '^\d{8}T\d{4}$'

function Read-DotEnv([string]$Path) {
  $vars = @{}
  if (Test-Path $Path) {
    foreach ($line in Get-Content $Path) {
      if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $vars[$Matches[1]] = $Matches[2] }
    }
  }
  return $vars
}

function Get-Backups {
  if (-not (Test-Path $SyncDir)) { return @() }
  Get-ChildItem $SyncDir -Directory | Where-Object { $_.Name -match $StampRe -and (Test-Path (Join-Path $_.FullName 'manifest.json')) } |
    Sort-Object Name
}

# --- inputs -------------------------------------------------------------------------------------------
foreach ($t in $Tables) { if ($t -notmatch '^[a-z_][a-z0-9_]*$') { throw "invalid table name: $t" } }

$infraEnv = Read-DotEnv (Join-Path $Infra '.env')
foreach ($k in 'PG_USER', 'PG_PASSWORD', 'PG_DB') {
  if (-not $infraEnv[$k]) { throw "set $k in deployment/infra/.env" }
}

$remoteDsn = $env:SYNC_REMOTE_DSN
if ($Mode -ne 'restore') {
  if (-not $remoteDsn) {
    # REMOTE_PG_DSN first: PG_DSN may already point the backend at the local copy.
    $backendEnv = Read-DotEnv (Join-Path $Repo 'backend/.env')
    $remoteDsn = if ($backendEnv['REMOTE_PG_DSN']) { $backendEnv['REMOTE_PG_DSN'] } else { $backendEnv['PG_DSN'] }
  }
  if (-not $remoteDsn) { throw 'set REMOTE_PG_DSN in backend/.env (or $env:SYNC_REMOTE_DSN)' }
  if ($remoteDsn -match '@(localhost|127\.0\.0\.1|\[::1\]|postgres)(:|/|$)') {
    throw 'the remote DSN points at the local database; set REMOTE_PG_DSN in backend/.env (or $env:SYNC_REMOTE_DSN) to the remote pmsonline'
  }
}

$stamp = (Get-Date).ToString('yyyyMMddTHHmm')
if ($Mode -eq 'restore') {
  if (-not $From) {
    $latest = Get-Backups | Select-Object -Last 1
    if (-not $latest) { throw "no backup in $SyncDir; run with -Mode backup first" }
    $From = $latest.Name
  }
  $manifest = Join-Path $SyncDir "$From/manifest.json"
  if (-not (Test-Path $manifest)) { throw "no complete backup '$From' in $SyncDir" }
  $Tables = (Get-Content $manifest -Raw | ConvertFrom-Json).tables    # restore exactly what the backup holds
}

# --- preflight ----------------------------------------------------------------------------------------
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running' }
$health = docker inspect -f '{{.State.Health.Status}}' postgres 2>$null
if ($health -ne 'healthy') { throw "local postgres container is not healthy ($health); run: docker compose up -d postgres" }
$network = docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' postgres

Write-Host "Mode:    $Mode"
Write-Host "Tables:  $($Tables -join ', ')"
if ($Mode -ne 'backup') {
  Write-Host "Restore: $(if ($Mode -eq 'restore') { $From } else { 'the new backup' }) -> local $($infraEnv['PG_DB']) (container postgres)"
  if (-not $Yes) {
    $answer = Read-Host "This DROPS and replaces these $($Tables.Count) table(s) in the LOCAL database. Continue? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Cancelled.'; exit 1 }
  }
}
New-Item -ItemType Directory -Force $SyncDir | Out-Null

# --- run ----------------------------------------------------------------------------------------------
$envVars = [ordered]@{
  SYNC_MODE           = $Mode
  SYNC_TABLES         = $Tables -join ' '
  SYNC_STAMP          = $stamp
  SYNC_FROM           = $From
  SYNC_JOBS           = "$Jobs"
  SYNC_REMOTE_DSN     = $remoteDsn
  SYNC_LOCAL_HOST     = 'postgres'
  SYNC_LOCAL_PORT     = '5432'
  SYNC_LOCAL_DB       = $infraEnv['PG_DB']
  SYNC_LOCAL_USER     = $infraEnv['PG_USER']
  SYNC_LOCAL_PASSWORD = $infraEnv['PG_PASSWORD']
  SYNC_RO_PASSWORD    = $infraEnv['PMSONLINE_RO_PASSWORD']
}
$dockerArgs = @('run', '--rm', '--name', "pmsonline-sync-$stamp", '--network', $network,
  '-v', "${SyncDir}:/sync", '-v', "$(Join-Path $Infra 'postgres/sync-app-tables.sh'):/scripts/sync.sh:ro")
foreach ($k in $envVars.Keys) { $dockerArgs += @('-e', $k) }    # name only: docker reads the value from our env
$dockerArgs += @($Image, 'bash', '/scripts/sync.sh')

$started = Get-Date
try {
  foreach ($k in $envVars.Keys) { Set-Item "env:$k" ([string]$envVars[$k]) }
  & docker @dockerArgs
  $code = $LASTEXITCODE
} finally {
  foreach ($k in $envVars.Keys) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
}
if ($code -ne 0) {
  Remove-Item (Join-Path $SyncDir "$stamp.partial") -Recurse -Force -ErrorAction SilentlyContinue
  throw "sync failed (exit $code)"
}

# --- retention ----------------------------------------------------------------------------------------
if ($Mode -ne 'restore') {
  $old = @(Get-Backups | Select-Object -SkipLast $Keep)
  foreach ($d in $old) { Write-Host "removing old backup $($d.Name)"; Remove-Item $d.FullName -Recurse -Force }
}
Write-Host ("Finished in {0:mm\:ss}. Backups: {1}" -f ((Get-Date) - $started), ((Get-Backups).Name -join ', '))
