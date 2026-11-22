"""Street search for the report screen: the citizen types a street or place and picks a suggestion.

Uses OpenStreetMap data through Photon (made for type-ahead search), with Nominatim as a fallback.
Searches are limited to the Prishtina area and cached. Only the typed text is sent; never the
user's location or account.
"""
import logging
import time

import httpx
from fastapi import APIRouter, Depends, Query

from . import schemas
from .auth import current_user
from .models import User

log = logging.getLogger("mendmap")
router = APIRouter(prefix="/geo", tags=["geo"])

CENTER = (42.6629, 21.1655)  # Prishtina
BBOX = (20.98, 42.56, 21.32, 42.74)  # lon/lat box around the municipality
HEADERS = {"User-Agent": "MendMap/1.0 (city street problem reporting app)"}
CACHE_S = 24 * 3600
_cache: dict[str, tuple[float, list[schemas.Place]]] = {}


def _inside(lat: float, lng: float) -> bool:
    return BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lng <= BBOX[2]


async def _photon(client: httpx.AsyncClient, q: str) -> list[schemas.Place]:
    r = await client.get("https://photon.komoot.io/api/", params={
        "q": q, "limit": 10, "lat": CENTER[0], "lon": CENTER[1], "bbox": ",".join(map(str, BBOX)),
    })
    r.raise_for_status()
    out = []
    for f in r.json().get("features", []):
        p, (lng, lat) = f.get("properties", {}), f["geometry"]["coordinates"]
        name = p.get("name") or p.get("street")
        if not name or not _inside(lat, lng):
            continue
        is_street = p.get("osm_key") == "highway"
        street = None if is_street else p.get("street")
        if street and p.get("housenumber"):
            street = f"{street} {p['housenumber']}"
        area = p.get("district") or p.get("locality") or p.get("city")
        out.append(schemas.Place(name=name, detail=", ".join(x for x in (street, area) if x and x != name) or None,
                                 kind="street" if is_street else "place", latitude=lat, longitude=lng))
    return out


async def _nominatim(client: httpx.AsyncClient, q: str) -> list[schemas.Place]:
    r = await client.get("https://nominatim.openstreetmap.org/search", params={
        "q": q, "format": "jsonv2", "limit": 8, "addressdetails": 1, "bounded": 1,
        "viewbox": f"{BBOX[0]},{BBOX[3]},{BBOX[2]},{BBOX[1]}",
    })
    r.raise_for_status()
    out = []
    for p in r.json():
        a = p.get("address", {})
        name = p.get("name") or a.get("road")
        if not name:
            continue
        area = a.get("suburb") or a.get("neighbourhood") or a.get("city")
        out.append(schemas.Place(name=name, detail=area if area != name else None,
                                 kind="street" if p.get("category") == "highway" else "place",
                                 latitude=float(p["lat"]), longitude=float(p["lon"])))
    return out


@router.get("/search", response_model=list[schemas.Place])
async def search(q: str = Query(..., min_length=2, max_length=100), _: User = Depends(current_user)):
    """Streets and places in Prishtina matching what the user typed (best first, at most 6)."""
    key = " ".join(q.lower().split())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    places: list[schemas.Place] = []
    async with httpx.AsyncClient(timeout=6, headers=HEADERS) as client:
        for source in (_photon, _nominatim):
            try:
                places = await source(client, key)
                break
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("Street search via %s failed: %s", source.__name__, exc)
    seen, unique = set(), []
    for p in places:  # one entry per street name + area (long streets come back in pieces)
        k = (p.name.lower(), (p.detail or "").lower())
        if k not in seen:
            seen.add(k)
            unique.append(p)
    unique = unique[:6]
    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = (time.monotonic(), unique)
    return unique
