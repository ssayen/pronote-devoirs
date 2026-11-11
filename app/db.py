import hashlib
import os
import shutil
import sqlite3

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "devoirs.db")

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
    c = sqlite3.connect(DB_PATH, timeout=30)
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
    os.makedirs(DATA_DIR, exist_ok=True)
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
    shutil.rmtree(os.path.join(DATA_DIR, "files"), ignore_errors=True)  # dossiers nommés d'après les anciens id
