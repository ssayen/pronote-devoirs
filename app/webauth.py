"""Connexion, inscription (avec QR code Pronote + PIN) et sessions par cookie."""
import base64
import binascii
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import accounts, db, qr as qrlogin, sync

COOKIE = "session"
PUBLIC = ("/login", "/register", "/logout", "/api/login", "/api/register", "/manifest.webmanifest", "/sw.js", "/favicon.ico")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter()


def invite_code() -> str:
    return os.environ.get("INVITE_CODE", "").strip()


def registration_open() -> bool:
    """Avec un code d'invitation : inscription ouverte à qui le connaît. Sans code : seul le premier compte peut se créer."""
    return bool(invite_code()) or accounts.count() == 0


async def auth(request: Request):
    """Dépendance globale : identifie l'utilisateur (cookie) et fixe son contexte de données."""
    if db.LOCAL:
        request.state.user = None
        request.state.readonly = False
        return
    user = accounts.user_from_token(request.cookies.get(COOKIE))
    request.state.user = user
    request.state.readonly = False
    if user:
        if user["role"] == "parent":  # un parent consulte les données de l'élève lié, sans pouvoir les modifier
            db.set_user(user["student_id"])
            request.state.readonly = True
            cocher = request.url.path.startswith("/api/packs/") and request.url.path.endswith("/delivered")   # seule écriture permise
            if request.method not in ("GET", "HEAD") and request.url.path != "/logout" and not cocher:
                raise HTTPException(403, "Compte parent : consultation seulement.")
        else:
            db.set_user(user["id"])
        return
    path = request.url.path
    if path in PUBLIC or path.startswith("/static/"):
        return
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        raise HTTPException(303, headers={"Location": "/login"})
    raise HTTPException(401, "Non connecté")


# ---- limitation des tentatives (en mémoire) ----
_FAILS: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "?")


def _throttle(*keys: str, limit: int = 8, window: int = 900) -> None:
    now = time.time()
    for k in keys:
        _FAILS[k] = [t for t in _FAILS.get(k, []) if now - t < window]
        if len(_FAILS[k]) >= limit:
            raise HTTPException(429, "Trop de tentatives, réessayer dans quelques minutes.")


def _fail(*keys: str) -> None:
    for k in keys:
        _FAILS.setdefault(k, []).append(time.time())


def _set_cookie(request: Request, resp, token: str) -> None:
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token, max_age=accounts.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=https, path="/")


@router.get("/login")
def login_page(request: Request):
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "auth.html", {"mode": "login", "open": True, "invite": bool(invite_code()),
                                                           "qr_required": False})


def qr_required() -> bool:
    return os.environ.get("ALLOW_RECONNECT", "1") == "1" and not (accounts.count() == 0 and accounts.has_legacy())


@router.get("/register")
def register_page(request: Request):
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "auth.html", {"mode": "register", "open": True, "student_open": registration_open(), "invite": bool(invite_code()),
                                                           "qr_required": qr_required(),
                                                           "legacy": accounts.count() == 0 and accounts.has_legacy(),
                                                           "can_qr": os.environ.get("ALLOW_RECONNECT", "1") == "1"})


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=200)


@router.post("/api/login")
def api_login(body: LoginIn, request: Request):
    ip, lg = "ip:" + _client_ip(request), "lg:" + accounts.normalize(body.login)
    _throttle(ip, lg)
    uid = accounts.verify(body.login, body.password)
    if uid is None:
        _fail(ip, lg)
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")
    resp = JSONResponse({"ok": True})
    _set_cookie(request, resp, accounts.new_session(uid))
    return resp


class RegisterIn(BaseModel):
    role: Literal["student", "parent"] = "student"
    login: str = Field(max_length=64)
    password: str = Field(max_length=200)
    invite: str = Field(default="", max_length=100)     # élève : code d'invitation du serveur
    link: str = Field(default="", max_length=40)        # parent : code de liaison donné par l'élève
    child: str = Field(default="", max_length=80)
    image: str = Field(default="", max_length=12_000_000)   # capture du QR code (base64)
    pin: str = Field(default="", max_length=10)


