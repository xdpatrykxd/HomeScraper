import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from app.models import canonical_url


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_listing_id TEXT,
            url TEXT NOT NULL UNIQUE, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            notification_sent INTEGER NOT NULL DEFAULT 0, property_json TEXT NOT NULL,
            UNIQUE(source, source_listing_id));
        CREATE TABLE IF NOT EXISTS deliveries (
            listing_id INTEGER NOT NULL REFERENCES listings(id), recipient TEXT NOT NULL,
            state TEXT NOT NULL, sid TEXT, PRIMARY KEY(listing_id, recipient));
        CREATE TABLE IF NOT EXISTS translations (
            cache_key TEXT PRIMARY KEY, translated_json TEXT NOT NULL);
        ''')

    def observe(self, p):
        url = canonical_url(p.url)
        row = self.conn.execute('SELECT id FROM listings WHERE (source=? AND source_listing_id=?) OR url=?',
                                (p.source, p.source_listing_id, url)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            if row:
                self.conn.execute('UPDATE listings SET last_seen=? WHERE id=?', (now, row[0]))
                return row[0]
            return self.conn.execute('INSERT INTO listings(source,source_listing_id,url,first_seen,last_seen,property_json) VALUES (?,?,?,?,?,?)',
                                     (p.source, p.source_listing_id, url, now, now, json.dumps(asdict(p)))).lastrowid

    def claim(self, listing_id, recipient):
        # Persist BEFORE the HTTP request: an interrupted/ambiguous send is never blindly retried.
        with self.conn:
            cursor = self.conn.execute("INSERT INTO deliveries VALUES (?,?,'sending',NULL) ON CONFLICT(listing_id,recipient) DO UPDATE SET state='sending',sid=NULL WHERE state='rejected'", (listing_id, recipient))
        return cursor.rowcount == 1

    def pending(self, listing_id, recipient):
        row = self.conn.execute('SELECT state FROM deliveries WHERE listing_id=? AND recipient=?',
                                (listing_id, recipient)).fetchone()
        return row is None or row[0] == 'rejected'

    def translation(self, key):
        row = self.conn.execute('SELECT translated_json FROM translations WHERE cache_key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_translation(self, key, value):
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO translations VALUES (?,?)', (key, json.dumps(value)))

    def delivery(self, listing_id, recipient, state, sid=None):
        with self.conn:
            self.conn.execute('UPDATE deliveries SET state=?,sid=? WHERE listing_id=? AND recipient=?', (state, sid, listing_id, recipient))

    def complete(self, listing_id, recipients):
        accepted = {r[0] for r in self.conn.execute("SELECT recipient FROM deliveries WHERE listing_id=? AND state='accepted'", (listing_id,))}
        with self.conn:
            self.conn.execute('UPDATE listings SET notification_sent=? WHERE id=?', (int(set(recipients) <= accepted), listing_id))

    def close(self):
        self.conn.close()
