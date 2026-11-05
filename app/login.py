"""Initialise credentials.json à partir du QR code Pronote.

Usage : python -m app.login '<json du QR code ou chemin du fichier>' <PIN à 4 chiffres>
"""
import json
import os
import sys
import uuid

import pronotepy

from . import db
from .sync import client_class, save_creds


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raw, pin = sys.argv[1], sys.argv[2]
    if os.path.isfile(raw):
        raw = open(raw).read()
    qr = json.loads(raw)
    os.makedirs(db.DATA_DIR, exist_ok=True)
    client = client_class(qr["url"]).qrcode_login(qr, pin, str(uuid.uuid4()))
    if not client.logged_in:
        sys.exit("Échec de connexion (QR code expiré ou PIN incorrect ?)")
    save_creds(client)
    print(f"OK, connecté en tant que {client.info.name}. Identifiants écrits dans {db.DATA_DIR}.")


if __name__ == "__main__":
    main()
