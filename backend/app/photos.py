"""Photo fingerprints (difference hash) to catch the same photo being sent twice.

A dHash survives resizing, recompression and small edits, so a photo saved from the web, a
screenshot of another report, or the "before" photo sent again as the "after" photo all match.
"""
import io

from PIL import Image, ImageFilter

SAME_PHOTO_MAX_BITS = 6  # out of 64: at or below this, it's the same picture


def fingerprint(data: bytes) -> str | None:
    """16-hex-digit dHash of an image, or None if it isn't an image."""
    try:
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    except Exception:
        return None
    px = list(img.getdata())
    if max(px) - min(px) < 8:  # a blank picture has no fingerprint worth comparing
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return f"{bits:016x}"


def distance(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 64
    return (int(a, 16) ^ int(b, 16)).bit_count()


def same(a: str | None, b: str | None) -> bool:
    return distance(a, b) <= SAME_PHOTO_MAX_BITS


def blur(data: bytes, boxes: list[dict]) -> bytes | None:
    """Blur faces and number plates. boxes use [ymin, xmin, ymax, xmax] on a 0-1000 scale of the stored
    pixels (the AI sees the same pixels, before any EXIF rotation). Returns None if there's nothing to do."""
    if not boxes:
        return None
    try:
        src = Image.open(io.BytesIO(data))
        fmt = "PNG" if src.format == "PNG" else "JPEG"
        exif = src.info.get("exif")
        img = src.convert("RGB")
    except Exception:
        return None
    w, h = img.size
    for b in boxes:
        y0, x0, y1, x1 = b["box"]
        bw, bh = (x1 - x0) * w / 1000, (y1 - y0) * h / 1000
        pad = 0.15  # a little extra around the box, so nothing peeks out
        left, top = max(0, int(x0 * w / 1000 - bw * pad)), max(0, int(y0 * h / 1000 - bh * pad))
        right, bottom = min(w, int(x1 * w / 1000 + bw * pad)), min(h, int(y1 * h / 1000 + bh * pad))
        if right - left < 2 or bottom - top < 2:
            continue
        region = img.crop((left, top, right, bottom))
        # Pixelate, then soften: unreadable, but still looks like part of the photo.
        small = region.resize((max(1, (right - left) // 14), max(1, (bottom - top) // 14)), Image.Resampling.BILINEAR)
        region = small.resize(region.size, Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(max(2, (right - left) // 30)))
        img.paste(region, (left, top))
    out = io.BytesIO()
    if fmt == "PNG":
        img.save(out, "PNG")
    else:
        img.save(out, "JPEG", quality=90, **({"exif": exif} if exif else {}))
    return out.getvalue()
