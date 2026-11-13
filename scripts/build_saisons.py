"""Prépare les fonds d'écran saisonniers à partir des images sources fond-<saison>.png déposées à la racine du projet.

Usage : .venv/bin/python scripts/build_saisons.py
Écrit app/static/saisons/<saison>.jpg (1600 px de large, JPEG optimisé). Les sources (PNG, ~2 Mo chacune) ne sont pas versionnées.
Saisons attendues : noel, hiver, printemps, ete, automne (le calendrier est dans le <head> de app/templates/index.html).
"""
import glob
import os

from PIL import Image

WIDTH = 1600
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
out = os.path.join(root, "app", "static", "saisons")
os.makedirs(out, exist_ok=True)
for path in sorted(glob.glob(os.path.join(root, "fond-*.png"))):
    name = os.path.basename(path)[len("fond-"):-len(".png")]
    img = Image.open(path).convert("RGB")
    if img.width > WIDTH:
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    dest = os.path.join(out, name + ".jpg")
    img.save(dest, "JPEG", quality=80, optimize=True, progressive=True)
    print(f"{name}: {os.path.getsize(dest) // 1024} Ko")
