"""Photo fingerprints (difference hash) to catch the same photo being sent twice.

A dHash survives resizing, recompression and small edits, so a photo saved from the web, a
screenshot of another report, or the "before" photo sent again as the "after" photo all match.
"""
import io

from PIL import Image

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
