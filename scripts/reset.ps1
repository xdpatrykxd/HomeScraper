param([switch]$Yes)
$ErrorActionPreference = 'Stop'
if (-not $Yes) {
    throw 'Run .\scripts\reset.ps1 -Yes to clear deliveries and translations. All current matches will be alerted again.'
}
Push-Location (Join-Path $PSScriptRoot '..')
try {
    docker compose build watcher
    if ($LASTEXITCODE -ne 0) { throw 'Build failed; database was not reset.' }
    docker compose stop watcher
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop watcher; database was not reset.' }
    docker compose run --rm --no-deps watcher python -m scripts.wipe_database --yes
    if ($LASTEXITCODE -ne 0) { throw 'Reset failed; watcher remains stopped.' }
    docker compose up -d watcher
    if ($LASTEXITCODE -ne 0) { throw 'Database was reset, but watcher restart failed.' }
} finally {
    Pop-Location
}
