"""Prépare les images du paquet à partir de paquet-complet.png, paquet-corps.png et paquet-couvercle.png (racine du projet, non versionnées).

Usage : .venv/bin/python scripts/build_paquet.py
Les trois images n'avaient pas le même cadrage : le corps et le couvercle sont remis à l'échelle et décalés pour se superposer exactement
au paquet complet (valeurs mesurées sur les pieds dorés du corps et sur la face turquoise du couvercle), puis les trois sont rognées
à la même boîte et réduites. Écrit app/static/paquet/{complet,corps,couvercle}.webp (mêmes dimensions) et affiche le rapport largeur/hauteur
et la hauteur de la jointure couvercle/corps (utiles au CSS).
"""
import os

from PIL import Image

N = 1254
ALIGN = {"corps": (0.974, 10.7, 63.0), "couvercle": (0.859, 83.0, -103.5)}   # échelle, décalage x, décalage y (dans le repère du paquet complet)
OUT_W = 720
MARGIN = 30

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
out = os.path.join(root, "app", "static", "paquet")
os.makedirs(out, exist_ok=True)


def load(name: str) -> Image.Image:
    im = Image.open(os.path.join(root, f"paquet-{name}.png")).convert("RGBA")
    if name in ALIGN:
        s, dx, dy = ALIGN[name]
        w = round(N * s)
        r = im.resize((w, w), Image.LANCZOS)
        im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); im.paste(r, (round(dx), round(dy)), r)
    # les halos très transparents (contours sales de la découpe) sont supprimés
    a = im.getchannel("A").point(lambda v: 0 if v < 24 else v)
    im.putalpha(a)
    return im


imgs = {n: load(n) for n in ("complet", "corps", "couvercle")}
boxes = [im.getchannel("A").getbbox() for im in imgs.values()]
x0, y0 = max(0, min(b[0] for b in boxes) - MARGIN), max(0, min(b[1] for b in boxes) - MARGIN)
x1, y1 = min(N, max(b[2] for b in boxes) + MARGIN), min(N, max(b[3] for b in boxes) + MARGIN)
w, h = x1 - x0, y1 - y0
for name, im in imgs.items():
    c = im.crop((x0, y0, x1, y1)).resize((OUT_W, round(OUT_W * h / w)), Image.LANCZOS)
    c.save(os.path.join(out, name + ".webp"), "WEBP", quality=88, method=6)
    print(name, c.size, os.path.getsize(os.path.join(out, name + ".webp")) // 1024, "Ko")
print(f"rapport largeur/hauteur : {w / h:.4f} ; jointure couvercle/corps à {(680 - y0) / h * 100:.1f} % de la hauteur")
