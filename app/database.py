"""SQLite persistence and transaction boundaries for the demo."""
import os
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

DEFAULT_DB = os.getenv("UPI_NETWORK_DB_PATH", "upi_network.db")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
    vpa TEXT PRIMARY KEY,
    holder_name TEXT NOT NULL,
    balance REAL NOT NULL CHECK(balance >= 0)
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_hash TEXT NOT NULL UNIQUE,
    sender_vpa TEXT NOT NULL,
    receiver_vpa TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    bridge_node_id TEXT NOT NULL,
    hop_count INTEGER NOT NULL DEFAULT 0,
    settled_at TEXT NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS idempotency_claims (
    packet_hash TEXT PRIMARY KEY,
    claimed_at TEXT NOT NULL
);
"""

class Database:
    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_DB
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def initialize(self):
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO accounts(vpa, holder_name, balance) VALUES (?, ?, ?)",
                    [("alice@demo", "Alice", 5000.0), ("bob@demo", "Bob", 2500.0),
                     ("carol@demo", "Carol", 3000.0), ("dave@demo", "Dave", 1000.0)],
                )

    @contextmanager
    def transaction(self, immediate: bool = True):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, sql: str, params=()):
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def clear_ledger_and_claims(self):
        with self.transaction() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM idempotency_claims")
            conn.execute("UPDATE accounts SET balance = CASE vpa WHEN 'alice@demo' THEN 5000.0 WHEN 'bob@demo' THEN 2500.0 WHEN 'carol@demo' THEN 3000.0 WHEN 'dave@demo' THEN 1000.0 ELSE balance END")
