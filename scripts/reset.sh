#!/bin/sh
# Run from any directory; only the watcher is stopped/restarted.
set -eu
if [ "${1:-}" != "--yes" ] || [ "$#" -ne 1 ]; then
    echo 'Usage: sh scripts/reset.sh --yes' >&2
    echo 'Clears deliveries and translations. All current matches will be alerted again.' >&2
    exit 2
fi
cd "$(dirname "$0")/.."
docker compose build watcher
docker compose stop watcher
docker compose run --rm --no-deps watcher python -m scripts.wipe_database --yes
docker compose up -d watcher
