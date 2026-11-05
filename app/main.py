import asyncio
import json
import os
import uuid
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import db, sync

INTERVAL_MIN = int(os.environ.get("SYNC_INTERVAL_MIN", "30"))
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
NEW_HOURS = int(os.environ.get("NEW_HOURS", "48"))  # durée d'affichage du badge « Nouveau »

DONE_KEEP_DAYS = int(os.environ.get("DONE_KEEP_DAYS", "3"))  # « Terminé » : masqué quand l'échéance a plus de N jours

NEW_SQL = f"(created_at >= datetime('now', '-{NEW_HOURS} hours')) AS is_new"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)


def auth(creds: HTTPBasicCredentials | None = Depends(security)):
    if not APP_PASSWORD:
        return
    ok = creds is not None and secrets.compare_digest(
        creds.username, APP_USER
    ) and secrets.compare_digest(creds.password, APP_PASSWORD)
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


async def sync_loop():
    while True:
        await asyncio.to_thread(sync.run_sync)
        await asyncio.sleep(INTERVAL_MIN * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    task = asyncio.create_task(sync_loop()) if INTERVAL_MIN > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan, dependencies=[Depends(auth)])
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


@app.get("/")
def index(request: Request):
    with db.conn() as c:
        rows = c.execute(f"SELECT *, {NEW_SQL} FROM homework ORDER BY due_date, subject").fetchall()
        last = c.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    cards = [card_dict(r) for r in rows]
    return templates.TemplateResponse(
        request,
        "index.html",
        {"cards": cards, "last": last, "today": date.today().isoformat(),
         "child": os.environ.get("CHILD_NAME", ""), "push": sync.push_enabled(),
         "keep_days": DONE_KEEP_DAYS,
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


@app.post("/sync")
def sync_now(background: BackgroundTasks):
    background.add_task(sync.run_sync)
    return RedirectResponse("/", status_code=303)


@app.get("/api/homework")
def api_homework():
    with db.conn() as c:
        return [dict(r) for r in c.execute(f"SELECT *, {NEW_SQL} FROM homework ORDER BY due_date")]
