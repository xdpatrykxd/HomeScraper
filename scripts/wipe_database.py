"""Reset only the configured SQLite database; preserve pairing and configuration."""
import argparse
import fcntl
import os
from pathlib import Path

from dotenv import load_dotenv


def wipe_database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    targets = [path, Path(str(path) + '-wal'), Path(str(path) + '-shm'), Path(str(path) + '-journal')]
    lock_path = Path(str(path) + '.lock')
    for target in [*targets, lock_path]:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError(f'Refusing to reset a symlink or non-file: {target}')
    # Use the watcher's own lock: never remove a database while it is sending.
    # Keep the lock file so concurrent processes always lock the same inode.
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Watcher is running; stop it before wiping the database') from None
        for target in targets:
            target.unlink(missing_ok=True)
    print(f'Reset {path}. WhatsApp pairing, .env and search criteria were preserved.')
    print('The next real scan will alert every currently matching property again.')


def main():
    parser = argparse.ArgumentParser(description='Clear listing records, deliveries and cached translations')
    parser.add_argument('--yes', action='store_true', help='Confirm the database reset')
    args = parser.parse_args()
    if not args.yes:
        parser.error('Pass --yes to reset. Every currently matching property will be alerted again.')
    load_dotenv()
    try:
        wipe_database(os.getenv('DATABASE_PATH', 'data/listings.sqlite3'))
    except (OSError, RuntimeError) as exc:
        parser.exit(1, f'Reset failed: {exc}\n')


if __name__ == '__main__':
    main()
