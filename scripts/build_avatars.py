"""Prépare les avatars web à partir des images sources du dossier avatars/ (PNG, triées par nom).

Usage : .venv/bin/python scripts/build_avatars.py
Écrit app/static/avatars/<id>.jpg (512 px) et app/static/avatars/avatars.json.
La n-ième image source (ordre alphabétique) reçoit le n-ième nom de la liste ci-dessous ;
pour en ajouter, déposer l'image dans avatars/ et ajouter son nom à la fin de la liste.
"""
import json
import os
import unicodedata

from PIL import Image, ImageOps

NAMES = ["Renard", "Hibou", "Chat", "Loup", "Lapin", "Panda", "Raton laveur", "Cerf", "Crocodile", "Perroquet",
         "Chien", "Tigre", "Koala", "Pieuvre", "Hérisson", "Ours polaire", "Caméléon", "Paon", "Grenouille", "Chauve-souris"]
SIZE = 512

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
src, out = os.path.join(root, "avatars"), os.path.join(root, "app", "static", "avatars")


def slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode().lower()
    return "-".join("".join(c if c.isalnum() else " " for c in s).split())


files = sorted(f for f in os.listdir(src) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
if len(files) > len(NAMES):
    raise SystemExit(f"{len(files)} images mais {len(NAMES)} noms : compléter NAMES dans ce script")
os.makedirs(out, exist_ok=True)
index = []
for f, name in zip(files, NAMES):
    img = ImageOps.fit(Image.open(os.path.join(src, f)).convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
    img.save(os.path.join(out, slug(name) + ".jpg"), "JPEG", quality=86, optimize=True, progressive=True)
    index.append({"id": slug(name), "name": name})
with open(os.path.join(out, "avatars.json"), "w", encoding="utf-8") as fh:
    json.dump(index, fh, ensure_ascii=False, indent=1)
print(f"{len(index)} avatars écrits dans app/static/avatars/")
