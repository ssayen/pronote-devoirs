"""Génère les icônes de la PWA (app/static/icons/) à partir de icone.png (couleurs) et « icone monochrome.png ».

- icon-192 / icon-512 : icône couleur, coins transparents
- maskable-512        : pleine page (fond dégradé prolongé), pour les formes d'icône d'Android
- monochrome-512      : silhouette sur fond transparent (icônes thématiques Material You)
- apple-touch-icon    : opaque, 180 px
- favicon.ico / favicon-32.png : tirés de l'icône couleur
"""
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "icons"
OUT.mkdir(parents=True, exist_ok=True)


def color_icon() -> Image.Image:
    """Les coins noirs du fichier source (RVB) deviennent transparents (remplissage depuis les bords)."""
    im = Image.open(ROOT / "icone.png").convert("RGB")
    w, h = im.size
    px = im.load()
    dark = lambda p: sum(p) < 90
    seen = bytearray(w * h)
    q = deque((x, y) for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] if dark(px[x, y]))
    for x, y in q:
        seen[y * w + x] = 1
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and dark(px[nx, ny]):
                seen[ny * w + nx] = 1
                q.append((nx, ny))
    mask = Image.frombytes("L", (w, h), bytes(255 if not v else 0 for v in seen))
    mask = mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.2))  # ronge le liseré sombre
    im = im.convert("RGBA")
    im.putalpha(mask)
    return im


def maskable(src: Image.Image, size=512) -> Image.Image:
    """Fond = dégradé aux couleurs des quatre coins de l'icône, icône réduite à 80 % au centre (zone de sécurité)."""
    w = src.width
    flat = src.convert("RGB").filter(ImageFilter.GaussianBlur(25))
    k = int(w * .13)
    tl, tr, bl, br = (flat.getpixel(p) for p in ((k, k), (w - k, k), (k, w - k), (w - k, w - k)))
    corners = Image.new("RGB", (2, 2))
    corners.putdata([tl, tr, bl, br])
    bg = corners.resize((size, size), Image.BILINEAR)
    inner = src.resize((int(size * .80),) * 2, Image.LANCZOS)
    bg.paste(inner, ((size - inner.width) // 2,) * 2, inner)
    return bg


def monochrome(size=512) -> Image.Image:
    g = ImageOps.autocontrast(Image.open(ROOT / "icone monochrome.png").convert("L"), cutoff=2)
    alpha = ImageOps.invert(g).point(lambda v: 0 if v < 40 else (255 if v > 215 else int((v - 40) * 255 / 175)))
    inner = alpha.resize((int(size * .72),) * 2, Image.LANCZOS)
    out = Image.new("L", (size, size), 0)
    out.paste(inner, ((size - inner.width) // 2,) * 2)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    img.putalpha(out)
    return img


c = color_icon()
c.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
c.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
m = maskable(c)
m.save(OUT / "maskable-512.png")
m.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
monochrome().save(OUT / "monochrome-512.png")
c.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
c.resize((256, 256), Image.LANCZOS).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
