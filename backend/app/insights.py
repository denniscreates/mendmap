"""Computed insights: neighbourhood, priority score, badges and crew route order.

Nothing here is stored: it is worked out from the reports each time, so it stays
correct when a report changes. The neighbourhood centres and points of interest are
approximate demo data for Prishtina; a real city would load them from its GIS.
"""
import math
from datetime import datetime, timedelta

from .models import Report, now

ALERT_RADIUS_M = 500
POI_RADIUS_M = 150


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Approximate centres of Prishtina neighbourhoods (lat, lng).
NEIGHBOURHOODS = {
    "Qendra": (42.6620, 21.1635),
    "Dardania": (42.6475, 21.1555),
    "Ulpiana": (42.6510, 21.1700),
    "Bregu i Diellit": (42.6550, 21.1795),
    "Arbëria": (42.6700, 21.1495),
    "Kalabria": (42.6415, 21.1495),
    "Lakrishte": (42.6515, 21.1470),
    "Mati 1": (42.6635, 21.1735),
    "Tophane": (42.6690, 21.1640),
    "Sofali": (42.6705, 21.1770),
    "Gërmia": (42.6720, 21.1880),
}


def neighbourhood(lat: float, lng: float) -> str | None:
    name, (nlat, nlng) = min(NEIGHBOURHOODS.items(), key=lambda kv: distance_m(lat, lng, *kv[1]))
    return name if distance_m(lat, lng, nlat, nlng) < 2500 else None


# Places where a problem matters more (approximate demo points).
POIS = [
    ("school", 42.6602, 21.1610), ("school", 42.6488, 21.1548), ("school", 42.6540, 21.1785),
    ("school", 42.6515, 21.1712), ("school", 42.6698, 21.1505),
    ("hospital", 42.6480, 21.1630),
    ("bus_stop", 42.6470, 21.1556), ("bus_stop", 42.6596, 21.1626), ("bus_stop", 42.6512, 21.1490),
    ("bus_stop", 42.6638, 21.1590), ("bus_stop", 42.6707, 21.1848),
]


def priority(r: Report, at: datetime | None = None) -> tuple[int, list[str]]:
    """0-100 score: how urgently the city should fix this. Fixed reports score 0.

    Severity (up to 50) + confirmations (up to 20) + age (up to 15) + near a school,
    hospital or bus stop (up to 15). Accessibility problems get +5.
    """
    if r.status == "fixed":
        return 0, []
    reasons: list[str] = []
    sev = r.severity or 3
    score = sev * 10
    if sev >= 4:
        reasons.append("severe")
    score += min(20, r.confirmations * 2)
    if r.confirmations >= 5:
        reasons.append("many_confirmations")
    days = ((at or now()) - r.created_at).total_seconds() / 86400
    score += min(15, int(days * 1.5))
    if days >= 7:
        reasons.append("waiting_long")
    near = {kind for kind, lat, lng in POIS if distance_m(r.latitude, r.longitude, lat, lng) <= POI_RADIUS_M}
    if "school" in near or "hospital" in near:
        score += 15
        reasons.append("near_school" if "school" in near else "near_hospital")
    elif "bus_stop" in near:
        score += 8
        reasons.append("near_bus_stop")
    if r.category and r.category.icon == "accessibility":
        score += 5
        reasons.append("accessibility")
    return min(100, score), reasons


# Problems a resident can safely fix themselves (clearing rubbish, moving an obstacle off a ramp).
# Potholes and streetlights need the city's tools and electrical work, so they stay with the crew.
NEIGHBOUR_FIXABLE = {"dumping", "accessibility", "other"}
MAX_ACTIVE_CLAIMS = 3
REWARD_EVERY = 20  # verified fixes (fixer badges) per reward
REWARD_EUR = 10
CLAIM_HOURS = 48  # a taken job goes back to the map if no after photo arrives in time

# Fixer levels by verified fixes (badges): (minimum badges, key)
LEVELS = [(0, "starter"), (1, "helper"), (5, "fixer"), (10, "hero"), (20, "legend")]


