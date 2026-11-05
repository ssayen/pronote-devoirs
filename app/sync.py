import hashlib
import json
import os
import threading
from datetime import date, timedelta

import pronotepy

from . import db

LOCK = threading.Lock()


def creds_path() -> str:
    return os.path.join(db.DATA_DIR, "credentials.json")


def save_creds(client) -> None:
    """Le jeton change à chaque connexion : on le réécrit toujours."""
    tmp = creds_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(client.export_credentials(), f)
    os.replace(tmp, creds_path())


def client_class(url: str):
    """Classe pronotepy selon l'espace Pronote (parent, vie scolaire, élève)."""
    page = url.split("?")[0].rsplit("/", 1)[-1]
    if "parent" in page:
        return pronotepy.ParentClient
    if "viescolaire" in page:
        return pronotepy.VieScolaireClient
    return pronotepy.Client


def get_client():
    """Point d'injection (remplaçable dans les tests)."""
    with open(creds_path()) as f:
        creds = json.load(f)
    client = client_class(creds["pronote_url"]).token_login(**creds)
    if not client.logged_in:
        raise RuntimeError("Connexion refusée : jeton expiré, régénérer le QR code")
    save_creds(client)
    child = os.environ.get("CHILD_NAME")
    if child:
        client.set_child(child)
    return client


def push_enabled() -> bool:
    """Écriture vers Pronote (« fait / pas fait ») : désactivée tant que PUSH_TO_PRONOTE != 1."""
    return os.environ.get("PUSH_TO_PRONOTE", "0") == "1"


MAX_FILE_BYTES = 25 * 1024 * 1024


def files_dir() -> str:
    return os.path.join(db.DATA_DIR, "files")


def _safe_name(name: str) -> str:
    name = os.path.basename(name.replace("\\", "/")).replace("\0", "").strip() or "fichier"
    return name[:150]


def _files(hid: str, h) -> str:
    """Liste des pièces jointes. Les fichiers Pronote (adresse liée à la session) sont
    téléchargés ici, pendant que la session est ouverte ; les liens externes restent des liens."""
    out = []
    for f in getattr(h, "files", None) or []:
        name = getattr(f, "name", "") or "fichier"
        if getattr(f, "type", 1) == 0:
            out.append({"name": name, "kind": "link", "url": getattr(f, "url", name)})
            continue
        rel = os.path.join(hashlib.sha1(hid.encode()).hexdigest()[:16], _safe_name(name))
        dest = os.path.join(files_dir(), rel)
        if not os.path.exists(dest):
            try:
                data = f.data
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError("fichier trop gros")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest + ".tmp", "wb") as fh:
                    fh.write(data)
                os.replace(dest + ".tmp", dest)
            except Exception:  # noqa: BLE001 - une pièce jointe en échec ne bloque pas la synchro
                rel = None
        out.append({"name": name, "kind": "file", "local": rel})
    return json.dumps(out)


def _sync() -> str:
    client = get_client()
    today = date.today()
    hws = list(client.homework(today - timedelta(days=7), today + timedelta(days=90)))
    by_id: dict[str, object] = {}
    seen: dict[str, int] = {}
    for h in hws:  # clé stable : l'id Pronote change à chaque connexion
        base = db.content_key(h.subject.name, h.date.isoformat(), h.description)
        n = seen.get(base, 0)
        seen[base] = n + 1
        by_id[f"{base}-{n}"] = h

    pushed = pulled = 0
    pushed_ids: set[str] = set()
    with db.conn() as c:
        # première synchro sur une base vide : tout arrive d'un coup, rien n'est « nouveau »
        first_run = c.execute("SELECT COUNT(*) FROM homework WHERE source = 'pronote'").fetchone()[0] == 0
        created = "'2000-01-01 00:00:00'" if first_run else "datetime('now')"
        # 1) renvoyer vers Pronote les changements « fait » faits dans l'app (si activé)
        if push_enabled():
            for row in c.execute("SELECT id, done FROM homework WHERE pending_push = 1").fetchall():
                h = by_id.get(row["id"])
                if h is not None:
                    if bool(h.done) != bool(row["done"]):
                        h.set_done(bool(row["done"]))
                        pushed += 1
                    pushed_ids.add(row["id"])
                    c.execute("UPDATE homework SET pending_push = 0, pronote_done = ? WHERE id = ?",
                              (row["done"], row["id"]))
                else:
                    c.execute("UPDATE homework SET pending_push = 0 WHERE id = ?", (row["id"],))

        # 2) importer / mettre à jour depuis Pronote
        for hid, h in by_id.items():
            files = _files(hid, h)
            p_done = int(bool(h.done))
            existing = c.execute(
                "SELECT status, pronote_done, pending_push FROM homework WHERE id = ?", (hid,)
            ).fetchone()
            if existing is None:
                c.execute(
                    "INSERT INTO homework (id, subject, description, due_date, done, status, pronote_done, files, "
                    f"created_at) VALUES (?,?,?,?,?,?,?,?,{created})",
                    (hid, h.subject.name, h.description, h.date.isoformat(), p_done,
                     "done" if p_done else "todo", p_done, files),
                )
                pulled += 1
                continue
            status, p_prev = existing["status"], existing["pronote_done"]
            if hid not in pushed_ids and not existing["pending_push"] and p_done != p_prev:
                # changement fait côté Pronote : il se répercute sur la colonne
                if p_done:
                    status = "done"
                elif status == "done":
                    status = "todo"
                p_prev = p_done
            c.execute(
                "UPDATE homework SET subject=?, description=?, due_date=?, files=?, status=?, done=?, "
                "pronote_done=?, updated_at=datetime('now') WHERE id=?",
                (h.subject.name, h.description, h.date.isoformat(), files, status,
                 int(status == "done"), p_prev, hid),
            )
    return f"{len(hws)} devoirs lus, {pulled} nouveaux, {pushed} statuts renvoyés vers Pronote"


def run_sync() -> None:
    if not LOCK.acquire(blocking=False):
        return  # synchro déjà en cours
    try:
        try:
            ok, msg = True, _sync()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"{type(e).__name__}: {e}"
        with db.conn() as c:
            c.execute("INSERT INTO sync_log (ok, message) VALUES (?, ?)", (int(ok), msg))
            c.execute("DELETE FROM sync_log WHERE id NOT IN (SELECT id FROM sync_log ORDER BY id DESC LIMIT 200)")
    finally:
        LOCK.release()
