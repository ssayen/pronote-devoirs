import hashlib
import json
import os
import threading
import urllib.request
from urllib.parse import urlparse
from datetime import date, timedelta

import pronotepy

from . import db

_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def lock() -> threading.Lock:
    """Verrou de synchro de l'utilisateur courant (une synchro à la fois par utilisateur)."""
    key = db.user_dir()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def creds_path() -> str:
    return os.path.join(db.user_dir(), "credentials.json")


def child_name() -> str:
    """Enfant suivi (compte parent) : réglage de l'utilisateur, à défaut la variable CHILD_NAME (ancienne installation)."""
    try:
        with db.conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key = 'child'").fetchone()
        if r and r["value"]:
            return r["value"]
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("CHILD_NAME", "")


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


class TokenExpired(RuntimeError):
    """Pronote refuse le jeton (ou il n'existe pas) : il faut régénérer un QR code."""


def get_client():
    """Point d'injection (remplaçable dans les tests)."""
    try:
        with open(creds_path()) as f:
            creds = json.load(f)
    except FileNotFoundError:
        raise TokenExpired("Aucun identifiant Pronote (credentials.json absent) : faire la connexion par QR code") from None
    client = client_class(creds["pronote_url"]).token_login(**creds)
    if not client.logged_in:
        raise TokenExpired("Connexion refusée : jeton expiré, régénérer le QR code")
    save_creds(client)
    remember_identity(client, creds["pronote_url"])  # sans requête supplémentaire ; permet de rattacher un parent à cet élève
    child = child_name()
    if child and hasattr(client, "set_child"):  # seulement les comptes parent (un compte élève n'a qu'un enfant : lui-même)
        client.set_child(child)
    return client


def display_name() -> str:
    """Nom affiché dans l'en-tête : enfant choisi, à défaut le nom du compte Pronote (élève)."""
    name = child_name()
    if name:
        return name
    try:
        with db.conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key = 'pronote_name'").fetchone()
        return r["value"] if r else ""
    except Exception:  # noqa: BLE001
        return ""


def _identity(info) -> dict:
    return {"id": str(getattr(info, "id", "") or ""), "name": getattr(info, "name", "") or "",
            "class": getattr(info, "class_name", "") or "", "est": getattr(info, "establishment", "") or ""}

def remember_identity(client, url: str) -> None:
    """Mémorise qui est ce compte Pronote (sert à nommer l'élève et à rattacher un parent à son enfant).
    Élève : son propre identifiant. Parent : la liste de ses enfants. Une erreur ici ne fait jamais échouer la connexion."""
    try:
        host = (urlparse(url).hostname or "").lower()
        values = {"pronote_name": client.info.name, "pronote_host": host}
        if hasattr(client, "children"):
            values["pronote_children"] = json.dumps([_identity(c) for c in client.children])
        else:
            me = _identity(client.info)
            values.update({"pronote_id": me["id"], "pronote_class": me["class"], "pronote_est": me["est"]})
        with db.conn() as c:
            c.executemany("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", list(values.items()))
    except Exception:  # noqa: BLE001
        pass


def push_enabled() -> bool:
    """Écriture vers Pronote (« fait / pas fait ») : désactivée tant que PUSH_TO_PRONOTE != 1."""
    return os.environ.get("PUSH_TO_PRONOTE", "0") == "1"


MAX_FILE_BYTES = 25 * 1024 * 1024


def files_dir() -> str:
    return os.path.join(db.user_dir(), "files")


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


def _num(v, out_of=None) -> float | None:
    """« 14,5 » -> 14.5 ; « Abs », « N.Not », vide -> None. Ramené sur 20 si le barème est différent."""
    try:
        x = float(str(v).strip().replace(",", "."))
        o = float(str(out_of).strip().replace(",", ".")) if out_of not in (None, "") else 20.0
    except ValueError:
        return None
    return round(x * 20 / o, 2) if o > 0 else None


def _sync_results(client) -> int:
    """Moyennes par matière (élève et classe) pour chaque période commencée. Retourne le nombre de périodes."""
    today = date.today()
    n = 0
    for pos, p in enumerate(client.periods):
        start = getattr(p, "start", None)
        if start is not None and hasattr(start, "date"):
            start = start.date()
        if start is not None and start > today:
            continue  # période pas encore commencée
        avgs = p.averages
        if not avgs:
            continue  # rien de publié : on garde ce qu'on avait
        end = getattr(p, "end", None)
        end = end.date() if end is not None and hasattr(end, "date") else end
        try:
            overall = _num(p.overall_average)
            if overall is not None and overall < 0:
                overall = None
        except Exception:  # noqa: BLE001
            overall = None
        try:
            class_overall = _num(p.class_overall_average)
        except Exception:  # noqa: BLE001
            class_overall = None
        with db.conn() as c:
            c.execute("DELETE FROM averages WHERE period = ?", (p.name,))
            for a in avgs:
                c.execute("INSERT OR REPLACE INTO averages (period, subject, student, class_avg, min, max) VALUES (?,?,?,?,?,?)",
                          (p.name, a.subject.name, _num(a.student, a.out_of), _num(a.class_average, a.out_of),
                           _num(a.min, a.out_of), _num(a.max, a.out_of)))
            c.execute("INSERT OR REPLACE INTO periods (name, position, start, end, overall, class_overall) VALUES (?,?,?,?,?,?)",
                      (p.name, pos, start.isoformat() if start else None, end.isoformat() if end else None,
                       overall, class_overall))
        n += 1
    return n


