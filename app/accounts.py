"""Comptes utilisateurs et sessions (accounts.db à la racine de DATA_DIR).

Les données scolaires de chaque utilisateur sont dans DATA_DIR/users/<id>/ (voir db.user_dir)."""
import hashlib
import json
import unicodedata
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
        CREATE TABLE IF NOT EXISTS invites (      -- codes de liaison parent : un élève invite un parent
            code_hash  TEXT PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );""")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "role" not in cols:  # 'student' (compte élève, ses propres données) ou 'parent' (suivi en lecture seule d'un élève)
            c.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")
        if "student_id" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN student_id INTEGER")


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
        return [r["id"] for r in c.execute("SELECT id FROM users WHERE role = 'student' ORDER BY id")]


def create(login: str, pw: str, role: str = "student", student_id: int | None = None) -> int | None:
    """Crée le compte ; None si l'identifiant est déjà pris."""
    try:
        with _conn() as c:
            return c.execute("INSERT INTO users (login, pw_hash, role, student_id) VALUES (?, ?, ?, ?)",
                             (login, hash_password(pw), role, student_id)).lastrowid
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
        r = c.execute("SELECT u.id, u.login, u.role, u.student_id FROM sessions s JOIN users u ON u.id = s.user_id "
                      "WHERE s.token_hash = ? AND s.expires_at > ?",
                      (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    return dict(r) if r else None


def end_session(token: str | None) -> None:
    if token:
        with _conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # sans I, L, O, 0, 1 : lisible à voix haute
INVITE_DAYS = 7


def _code_hash(code: str) -> str:
    return hashlib.sha256(re.sub(r"[^A-Z0-9]", "", (code or "").upper()).encode()).hexdigest()


def new_invite(student_id: int) -> str:
    """Code à donner à un parent : valable 7 jours, à usage unique (le précédent est annulé)."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    with _conn() as c:
        c.execute("DELETE FROM invites WHERE student_id = ? OR expires_at < ?", (student_id, int(time.time())))
        c.execute("INSERT INTO invites VALUES (?,?,?)", (_code_hash(raw), student_id, int(time.time()) + INVITE_DAYS * 86400))
    return f"{raw[:4]}-{raw[4:]}"


def invite_student(code: str) -> int | None:
    with _conn() as c:
        r = c.execute("SELECT student_id FROM invites WHERE code_hash = ? AND expires_at > ?",
                      (_code_hash(code), int(time.time()))).fetchone()
    return r["student_id"] if r else None


def use_invite(code: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM invites WHERE code_hash = ?", (_code_hash(code),))


def parents_of(student_id: int) -> list[str]:
    with _conn() as c:
        return [r["login"] for r in c.execute("SELECT login FROM users WHERE role = 'parent' AND student_id = ?", (student_id,))]


def set_student(parent_id: int, student_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET student_id = ? WHERE id = ? AND role = 'parent'", (student_id, parent_id))


def _norm(name: str) -> str:
    """Nom sans accents ni casse, mots triés : « POLESE Lucie » == « Lucie Polese »."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.findall(r"[a-z0-9]+", s)))


def _settings_of(uid: int) -> dict:
    path = os.path.join(db.DATA_DIR, "users", str(uid), "devoirs.db")
    try:
        with sqlite3.connect(path, timeout=30) as c:
            return dict(c.execute("SELECT key, value FROM settings").fetchall())
    except sqlite3.Error:
        return {}


def match_students(children: list[dict], host: str) -> list[tuple[int, str, str]]:
    """Élèves StudyFun correspondant aux enfants Pronote d'un parent : (id du compte, nom, niveau).
    Niveau « id » : même serveur Pronote et même identifiant. Niveau « nom » : même nom (normalisé) et même classe / établissement."""
    found: dict[int, tuple[int, str, str]] = {}
    for uid in user_ids():
        s = _settings_of(uid)
        if not s.get("pronote_host") or s["pronote_host"] != host:
            continue
        for ch in children:
            if s.get("pronote_id") and ch.get("id") == s["pronote_id"]:
                found[uid] = (uid, s.get("pronote_name", ""), "id")
                break
            same_name = _norm(ch.get("name", "")) == _norm(s.get("pronote_name", "")) != ""
            same_class = not (ch.get("class") and s.get("pronote_class")) or ch["class"] == s["pronote_class"]
            same_est = not (ch.get("est") and s.get("pronote_est")) or ch["est"] == s["pronote_est"]
            if same_name and same_class and same_est and uid not in found:
                found[uid] = (uid, s.get("pronote_name", ""), "nom")
    return list(found.values())


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
