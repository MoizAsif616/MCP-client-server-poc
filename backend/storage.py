import json
import secrets
import sqlite3
import time
from contextlib import contextmanager


class Store:
    def __init__(self, settings):
        self.settings = settings
        settings.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, roles TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id TEXT, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pending (
                    id TEXT PRIMARY KEY, params TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS codes (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, params TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (
                    access TEXT PRIMARY KEY, refresh TEXT UNIQUE, user_id TEXT NOT NULL,
                    client_id TEXT NOT NULL, resource TEXT NOT NULL, scope TEXT NOT NULL,
                    access_expires REAL NOT NULL, refresh_expires REAL NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.settings.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def user(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT id,email,roles FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) | {"roles": json.loads(row["roles"])} if row else None

    def signup(self, email, password, roles):
        user_id = secrets.token_hex(12)
        with self.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?,?)", (user_id, email, password, json.dumps(roles)))
        return user_id

    def login(self, email, password):
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE email=? AND password=?", (email, password)).fetchone()
        return row["id"] if row else None

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (session_id, time.time())).fetchone()
        return dict(row) if row else None

    def new_session(self, user_id=None):
        row = dict(id=secrets.token_urlsafe(32), user_id=user_id, csrf=secrets.token_urlsafe(24),
                   expires=time.time() + self.settings.session_seconds)
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (:id,:user_id,:csrf,:expires)", row)
        return row

    def delete_session(self, session_id):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def client(self, client_id):
        with self.connect() as db:
            row = db.execute("SELECT metadata FROM clients WHERE id=?", (client_id,)).fetchone()
        return json.loads(row["metadata"]) if row else None

    def access(self, value):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tokens WHERE access=?", (value,)).fetchone()
        return dict(row) if row else None
