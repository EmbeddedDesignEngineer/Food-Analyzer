"""Generate recognizable sample meal images for the Topic 2 dataset.

The PNGs in this folder are ALREADY GENERATED — you do not need to run
this script. It is provided as a reference and a way to regenerate or
extend the sample set.

These are illustrative drawings (NOT photographs) of meals composed from
common ingredients. They have recognizable arranged shapes (rice grains,
grilled chicken, broccoli florets, halved tomatoes, etc.) so visual
inspection isn't misleading, but they are not real food photos.

For real testing, replace these PNGs with actual meal photos. The filenames
hint at the contents so the offline `_OfflineVLM` in `demo_ai.py` can
produce a plausible identification without any real CV.

Requires Pillow (`pip install pillow`). Run from the topic root:
    python data/_make_samples.py
"""

import random
from pathlib import Path
from PIL import Image, ImageDraw

IMG = 320  # canvas size


# --- ingredient drawers ---------------------------------------------------

def _plate(d, cx, cy, r, plate_color=(245, 245, 240)):
    """Draw a circular plate with a soft rim."""
    # shadow
    d.ellipse([cx - r - 4, cy - r + 6, cx + r + 4, cy + r + 10], fill=(220, 215, 205))
    # plate
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=plate_color, outline=(220, 215, 205), width=2)
    # rim
    d.ellipse([cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12],
              outline=(225, 220, 210), width=1)


