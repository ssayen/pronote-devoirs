"""Génère les icônes de la PWA (app/static/icons/*.png) : carré arrondi bleu avec un post-it."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
OUT.mkdir(parents=True, exist_ok=True)


def icon(size, maskable=False):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill="#3b82f6")
        k = 0.6  # zone de sécurité
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s // 5, fill="#3b82f6")
        k = 0.7
    w = s * k
    x0 = (s - w) / 2
    for i, c in enumerate(["#ffffff", "#fde68a", "#bbf7d0"]):
        off = (i - 1) * w * 0.07
        d.rounded_rectangle([x0 + off + w * .06, x0 + w * .02 - off * .3, x0 + off + w * .94, x0 + w * .98 - off * .3 - (2 - i) * w * .0],
                            radius=int(w * .06), fill=c)
    # trois lignes de texte sur le premier plan
    for j in range(3):
        y = x0 + w * (.28 + j * .2)
        d.rounded_rectangle([x0 + w * .22, y, x0 + w * (.78 - j * .12), y + w * .06], radius=int(w * .03), fill="#3b82f6")
    return img.resize((size, size), Image.LANCZOS)


for n, sz, m in [("icon-192", 192, False), ("icon-512", 512, False), ("maskable-512", 512, True), ("apple-touch-icon", 180, False)]:
    icon(sz, m).save(OUT / f"{n}.png")
