"""Local message history. The iPhone only exposes recent messages over
Bluetooth, so everything we see is kept here."""
import hashlib
import os
import re
import sqlite3
import time


def conv_key(address):
    """Group "+1 (555) 123-4567" and "5551234567" into one conversation."""
    a = (address or "").strip()
    if "@" in a:
        return a.lower()
    digits = re.sub(r"\D", "", a)
    if len(digits) >= 10:
        return digits[-10:]
    return digits or a


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                conv TEXT NOT NULL,
                address TEXT NOT NULL,
                name TEXT,
                outgoing INTEGER NOT NULL,
                text TEXT NOT NULL,
                ts REAL NOT NULL,
                handle TEXT,
                status TEXT,
                dedupe TEXT UNIQUE
            )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv, ts)")
        self.db.execute("CREATE TABLE IF NOT EXISTS contacts (key TEXT PRIMARY KEY, name TEXT NOT NULL)")
        columns = [r["name"] for r in self.db.execute("PRAGMA table_info(messages)")]
        if "reply_to" not in columns:  # databases from before replies existed
            self.db.execute("ALTER TABLE messages ADD COLUMN reply_to INTEGER")
        if "reaction" not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN reaction TEXT")
        if "read" not in columns:  # existing messages count as already read
            self.db.execute("ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 1")
        contact_columns = [r["name"] for r in self.db.execute("PRAGMA table_info(contacts)")]
        if "photo" not in contact_columns:
            self.db.execute("ALTER TABLE contacts ADD COLUMN photo TEXT")
        if "address" not in contact_columns:  # full number with country code, filled on next sync
            self.db.execute("ALTER TABLE contacts ADD COLUMN address TEXT")
        # remove copies of one phone message saved twice by older versions
        self.db.execute("""
            DELETE FROM messages WHERE handle IS NOT NULL AND EXISTS (
                SELECT 1 FROM messages o WHERE o.id < messages.id AND o.handle IS NOT NULL
                AND o.conv = messages.conv AND o.outgoing = messages.outgoing
                AND o.text = messages.text AND abs(o.ts - messages.ts) < 300)""")
        self.db.commit()

    def has_handle(self, handle, ts):
        row = self.db.execute(
            "SELECT 1 FROM messages WHERE handle = ? AND abs(ts - ?) < 1", (handle, ts or 0)
        ).fetchone()
        return row is not None

    def add(self, address, text, outgoing, name="", ts=None, handle=None, status=None, reply_to=None,
            reaction=None):
        """Insert a message; returns its id, or None if it was already stored."""
        ts = ts or time.time()
        conv = conv_key(address)
        dedupe = None
        if handle:  # messages read from the phone; our own sends are never duplicates
            dedupe = hashlib.sha1(("%s|%d|%d|%s" % (conv, outgoing, int(ts), text)).encode()).hexdigest()
            # the phone can report one message twice (notification + listing) with different times
            if self.db.execute("SELECT 1 FROM messages WHERE conv = ? AND outgoing = ? AND text = ?"
                               " AND handle IS NOT NULL AND abs(ts - ?) < 300",
                               (conv, int(outgoing), text, ts)).fetchone():
                return None
        try:
            cur = self.db.execute(
                "INSERT INTO messages (conv, address, name, outgoing, text, ts, handle, status, dedupe,"
                " reply_to, read, reaction) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conv, address, name or "", int(outgoing), text, ts, handle, status, dedupe,
                 reply_to, int(outgoing), reaction),
            )
        except sqlite3.IntegrityError:
            return None
        self.db.commit()
        return cur.lastrowid

    def set_status(self, msg_id, status):
        self.db.execute("UPDATE messages SET status = ? WHERE id = ?", (status, msg_id))
        self.db.commit()

    def conversations(self):
        return self.db.execute("""
            SELECT m.conv, m.text, m.ts, m.outgoing,
                   COALESCE((SELECT name FROM contacts c WHERE c.key = m.conv),
                            (SELECT name FROM messages n WHERE n.conv = m.conv AND n.name != ''
                             ORDER BY n.ts DESC LIMIT 1)) AS name,
                   (SELECT photo FROM contacts c WHERE c.key = m.conv) AS photo,
                   (SELECT count(*) FROM messages u WHERE u.conv = m.conv AND u.read = 0) AS unread,
                   (SELECT address FROM messages a WHERE a.conv = m.conv
                    ORDER BY a.outgoing, a.ts DESC LIMIT 1) AS address
            FROM messages m
            WHERE m.id = (SELECT id FROM messages x WHERE x.conv = m.conv ORDER BY x.ts DESC, x.id DESC LIMIT 1)
            ORDER BY m.ts DESC""").fetchall()

    def mark_read(self, conv):
        """Returns True if anything changed."""
        cur = self.db.execute("UPDATE messages SET read = 1 WHERE conv = ? AND read = 0", (conv,))
        self.db.commit()
        return cur.rowcount > 0

    def delete_conversation(self, conv):
        with self.db:
            self.db.execute("DELETE FROM messages WHERE conv = ?", (conv,))

    def messages(self, conv):
        return self.db.execute(
            "SELECT * FROM messages WHERE conv = ? ORDER BY ts, id", (conv,)
        ).fetchall()

    def replace_contacts(self, contacts):
        """contacts: {conv_key: (name, photo path or None, address)} from the phone's address book."""
        with self.db:
            self.db.execute("DELETE FROM contacts")
            self.db.executemany("INSERT INTO contacts (key, name, photo, address) VALUES (?, ?, ?, ?)",
                                [(k, name, photo, address)
                                 for k, (name, photo, address) in contacts.items()])

    def contacts(self):
        return self.db.execute(
            "SELECT * FROM contacts ORDER BY name COLLATE NOCASE, address"
        ).fetchall()

    def contact_name(self, address):
        row = self.db.execute("SELECT name FROM contacts WHERE key = ?", (conv_key(address),)).fetchone()
        return row["name"] if row else ""

    def contact_photo(self, address):
        row = self.db.execute("SELECT photo FROM contacts WHERE key = ?", (conv_key(address),)).fetchone()
        return row["photo"] if row and row["photo"] and os.path.exists(row["photo"]) else None

    def get(self, msg_id):
        return self.db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
