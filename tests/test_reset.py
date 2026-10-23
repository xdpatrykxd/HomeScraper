import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.database import Database
from scripts.wipe_database import wipe_database


class ResetTests(unittest.TestCase):
    def test_reset_preserves_session_and_settings_and_can_start_fresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'listings.sqlite3'
            db = Database(path)
            db.save_translation('key', {'title': 'Dom'})
            db.close()
            retained = [root / '.env', root / 'filters.yaml', root / 'whatsapp-sessions' / 'session']
            for file in retained:
                file.parent.mkdir(exist_ok=True)
                file.write_text('keep')
            sidecars = [Path(str(path) + suffix) for suffix in ('-wal', '-shm', '-journal')]
            for file in sidecars:
                file.write_text('old')
            with patch('builtins.print'):
                wipe_database(path)
                wipe_database(path)  # Resetting an already empty database is safe.
            self.assertFalse(any(file.exists() for file in [path, *sidecars]))
            self.assertTrue(all(file.read_text() == 'keep' for file in retained))
            db = Database(path)
            self.assertIsNone(db.translation('key'))
            self.assertEqual(db.conn.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)
            db.close()

    def test_running_watcher_lock_prevents_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'listings.sqlite3'
            path.write_text('unchanged')
            with Path(str(path) + '.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, 'Watcher is running'):
                    wipe_database(path)
                self.assertEqual(path.read_text(), 'unchanged')

    def test_symlink_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'keep'
            target.write_text('keep')
            path = Path(folder) / 'listings.sqlite3'
            path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                wipe_database(path)
            self.assertEqual(target.read_text(), 'keep')
