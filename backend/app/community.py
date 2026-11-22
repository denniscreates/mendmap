"""Neighbours working together: clean-up days, adopted streets, the monthly top 10 and the city's weekly summary.

- Clean-up days ("aksion"): anyone can organise one in their neighbourhood (or the whole city). It shows up in that
  chat room, residents get a push, people tap "I'm coming", everyone going gets a reminder the day before, and after
  it the organiser ticks who came: each of them earns a badge (spendable on partner rewards like fixes).
- Adopt a street: a resident, school or business looks after a street and hears about every new problem on it.
- Top 10: the open problems most neighbours confirmed ("I see this too") this month.
- Weekly summary for the city team, written by the AI from the numbers.
"""
import asyncio
import logging
import re
import time
import unicodedata
from datetime import timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai, mailer, schemas
from .auth import admin_user, current_user
from .chat import CITY, _room, post_message, residents
from .db import SessionLocal, get_db
from .insights import distance_m, neighbourhood
from .models import CleanupEvent, EventRsvp, Report, StatusUpdate, StreetAdoption, User, now
from .push import send_many

log = logging.getLogger("mendmap")
router = APIRouter(tags=["community"])

MAX_DAYS_AHEAD = 60
MAX_UPCOMING_PER_USER = 3
ATTENDANCE_DAYS = 7  # the organiser can tick who came up to a week after
MAX_STREETS = 5
REPEAT_RADIUS_M = 40
REPEAT_DAYS = 90
WAITING_LONG_DAYS = 10


# ---------- clean-up days ----------
def _event_out(db: Session, e: CleanupEvent, me: User, with_people: bool = False) -> schemas.EventOut:
    rsvps = db.scalars(select(EventRsvp).where(EventRsvp.event_id == e.id).order_by(EventRsvp.created_at)).all()
    mine = e.created_by == me.id
    show = with_people and (mine or me.role == "admin")
    return schemas.EventOut(
        id=e.id, room=e.room, title=e.title, details=e.details, starts_at=e.starts_at, place=e.place,
        latitude=e.latitude, longitude=e.longitude, organiser_id=e.created_by, organiser_name=e.organiser.name,
        going=len(rsvps), me_going=any(r.user_id == me.id for r in rsvps), mine=mine, cancelled=bool(e.cancelled),
        done=bool(e.done), past=e.starts_at <= now(),
        people=[schemas.EventPerson(user_id=r.user_id, name=r.user.name, attended=bool(r.attended)) for r in rsvps] if show else [],
    )


def _event(db: Session, event_id: int) -> CleanupEvent:
    e = db.get(CleanupEvent, event_id)
    if e is None:
        raise HTTPException(404, "Clean-up day not found")
    return e


def event_badges(db: Session, user_id: int) -> int:
    """Badges from clean-up days: one per day you came to, plus one per day you organised that 3+ people came to."""
    came = db.scalar(select(func.count()).select_from(EventRsvp).where(EventRsvp.user_id == user_id, EventRsvp.attended == 1)) or 0
    organised = db.execute(
        select(CleanupEvent.id).join(EventRsvp, EventRsvp.event_id == CleanupEvent.id)
        .where(CleanupEvent.created_by == user_id, EventRsvp.attended == 1, EventRsvp.user_id != user_id)
        .group_by(CleanupEvent.id).having(func.count() >= 3)
    ).all()
    return came + len(organised)


