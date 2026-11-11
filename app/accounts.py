"""Comptes utilisateurs et sessions (accounts.db à la racine de DATA_DIR).

Les données scolaires de chaque utilisateur sont dans DATA_DIR/users/<id>/ (voir db.user_dir)."""
import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import time

from . import db

SESSION_DAYS = 180
LOGIN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")


def _path() -> str:
    return os.path.join(db.DATA_DIR, "accounts.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    os.makedirs(db.DATA_DIR, exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login      TEXT NOT NULL UNIQUE,
            pw_hash    TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );""")


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def _check(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except ValueError:
        return False


_DUMMY = hash_password("x")


def normalize(login: str) -> str:
    return (login or "").strip().lower()


def count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def user_ids() -> list[int]:
    with _conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM users ORDER BY id")]


def create(login: str, pw: str) -> int | None:
    """Crée le compte ; None si l'identifiant est déjà pris."""
    try:
        with _conn() as c:
            return c.execute("INSERT INTO users (login, pw_hash) VALUES (?, ?)", (login, hash_password(pw))).lastrowid
    except sqlite3.IntegrityError:
        return None


def delete(uid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        c.execute("DELETE FROM users WHERE id = ?", (uid,))
    shutil.rmtree(os.path.join(db.DATA_DIR, "users", str(uid)), ignore_errors=True)


def verify(login: str, pw: str) -> int | None:
    with _conn() as c:
        r = c.execute("SELECT id, pw_hash FROM users WHERE login = ?", (normalize(login),)).fetchone()
    ok = _check(pw, r["pw_hash"] if r else _DUMMY)  # même durée que le compte existe ou non
    return r["id"] if r and ok else None


def new_session(uid: int) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        c.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(), uid, int(time.time()) + SESSION_DAYS * 86400))
    return token


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    with _conn() as c:
        r = c.execute("SELECT u.id, u.login FROM sessions s JOIN users u ON u.id = s.user_id "
                      "WHERE s.token_hash = ? AND s.expires_at > ?",
                      (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    return dict(r) if r else None


def end_session(token: str | None) -> None:
    if token:
        with _conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def claim_legacy(uid: int) -> bool:
    """Ancienne installation mono-utilisateur (DATA_DIR/devoirs.db) : rattachée à ce compte, sans rien perdre."""
    old = os.path.join(db.DATA_DIR, "devoirs.db")
    if not os.path.isfile(old):
        return False
    dest = os.path.join(db.DATA_DIR, "users", str(uid))
    os.makedirs(dest, exist_ok=True)
    for name in ("devoirs.db", "credentials.json", "files"):
        src = os.path.join(db.DATA_DIR, name)
        if os.path.exists(src):
            target = os.path.join(dest, name)
            if name == "credentials.json" and os.path.exists(target):
                os.remove(src)  # un QR code vient d'être saisi : le plus récent l'emporte
                continue
            if os.path.isdir(target):
                shutil.rmtree(target)
            elif os.path.exists(target):
                os.remove(target)
            shutil.move(src, target)
    return True


def has_legacy() -> bool:
    return os.path.isfile(os.path.join(db.DATA_DIR, "devoirs.db"))
