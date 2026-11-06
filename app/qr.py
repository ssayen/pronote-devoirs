"""Connexion à Pronote par QR code : décodage d'une capture d'écran, validation, connexion.

Partagé par la ligne de commande (python -m app.login) et par le formulaire web (/api/reconnect).
Ne journalise et ne renvoie jamais le contenu du QR code (il contient un jeton d'accès).
"""
import io
import ipaddress
import json
import re
import uuid
from urllib.parse import urlparse

import zxingcpp
from PIL import Image, ImageOps

from .sync import client_class, creds_path, save_creds

MAX_IMAGE_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse les « bombes de décompression »

GENERIC_FAILURE = "Connexion refusée : QR code expiré, PIN incorrect, ou Pronote injoignable. Régénérer un QR code et réessayer."


class QRError(ValueError):
    """Erreur présentable telle quelle à l'utilisateur."""


def decode_image(data: bytes) -> dict:
    """Lit le QR code d'une image (capture d'écran, photo) et retourne son contenu JSON."""
    if len(data) > MAX_IMAGE_BYTES:
        raise QRError("Image trop volumineuse (8 Mo maximum).")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001 - format inconnu, fichier tronqué, trop grand…
        raise QRError("Fichier illisible : déposer une capture d'écran (PNG ou JPG) du QR code.") from None

    # plusieurs essais : original, niveaux de gris, réduit/agrandi (les captures retina sont parfois trop fines)
    variants = [img, ImageOps.grayscale(img)]
    for scale in (0.5, 0.25, 2.0):
        w, h = int(img.width * scale), int(img.height * scale)
        if 100 <= w <= 4000 and 100 <= h <= 4000:
            variants.append(img.resize((w, h), Image.LANCZOS))
    for v in variants:
        for r in zxingcpp.read_barcodes(v, formats=zxingcpp.BarcodeFormat.QRCode):
            try:
                qr = json.loads(r.text)
            except ValueError:
                continue
            if isinstance(qr, dict):
                return qr
    raise QRError("Aucun QR code Pronote détecté dans l'image : recadrer sur le QR code et réessayer.")


def validate_qr(qr: dict) -> None:
    """Le QR code doit être bien formé, et l'adresse ne doit pas viser autre chose que Pronote."""
    if not all(isinstance(qr.get(k), str) and qr[k] for k in ("url", "login", "jeton")):
        raise QRError("Ce QR code n'est pas un QR code Pronote (application mobile).")
    url = urlparse(qr["url"])
    host = (url.hostname or "").lower()
    if url.scheme != "https" or not host or url.username or url.password:
        raise QRError("Adresse Pronote refusée (HTTPS requis).")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise QRError("Adresse Pronote refusée.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise QRError("Adresse Pronote refusée.")
    # une fois configuré, on ne change plus de serveur Pronote par cette voie
    try:
        with open(creds_path()) as f:
            known = (urlparse(json.load(f)["pronote_url"]).hostname or "").lower()
    except (OSError, ValueError, KeyError):
        known = ""  # pas encore configuré (ou fichier illisible) : première connexion
    if known and known != host:  # hors du try : QRError est un ValueError et serait avalée
        raise QRError("Ce QR code vient d'un autre serveur Pronote que celui déjà configuré.")


def connect(qr: dict, pin: str) -> str:
    """Se connecte avec le QR code + PIN, écrit credentials.json, retourne le nom du compte."""
    if not re.fullmatch(r"\d{4}", pin or ""):
        raise QRError("Le PIN comporte 4 chiffres.")
    validate_qr(qr)
    try:
        client = client_class(qr["url"]).qrcode_login(qr, pin, str(uuid.uuid4()))
        ok = bool(client.logged_in)
    except Exception:  # noqa: BLE001 - le détail pourrait contenir le jeton : on ne le propage pas
        ok = False
    if not ok:
        raise QRError(GENERIC_FAILURE)
    save_creds(client)
    return client.info.name