@router.get("/events", response_model=list[schemas.EventOut])
def list_events(room: str | None = None, past: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Upcoming clean-up days (soonest first), or past ones (latest first)."""
    q = select(CleanupEvent)
    if room:
        q = q.where(CleanupEvent.room == _room(room))
    cutoff = now() - timedelta(hours=3)  # still listed while it's happening
    if past:
        q = q.where(CleanupEvent.starts_at < cutoff).order_by(CleanupEvent.starts_at.desc()).limit(30)
    else:
        q = q.where(CleanupEvent.starts_at >= cutoff, CleanupEvent.cancelled == 0).order_by(CleanupEvent.starts_at)
    return [_event_out(db, e, user) for e in db.scalars(q)]


@router.get("/events/{event_id}", response_model=schemas.EventOut)
def get_event(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _event_out(db, _event(db, event_id), user, with_people=True)


@router.post("/events", response_model=schemas.EventOut, status_code=201)
def create_event(body: schemas.EventIn, tasks: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "crew":
        raise HTTPException(403, "Crew accounts can't organise clean-up days")
    room = _room(body.room)
    starts = body.starts_at  # stored as UTC without a time zone, like every other time here
    if starts.tzinfo is not None:
        starts = starts.astimezone(timezone.utc).replace(tzinfo=None)
    if starts <= now() + timedelta(minutes=30):
        raise HTTPException(422, "Pick a time later than now")
    if starts > now() + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(422, "Pick a day within the next 2 months")
    upcoming = db.scalar(select(func.count()).select_from(CleanupEvent).where(
        CleanupEvent.created_by == user.id, CleanupEvent.cancelled == 0, CleanupEvent.starts_at > now())) or 0
    if upcoming >= MAX_UPCOMING_PER_USER:
        raise HTTPException(429, "You already have 3 clean-up days planned")
    e = CleanupEvent(room=room, title=body.title.strip(), details=(body.details or "").strip() or None, starts_at=starts,
                     place=body.place.strip(), latitude=body.latitude, longitude=body.longitude, created_by=user.id)
    db.add(e)
    db.flush()
    db.add(EventRsvp(event_id=e.id, user_id=user.id))  # the organiser is going
    post_message(db, room, user, e.title, kind="event", event_id=e.id)
    db.commit()
    tokens = [t for t in residents(db, room) if t != user.push_token]
    tasks.add_task(send_many, tokens, f"🧹 {e.title}", f"{e.place} · {user.name.split(' ')[0]} is organising a clean-up day",
                   {"screen": "event", "id": e.id})
    return _event_out(db, e, user, with_people=True)


@router.post("/events/{event_id}/rsvp", response_model=schemas.EventOut)
def rsvp(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _event(db, event_id)
    if e.cancelled:
        raise HTTPException(409, "This clean-up day was cancelled")
    if e.starts_at <= now():
        raise HTTPException(409, "This clean-up day has already started")
    if db.get(EventRsvp, (e.id, user.id)) is None:
        db.add(EventRsvp(event_id=e.id, user_id=user.id))
        db.commit()
    return _event_out(db, e, user, with_people=True)


@router.delete("/events/{event_id}/rsvp", response_model=schemas.EventOut)
def un_rsvp(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _event(db, event_id)
    if e.created_by == user.id:
        raise HTTPException(409, "You're the organiser. Cancel the clean-up day instead.")
    r = db.get(EventRsvp, (e.id, user.id))
    if r is not None and e.starts_at > now():
        db.delete(r)
        db.commit()
    return _event_out(db, e, user, with_people=True)


@router.post("/events/{event_id}/attendance", response_model=schemas.EventOut)
def attendance(event_id: int, body: schemas.AttendanceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """After the clean-up day the organiser ticks who came. Each of them earns a badge."""
    e = _event(db, event_id)
    if e.created_by != user.id and user.role != "admin":
        raise HTTPException(403, "Only the organiser can confirm who came")
    if e.cancelled:
        raise HTTPException(409, "This clean-up day was cancelled")
    if e.starts_at > now():
        raise HTTPException(409, "You can confirm who came once the clean-up day has started")
    if e.starts_at < now() - timedelta(days=ATTENDANCE_DAYS):
        raise HTTPException(409, "It's too late to change who came")
    came = set(body.user_ids)
    for r in db.scalars(select(EventRsvp).where(EventRsvp.event_id == e.id)):
        r.attended = 1 if r.user_id in came else 0
    e.done = 1
    db.commit()
    return _event_out(db, e, user, with_people=True)


@router.delete("/events/{event_id}", response_model=schemas.EventOut)
def cancel_event(event_id: int, tasks: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _event(db, event_id)
    if e.created_by != user.id and user.role != "admin":
        raise HTTPException(403, "Only the organiser can cancel it")
    if e.starts_at <= now():
        raise HTTPException(409, "This clean-up day has already started")
    e.cancelled = 1
    db.commit()
    tokens = [r.user.push_token for r in db.scalars(select(EventRsvp).where(EventRsvp.event_id == e.id))
              if r.user_id != e.created_by and r.user.push_token]
    tasks.add_task(send_many, tokens, f"❌ {e.title}", "This clean-up day was cancelled.", {"screen": "event", "id": e.id})
    return _event_out(db, e, user, with_people=True)


async def send_reminders() -> int:
    """The day-before reminder for everyone going. Returns how many clean-up days were reminded."""
    with SessionLocal() as db:
        due = db.scalars(select(CleanupEvent).where(
            CleanupEvent.cancelled == 0, CleanupEvent.reminded == 0,
            CleanupEvent.starts_at > now(), CleanupEvent.starts_at <= now() + timedelta(hours=24))).all()
        jobs = []
        for e in due:
            tokens = [r.user.push_token for r in db.scalars(select(EventRsvp).where(EventRsvp.event_id == e.id)) if r.user.push_token]
            jobs.append((tokens, f"🧹 Tomorrow: {e.title}" if e.starts_at - now() > timedelta(hours=6) else f"🧹 Soon: {e.title}",
                         f"Meet at {e.place}. Bring gloves!", {"screen": "event", "id": e.id}))
            e.reminded = 1
        db.commit()
    for job in jobs:
        await send_many(*job)
    return len(jobs)


async def reminder_loop() -> None:
    while True:
        try:
            await send_reminders()
        except Exception as exc:  # never let the loop die
            log.warning("Clean-up reminders failed: %s", exc)
        await asyncio.sleep(600)


# ---------- adopt a street ----------
_PREFIX = re.compile(r"^(rruga|rr\.?|bulevardi|bul\.?|sheshi|street|st\.?)\s+")


def street_key(name: str | None) -> str:
    """ "Rr. Agim Ramadani 12" and "agim ramadani" are the same street."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name.split(",")[0]).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = " ".join(s.split())
    s = _PREFIX.sub("", s)
    s = re.sub(r"\s+\d+[a-z]?$", "", s)  # house number
    return s.strip()


def adopters_for(db: Session, address: str | None) -> list[StreetAdoption]:
    key = street_key(address)
    return list(db.scalars(select(StreetAdoption).where(StreetAdoption.key == key))) if key else []


def adopter_names(db: Session, address: str | None) -> list[str]:
    return list(dict.fromkeys(a.sponsor or a.user.name.split(" ")[0] for a in adopters_for(db, address)))


async def alert_adopters(report_id: int) -> None:
    """A new problem on an adopted street: tell the people looking after it."""
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        if r is None or not r.address:
            return
        tokens = [a.user.push_token for a in adopters_for(db, r.address) if a.user_id != r.user_id and a.user.push_token]
        title, street = r.category.name.capitalize(), r.address
    if tokens:
        await send_many(list(dict.fromkeys(tokens)), f"💚 New problem on {street}", f"{title} reported on the street you look after.",
                        {"screen": "report", "id": report_id})


def _adoption_out(db: Session, a: StreetAdoption) -> schemas.AdoptionOut:
    open_ = sum(1 for (addr,) in db.execute(select(Report.address).where(Report.status != "fixed", Report.address.is_not(None)))
                if street_key(addr) == a.key)
    return schemas.AdoptionOut(id=a.id, street=a.street, sponsor=a.sponsor, open=open_, created_at=a.created_at)


@router.get("/adoptions/me", response_model=list[schemas.AdoptionOut])
def my_streets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(StreetAdoption).where(StreetAdoption.user_id == user.id).order_by(StreetAdoption.created_at)).all()
    return [_adoption_out(db, a) for a in rows]