def _sync_lessons(client) -> int:
    """Emploi du temps : de la semaine précédente à 5 semaines devant. Remplace cette fenêtre
    (un cours annulé ou déplacé doit disparaître / changer), sans toucher à l'historique plus ancien."""
    mon = date.today() - timedelta(days=date.today().weekday())
    lo, hi = mon - timedelta(days=7), mon + timedelta(days=35)
    rows, seen = [], {}
    for l in client.lessons(lo, hi):
        subject = (l.subject.name if l.subject else None) or "Cours"
        start, end = l.start.strftime("%Y-%m-%dT%H:%M"), l.end.strftime("%Y-%m-%dT%H:%M")
        base = db.content_key(subject, start, end)
        n = seen.get(base, 0); seen[base] = n + 1
        rows.append((f"{base}-{n}", start, end, subject, l.teacher_name, l.classroom, l.status,
                     int(bool(l.canceled)), int(bool(l.test)), int(bool(l.detention)), int(bool(l.outing)), l.memo))
    with db.conn() as c:
        c.execute("DELETE FROM lessons WHERE start >= ? AND start < ?", (lo.isoformat(), hi.isoformat()))
        c.executemany("INSERT OR REPLACE INTO lessons (id, start, end, subject, teacher, room, status, canceled, test, detention, outing, memo) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


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
    msg = f"{len(hws)} devoirs lus, {pulled} nouveaux, {pushed} statuts renvoyés vers Pronote"
    try:  # les résultats ne doivent jamais faire échouer la synchro des devoirs
        msg += f", moyennes de {_sync_results(client)} période(s)"
    except Exception as e:  # noqa: BLE001
        msg += f" (moyennes non lues : {type(e).__name__})"
    try:
        msg += f", {_sync_lessons(client)} cours"
    except Exception as e:  # noqa: BLE001
        msg += f" (emploi du temps non lu : {type(e).__name__})"
    return msg


def notify(title: str, message: str) -> str | None:
    """Notification poussée (compatible ntfy) vers NOTIFY_URL ; désactivée si elle est vide.
    Ne transmet jamais de données de devoirs. Retourne un message d'erreur, ou None."""
    url = os.environ.get("NOTIFY_URL", "").strip()
    if not url:
        return None
    headers = {"Title": title, "Priority": "high", "Tags": "key", "Content-Type": "text/plain; charset=utf-8"}
    if os.environ.get("NOTIFY_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["NOTIFY_TOKEN"]
    try:
        req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:  # noqa: BLE001 - une notification ratée ne doit jamais bloquer la synchro
        return f"{type(e).__name__}: {e}"
    return None


def run_sync() -> None:
    lk = lock()
    if not lk.acquire(blocking=False):
        return  # synchro déjà en cours
    try:
        try:
            kind, msg = "ok", _sync()
        except TokenExpired as e:
            kind, msg = "auth", str(e)
        except Exception as e:  # noqa: BLE001
            kind, msg = "error", f"{type(e).__name__}: {e}"
        with db.conn() as c:
            prev = c.execute("SELECT kind FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_kind = prev["kind"] if prev else "ok"
        # une seule notification par changement d'état (pas une toutes les 30 min)
        failure = None
        if kind == "auth" and prev_kind != "auth":
            failure = notify("StudyFun : jeton Pronote expire",
                             "Pronote a refuse le jeton : les devoirs ne sont plus synchronises. "
                             "Regenerer un QR code et relancer la connexion (voir le bandeau rouge de l'application).")
        elif kind == "ok" and prev_kind == "auth":
            failure = notify("StudyFun : Pronote reconnecte", "La synchronisation avec Pronote fonctionne de nouveau.")
        if failure:
            msg += f" (notification non envoyée : {failure})"
        with db.conn() as c:
            c.execute("INSERT INTO sync_log (ok, kind, message) VALUES (?, ?, ?)", (int(kind == "ok"), kind, msg))
            c.execute("DELETE FROM sync_log WHERE id NOT IN (SELECT id FROM sync_log ORDER BY id DESC LIMIT 200)")
    finally:
        lk.release()