def level(badges_: int) -> tuple[str, int | None]:
    """The fixer's level and the badge count that reaches the next one (None at the top)."""
    current, nxt = LEVELS[0][1], None
    for need, key in LEVELS:
        if badges_ >= need:
            current = key
        elif nxt is None:
            nxt = need
    return current, nxt


def flag_list(r: Report) -> list[str]:
    return [f for f in (r.ai_flags or "").split(",") if f]


def is_flagged(r: Report) -> bool:
    """The AI or the fingerprint check found something off, and no official has cleared it."""
    return bool(flag_list(r)) and not r.flag_cleared


def neighbour_ok(r: Report) -> bool:
    """The AI's safety verdict when it has checked the photo; otherwise only the safe categories.
    Never for a flagged report: a fake or reused photo shouldn't earn anyone a reward."""
    if is_flagged(r):
        return False
    if r.ai_neighbour_safe is not None:
        return bool(r.ai_neighbour_safe) and r.ai_is_problem != 0
    return bool(r.category and r.category.icon in NEIGHBOUR_FIXABLE)


def enrich(out, r: Report):
    """Fills the computed fields of a ReportOut/ReportDetail."""
    out.priority, out.priority_reasons = priority(r)
    out.neighbourhood = neighbourhood(r.latitude, r.longitude)
    out.neighbour_fixable = neighbour_ok(r)
    out.flagged = is_flagged(r)
    out.ai_flags = [f.split(":")[0] for f in flag_list(r)]
    reused = next((f for f in flag_list(r) if f.startswith("reused_photo:")), None)
    out.reused_from = int(reused.split(":")[1]) if reused and reused.split(":")[1].isdigit() else None
    out.flag_cleared = bool(r.flag_cleared)
    claimer = r.claimer if r.claimed_by else None
    out.claimed_by_name = claimer.name.split(" ")[0] if claimer else None
    if r.claimed_by and r.claimed_at and r.status == "in_progress" and not r.fix_status:
        out.claim_deadline = r.claimed_at + timedelta(hours=CLAIM_HOURS)
    return out


# ---------- badges ----------
BADGES = [  # key, goal
    ("first_report", 1),
    ("reporter_5", 5),
    ("mended", 1),
    ("confirmer", 3),
    ("accessibility", 1),
    ("local_hero", 3),
]


def badges(my_reports: list[Report], confirmations_given: int) -> list[dict]:
    per_area: dict[str, int] = {}
    for r in my_reports:
        area = neighbourhood(r.latitude, r.longitude)
        if area:
            per_area[area] = per_area.get(area, 0) + 1
    progress = {
        "first_report": len(my_reports),
        "reporter_5": len(my_reports),
        "mended": sum(r.status == "fixed" for r in my_reports),
        "confirmer": confirmations_given,
        "accessibility": sum(bool(r.category and r.category.icon == "accessibility") for r in my_reports),
        "local_hero": max(per_area.values(), default=0),
    }
    return [{"key": k, "goal": g, "progress": min(progress[k], g), "earned": progress[k] >= g} for k, g in BADGES]


# ---------- crew route ----------
def route_order(start: tuple[float, float] | None, reports: list[Report]) -> list[tuple[Report, float | None]]:
    """Nearest-neighbour route from the crew's position: good enough for a day's list of jobs."""
    left = list(reports)
    if not left:
        return []
    out: list[tuple[Report, float | None]] = []
    if start is None:  # no GPS: start at the highest-priority job
        left.sort(key=lambda r: -priority(r)[0])
        cur = left.pop(0)
        out.append((cur, None))
        pos = (cur.latitude, cur.longitude)
    else:
        pos = start
    while left:
        nxt = min(left, key=lambda r: distance_m(pos[0], pos[1], r.latitude, r.longitude))
        out.append((nxt, round(distance_m(pos[0], pos[1], nxt.latitude, nxt.longitude), 1)))
        left.remove(nxt)
        pos = (nxt.latitude, nxt.longitude)
    return out