@router.post("/adoptions", response_model=schemas.AdoptionOut, status_code=201)
def adopt(body: schemas.AdoptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "crew":
        raise HTTPException(403, "Crew accounts can't adopt streets")
    key = street_key(body.street)
    if not key:
        raise HTTPException(422, "Write the street's name")
    mine = db.scalars(select(StreetAdoption).where(StreetAdoption.user_id == user.id)).all()
    if any(a.key == key for a in mine):
        raise HTTPException(409, "You already look after this street")
    if len(mine) >= MAX_STREETS:
        raise HTTPException(429, "You can look after up to 5 streets")
    a = StreetAdoption(user_id=user.id, street=body.street.split(",")[0].strip(), key=key,
                       sponsor=(body.sponsor or "").strip() or None)
    db.add(a)
    db.commit()
    return _adoption_out(db, a)


@router.delete("/adoptions/{adoption_id}", status_code=204)
def unadopt(adoption_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(StreetAdoption, adoption_id)
    if a is None or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Street not found")
    db.delete(a)
    db.commit()


# ---------- fixed badly: the same problem back at a spot fixed recently ----------
def find_repeat(db: Session, category_id: int, lat: float, lng: float) -> int | None:
    d = 0.0005  # ~50 m box first, then the exact distance
    rows = db.scalars(select(Report).where(
        Report.category_id == category_id, Report.status == "fixed", Report.updated_at >= now() - timedelta(days=REPEAT_DAYS),
        Report.latitude.between(lat - d, lat + d), Report.longitude.between(lng - d, lng + d),
    ).order_by(Report.updated_at.desc())).all()
    near = [r for r in rows if distance_m(lat, lng, r.latitude, r.longitude) <= REPEAT_RADIUS_M]
    return near[0].id if near else None


def fixed_at(db: Session) -> dict[int, object]:
    """When each report was (first) marked fixed."""
    return dict(db.execute(select(StatusUpdate.report_id, func.min(StatusUpdate.created_at))
                           .where(StatusUpdate.new_status == "fixed").group_by(StatusUpdate.report_id)).all())


# ---------- top 10 ----------
@router.get("/public/top", response_model=list[schemas.TopReport], tags=["public"])
def top10(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """The open problems most neighbours confirmed lately: what the city should fix first."""
    rows = db.scalars(select(Report).where(Report.status != "fixed", Report.created_at >= now() - timedelta(days=days),
                                           Report.confirmations > 0)
                      .order_by(Report.confirmations.desc(), Report.created_at).limit(10)).all()
    return [schemas.TopReport(id=r.id, title=r.category.name.capitalize(), address=r.address,
                              neighbourhood=neighbourhood(r.latitude, r.longitude), status=r.status,
                              confirmations=r.confirmations, photo_url=r.photo_url, created_at=r.created_at) for r in rows]


# ---------- weekly summary for the city ----------
_summary_cache: dict[tuple[int, str], tuple[float, schemas.SummaryOut]] = {}


def _facts(db: Session, days: int) -> dict:
    since = now() - timedelta(days=days)
    new = db.scalars(select(Report).where(Report.created_at >= since)).all()
    done = fixed_at(db)
    fixed = [rid for rid, at in done.items() if at >= since]
    waiting = db.scalars(select(Report).where(Report.status != "fixed",
                                              Report.created_at < now() - timedelta(days=WAITING_LONG_DAYS))).all()
    areas: dict[str, int] = {}
    streets: dict[str, int] = {}
    cats: dict[str, int] = {}
    for r in new:
        a = neighbourhood(r.latitude, r.longitude) or "Other"
        areas[a] = areas.get(a, 0) + 1
        if r.address:
            streets[r.address.split(",")[0]] = streets.get(r.address.split(",")[0], 0) + 1
        cats[r.category.name] = cats.get(r.category.name, 0) + 1
    top = lambda d: sorted(d.items(), key=lambda kv: -kv[1])[:5]
    return {
        "days": days, "new": len(new), "fixed": len(fixed), "waiting_long": len(waiting),
        "came_back": sum(1 for r in new if r.repeat_of), "top_areas": top(areas), "top_streets": top(streets),
        "by_category": top(cats),
        "oldest_waiting": [{"id": r.id, "category": r.category.name, "area": neighbourhood(r.latitude, r.longitude),
                            "street": r.address, "days": (now() - r.created_at).days}
                           for r in sorted(waiting, key=lambda r: r.created_at)[:5]],
    }


@router.get("/admin/summary", response_model=schemas.SummaryOut, tags=["admin"])
async def summary(days: int = Query(7, ge=1, le=90), lang: str = "en", fresh: bool = False,
                  _: User = Depends(admin_user), db: Session = Depends(get_db)):
    key = (days, lang)
    hit = _summary_cache.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < 1800:
        return hit[1]
    f = _facts(db, days)
    text = await ai.city_summary(f, lang) if f["new"] or f["waiting_long"] else None
    out = schemas.SummaryOut(text=text, **{k: f[k] for k in schemas.SummaryOut.model_fields if k in f})
    if text:
        _summary_cache[key] = (time.monotonic(), out)
    return out


@router.post("/admin/summary/email", tags=["admin"])
async def email_summary(days: int = Query(7, ge=1, le=90), lang: str = "en", user: User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    """Sends the summary to the signed-in admin's email."""
    if not mailer.configured():
        raise HTTPException(400, "Email isn't set up on this server")
    s = await summary(days, lang, False, user, db)
    body = (s.text or "No AI summary this time.") + (
        f"\n\nNew: {s.new} · Fixed: {s.fixed} · Waiting over {WAITING_LONG_DAYS} days: {s.waiting_long}"
        f" · Came back after a fix: {s.came_back}")
    await asyncio.to_thread(mailer._send, user.email, f"MendMap: the last {days} days in Prishtina", body)
    return {"sent": True, "to": user.email}
