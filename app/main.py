import asyncio
import base64
import binascii
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import accounts, db, game, qr as qrlogin, sync, webauth

INTERVAL_MIN = int(os.environ.get("SYNC_INTERVAL_MIN", "30"))
NEW_HOURS = int(os.environ.get("NEW_HOURS", "48"))  # durée d'affichage du badge « Nouveau »

DONE_KEEP_DAYS = int(os.environ.get("DONE_KEEP_DAYS", "3"))  # « Terminé » : masqué quand l'échéance a plus de N jours

NEW_SQL = f"(created_at >= datetime('now', '-{NEW_HOURS} hours')) AS is_new"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _sync_user(uid):
    with db.as_user(uid):
        sync.run_sync()


async def sync_loop():
    while True:
        for uid in ([None] if db.LOCAL else accounts.user_ids()):
            await asyncio.to_thread(_sync_user, uid)
        await asyncio.sleep(INTERVAL_MIN * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    accounts.init()
    for uid in ([None] if db.LOCAL else accounts.user_ids(("student", "admin"))):
        with db.as_user(uid):
            db.init()
    task = asyncio.create_task(sync_loop()) if INTERVAL_MIN > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan, dependencies=[Depends(webauth.auth)])
app.include_router(webauth.router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def card_dict(r) -> dict:
    d = dict(r)
    d["files"] = json.loads(d["files"] or "[]")
    return d


def get_card(c, hw_id: str) -> dict:
    row = c.execute(f"SELECT *, {NEW_SQL} FROM homework WHERE id = ?", (hw_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    return card_dict(row)


def results_data() -> dict:
    """Moyennes par période : {periods: [{name, overall, class_overall, subjects: [...]}]}, la plus récente en dernier."""
    with db.conn() as c:
        periods = c.execute("SELECT * FROM periods ORDER BY position").fetchall()
        out = []
        for p in periods:
            rows = c.execute("SELECT subject, student, class_avg, min, max FROM averages WHERE period = ? ORDER BY subject",
                             (p["name"],)).fetchall()
            out.append({"name": p["name"], "start": p["start"], "end": p["end"], "overall": p["overall"],
                        "class_overall": p["class_overall"], "subjects": [dict(r) for r in rows]})
    return {"periods": out}


def avatar_list() -> list[dict]:
    """Avatars disponibles : app/static/avatars/avatars.json (écrit par scripts/build_avatars.py), image présente."""
    folder = Path(__file__).parent / "static" / "avatars"
    try:
        items = json.loads((folder / "avatars.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a for a in items if isinstance(a, dict) and isinstance(a.get("id"), str) and (folder / f"{a['id']}.jpg").is_file()]


def settings_data() -> dict:
    with db.conn() as c:
        rows = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}
    ids = {a["id"] for a in avatar_list()}
    return {"avatar": rows.get("avatar") if rows.get("avatar") in ids else None,
            "theme": rows.get("theme") if rows.get("theme") in ("light", "dark") else "auto"}


class SettingsIn(BaseModel):
    """Seuls les champs présents sont modifiés ; null (avatar) ou « auto » (thème) = valeur par défaut."""
    avatar: str | None = Field(default=None, max_length=60)
    theme: Literal["auto", "light", "dark"] | None = None


@app.get("/api/settings")
def get_settings():
    return settings_data()


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    """Enregistre la personnalisation : avatar et thème (clair / sombre / auto)."""
    given = body.model_fields_set
    if "avatar" in given and body.avatar is not None and body.avatar not in {a["id"] for a in avatar_list()}:
        raise HTTPException(422, "Avatar inconnu")
    changes = {}
    if "avatar" in given:
        changes["avatar"] = body.avatar
    if "theme" in given:
        changes["theme"] = None if body.theme in (None, "auto") else body.theme
    with db.conn() as c:
        for key, value in changes.items():
            if value is None:
                c.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                          (key, value))
    return settings_data()


def lessons_data() -> list[dict]:
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM lessons ORDER BY start, end, subject")]


@app.get("/api/lessons")
def api_lessons():
    return lessons_data()


@app.get("/api/game")
def api_game(request: Request):
    with db.conn() as c:
        if not request.state.readonly:  # un parent consulte sans rien modifier
            game.update(c)
        return game.overview(c)


class PointsIn(BaseModel):
    points: int = Field(ge=1, le=100)


@app.post("/api/admin/points")
def admin_points(body: PointsIn, request: Request):
    """Outil de test : le compte administrateur s'octroie des points (les niveaux et paquets suivent)."""
    if (request.state.user or {}).get("role") != "admin":
        raise HTTPException(403, "Réservé au compte administrateur.")
    with db.conn() as c:
        game.award(c, "admin", f"admin:{uuid.uuid4().hex}", body.points, "Points ajoutés (test)")
        game.ensure_packs(c)
        return game.summary(c)


@app.post("/api/packs/{level}/open")
def open_pack(level: int):
    with db.conn() as c:
        reward = game.open_pack(c, level)
    if reward is None:
        raise HTTPException(404, "Paquet introuvable ou déjà ouvert.")
    return {"level": level, "reward": reward["label"], "rarity": reward["rarity"], "icon": reward["icon"]}


@app.get("/api/results")
def api_results():
    return results_data()


@app.get("/manifest.webmanifest")
def manifest(request: Request):
    child = sync.display_name() if (db.LOCAL or request.state.user) else ""
    name = "StudyFun" + (f" — {child}" if child else "")
    icons = [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        {"src": "/static/icons/monochrome-512.png", "sizes": "512x512", "type": "image/png", "purpose": "monochrome"},
    ]
    return JSONResponse(
        {"name": name, "short_name": "StudyFun", "lang": "fr", "start_url": "/", "scope": "/", "display": "standalone",
         "background_color": "#f4f6fb", "theme_color": "#3b82f6", "icons": icons},
        media_type="application/manifest+json",
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(Path(__file__).parent / "static" / "icons" / "favicon.ico", media_type="image/x-icon")


@app.get("/sw.js")
def service_worker():
    # servi à la racine pour que son périmètre couvre toute l'app
    return FileResponse(Path(__file__).parent / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/")
def index(request: Request):
    with db.conn() as c:
        rows = c.execute(f"SELECT *, {NEW_SQL} FROM homework ORDER BY due_date, subject").fetchall()
        last = c.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        gm = game.summary(c)
    cards = [card_dict(r) for r in rows]
    return templates.TemplateResponse(
        request,
        "index.html",
        {"cards": cards, "results": results_data(), "game": gm, "lessons": lessons_data(), "settings": settings_data(), "avatars": avatar_list(), "last": last, "today": date.today().isoformat(),
         "child": sync.display_name(), "account": (request.state.user or {}).get("login", ""),
         "role": (request.state.user or {}).get("role", "student"), "readonly": getattr(request.state, "readonly", False), "push": sync.push_enabled(),
         "keep_days": DONE_KEEP_DAYS, "auth_problem": bool(last and last["kind"] == "auth"),
         "fonds": sorted(p.stem for p in (Path(__file__).parent / "static" / "fonds").glob("*.jpg"))},
    )


class CardIn(BaseModel):
    subject: str = Field(default="Perso", max_length=60)
    description: str = Field(min_length=1, max_length=2000)
    due_date: date
    status: str = "todo"


@app.post("/api/cards", status_code=201)
def create_card(body: CardIn):
    """Carte personnelle : jamais touchée par la synchro, jamais envoyée à Pronote."""
    if body.status not in db.STATUSES:
        raise HTTPException(422, "statut inconnu")
    hw_id = "local-" + uuid.uuid4().hex[:12]
    with db.conn() as c:
        c.execute(
            "INSERT INTO homework (id, subject, description, due_date, done, status, source, created_at) "
            "VALUES (?,?,?,?,?,?,'local','2000-01-01 00:00:00')",
            (hw_id, body.subject.strip() or "Perso", body.description.strip(), body.due_date.isoformat(),
             int(body.status == "done"), body.status),
        )
        return get_card(c, hw_id)


def _own_card(c, hw_id: str) -> None:
    row = c.execute("SELECT source FROM homework WHERE id = ?", (hw_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    if row["source"] != "local":
        raise HTTPException(403, "carte Pronote : modifiée par la synchro, non éditable")


@app.put("/api/cards/{hw_id}")
def update_card(hw_id: str, body: CardIn):
    if body.status not in db.STATUSES:
        raise HTTPException(422, "statut inconnu")
    with db.conn() as c:
        _own_card(c, hw_id)
        c.execute(
            "UPDATE homework SET subject=?, description=?, due_date=?, status=?, done=?, "
            "updated_at=datetime('now') WHERE id=?",
            (body.subject.strip() or "Perso", body.description.strip(), body.due_date.isoformat(),
             body.status, int(body.status == "done"), hw_id),
        )
        return get_card(c, hw_id)


@app.delete("/api/cards/{hw_id}", status_code=204)
def delete_card(hw_id: str):
    with db.conn() as c:
        _own_card(c, hw_id)
        c.execute("DELETE FROM homework WHERE id = ?", (hw_id,))


class Move(BaseModel):
    status: str


@app.post("/move/{hw_id}")
def move(hw_id: str, body: Move, background: BackgroundTasks):
    if body.status not in db.STATUSES:
        raise HTTPException(422, "statut inconnu")
    with db.conn() as c:
        row = c.execute("SELECT status, pronote_done, source FROM homework WHERE id = ?", (hw_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        done = int(body.status == "done")
        # seul le passage fait / pas fait concerne Pronote (et seulement si l'écriture est activée)
        push = int(sync.push_enabled() and row["source"] == "pronote" and done != row["pronote_done"])
        c.execute(
            "UPDATE homework SET status = ?, done = ?, pending_push = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (body.status, done, push, hw_id),
        )
    if push:
        background.add_task(sync.run_sync)
    return {"id": hw_id, "status": body.status, "push": bool(push)}


@app.get("/file/{hw_id}/{idx}")
def attachment(hw_id: str, idx: int):
    with db.conn() as c:
        row = c.execute("SELECT files FROM homework WHERE id = ?", (hw_id,)).fetchone()
    files = json.loads(row["files"]) if row else []
    if not 0 <= idx < len(files) or not files[idx].get("local"):
        raise HTTPException(404)
    root = os.path.realpath(sync.files_dir())
    path = os.path.realpath(os.path.join(root, files[idx]["local"]))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, filename=files[idx]["name"])


class Reconnect(BaseModel):
    image: str = Field(max_length=12_000_000)   # capture du QR code en base64 (préfixe « data:… » toléré)
    pin: str = Field(max_length=10)


@app.post("/api/reconnect")
def reconnect(body: Reconnect, request: Request, background: BackgroundTasks):
    """Reconnexion à Pronote depuis une capture du QR code + son PIN. Rien n'est conservé hors credentials.json."""
    if (request.state.user or {}).get("role") == "admin":
        raise HTTPException(403, "Compte administrateur : pas de connexion Pronote.")
    if os.environ.get("ALLOW_RECONNECT", "1") != "1":
        raise HTTPException(403, "Reconnexion désactivée dans cet environnement (ALLOW_RECONNECT=0).")
    try:
        data = base64.b64decode(body.image.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Image illisible.") from None
    lk = sync.lock()
    if not lk.acquire(timeout=30):  # ne pas réécrire credentials.json pendant une synchro
        raise HTTPException(409, "Une synchronisation est en cours, réessayer dans un instant.")
    try:
        name = qrlogin.connect(qrlogin.decode_image(data), body.pin, (request.state.user or {}).get("role"))
    except qrlogin.QRError as e:
        raise HTTPException(400, str(e)) from None
    finally:
        lk.release()
    background.add_task(sync.run_sync)  # première synchro tout de suite : lève la bannière et notifie « reconnecté »
    return {"ok": True, "name": name}


@app.post("/sync")
def sync_now(request: Request, background: BackgroundTasks):
    if (request.state.user or {}).get("role") == "admin":  # pas de Pronote pour ce compte
        return RedirectResponse("/", status_code=303)
    background.add_task(sync.run_sync)
    return RedirectResponse("/", status_code=303)


@app.get("/api/homework")
def api_homework():
    with db.conn() as c:
        return [dict(r) for r in c.execute(f"SELECT *, {NEW_SQL} FROM homework ORDER BY due_date")]