def draw_rice(d, cx, cy, w=80, h=70):
    """A pile of rice — many small near-white grains."""
    rng = random.Random(cx * 31 + cy * 17)
    # base mound
    d.ellipse([cx - w, cy - h // 2, cx + w, cy + h // 2], fill=(245, 240, 225))
    # individual grains
    for _ in range(80):
        gx = cx + rng.randint(-w + 8, w - 8)
        gy = cy + rng.randint(-h // 2 + 4, h // 2 - 4)
        gw = rng.randint(3, 5)
        gh = rng.randint(2, 3)
        d.ellipse([gx - gw, gy - gh, gx + gw, gy + gh],
                  fill=(255, 250, 235), outline=(220, 210, 190))


def draw_chicken(d, cx, cy, w=70, h=50):
    """Grilled chicken breast — golden-brown oval with grill marks."""
    d.ellipse([cx - w, cy - h, cx + w, cy + h], fill=(180, 130, 70), outline=(120, 80, 40), width=2)
    # darker char highlights
    d.ellipse([cx - w + 10, cy - h + 8, cx + w - 10, cy + h - 8],
              outline=(140, 95, 50), width=1)
    # grill marks
    for off in (-30, -10, 10, 30):
        d.line([(cx + off, cy - h + 8), (cx + off + 6, cy + h - 8)],
               fill=(80, 50, 25), width=2)


def draw_broccoli(d, cx, cy, n=4):
    """A few broccoli florets, clustered."""
    for i in range(n):
        ox = (i - n // 2) * 22 + (i % 2) * 8
        oy = (i % 2) * 14 - 5
        # stalk
        d.rectangle([cx + ox - 4, cy + oy + 2, cx + ox + 4, cy + oy + 18],
                    fill=(200, 220, 160))
        # head (a cluster of tiny circles)
        for jx, jy in ((-8, -6), (0, -10), (8, -6), (-4, 0), (4, 0)):
            d.ellipse([cx + ox + jx - 7, cy + oy + jy - 7,
                       cx + ox + jx + 7, cy + oy + jy + 7],
                      fill=(60, 130, 70), outline=(40, 90, 50))


def draw_salmon(d, cx, cy, w=70, h=45):
    """Grilled salmon fillet — pink-orange with horizontal flake lines."""
    d.polygon([(cx - w, cy), (cx - w + 20, cy - h), (cx + w - 10, cy - h + 5),
               (cx + w, cy), (cx + w - 10, cy + h - 5), (cx - w + 20, cy + h)],
              fill=(220, 130, 95), outline=(170, 80, 60))
    # flake lines
    for off in (-25, -10, 5, 20):
        d.line([(cx + off - 30, cy - h + 12), (cx + off + 30, cy - h + 16)],
               fill=(180, 90, 70), width=1)
        d.line([(cx + off - 30, cy + h - 14), (cx + off + 30, cy + h - 18)],
               fill=(180, 90, 70), width=1)


def draw_potato(d, cx, cy, w=55, h=40):
    """Baked potato — beige oval with skin texture."""
    d.ellipse([cx - w, cy - h, cx + w, cy + h], fill=(200, 165, 120), outline=(140, 105, 70), width=2)
    rng = random.Random(cx * 13 + cy * 7)
    for _ in range(20):
        sx = cx + rng.randint(-w + 8, w - 8)
        sy = cy + rng.randint(-h + 6, h - 6)
        d.ellipse([sx - 2, sy - 1, sx + 2, sy + 1], fill=(150, 110, 75))


def draw_egg(d, cx, cy, r=35):
    """Boiled egg — white oval with yolk circle."""
    d.ellipse([cx - r, cy - r * 0.85, cx + r, cy + r * 0.85],
              fill=(250, 245, 230), outline=(200, 195, 175))
    # yolk
    d.ellipse([cx - 14, cy - 12, cx + 14, cy + 12],
              fill=(245, 200, 80), outline=(210, 160, 60))


def draw_salad(d, cx, cy, w=85, h=50):
    """Mixed greens — overlapping green blobs."""
    rng = random.Random(cx + cy)
    for _ in range(18):
        lx = cx + rng.randint(-w, w)
        ly = cy + rng.randint(-h, h)
        sz = rng.randint(14, 22)
        shade = rng.choice([(110, 165, 70), (80, 140, 60), (140, 180, 90)])
        d.ellipse([lx - sz, ly - sz // 2, lx + sz, ly + sz // 2], fill=shade)


def draw_pasta(d, cx, cy, w=80, h=55):
    """Spaghetti — many curved yellow lines."""
    rng = random.Random(cx)
    # base mound
    d.ellipse([cx - w, cy - h // 2, cx + w, cy + h // 2], fill=(230, 200, 130))
    for _ in range(40):
        sx = cx + rng.randint(-w + 5, w - 5)
        sy = cy + rng.randint(-h // 2, h // 2)
        ex = sx + rng.randint(-30, 30)
        ey = sy + rng.randint(-15, 15)
        d.line([(sx, sy), (ex, ey)], fill=(245, 220, 140), width=2)


def draw_tomato(d, cx, cy, n=3):
    """A few red tomato halves."""
    for i in range(n):
        ox = (i - n // 2) * 28
        d.ellipse([cx + ox - 14, cy - 12, cx + ox + 14, cy + 12],
                  fill=(200, 50, 50), outline=(140, 30, 30), width=1)
        # seeds
        d.ellipse([cx + ox - 4, cy - 3, cx + ox + 4, cy + 3], fill=(240, 220, 180))


def draw_cheese(d, cx, cy, w=55, h=40):
    """Cheddar cube — orange triangle with holes."""
    d.polygon([(cx - w, cy + h), (cx, cy - h), (cx + w, cy + h)],
              fill=(230, 165, 70), outline=(180, 120, 40), width=2)
    # holes
    d.ellipse([cx - 12, cy + 5, cx - 4, cy + 13], fill=(245, 200, 110))
    d.ellipse([cx + 8, cy - 5, cx + 16, cy + 3], fill=(245, 200, 110))


def draw_avocado(d, cx, cy, w=45, h=55):
    """Half avocado — green with brown pit."""
    d.ellipse([cx - w, cy - h, cx + w, cy + h], fill=(140, 170, 80), outline=(80, 110, 50), width=2)
    # inner flesh ring
    d.ellipse([cx - w + 10, cy - h + 12, cx + w - 10, cy + h - 12],
              fill=(180, 200, 110), outline=(140, 170, 80))
    # pit
    d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=(120, 80, 40), outline=(80, 50, 25))


def draw_bread(d, cx, cy, w=70, h=45):
    """A slice of bread — beige square with crust."""
    d.rounded_rectangle([cx - w, cy - h, cx + w, cy + h], radius=18,
                        fill=(220, 180, 120), outline=(150, 110, 70), width=3)
    # interior softer color
    d.rounded_rectangle([cx - w + 10, cy - h + 10, cx + w - 10, cy + h - 10],
                        radius=10, fill=(240, 215, 165))


# --- meal compositions ---------------------------------------------------

def _make(bg=(252, 248, 240)):
    img = Image.new("RGB", (IMG, IMG), bg)
    d = ImageDraw.Draw(img)
    _plate(d, IMG // 2, IMG // 2, 130)
    return img, d


def meal_rice_chicken_broccoli():
    img, d = _make()
    draw_rice(d, 120, 130)
    draw_chicken(d, 200, 180)
    draw_broccoli(d, 110, 210)
    return img


def meal_salmon_potato():
    img, d = _make()
    draw_salmon(d, 130, 140)
    draw_potato(d, 200, 200)
    return img


def meal_pasta_tomato_cheese():
    img, d = _make()
    draw_pasta(d, 160, 140)
    draw_tomato(d, 130, 215)
    draw_cheese(d, 215, 215)
    return img


def meal_egg_avocado_bread():
    img, d = _make()
    draw_bread(d, 120, 140)
    draw_egg(d, 220, 140)
    draw_avocado(d, 160, 215)
    return img


def meal_salad_chicken():
    img, d = _make()
    draw_salad(d, 130, 145)
    draw_chicken(d, 200, 200)
    return img


def meal_rice_egg():
    img, d = _make()
    draw_rice(d, 130, 160)
    draw_egg(d, 215, 160)
    return img


def meal_pasta_chicken():
    img, d = _make()
    draw_pasta(d, 130, 150)
    draw_chicken(d, 210, 195)
    return img


def meal_salad_avocado_tomato():
    img, d = _make()
    draw_salad(d, 130, 140)
    draw_avocado(d, 215, 145)
    draw_tomato(d, 160, 220)
    return img


def meal_salmon_broccoli_rice():
    img, d = _make()
    draw_salmon(d, 130, 140)
    draw_broccoli(d, 215, 145)
    draw_rice(d, 160, 215)
    return img


def meal_potato_egg():
    img, d = _make()
    draw_potato(d, 130, 160)
    draw_egg(d, 215, 160)
    return img


def meal_bread_cheese():
    img, d = _make()
    draw_bread(d, 130, 160)
    draw_cheese(d, 215, 175)
    return img


def meal_broccoli_egg():
    img, d = _make()
    draw_broccoli(d, 130, 160)
    draw_egg(d, 215, 160)
    return img


def meal_rice_chicken():
    img, d = _make()
    draw_rice(d, 130, 160)
    draw_chicken(d, 215, 175)
    return img


def meal_salad_tomato():
    img, d = _make()
    draw_salad(d, 130, 145)
    draw_tomato(d, 200, 215)
    return img


def meal_potato_chicken():
    img, d = _make()
    draw_potato(d, 130, 165)
    draw_chicken(d, 215, 175)
    return img


def no_meal_blue():
    """Not a meal — a blue rectangle (sky/wall photo). Used to test the
    "meal_recognized = False" branch."""
    img = Image.new("RGB", (IMG, IMG), (90, 130, 200))
    d = ImageDraw.Draw(img)
    # add some clouds so it looks intentionally non-meal
    for cx, cy, w in ((80, 100, 50), (200, 80, 60), (250, 180, 40), (60, 220, 45)):
        d.ellipse([cx - w, cy - 18, cx + w, cy + 18], fill=(245, 245, 250))
    return img


SAMPLES = [
    ("rice_chicken_broccoli.png",   meal_rice_chicken_broccoli),
    ("salmon_potato.png",           meal_salmon_potato),
    ("pasta_tomato_cheese.png",     meal_pasta_tomato_cheese),
    ("egg_avocado_bread.png",       meal_egg_avocado_bread),
    ("salad_chicken.png",           meal_salad_chicken),
    ("rice_egg.png",                meal_rice_egg),
    ("pasta_chicken.png",           meal_pasta_chicken),
    ("salad_avocado_tomato.png",    meal_salad_avocado_tomato),
    ("salmon_broccoli_rice.png",    meal_salmon_broccoli_rice),
    ("potato_egg.png",              meal_potato_egg),
    ("bread_cheese.png",            meal_bread_cheese),
    ("broccoli_egg.png",            meal_broccoli_egg),
    ("rice_chicken.png",            meal_rice_chicken),
    ("salad_tomato.png",            meal_salad_tomato),
    ("potato_chicken.png",          meal_potato_chicken),
    ("no_meal_blue.png",            no_meal_blue),
]


def main() -> None:
    root = Path(__file__).parent
    root.mkdir(parents=True, exist_ok=True)
    for name, fn in SAMPLES:
        out = root / name
        img = fn()
        img.save(out, "PNG")
        print(f"wrote {out.relative_to(root.parent)}")


if __name__ == "__main__":
    main()
