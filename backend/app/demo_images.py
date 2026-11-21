"""Draws illustrated demo photos for seeded reports (no downloads, no copyrighted images).

Each category gets its own scene: potholes on asphalt, broken streetlights at night,
dumped rubbish, and "other" problems (missing manhole cover, broken bench, bent sign).
A seed makes every image different but reproducible.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 1200, 900


def _noise(rnd: random.Random, base: tuple[int, int, int], sigma: int) -> Image.Image:
    """Textured surface: base colour plus grain."""
    grain = Image.effect_noise((W // 2, H // 2), sigma).resize((W, H)).convert("RGB")
    flat = Image.new("RGB", (W, H), base)
    return ImageChops.add(flat, grain, scale=1.0, offset=-128)


def _vignette(img: Image.Image, strength: float = 0.55) -> Image.Image:
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    for i in range(40):
        t = i / 40
        d.ellipse([-W * 0.25 + t * W * 0.25, -H * 0.3 + t * H * 0.3, W * 1.25 - t * W * 0.25, H * 1.3 - t * H * 0.3],
                  fill=int(255 * (1 - strength) + 255 * strength * t))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(img, dark, mask.filter(ImageFilter.GaussianBlur(60)))


def _blob(rnd: random.Random, cx: float, cy: float, rx: float, ry: float, points: int = 18, jitter: float = 0.25):
    pts = []
    for i in range(points):
        a = 2 * math.pi * i / points
        r = 1 + rnd.uniform(-jitter, jitter)
        pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r))
    return pts


def _crack(d: ImageDraw.ImageDraw, rnd: random.Random, x: float, y: float, length: int, color, width=3):
    for _ in range(length):
        nx, ny = x + rnd.uniform(-28, 28), y + rnd.uniform(-22, 22)
        d.line([(x, y), (nx, ny)], fill=color, width=width)
        x, y = nx, ny


def _asphalt(rnd: random.Random, lane: bool = True) -> Image.Image:
    shade = rnd.randint(68, 92)
    img = _noise(rnd, (shade, shade, shade + 4), 38)
    d = ImageDraw.Draw(img)
    if lane:
        # Perspective lane markings toward a vanishing point.
        vx = W * rnd.uniform(0.4, 0.6)
        for i in range(6):
            y0 = H * (0.15 + i * 0.16)
            y1 = y0 + H * 0.08
            w0, w1 = 4 + i * 4, 6 + i * 4
            x0 = vx + (W * 0.12) * (y0 / H)
            x1 = vx + (W * 0.12) * (y1 / H)
            d.polygon([(x0 - w0, y0), (x0 + w0, y0), (x1 + w1, y1), (x1 - w1, y1)], fill=(222, 220, 205))
        d.line([(0, H * 0.06), (W, H * 0.02)], fill=(150, 150, 145), width=10)  # kerb
    return img


def pothole(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = _asphalt(rnd)
    d = ImageDraw.Draw(img)
    cx, cy = W * rnd.uniform(0.3, 0.65), H * rnd.uniform(0.5, 0.68)
    rx, ry = rnd.uniform(170, 260), rnd.uniform(90, 140)
    d.polygon(_blob(rnd, cx, cy, rx * 1.18, ry * 1.2, jitter=0.18), fill=(58, 56, 54))       # broken edge
    d.polygon(_blob(rnd, cx, cy, rx, ry), fill=(34, 32, 30))                               # hole
    d.polygon(_blob(rnd, cx + 10, cy + 12, rx * 0.72, ry * 0.6, jitter=0.12), fill=(52, 66, 82))  # water
    d.ellipse([cx - rx * 0.35, cy - ry * 0.05, cx + rx * 0.1, cy + ry * 0.12], fill=(120, 140, 165))  # reflection
    for _ in range(rnd.randint(8, 14)):  # loose gravel
        gx, gy = cx + rnd.uniform(-rx * 1.6, rx * 1.6), cy + rnd.uniform(-ry * 1.6, ry * 1.6)
        s = rnd.uniform(4, 11)
        g = rnd.randint(95, 130)
        d.ellipse([gx, gy, gx + s, gy + s * 0.8], fill=(g, g, g - 6))
    for _ in range(4):
        _crack(d, rnd, cx + rnd.uniform(-rx, rx), cy + rnd.uniform(-ry, ry), rnd.randint(6, 12), (40, 40, 40))
    return _vignette(img.filter(ImageFilter.GaussianBlur(1.1)))


def streetlight(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # night sky
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(10 + 20 * t), int(16 + 26 * t), int(38 + 40 * t)))
    for _ in range(rnd.randint(7, 10)):  # buildings with lit windows
        bx, bw = rnd.uniform(-50, W), rnd.uniform(140, 260)
        top = H * rnd.uniform(0.2, 0.5)
        d.rectangle([bx, top, bx + bw, H], fill=(22, 28, 48))
        for wy in range(int(top) + 20, H - 140, 46):
            for wx in range(int(bx) + 16, int(bx + bw) - 20, 38):
                if rnd.random() < 0.35:
                    d.rectangle([wx, wy, wx + 16, wy + 22], fill=(240, 196, 92))
    d.rectangle([0, H * 0.82, W, H], fill=(38, 40, 46))  # pavement
    # A working lamp far away, glowing.
    gx, gy = W * 0.85, H * 0.34
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([gx - 120, gy - 120, gx + 120, gy + 120], fill=150)
    img = Image.composite(Image.new("RGB", (W, H), (250, 210, 120)), img, glow.filter(ImageFilter.GaussianBlur(50)))
    d = ImageDraw.Draw(img)
    d.rectangle([gx - 5, gy, gx + 5, H * 0.82], fill=(70, 74, 84))
    # The broken lamp in front: dark head, cracked glass, tilted.
    px = W * rnd.uniform(0.3, 0.5)
    d.rectangle([px - 14, H * 0.18, px + 14, H * 0.82], fill=(92, 98, 110))
    d.line([(px, H * 0.18), (px + 150, H * 0.13)], fill=(92, 98, 110), width=18)
    hx, hy = px + 150, H * 0.13
    d.polygon([(hx - 70, hy), (hx + 60, hy - 8), (hx + 45, hy + 40), (hx - 55, hy + 46)], fill=(60, 64, 72))
    d.polygon([(hx - 50, hy + 40), (hx + 40, hy + 36), (hx + 25, hy + 62), (hx - 38, hy + 64)], fill=(30, 34, 42))
    _crack(d, rnd, hx - 20, hy + 50, 5, (140, 150, 165), 2)
    for _ in range(14):  # broken glass on the pavement
        sx, sy = px + rnd.uniform(40, 260), H * rnd.uniform(0.84, 0.95)
        d.polygon([(sx, sy), (sx + rnd.uniform(6, 16), sy + 3), (sx + 4, sy + rnd.uniform(6, 12))], fill=(150, 170, 190))
    return _vignette(img.filter(ImageFilter.GaussianBlur(0.8)), 0.4)


def dumping(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = _noise(rnd, (78, 96, 52), 46)  # grass and dirt
    d = ImageDraw.Draw(img)
    for y in range(int(H * 0.35)):  # background wall/sky
        t = y / (H * 0.35)
        d.line([(0, y), (W, y)], fill=(int(150 + 40 * t), int(160 + 30 * t), int(170 + 10 * t)))
    d.rectangle([0, H * 0.26, W, H * 0.38], fill=(150, 140, 128))  # concrete wall
    for x in range(0, W, 120):
        d.line([(x, H * 0.26), (x, H * 0.38)], fill=(120, 112, 100), width=3)
    cx = W * rnd.uniform(0.4, 0.6)
    items = []
    for _ in range(rnd.randint(14, 20)):
        items.append((rnd.uniform(cx - 380, cx + 380), rnd.uniform(H * 0.45, H * 0.85), rnd.choice("bbbbccrt")))
    items.sort(key=lambda i: i[1])
    for x, y, kind in items:
        if kind == "b":  # rubbish bags
            col = rnd.choice([(24, 24, 28), (30, 32, 40), (36, 70, 140), (40, 40, 44)])
            r = rnd.uniform(55, 95)
            d.polygon(_blob(rnd, x, y, r, r * 0.8, jitter=0.15), fill=col)
            d.ellipse([x - r * 0.4, y - r * 0.6, x - r * 0.1, y - r * 0.4], fill=tuple(min(255, c + 50) for c in col))
            d.polygon([(x - 10, y - r * 0.8), (x + 10, y - r * 0.8), (x, y - r * 1.05)], fill=col)
        elif kind == "c":  # cardboard boxes
            w, h = rnd.uniform(90, 150), rnd.uniform(70, 110)
            d.polygon([(x, y), (x + w, y - 10), (x + w, y + h - 10), (x, y + h)], fill=(176, 130, 78))
            d.polygon([(x, y), (x + w, y - 10), (x + w - 20, y - 34), (x - 18, y - 24)], fill=(200, 156, 100))
            d.line([(x + w / 2, y - 5), (x + w / 2, y + h - 5)], fill=(150, 110, 60), width=4)
        elif kind == "r":  # rubble
            for _ in range(5):
                g = rnd.randint(120, 175)
                d.polygon(_blob(rnd, x + rnd.uniform(-40, 40), y + rnd.uniform(-20, 20), rnd.uniform(18, 34), rnd.uniform(14, 24), 7, 0.4), fill=(g, g - 6, g - 14))
        else:  # old tyre
            d.ellipse([x - 70, y - 40, x + 70, y + 40], fill=(22, 22, 22))
            d.ellipse([x - 32, y - 18, x + 32, y + 18], fill=(70, 86, 46))
    return _vignette(img.filter(ImageFilter.GaussianBlur(0.9)))


def other(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    kind = seed % 3
    if kind == 0:  # missing manhole cover with a warning cone
        img = _asphalt(rnd, lane=False)
        d = ImageDraw.Draw(img)
        cx, cy = W * 0.5, H * 0.6
        d.ellipse([cx - 210, cy - 120, cx + 210, cy + 120], fill=(110, 110, 112))
        d.ellipse([cx - 180, cy - 100, cx + 180, cy + 100], fill=(12, 12, 14))
        d.ellipse([cx - 150, cy - 60, cx + 150, cy + 100], fill=(4, 4, 6))
        bx = cx + 260
        d.polygon([(bx, cy - 230), (bx - 70, cy + 40), (bx + 70, cy + 40)], fill=(242, 106, 46))
        d.polygon([(bx - 24, cy - 140), (bx + 24, cy - 140), (bx + 38, cy - 80), (bx - 38, cy - 80)], fill=(245, 245, 240))
        d.rectangle([bx - 95, cy + 40, bx + 95, cy + 62], fill=(220, 90, 36))
    elif kind == 1:  # broken park bench
        img = _noise(rnd, (90, 112, 64), 40)
        d = ImageDraw.Draw(img)
        d.rectangle([0, H * 0.62, W, H], fill=(150, 140, 120))  # paved path
        x0, y0 = W * 0.2, H * 0.45
        for leg in (x0 + 40, x0 + 640):
            d.rectangle([leg, y0 + 40, leg + 24, y0 + 260], fill=(50, 52, 58))
        for i, y in enumerate((y0 - 120, y0 - 70, y0 + 20, y0 + 60)):
            if i == 1:  # snapped slat hanging down
                d.polygon([(x0, y), (x0 + 330, y + 6), (x0 + 330, y + 30), (x0, y + 26)], fill=(140, 92, 52))
                d.polygon([(x0 + 360, y + 30), (x0 + 700, y + 160), (x0 + 690, y + 186), (x0 + 350, y + 56)], fill=(122, 80, 44))
            else:
                d.rectangle([x0, y, x0 + 700, y + 28], fill=(150, 100, 58))
        for _ in range(10):  # splinters
            sx, sy = x0 + rnd.uniform(300, 700), H * rnd.uniform(0.72, 0.9)
            d.line([(sx, sy), (sx + rnd.uniform(10, 40), sy + rnd.uniform(-6, 6))], fill=(130, 86, 48), width=5)
    else:  # bent traffic sign
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(130 + 60 * t), int(170 + 40 * t), int(215 + 20 * t)))
        d.rectangle([0, H * 0.7, W, H], fill=(96, 96, 100))
        px = W * 0.45
        d.line([(px, H * 0.95), (px + 20, H * 0.55), (px + 190, H * 0.3)], fill=(150, 154, 160), width=22)
        sx, sy = px + 200, H * 0.26
        d.polygon([(sx, sy - 130), (sx + 120, sy + 80), (sx - 120, sy + 80)], fill=(230, 40, 40))
        d.polygon([(sx, sy - 85), (sx + 78, sy + 55), (sx - 78, sy + 55)], fill=(250, 250, 250))
        d.text((sx - 6, sy - 10), "!", fill=(20, 20, 20))
    return _vignette(img.filter(ImageFilter.GaussianBlur(1.0)), 0.45)


def _sidewalk(rnd: random.Random) -> Image.Image:
    """Pavement with a kerb and road, seen from the side of the street."""
    img = _noise(rnd, (176, 172, 164), 30)  # paving
    d = ImageDraw.Draw(img)
    for y in range(int(H * 0.08), int(H * 0.6), 70):  # paving joints
        d.line([(0, y), (W, y + 12)], fill=(150, 146, 138), width=3)
    road = _noise(rnd, (78, 78, 82), 34).crop((0, 0, W, int(H * 0.38)))
    img.paste(road, (0, int(H * 0.62)))
    d.rectangle([0, H * 0.6, W, H * 0.64], fill=(206, 204, 196))  # kerb edge
    return img


def _ramp(d: ImageDraw.ImageDraw, rx: float, shade: int) -> None:
    d.polygon([(rx - 130, H * 0.6), (rx + 130, H * 0.6), (rx + 90, H * 0.42), (rx - 90, H * 0.42)], fill=(shade, shade - 4, shade - 12))
    for i in range(6):  # tactile strip
        d.line([(rx - 80 + i * 32, H * 0.55), (rx - 80 + i * 32, H * 0.59)], fill=(230, 192, 56), width=10)


def accessibility(seed: int) -> Image.Image:
    """Blocked sidewalk: a car parked across the curb ramp, or a broken ramp."""
    rnd = random.Random(seed)
    img = _sidewalk(rnd)
    d = ImageDraw.Draw(img)
    rx = W * rnd.uniform(0.35, 0.55)
    _ramp(d, rx, 196)
    if seed % 2 == 0:  # car parked on the ramp
        cx, cy = rx + 40, H * 0.47
        col = rnd.choice([(150, 30, 34), (40, 60, 110), (200, 200, 205), (30, 30, 34)])
        d.rounded_rectangle([cx - 330, cy - 90, cx + 330, cy + 80], 40, fill=col)
        d.rounded_rectangle([cx - 190, cy - 190, cx + 170, cy - 70], 40, fill=tuple(max(0, c - 30) for c in col))
        d.rectangle([cx - 160, cy - 170, cx - 20, cy - 90], fill=(120, 150, 180))
        d.rectangle([cx + 10, cy - 170, cx + 140, cy - 90], fill=(120, 150, 180))
        for wx in (cx - 220, cx + 220):
            d.ellipse([wx - 70, cy + 20, wx + 70, cy + 160], fill=(20, 20, 22))
            d.ellipse([wx - 30, cy + 60, wx + 30, cy + 120], fill=(140, 140, 146))
    else:  # ramp broken into slabs
        d.polygon(_blob(rnd, rx, H * 0.5, 120, 40, 9, 0.35), fill=(110, 106, 100))
        for _ in range(5):
            _crack(d, rnd, rx + rnd.uniform(-100, 100), H * rnd.uniform(0.44, 0.58), 6, (90, 86, 80), 4)
        d.rectangle([rx - 140, H * 0.58, rx + 140, H * 0.62], fill=(120, 118, 112))
    return _vignette(img.filter(ImageFilter.GaussianBlur(0.9)), 0.4)


DRAW = {"pothole": pothole, "streetlight": streetlight, "dumping": dumping, "other": other, "accessibility": accessibility}


# ---------- "after" photos: the same kind of place, mended ----------

def _sky(d: ImageDraw.ImageDraw) -> None:
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(130 + 60 * t), int(170 + 40 * t), int(215 + 20 * t)))


def _after(icon: str, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    if icon == "pothole":  # fresh asphalt patch
        img = _asphalt(rnd)
        d = ImageDraw.Draw(img)
        cx, cy = W * rnd.uniform(0.3, 0.65), H * rnd.uniform(0.5, 0.68)
        d.rectangle([cx - 260, cy - 150, cx + 260, cy + 150], fill=(44, 44, 48), outline=(30, 30, 32), width=6)
        return _vignette(img.filter(ImageFilter.GaussianBlur(1.0)))
    if icon == "streetlight":  # the lamp works again
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(10 + 20 * t), int(16 + 26 * t), int(38 + 40 * t)))
        d.rectangle([0, H * 0.82, W, H], fill=(52, 50, 48))
        px = W * rnd.uniform(0.3, 0.5)
        hx, hy = px + 150, H * 0.13
        glow = Image.new("L", (W, H), 0)
        g = ImageDraw.Draw(glow)
        g.polygon([(hx - 40, hy + 40), (hx + 40, hy + 40), (hx + 320, H * 0.95), (hx - 320, H * 0.95)], fill=110)
        g.ellipse([hx - 110, hy - 70, hx + 110, hy + 140], fill=200)
        img = Image.composite(Image.new("RGB", (W, H), (255, 222, 150)), img, glow.filter(ImageFilter.GaussianBlur(45)))
        d = ImageDraw.Draw(img)
        d.rectangle([px - 14, H * 0.18, px + 14, H * 0.82], fill=(92, 98, 110))
        d.line([(px, H * 0.18), (hx, hy)], fill=(92, 98, 110), width=18)
        d.polygon([(hx - 70, hy), (hx + 60, hy - 8), (hx + 45, hy + 40), (hx - 55, hy + 46)], fill=(70, 74, 84))
        d.polygon([(hx - 50, hy + 40), (hx + 40, hy + 36), (hx + 25, hy + 62), (hx - 38, hy + 64)], fill=(255, 240, 200))
        return _vignette(img.filter(ImageFilter.GaussianBlur(0.8)), 0.35)
    if icon == "dumping":  # cleared, with a proper bin
        img = _noise(rnd, (82, 108, 56), 40)
        d = ImageDraw.Draw(img)
        for y in range(int(H * 0.35)):
            t = y / (H * 0.35)
            d.line([(0, y), (W, y)], fill=(int(150 + 40 * t), int(160 + 30 * t), int(170 + 10 * t)))
        d.rectangle([0, H * 0.26, W, H * 0.38], fill=(150, 140, 128))
        bx = W * 0.7
        d.rounded_rectangle([bx, H * 0.42, bx + 200, H * 0.72], 14, fill=(40, 110, 70))
        d.rectangle([bx - 10, H * 0.4, bx + 210, H * 0.45], fill=(30, 90, 56))
        return _vignette(img.filter(ImageFilter.GaussianBlur(0.9)))
    if icon == "accessibility":  # clear ramp, bollards keep cars off
        img = _sidewalk(rnd)
        d = ImageDraw.Draw(img)
        rx = W * rnd.uniform(0.35, 0.55)
        _ramp(d, rx, 214)
        for bx in (rx - 200, rx + 200):
            d.rounded_rectangle([bx - 14, H * 0.3, bx + 14, H * 0.6], 10, fill=(60, 62, 70))
        return _vignette(img.filter(ImageFilter.GaussianBlur(0.9)), 0.4)
    kind = seed % 3  # other: same variants as other()
    if kind == 0:  # manhole cover back in place
        img = _asphalt(rnd, lane=False)
        d = ImageDraw.Draw(img)
        cx, cy = W * 0.5, H * 0.6
        d.ellipse([cx - 210, cy - 120, cx + 210, cy + 120], fill=(110, 110, 112))
        d.ellipse([cx - 180, cy - 100, cx + 180, cy + 100], fill=(70, 72, 76))
        for i in range(-4, 5):
            d.line([(cx - 150, cy + i * 20), (cx + 150, cy + i * 20)], fill=(58, 60, 64), width=5)
    elif kind == 1:  # repaired bench
        img = _noise(rnd, (90, 112, 64), 40)
        d = ImageDraw.Draw(img)
        d.rectangle([0, H * 0.62, W, H], fill=(150, 140, 120))
        x0, y0 = W * 0.2, H * 0.45
        for leg in (x0 + 40, x0 + 640):
            d.rectangle([leg, y0 + 40, leg + 24, y0 + 260], fill=(50, 52, 58))
        for y in (y0 - 120, y0 - 70, y0 + 20, y0 + 60):
            d.rectangle([x0, y, x0 + 700, y + 28], fill=(176, 118, 66))
    else:  # straight sign
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        _sky(d)
        d.rectangle([0, H * 0.7, W, H], fill=(96, 96, 100))
        px = W * 0.5
        d.line([(px, H * 0.95), (px, H * 0.3)], fill=(150, 154, 160), width=22)
        sx, sy = px, H * 0.22
        d.polygon([(sx, sy - 130), (sx + 120, sy + 80), (sx - 120, sy + 80)], fill=(230, 40, 40))
        d.polygon([(sx, sy - 85), (sx + 78, sy + 55), (sx - 78, sy + 55)], fill=(250, 250, 250))
    return _vignette(img.filter(ImageFilter.GaussianBlur(1.0)), 0.45)


def make_photo(icon: str, seed: int, folder: Path) -> str:
    """Draws a photo for the category icon and returns its /uploads/... URL."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"demo-{icon}-{seed}.jpg"
    DRAW.get(icon, other)(seed).save(folder / name, "JPEG", quality=84)
    return f"/uploads/{name}"


def make_after_photo(icon: str, seed: int, folder: Path) -> str:
    """The "after" photo of a fixed demo report."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"demo-after-{icon}-{seed}.jpg"
    _after(icon, seed).save(folder / name, "JPEG", quality=84)
    return f"/uploads/{name}"