def _link_by_children() -> int:
    """Parent sans code : retrouve l'élève StudyFun parmi les enfants de son compte Pronote (identifiant, à défaut nom + classe)."""
    import json
    with db.conn() as c:
        st = dict(c.execute("SELECT key, value FROM settings").fetchall())
    children = json.loads(st.get("pronote_children", "[]"))
    found = accounts.match_students(children, st.get("pronote_host", ""))
    if len(found) == 1:
        return found[0][0]
    names = ", ".join(ch["name"] for ch in children) or "aucun"
    if not found:
        raise HTTPException(400, f"Aucun élève inscrit sur StudyFun ne correspond à tes enfants Pronote ({names}). "
                                 "L'élève doit d'abord créer son compte avec son QR code, ou te donner un code de liaison.")
    raise HTTPException(400, "Plusieurs élèves correspondent à tes enfants : demande un code de liaison à celui que tu veux suivre.")


@router.post("/api/register")
def api_register(body: RegisterIn, request: Request, background: BackgroundTasks):
    ip = "reg:" + _client_ip(request)
    _throttle(ip)
    parent = body.role == "parent"
    student_id = None
    if parent:
        if body.link.strip():  # code de liaison généré par l'élève ; sans code, le lien se fait par les enfants du QR code parent
            student_id = accounts.invite_student(body.link)
            if student_id is None:
                _fail(ip)
                raise HTTPException(403, "Code de liaison invalide ou expiré : l'élève peut en générer un nouveau.")
        elif not body.image:
            raise HTTPException(400, "Le QR code parent (capture d'écran) et son PIN sont nécessaires, ou un code de liaison.")
    else:
        if not registration_open():
            raise HTTPException(403, "Les inscriptions sont fermées.")
        if invite_code() and not secrets.compare_digest(body.invite.strip(), invite_code()):
            _fail(ip)
            raise HTTPException(403, "Code d'invitation incorrect.")
    login = accounts.normalize(body.login)
    if not accounts.LOGIN_RE.fullmatch(login):
        raise HTTPException(400, "Identifiant : 3 à 32 caractères (lettres, chiffres, . _ -).")
    if len(body.password) < 8:
        raise HTTPException(400, "Mot de passe : 8 caractères minimum.")
    want_qr = bool(body.image)
    if not want_qr and qr_required():
        raise HTTPException(400, "Le QR code Pronote (capture d'écran) et son PIN sont nécessaires.")
    qr = None
    if want_qr:
        try:
            qr = qrlogin.decode_image(base64.b64decode(body.image.split(",", 1)[-1], validate=True))
        except (binascii.Error, ValueError, qrlogin.QRError) as e:
            raise HTTPException(400, str(e) if isinstance(e, qrlogin.QRError) else "Image illisible.") from None
    uid = accounts.create(login, body.password, body.role, student_id)
    if uid is None:
        raise HTTPException(409, "Cet identifiant est déjà pris.")
    first = not parent and accounts.count() == 1
    with db.as_user(uid):  # le compte parent n'utilise ce dossier que pour son propre jeton
        try:
            db.init()
            if body.child.strip() and not parent:
                with db.conn() as c:
                    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('child', ?)", (body.child.strip(),))
            if qr is not None:
                try:
                    qrlogin.connect(qr, body.pin, body.role)
                except qrlogin.QRError as e:
                    raise HTTPException(400, str(e)) from None
            if parent and student_id is None:
                student_id = _link_by_children()
            if first and accounts.claim_legacy(uid):
                db.init()  # migrations de l'ancienne base
                if body.child.strip():  # le réglage saisi doit survivre au remplacement de la base
                    with db.conn() as c:
                        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('child', ?)", (body.child.strip(),))
        except Exception:
            accounts.delete(uid)
            raise
    if parent:
        accounts.set_student(uid, student_id)
        if body.link.strip():
            accounts.use_invite(body.link)
    resp = JSONResponse({"ok": True}, status_code=201)
    _set_cookie(request, resp, accounts.new_session(uid))
    if not parent:
        def first_sync():
            with db.as_user(uid):
                sync.run_sync()
        background.add_task(first_sync)
        resp.background = background
    return resp


@router.post("/api/parent-invite")
def parent_invite(request: Request):
    """L'élève génère un code de liaison pour un parent (valable 7 jours, usage unique)."""
    user = request.state.user
    if user is None or user["role"] not in ("student", "admin"):
        raise HTTPException(403, "Réservé aux comptes élèves.")
    return {"code": accounts.new_invite(user["id"]), "days": accounts.INVITE_DAYS, "parents": accounts.parents_of(user["id"])}


@router.post("/logout")
def logout(request: Request):
    accounts.end_session(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
