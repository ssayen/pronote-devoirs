import hashlib
import os
import shutil
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar

DATA_DIR = os.environ.get("DATA_DIR", "/data")
# AUTH_DISABLED=1 : mode local sans compte (développement, tests) ; les données sont à la racine de DATA_DIR.
LOCAL = os.environ.get("AUTH_DISABLED", "0") == "1"

# Utilisateur courant (une base, un jeton Pronote et des fichiers par utilisateur : DATA_DIR/users/<id>/)
_user: ContextVar[int | None] = ContextVar("user", default=None)


def set_user(uid: int | None):
    return _user.set(uid)


@contextmanager
def as_user(uid: int | None):
    tok = _user.set(uid)
    try:
        yield
    finally:
        _user.reset(tok)


def user_dir() -> str:
    uid = _user.get()
    if uid is None:
        if not LOCAL:
            raise RuntimeError("Aucun utilisateur courant")
        return DATA_DIR
    return os.path.join(DATA_DIR, "users", str(uid))


def db_path() -> str:
    return os.path.join(user_dir(), "devoirs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS homework (
    id           TEXT PRIMARY KEY,
    subject      TEXT NOT NULL,
    description  TEXT NOT NULL,
    due_date     TEXT NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    pending_push INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'todo',
    pronote_done INTEGER NOT NULL DEFAULT 0,
    files        TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    source       TEXT NOT NULL DEFAULT 'pronote',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS periods (
    name          TEXT PRIMARY KEY,
    position      INTEGER NOT NULL,
    start         TEXT,
    end           TEXT,
    overall       REAL,          -- moyenne générale de l'élève (sur 20)
    class_overall REAL,          -- moyenne générale de la classe (sur 20)
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS averages (   -- toutes les valeurs sont ramenées sur 20
    period    TEXT NOT NULL,
    subject   TEXT NOT NULL,
    student   REAL,
    class_avg REAL,
    min       REAL,
    max       REAL,
    PRIMARY KEY (period, subject)
);
CREATE TABLE IF NOT EXISTS lessons (      -- emploi du temps ; dates locales « AAAA-MM-JJTHH:MM »
    id        TEXT PRIMARY KEY,
    start     TEXT NOT NULL,
    end       TEXT NOT NULL,
    subject   TEXT NOT NULL,
    teacher   TEXT,
    room      TEXT,
    status    TEXT,
    canceled  INTEGER NOT NULL DEFAULT 0,
    test      INTEGER NOT NULL DEFAULT 0,
    detention INTEGER NOT NULL DEFAULT 0,
    outing    INTEGER NOT NULL DEFAULT 0,
    memo      TEXT
);
CREATE TABLE IF NOT EXISTS grades (       -- notes individuelles ; grade / class_avg / max ramenés sur 20
    id        TEXT PRIMARY KEY,           -- clé de contenu (les identifiants Pronote changent à chaque connexion)
    period    TEXT NOT NULL,
    subject   TEXT NOT NULL,
    date      TEXT NOT NULL,
    grade     REAL NOT NULL,
    out_of    REAL,
    coef      REAL,
    class_avg REAL,
    max       REAL,
    comment   TEXT,
    first_seen TEXT,                      -- date d'arrivée dans l'app (la date de la note, elle, peut être ancienne)
    seen_at   TEXT                        -- NULL tant que l'élève n'a pas vu la note
);
CREATE TABLE IF NOT EXISTS points (       -- journal des points : on n'y fait qu'ajouter ; « ref » unique = une seule attribution par événement
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL DEFAULT (datetime('now')),
    kind   TEXT NOT NULL,                 -- grade | mission
    ref    TEXT NOT NULL UNIQUE,
    points INTEGER NOT NULL,
    label  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,             -- avg_up | beat_class | good_grades
    subject    TEXT,
    params     TEXT NOT NULL DEFAULT '{}',   -- objectif (ex. {"target": 14} ; anciennes missions : {"delta": 1})
    baseline   TEXT NOT NULL DEFAULT '{}',   -- état au démarrage (ex. {"avg": 12.4, "period": "Trimestre 1"})
    points     INTEGER NOT NULL,
    label      TEXT NOT NULL,
    started_at TEXT NOT NULL,             -- AAAA-MM-JJ : seules les notes postérieures comptent
    expires_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | done | expired
    done_at    TEXT,
    celebrated_at TEXT                    -- NULL tant que l'élève n'a pas vu la célébration d'une mission réussie
);
CREATE TABLE IF NOT EXISTS packs (        -- un paquet par niveau atteint
    level      INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    opened_at  TEXT,
    reward     TEXT,
    rarity     TEXT,
    delivered_at TEXT,                    -- remis à l'élève (coché par le parent)
    icon       TEXT,
    bonus_n    INTEGER,                   -- bonus systématique tiré à l'ouverture (ex. 2 crédits), en plus de la récompense
    bonus_unit TEXT,
    bonus_delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS bonus_rules (  -- bonus systématique par rareté : un nombre tiré entre min et max ; l'unité (« crédits ») est dans settings.bonus_unit
    rarity TEXT PRIMARY KEY,
    min    INTEGER NOT NULL,
    max    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rewards (      -- récompenses propres à l'élève, définies par le parent ; aucune = pas de paquets
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rarity TEXT NOT NULL,                 -- common | rare | epic | legendary
    label  TEXT NOT NULL,
    icon   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS levelups (     -- niveaux gagnés sans paquet (aucune récompense définie) : célébrés par une animation
    level         INTEGER PRIMARY KEY,
    reached_at    TEXT NOT NULL DEFAULT (datetime('now')),
    celebrated_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (     -- personnalisation de l'interface (clé / valeur), conservée dans le volume de données
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL DEFAULT (datetime('now')),
    ok      INTEGER NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'ok',   -- ok | error | auth (jeton Pronote refusé)
    message TEXT NOT NULL
);
"""


def content_key(subject: str, due: str, description: str) -> str:
    """Les identifiants Pronote changent à chaque connexion : on identifie un devoir par son contenu."""
    raw = "|".join((subject.strip(), due, " ".join(description.split())))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


STATUSES = ("todo", "doing", "done")

# colonnes ajoutées après la première version : migration des bases existantes
MIGRATIONS = {
    "status": "ALTER TABLE homework ADD COLUMN status TEXT NOT NULL DEFAULT 'todo'",
    "pronote_done": "ALTER TABLE homework ADD COLUMN pronote_done INTEGER NOT NULL DEFAULT 0",
    "files": "ALTER TABLE homework ADD COLUMN files TEXT NOT NULL DEFAULT '[]'",
    "source": "ALTER TABLE homework ADD COLUMN source TEXT NOT NULL DEFAULT 'pronote'",
    # devoirs déjà connus avant cette colonne : date ancienne, pour ne pas les afficher « Nouveau »
    "created_at": "ALTER TABLE homework ADD COLUMN created_at TEXT NOT NULL DEFAULT '2000-01-01 00:00:00'",
}


def init() -> None:
    os.makedirs(user_dir(), exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(homework)")}
        for name, ddl in MIGRATIONS.items():
            if name not in cols:
                c.execute(ddl)
                if name == "status":
                    c.execute("UPDATE homework SET status = CASE WHEN done = 1 THEN 'done' ELSE 'todo' END")
                if name == "pronote_done":
                    c.execute("UPDATE homework SET pronote_done = done")

        gcols = {r["name"] for r in c.execute("PRAGMA table_info(grades)")}
        if "seen_at" not in gcols:   # notes déjà connues avant cette fonction : considérées comme vues
            c.execute("ALTER TABLE grades ADD COLUMN first_seen TEXT")
            c.execute("ALTER TABLE grades ADD COLUMN seen_at TEXT")
            c.execute("UPDATE grades SET first_seen = datetime('now'), seen_at = datetime('now')")
        if "celebrated_at" not in {r["name"] for r in c.execute("PRAGMA table_info(missions)")}:   # missions déjà réussies : pas de célébration rétroactive
            c.execute("ALTER TABLE missions ADD COLUMN celebrated_at TEXT")
            c.execute("UPDATE missions SET celebrated_at = datetime('now') WHERE status != 'active'")
        if "rarity" not in {r["name"] for r in c.execute("PRAGMA table_info(packs)")}:
            c.execute("ALTER TABLE packs ADD COLUMN rarity TEXT")
        if "icon" not in {r["name"] for r in c.execute("PRAGMA table_info(packs)")}:
            c.execute("ALTER TABLE packs ADD COLUMN icon TEXT")
        for col, ddl in (("bonus_n", "INTEGER"), ("bonus_unit", "TEXT"), ("bonus_delivered_at", "TEXT")):
            if col not in {r["name"] for r in c.execute("PRAGMA table_info(packs)")}:
                c.execute(f"ALTER TABLE packs ADD COLUMN {col} {ddl}")
        if "delivered_at" not in {r["name"] for r in c.execute("PRAGMA table_info(packs)")}:
            c.execute("ALTER TABLE packs ADD COLUMN delivered_at TEXT")
        if "kind" not in {r["name"] for r in c.execute("PRAGMA table_info(sync_log)")}:
            c.execute("ALTER TABLE sync_log ADD COLUMN kind TEXT NOT NULL DEFAULT 'ok'")
            c.execute("UPDATE sync_log SET kind = 'error' WHERE ok = 0")
        _migrate_ids(c)


def _migrate_ids(c: sqlite3.Connection) -> None:
    """Anciennes lignes (id Pronote contenant « # ») : regroupe les doublons, garde le plus récent."""
    old = c.execute("SELECT * FROM homework WHERE id LIKE '%#%' ORDER BY updated_at DESC").fetchall()
    if not old:
        return
    seen: dict[str, int] = {}
    for r in old:
        base = content_key(r["subject"], r["due_date"], r["description"])
        n = seen.get(base, 0)
        seen[base] = n + 1
        c.execute("DELETE FROM homework WHERE id = ?", (r["id"],))
        if n == 0:
            c.execute(
                "INSERT OR IGNORE INTO homework (id, subject, description, due_date, done, pending_push, "
                "status, pronote_done, files, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{base}-0", r["subject"], r["description"], r["due_date"], r["done"], r["pending_push"],
                 r["status"], r["pronote_done"], r["files"], r["created_at"], r["updated_at"]),
            )
    shutil.rmtree(os.path.join(user_dir(), "files"), ignore_errors=True)  # dossiers nommés d'après les anciens id
