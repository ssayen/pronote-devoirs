"""Initialise credentials.json à partir du QR code Pronote (alternative au formulaire web).

Usage : python -m app.login <capture.png | qr.json | json du QR code> <PIN à 4 chiffres>
"""
import json
import os
import sys

from . import db
from .qr import QRError, connect, decode_image

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raw, pin = sys.argv[1], sys.argv[2]
    try:
        if os.path.isfile(raw):
            if raw.lower().endswith(IMAGE_EXT):
                with open(raw, "rb") as f:
                    qr = decode_image(f.read())
            else:
                with open(raw) as f:
                    qr = json.load(f)
        else:
            qr = json.loads(raw)
        os.makedirs(db.DATA_DIR, exist_ok=True)
        name = connect(qr, pin)
    except (QRError, ValueError) as e:
        sys.exit(f"Échec : {e}")
    print(f"OK, connecté en tant que {name}. Identifiants écrits dans {db.DATA_DIR}.")


if __name__ == "__main__":
    main()
