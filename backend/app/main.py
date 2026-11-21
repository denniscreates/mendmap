"""MendMap API — Spot it. Snap it. Mended.

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Docs: http://localhost:8000/docs     Admin panel: http://localhost:8000/admin
Public transparency page: http://localhost:8000/city
"""
import asyncio
import hashlib
import hmac
import logging
import math
import os
import secrets
from datetime import timedelta
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import ai, mailer, photos, schemas
from .auth import JWT_SECRET, admin_user, create_token, current_user, hash_password, verify_password
from .db import Base, SessionLocal, engine, get_db
from .insights import (
    ALERT_RADIUS_M, CLAIM_HOURS, MAX_ACTIVE_CLAIMS, NEIGHBOUR_FIXABLE, NEIGHBOURHOODS, REWARD_EUR, REWARD_EVERY,
    badges, distance_m, enrich, flag_list, is_flagged, level, neighbour_ok, neighbourhood, priority, route_order,
)
from .models import Category, Confirmation, OtpCode, Report, StatusUpdate, User, migrate, now
from .push import send_many, send_status_push
from .seed import seed

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
ADMIN_DIR = ROOT.parent / "admin"
PUBLIC_DIR = ROOT.parent / "public"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_VOICE_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
VOICE_TYPES = {
    "audio/m4a": ".m4a", "audio/x-m4a": ".m4a", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/3gpp": ".3gp",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    UPLOADS.mkdir(exist_ok=True)
    Base.metadata.create_all(engine)
    migrate(engine)
    seed()
    yield


app = FastAPI(title="MendMap API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
UPLOADS.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin/")


# ---------- helpers ----------

def parse_near(near: str) -> tuple[float, float]:
    try:
        lat, lng = (float(x) for x in near.split(","))
    except ValueError:
        raise HTTPException(400, "near must be 'lat,lng'")
    return lat, lng


def report_query():
    return select(Report).options(selectinload(Report.category), selectinload(Report.claimer))


def _find_same_photo(db: Session, fp: str | None, skip: int | None = None) -> int | None:
    """The id of a report whose photo (or after photo) is the same picture as `fp`, if any."""
    if not fp:
        return None
    rows = db.execute(select(Report.id, Report.photo_hash, Report.after_hash).where(
        (Report.photo_hash.is_not(None)) | (Report.after_hash.is_not(None)))).all()
    for rid, ph, ah in rows:
        if rid != skip and (photos.same(fp, ph) or photos.same(fp, ah)):
            return rid
    return None


def release_stale(db: Session) -> None:
    """Neighbour jobs with no after photo after CLAIM_HOURS go back to the map for someone else."""
    cutoff = now() - timedelta(hours=CLAIM_HOURS)
    stale = db.scalars(select(Report).options(selectinload(Report.updates)).where(
        Report.claimed_by.is_not(None), Report.status == "in_progress",
        Report.fix_status.is_(None), Report.claimed_at < cutoff,
    )).all()
    for r in stale:
        r.claimer, r.claimed_at, r.status, r.updated_at = None, None, "reported", now()
        r.updates.append(StatusUpdate(old_status="in_progress", new_status="reported",
                                      comment=f"Not finished within {CLAIM_HOURS} hours, so it's open again."))
    if stale:
        db.commit()


def out(report: Report) -> schemas.ReportOut:
    return enrich(schemas.ReportOut.model_validate(report), report)


def detail(report: Report) -> schemas.ReportDetail:
    d = enrich(schemas.ReportDetail.model_validate(report), report)
    d.reporter_name = report.user.name if report.user else None
    return d


async def save_upload(file: UploadFile, types: dict[str, str], max_bytes: int, what: str) -> str:
    ext = types.get((file.content_type or "").split(";")[0])
    if not ext:
        raise HTTPException(415, f"Unsupported {what} type")
    data = await file.read()
    if not data:
        raise HTTPException(400, f"The {what} is empty")
    if len(data) > max_bytes:
        raise HTTPException(413, f"The {what} is too large")
    name = f"{uuid.uuid4().hex}{ext}"
    (UPLOADS / name).write_bytes(data)
    return f"/uploads/{name}"


def crew_user(user: User = Depends(current_user)) -> User:
    if user.role not in ("crew", "admin"):
        raise HTTPException(403, "Crew only")
    return user


async def transcribe_voice(report_id: int, voice_url: str) -> None:
    """Runs after the report is saved, so sending a report never waits for the AI."""
    path = UPLOADS / Path(voice_url).name
    if not path.exists():
        return
    text = await ai.transcribe(path.read_bytes(), path.suffix)
    if not text:
        return
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        if r and r.voice_url == voice_url:
            r.voice_text = text
            db.commit()


async def ai_review(report_id: int) -> bool:
    """Server-side AI check of a new report's photo: stores the verdict, fills in the severity if the
    citizen left it empty, and decides whether neighbours may take the job."""
    """Returns False when the AI didn't answer (busy), so the caller can try again later."""
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        if not r or not r.photo_url:
            return True
        path = UPLOADS / Path(r.photo_url).name
    if not path.exists():
        return True
    res = await ai.check_photo(path.read_bytes())
    if not res.get("available"):
        return ai.provider() is None  # no AI configured: nothing to retry
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        if not r:
            return True
        r.ai_is_problem = int(bool(res.get("is_street_problem")))
        r.ai_category = res.get("category")
        r.ai_severity = res.get("severity")
        r.ai_reason = (res.get("reason") or "")[:500] or None
        r.ai_neighbour_safe = int(bool(res.get("neighbour_safe")))
        r.ai_safety_reason = (res.get("safety_reason") or "")[:500] or None
        r.ai_photo_kind = res.get("photo_kind")
        r.ai_kind_reason = (res.get("kind_reason") or "")[:500] or None
        flags = [f for f in flag_list(r) if f not in ("fake_photo", "not_problem")]
        if r.ai_photo_kind and r.ai_photo_kind != "real_photo":
            flags.append("fake_photo")
        if not r.ai_is_problem:
            flags.append("not_problem")
        r.ai_flags = ",".join(flags) or None
        if r.severity is None and r.ai_is_problem:
            r.severity = r.ai_severity
        db.commit()
    return True


async def review_then_alert(report_id: int) -> None:
    """AI first, so "a job you can fix" alerts follow the AI's safety verdict."""
    ok = True
    try:
        ok = await ai_review(report_id)
    except Exception as exc:  # the report is saved either way
        logging.getLogger("mendmap").warning("AI review of report %s failed: %s", report_id, exc)
    await alert_neighbours(report_id, "new")
    # Gemini was busy: try again a little later (twice), so every report gets its AI check.
    for wait in AI_RETRY_S if not ok else ():
        await asyncio.sleep(wait)
        try:
            if await ai_review(report_id):
                break
        except Exception:
            pass


AI_RETRY_S = (90, 300)


async def alert_neighbours(report_id: int, kind: str) -> None:
    """Push "near you" alerts to people whose home area contains the report."""
    with SessionLocal() as db:
        r = db.scalar(report_query().where(Report.id == report_id))
        if not r:
            return
        area = neighbourhood(r.latitude, r.longitude) or "your area"
        fixers: list[str] = []
        if kind == "new" and neighbour_ok(r) and area != "your area":
            fixers = list(db.scalars(select(User.push_token).where(
                User.role == "citizen", User.neighbourhood == area, User.push_token.is_not(None), User.id != r.user_id,
            )))
            if fixers:
                await send_many(fixers, "A job you can fix 🛠️",
                                f"A {r.category.name.lower()} in {area}. Fix it and earn a badge.", {"reportId": r.id})
        users = db.scalars(select(User).where(User.home_lat.is_not(None), User.push_token.is_not(None), User.id != r.user_id))
        tokens = [u.push_token for u in users
                  if u.push_token not in fixers and distance_m(u.home_lat, u.home_lng, r.latitude, r.longitude) <= ALERT_RADIUS_M]
        if not tokens:
            return
        if kind == "fixed":
            title, body = "Mended near you ✨", f"A {r.category.name.lower()} in {area} was fixed."
        else:
            title, body = "New report near you", f"Someone reported a {r.category.name.lower()} in {area}. Seen it too?"
        await send_many(tokens, title, body, {"reportId": r.id})


# ---------- auth ----------

def _check_area(name: str | None) -> str | None:
    if name is None or not name.strip():
        return None
    if name not in NEIGHBOURHOODS:
        raise HTTPException(422, "Unknown neighbourhood")
    return name


@app.get("/neighbourhoods", response_model=list[str], tags=["auth"])
def neighbourhoods():
    """Neighbourhoods a user can pick at sign-up."""
    return sorted(NEIGHBOURHOODS)


# ---------- one-time codes ----------
OTP_TTL_S = 600        # a code works for 10 minutes
OTP_RESEND_S = 30      # wait this long before asking for another
OTP_MAX_ATTEMPTS = 5   # wrong guesses per code


def _otp_hash(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


@app.post("/auth/otp/send", response_model=schemas.OtpSent, tags=["auth"])
async def send_otp(body: schemas.OtpSend, db: Session = Depends(get_db)):
    """Sends a 6-digit code to the email. In demo mode (no SMTP) the code is returned instead."""
    email = body.email.strip().lower()
    existing = db.scalar(select(User.id).where(User.email == email)) is not None
    if existing and body.purpose == "register":
        raise HTTPException(409, "An account with this email already exists")
    last = db.scalar(select(OtpCode).where(OtpCode.email == email).order_by(OtpCode.created_at.desc()).limit(1))
    if last and (now() - last.created_at).total_seconds() < OTP_RESEND_S:
        raise HTTPException(429, "Wait a moment before asking for a new code")
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(OtpCode(email=email, code_hash=_otp_hash(email, code), expires_at=now() + timedelta(seconds=OTP_TTL_S)))
    db.commit()
    demo = not mailer.configured()
    if not demo:
        await mailer.send_code(email, code)
    return schemas.OtpSent(
        sent=True, expires_in=OTP_TTL_S, resend_in=OTP_RESEND_S, existing=existing, demo_code=code if demo else None
    )


def _check_otp(db: Session, email: str, code: str | None) -> None:
    if not code:
        raise HTTPException(400, "Verify your email first")
    row = db.scalar(
        select(OtpCode).where(OtpCode.email == email, OtpCode.used == 0).order_by(OtpCode.created_at.desc()).limit(1)
    )
    if not row or row.expires_at < now():
        raise HTTPException(400, "The code expired. Ask for a new one")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many tries. Ask for a new code")
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, _otp_hash(email, code.strip())):
        db.commit()
        raise HTTPException(400, "Wrong code")
    row.used = 1
    db.commit()


@app.post("/auth/social", response_model=schemas.TokenOut, tags=["auth"])
def social_sign_in(body: schemas.SocialIn, db: Session = Depends(get_db)):
    """DEMO Google/Apple sign-in. No Google or Apple account is checked: the email is confirmed
    with a one-time code instead. Real sign-in needs OAuth client IDs (see README)."""
    email = body.email.strip().lower()
    _check_otp(db, email, body.code)
    user = db.scalar(select(User).where(User.email == email))
    is_new = user is None
    if is_new:
        user = User(
            name=body.name.strip(), email=email, password_hash=hash_password(secrets.token_urlsafe(24)),
            neighbourhood=_check_area(body.neighbourhood), auth_provider=body.provider,
        )
        db.add(user)
        db.commit()
    return {"token": create_token(user), "user": user, "is_new": is_new}


@app.post("/auth/register", response_model=schemas.TokenOut, status_code=201, tags=["auth"])
def register(body: schemas.Register, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    area = _check_area(body.neighbourhood)
    _check_otp(db, email, body.code)
    user = User(
        name=body.name.strip(), email=email, password_hash=hash_password(body.password),
        neighbourhood=area, auth_provider="email",
    )
    db.add(user)
    db.commit()
    return {"token": create_token(user), "user": user, "is_new": True}


@app.post("/auth/login", response_model=schemas.TokenOut, tags=["auth"])
def login(body: schemas.Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token(user), "user": user}


@app.get("/me", response_model=schemas.UserOut, tags=["me"])
def me(user: User = Depends(current_user)):
    return user


@app.put("/me/push-token", status_code=204, tags=["me"])
def set_push_token(body: schemas.PushTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.get(User, user.id).push_token = body.push_token
    db.commit()


@app.put("/me/home", response_model=schemas.UserOut, tags=["me"])
def set_home(body: schemas.HomeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Home area for "near you" alerts. Send nulls to turn them off."""
    u = db.get(User, user.id)
    if body.latitude is None or body.longitude is None:
        u.home_lat = u.home_lng = None
    else:
        u.home_lat, u.home_lng = body.latitude, body.longitude
    db.commit()
    return u


@app.put("/me/neighbourhood", response_model=schemas.UserOut, tags=["me"])
def set_neighbourhood(body: schemas.NeighbourhoodIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    u.neighbourhood = _check_area(body.neighbourhood)
    db.commit()
    return u


@app.get("/me/nearby", response_model=list[schemas.ReportOut], tags=["me"])
def nearby(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reports within 500 m of the home area, newest first."""
    if user.home_lat is None:
        return []
    dlat = ALERT_RADIUS_M / 111_320
    dlng = ALERT_RADIUS_M / (111_320 * max(math.cos(math.radians(user.home_lat)), 0.01))
    q = report_query().where(
        Report.latitude.between(user.home_lat - dlat, user.home_lat + dlat),
        Report.longitude.between(user.home_lng - dlng, user.home_lng + dlng),
    ).order_by(Report.updated_at.desc())
    result = []
    for r in db.scalars(q):
        d = distance_m(user.home_lat, user.home_lng, r.latitude, r.longitude)
        if d <= ALERT_RADIUS_M:
            o = out(r)
            o.distance_m = round(d, 1)
            result.append(o)
    return result


@app.get("/me/badges", response_model=list[schemas.Badge], tags=["me"])
def my_badges(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "citizen":  # badges reward residents; crew and admins see their work stats instead
        return []
    mine = db.scalars(report_query().where(Report.user_id == user.id)).all()
    given = db.scalar(select(func.count()).select_from(Confirmation).where(Confirmation.user_id == user.id)) or 0
    return badges(list(mine), given)


# ---------- categories & AI ----------

@app.get("/categories", response_model=list[schemas.CategoryOut], tags=["reports"])
def categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.id)).all()


@app.get("/ai/status", tags=["reports"])
def ai_status():
    """Which AI features are switched on (no secrets are returned)."""
    which = ai.provider()
    return {"provider": which, "photo_check": which is not None, "transcription": which == "gemini"}


@app.post("/ai/check-photo", response_model=schemas.PhotoCheck, tags=["reports"])
async def check_photo(photo: UploadFile = File(...), _: User = Depends(current_user)):
    """AI photo check: suggested category and severity, and whether it shows a street problem."""
    data = await photo.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is larger than 10 MB")
    return await ai.check_photo(data)


# ---------- reports ----------

@app.post("/reports", response_model=schemas.ReportOut, status_code=201, tags=["reports"])
async def create_report(
    background: BackgroundTasks,
    category_id: int = Form(...),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    description: str | None = Form(None, max_length=2000),
    severity: int | None = Form(None, ge=1, le=5),
    photo: UploadFile | None = File(None),
    voice: UploadFile | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.role == "crew":
        raise HTTPException(403, "Crew accounts log work in Jobs, not reports")
    if not db.get(Category, category_id):
        raise HTTPException(400, "Unknown category")
    # Every report needs a photo: crews use it to judge the problem before going out.
    if photo is None or not photo.filename:
        raise HTTPException(400, "A photo is required")
    if (photo.content_type or "") not in PHOTO_TYPES:
        raise HTTPException(415, "Photo must be JPEG, PNG, WebP or HEIC")
    data = await photo.read()
    if not data:
        raise HTTPException(400, "A photo is required")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is larger than 10 MB")
    name = f"{uuid.uuid4().hex}{PHOTO_TYPES[photo.content_type]}"
    (UPLOADS / name).write_bytes(data)
    fp = photos.fingerprint(data)
    reused_from = _find_same_photo(db, fp)

    voice_url = None
    if voice is not None and voice.filename:
        voice_url = await save_upload(voice, VOICE_TYPES, MAX_VOICE_BYTES, "voice note")

    report = Report(
        user_id=user.id,
        category_id=category_id,
        description=(description or "").strip() or None,
        photo_url=f"/uploads/{name}",
        voice_url=voice_url,
        severity=severity,
        latitude=latitude,
        longitude=longitude,
        photo_hash=fp,
        ai_flags=f"reused_photo:{reused_from}" if reused_from else None,
    )
    report.updates.append(StatusUpdate(old_status=None, new_status="reported", comment="Report submitted"))
    db.add(report)
    db.commit()
    background.add_task(review_then_alert, report.id)
    if voice_url:
        background.add_task(transcribe_voice, report.id, voice_url)
    return out(db.scalar(report_query().where(Report.id == report.id)))


@app.get("/reports", response_model=list[schemas.ReportOut], tags=["reports"])
def list_reports(
    category: int | None = Query(None, description="Category id"),
    status_: str | None = Query(None, alias="status", description="One or more statuses, comma separated"),
    near: str | None = Query(None, description="lat,lng — sorts by distance"),
    radius: float = Query(2000, gt=0, le=50_000, description="Metres around `near`"),
    sort: str = Query("new", pattern="^(new|priority)$"),
    limit: int = Query(500, gt=0, le=2000),
    db: Session = Depends(get_db),
):
    release_stale(db)
    q = report_query()
    if category:
        q = q.where(Report.category_id == category)
    if status_:
        q = q.where(Report.status.in_([s.strip() for s in status_.split(",") if s.strip()]))

    if not near:
        rows = [out(r) for r in db.scalars(q.order_by(Report.created_at.desc()).limit(2000))]
        if sort == "priority":
            rows.sort(key=lambda r: -r.priority)
        return rows[:limit]

    lat, lng = parse_near(near)
    # Cheap bounding box in SQL, exact distance in Python.
    dlat = radius / 111_320
    dlng = radius / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    q = q.where(Report.latitude.between(lat - dlat, lat + dlat), Report.longitude.between(lng - dlng, lng + dlng))
    results = []
    for r in db.scalars(q).all():
        d = distance_m(lat, lng, r.latitude, r.longitude)
        if d <= radius:
            o = out(r)
            o.distance_m = round(d, 1)
            results.append(o)
    results.sort(key=lambda r: r.distance_m)
    return results[:limit]


@app.get("/reports/{report_id}", response_model=schemas.ReportDetail, tags=["reports"])
def get_report(report_id: int, db: Session = Depends(get_db)):
    release_stale(db)
    report = db.scalar(
        report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == report_id)
    )
    if not report:
        raise HTTPException(404, "Report not found")
    return detail(report)


@app.post("/reports/{report_id}/confirm", response_model=schemas.ReportOut, tags=["reports"])
def confirm_report(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "citizen":
        raise HTTPException(403, "Only residents can confirm reports")
    report = db.scalar(report_query().where(Report.id == report_id))
    if not report:
        raise HTTPException(404, "Report not found")
    if report.user_id == user.id:
        raise HTTPException(400, "You reported this yourself")
    if report.status == "fixed":
        raise HTTPException(400, "This report is already fixed")
    if db.get(Confirmation, (report_id, user.id)):
        raise HTTPException(409, "You already confirmed this report")
    db.add(Confirmation(report_id=report_id, user_id=user.id))
    report.confirmations += 1
    db.commit()
    return out(report)


@app.get("/me/reports", response_model=list[schemas.ReportDetail], tags=["me"])
def my_reports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    reports = db.scalars(
        report_query()
        .options(selectinload(Report.updates), selectinload(Report.user))
        .where(Report.user_id == user.id)
        .order_by(Report.created_at.desc())
    ).all()
    return [detail(r) for r in reports]


# ---------- public (no sign-in) ----------

def _stats(db: Session) -> schemas.StatsOut:
    # Time to fix = first status update to "fixed" minus report creation.
    fixed_at = (
        select(StatusUpdate.report_id, func.min(StatusUpdate.created_at).label("fixed_at"))
        .where(StatusUpdate.new_status == "fixed")
        .group_by(StatusUpdate.report_id)
        .subquery()
    )
    rows = db.execute(
        select(Category.name, Report.status, Report.created_at, fixed_at.c.fixed_at)
        .join(Report, Report.category_id == Category.id)
        .outerjoin(fixed_at, fixed_at.c.report_id == Report.id)
    ).all()

    per: dict[str, dict] = {
        name: {"category": name, "total": 0, "reported": 0, "in_progress": 0, "fixed": 0, "_days": []}
        for name in db.scalars(select(Category.name).order_by(Category.id))
    }
    for name, st, created, fixed in rows:
        c = per[name]
        c["total"] += 1
        c[st] += 1
        if st == "fixed" and fixed:
            c["_days"].append((fixed - created).total_seconds() / 86400)

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    all_days = [d for c in per.values() for d in c["_days"]]
    cats = [schemas.CategoryStat(**{k: v for k, v in c.items() if k != "_days"}, avg_days_to_fix=avg(c["_days"]))
            for c in per.values()]
    return schemas.StatsOut(
        total=sum(c.total for c in cats),
        reported=sum(c.reported for c in cats),
        in_progress=sum(c.in_progress for c in cats),
        fixed=sum(c.fixed for c in cats),
        avg_days_to_fix=avg(all_days),
        per_category=cats,
    )


@app.get("/public/stats", response_model=schemas.PublicStats, tags=["public"])
def public_stats(db: Session = Depends(get_db)):
    """Transparency numbers anyone can see, plus the neighbourhood leaderboard."""
    base = _stats(db)
    areas: dict[str, dict] = {}
    for lat, lng, st in db.execute(select(Report.latitude, Report.longitude, Report.status)):
        name = neighbourhood(lat, lng) or "Other"
        a = areas.setdefault(name, {"name": name, "total": 0, "fixed": 0, "open": 0})
        a["total"] += 1
        a["fixed" if st == "fixed" else "open"] += 1
    board = [schemas.NeighbourhoodStat(**a, fix_rate=round(a["fixed"] / a["total"], 2)) for a in areas.values()]
    board.sort(key=lambda a: (-a.total, -a.fix_rate))
    return schemas.PublicStats(
        **base.model_dump(),
        fix_rate=round(base.fixed / base.total, 2) if base.total else 0,
        neighbourhoods=board,
    )


@app.get("/public/gallery", response_model=list[schemas.ReportOut], tags=["public"])
def gallery(limit: int = Query(30, gt=0, le=200), db: Session = Depends(get_db)):
    """Fixed reports with a before and an after photo, newest first."""
    q = report_query().where(Report.status == "fixed", Report.after_photo_url.is_not(None)).order_by(Report.updated_at.desc())
    return [out(r) for r in db.scalars(q.limit(limit))]


# ---------- crew ----------

@app.get("/crew/jobs", response_model=list[schemas.Job], tags=["crew"])
def crew_jobs(
    near: str | None = Query(None, description="Crew position lat,lng: jobs come back in driving order from here"),
    _: User = Depends(crew_user),
    db: Session = Depends(get_db),
):
    jobs = db.scalars(report_query().where(Report.status == "in_progress")).all()
    start = parse_near(near) if near else None
    result = []
    for i, (r, leg) in enumerate(route_order(start, list(jobs)), start=1):
        j = enrich(schemas.Job.model_validate({**schemas.ReportOut.model_validate(r).model_dump(), "stop": i}), r)
        j.leg_m = leg
        result.append(j)
    return result


@app.get("/crew/stats", response_model=schemas.CrewStats, tags=["crew"])
def crew_stats(crew: User = Depends(crew_user), db: Session = Depends(get_db)):
    """Jobs this crew member closed (they are the one who set the report to Fixed)."""
    rows = db.execute(
        select(StatusUpdate.created_at, Report.created_at)
        .join(Report, Report.id == StatusUpdate.report_id)
        .where(StatusUpdate.admin_id == crew.id, StatusUpdate.new_status == "fixed", StatusUpdate.old_status != "fixed")
    ).all()
    t = now()
    today = t.replace(hour=0, minute=0, second=0, microsecond=0)
    week = t - timedelta(days=7)
    days = [(fixed - created).total_seconds() / 86400 for fixed, created in rows]
    open_jobs = db.scalar(select(func.count()).select_from(Report).where(Report.status == "in_progress")) or 0
    return schemas.CrewStats(
        open_jobs=open_jobs,
        fixed_today=sum(f >= today for f, _ in rows),
        fixed_week=sum(f >= week for f, _ in rows),
        fixed_total=len(rows),
        avg_days_to_fix=round(sum(days) / len(days), 1) if days else None,
    )


async def _mark_fixed(report: Report, by: User, after_url: str | None, comment: str | None, db: Session, background: BackgroundTasks):
    old = report.status
    report.status = "fixed"
    if after_url:
        report.after_photo_url = after_url
    report.updated_at = now()
    report.updates.append(StatusUpdate(admin_id=by.id, old_status=old, new_status="fixed", comment=comment))
    db.commit()
    db.refresh(report)
    if old != "fixed":
        await send_status_push(report.user.push_token, report.id, report.category.name, "fixed")
        background.add_task(alert_neighbours, report.id, "fixed")


@app.post("/crew/jobs/{report_id}/done", response_model=schemas.ReportDetail, tags=["crew"])
async def crew_done(
    report_id: int,
    background: BackgroundTasks,
    after_photo: UploadFile = File(...),
    comment: str | None = Form(None, max_length=1000),
    crew: User = Depends(crew_user),
    db: Session = Depends(get_db),
):
    """The crew marks a job fixed with an "after" photo."""
    report = db.scalar(
        report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == report_id)
    )
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status == "fixed":  # e.g. sent twice from the offline queue
        return detail(report)
    after_url = await save_upload(after_photo, PHOTO_TYPES, MAX_PHOTO_BYTES, "photo")
    await _mark_fixed(report, crew, after_url, (comment or "").strip() or "Fixed by the city crew.", db, background)
    return detail(report)


# ---------- admin ----------

@app.patch("/admin/reports/{report_id}/status", response_model=schemas.ReportDetail, tags=["admin"])
async def change_status(
    report_id: int,
    body: schemas.StatusChange,
    background: BackgroundTasks,
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    report = db.scalar(
        report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == report_id)
    )
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status == body.status and not body.comment:
        raise HTTPException(400, "Report already has this status")

    if body.status == "fixed":
        await _mark_fixed(report, admin, None, body.comment, db, background)
        return detail(report)

    old = report.status
    report.status = body.status
    report.updated_at = now()
    report.updates.append(
        StatusUpdate(admin_id=admin.id, old_status=old, new_status=body.status, comment=body.comment)
    )
    db.commit()
    db.refresh(report)

    if old != body.status:
        await send_status_push(report.user.push_token, report.id, report.category.name, body.status)
    return detail(report)


@app.post("/admin/reports/{report_id}/after-photo", response_model=schemas.ReportDetail, tags=["admin"])
async def upload_after_photo(
    report_id: int,
    after_photo: UploadFile = File(...),
    _: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    report = db.scalar(
        report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == report_id)
    )
    if not report:
        raise HTTPException(404, "Report not found")
    report.after_photo_url = await save_upload(after_photo, PHOTO_TYPES, MAX_PHOTO_BYTES, "photo")
    db.commit()
    db.refresh(report)
    return detail(report)


@app.delete("/admin/reports/{report_id}", status_code=204, tags=["admin"])
def delete_report(report_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    db.query(Confirmation).filter(Confirmation.report_id == report_id).delete()
    db.delete(report)
    db.commit()


@app.get("/admin/stats", response_model=schemas.StatsOut, tags=["admin"])
def stats(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return _stats(db)


# ---------- neighbour fixes ----------
# A resident of the report's neighbourhood can take a job, fix it and send an "after" photo.
# The city checks the photo; each verified fix is a fixer badge, and every REWARD_EVERY badges
# earns a REWARD_EUR reward that the city pays out (recorded in the admin panel).

def _report_full(db: Session, report_id: int) -> Report:
    r = db.scalar(
        report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == report_id)
    )
    if not r:
        raise HTTPException(404, "Report not found")
    return r


def _fixer_counts(db: Session, user_id: int) -> tuple[int, int]:
    rows = db.execute(
        select(Report.fix_status, func.count())
        .where(Report.claimed_by == user_id, Report.fix_status.is_not(None))
        .group_by(Report.fix_status)
    ).all()
    d = {k: n for k, n in rows}
    return d.get("verified", 0), d.get("pending", 0)


@app.post("/reports/{report_id}/claim", response_model=schemas.ReportDetail, tags=["neighbour fix"])
async def claim(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """"I'll fix it": only for residents of the report's neighbourhood, and only safe categories."""
    if user.role != "citizen":
        raise HTTPException(403, "Only residents can take neighbour jobs")
    release_stale(db)
    r = _report_full(db, report_id)
    area = neighbourhood(r.latitude, r.longitude) or "the area"
    if r.ai_neighbour_safe == 0 or r.ai_is_problem == 0:
        raise HTTPException(400, "The AI check says this isn't safe for neighbours")
    if not neighbour_ok(r):
        raise HTTPException(400, "This problem needs the city crew")
    if r.status != "reported" or r.claimed_by is not None:
        raise HTTPException(409, "Someone is already working on this")
    active = db.scalar(
        select(func.count()).select_from(Report).where(Report.claimed_by == user.id, Report.status == "in_progress")
    ) or 0
    if active >= MAX_ACTIVE_CLAIMS:
        raise HTTPException(400, "Finish your other jobs first")
    r.claimer = db.get(User, user.id)  # sets claimed_by on flush
    r.claimed_at, r.fix_status = now(), None
    r.status = "in_progress"
    r.updated_at = now()
    r.updates.append(StatusUpdate(old_status="reported", new_status="in_progress",
                                  comment="A neighbour is fixing this."))
    db.commit()
    r = _report_full(db, report_id)
    if r.user_id != user.id:
        await send_status_push(r.user.push_token, r.id, r.category.name, "in_progress")
    return detail(r)


@app.post("/reports/{report_id}/unclaim", response_model=schemas.ReportDetail, tags=["neighbour fix"])
def unclaim(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Give the job back, e.g. it's bigger than expected."""
    r = _report_full(db, report_id)
    if r.claimed_by != user.id or r.status != "in_progress":
        raise HTTPException(409, "This job isn't yours")
    r.claimer = None
    r.claimed_at = None
    r.status = "reported"
    r.updated_at = now()
    r.updates.append(StatusUpdate(old_status="in_progress", new_status="reported",
                                  comment="The neighbour handed this back to the city."))
    db.commit()
    return detail(_report_full(db, report_id))


@app.post("/reports/{report_id}/neighbour-fixed", response_model=schemas.ReportDetail, tags=["neighbour fix"])
async def neighbour_fixed(
    report_id: int,
    background: BackgroundTasks,
    after_photo: UploadFile = File(...),
    comment: str | None = Form(None, max_length=1000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The neighbour sends the "after" photo. The city then checks it (verify-fix)."""
    r = _report_full(db, report_id)
    if r.claimed_by != user.id:
        raise HTTPException(409, "This job isn't yours")
    if r.status == "fixed":
        return detail(r)
    data = await after_photo.read()
    await after_photo.seek(0)
    fp = photos.fingerprint(data)
    # Cheap checks first: the report photo sent back, or a photo already used somewhere else.
    if fp and photos.same(fp, r.photo_hash):
        raise HTTPException(400, "That's the photo from the report. Take a new photo after fixing it")
    if _find_same_photo(db, fp, skip=r.id):
        raise HTTPException(400, "This photo was already used in another report. Take a new photo")
    after_url = await save_upload(after_photo, PHOTO_TYPES, MAX_PHOTO_BYTES, "photo")
    r.fix_status = "pending"
    r.after_hash = fp
    r.fix_ai, r.fix_ai_reason = None, None
    text = (comment or "").strip()
    await _mark_fixed(r, user, after_url, f"Fixed by a neighbour. {text}".strip(), db, background)
    background.add_task(ai_check_fix, report_id)
    return detail(_report_full(db, report_id))


AUTO_VERIFY_MIN = 80  # AI confidence (0-100) needed to accept a fix without an official


async def ai_check_fix(report_id: int) -> None:
    """The AI compares the before and after photos. A clear, genuine fix is accepted straight away
    (an official can still undo it); anything doubtful waits for an official with the AI's reason."""
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        if not r or r.fix_status != "pending" or not r.photo_url or not r.after_photo_url:
            return
        before, after = UPLOADS / Path(r.photo_url).name, UPLOADS / Path(r.after_photo_url).name
    if not before.exists() or not after.exists():
        return
    res = await ai.check_fix(before.read_bytes(), after.read_bytes())
    if not res.get("available"):
        return  # no AI or busy: an official checks it as before
    auto = os.getenv("MENDMAP_AUTO_VERIFY", "on").lower() != "off"
    if not res["after_is_real_photo"]:
        verdict = "fake"
    elif not res["same_place"]:
        verdict = "different_place"
    elif not res["problem_gone"]:
        verdict = "not_fixed"
    elif auto and res["confidence"] >= AUTO_VERIFY_MIN:
        verdict = "auto_verified"
    else:
        verdict = "looks_fixed"
    push = None
    with SessionLocal() as db:
        r = db.scalar(report_query().options(selectinload(Report.updates)).where(Report.id == report_id))
        if not r or r.fix_status != "pending":
            return
        r.fix_ai, r.fix_ai_reason = verdict, res["reason"] or None
        claimer = db.get(User, r.claimed_by) if r.claimed_by else None
        if verdict == "auto_verified":
            r.fix_status = "verified"
            r.updates.append(StatusUpdate(old_status="fixed", new_status="fixed",
                                          comment="The AI compared the before and after photos and accepted the fix. Thank you!"))
            push = ("New fixer badge 🛠️", f"Your fix of the {r.category.name.lower()} was accepted.")
        elif verdict in ("fake", "different_place", "not_fixed"):
            push = ("We're checking your fix", "The AI couldn't confirm it from your photo, so a city official will look.")
        db.commit()
        token = claimer.push_token if claimer else None
    if push and token:
        await send_many([token], push[0], push[1], {"reportId": report_id})


@app.get("/me/fixer", response_model=schemas.FixerOut, tags=["neighbour fix"])
def my_fixer(user: User = Depends(current_user), db: Session = Depends(get_db)):
    release_stale(db)
    verified, pending = _fixer_counts(db, user.id)
    active = db.scalars(report_query().where(Report.claimed_by == user.id, Report.status == "in_progress")).all()
    available: list[schemas.ReportOut] = []
    if user.role == "citizen":
        open_ = db.scalars(report_query().where(Report.status == "reported", Report.claimed_by.is_(None))).all()
        # Every job the AI calls safe, anywhere; your own neighbourhood first, then by priority.
        available = sorted((out(r) for r in open_ if neighbour_ok(r)),
                           key=lambda r: (r.neighbourhood != user.neighbourhood, -r.priority))
    lvl, nxt = level(verified)
    return schemas.FixerOut(
        neighbourhood=user.neighbourhood, verified=verified, pending=pending, active=[out(r) for r in active],
        goal=REWARD_EVERY, reward_eur=REWARD_EUR,
        rewards_earned=verified // REWARD_EVERY, rewards_paid=user.rewards_paid or 0,
        level=lvl, next_level_at=nxt, claim_hours=CLAIM_HOURS, max_active=MAX_ACTIVE_CLAIMS, available=available,
    )


@app.post("/admin/reports/{report_id}/ai-check", response_model=schemas.ReportDetail, tags=["admin"])
async def admin_ai_check(report_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Run (or re-run) the AI photo check on a report, e.g. one sent before AI was switched on."""
    if ai.provider() is None:
        raise HTTPException(503, "AI is not configured")
    await ai_review(report_id)
    db.expire_all()
    return detail(_report_full(db, report_id))


@app.post("/admin/reports/{report_id}/clear-flag", response_model=schemas.ReportDetail, tags=["admin"])
def clear_flag(report_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """An official looked at a flagged report and it's genuine."""
    r = _report_full(db, report_id)
    r.flag_cleared = 1
    db.commit()
    return detail(_report_full(db, report_id))


@app.post("/admin/ai/review-all", tags=["admin"])
async def review_all(background: BackgroundTasks, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Fingerprints every photo (flags reused ones) and queues an AI check for every report not checked yet."""
    rows = db.scalars(select(Report).order_by(Report.id)).all()
    for r in rows:
        if r.photo_url and not r.photo_hash:
            path = UPLOADS / Path(r.photo_url).name
            if path.exists():
                r.photo_hash = photos.fingerprint(path.read_bytes())
    db.commit()
    reused = 0
    for r in rows:
        other = _find_same_photo(db, r.photo_hash, skip=r.id)
        if other and other < r.id and not any(f.startswith("reused_photo") for f in flag_list(r)):
            r.ai_flags = ",".join([*flag_list(r), f"reused_photo:{other}"])
            reused += 1
    db.commit()
    todo = [r.id for r in rows if r.photo_url and r.ai_is_problem is None]
    queued = len(todo) if ai.provider() else 0

    async def run():
        for rid in todo:
            try:
                await ai_review(rid)
            except Exception as exc:
                logging.getLogger("mendmap").warning("AI review of report %s failed: %s", rid, exc)

    if queued:
        background.add_task(run)
    return {"queued": queued, "reused_photos": reused}


@app.get("/public/fixers", response_model=list[schemas.TopFixer], tags=["public"])
def top_fixers(db: Session = Depends(get_db)):
    """The neighbours with the most checked fixes (first names only)."""
    rows = db.execute(
        select(User, func.count(Report.id).label("n"))
        .join(Report, Report.claimed_by == User.id)
        .where(Report.fix_status == "verified")
        .group_by(User.id).order_by(func.count(Report.id).desc()).limit(10)
    ).all()
    return [schemas.TopFixer(name=u.name.split(" ")[0], neighbourhood=u.neighbourhood, badges=n, level=level(n)[0])
            for u, n in rows]


@app.post("/admin/reports/{report_id}/verify-fix", response_model=schemas.ReportDetail, tags=["admin"])
async def verify_fix(
    report_id: int, body: schemas.FixVerdict, admin: User = Depends(admin_user), db: Session = Depends(get_db),
):
    """Accept a neighbour's fix (it becomes a fixer badge) or reject it (back to Reported)."""
    r = _report_full(db, report_id)
    undo_ai = r.fix_status == "verified" and r.fix_ai == "auto_verified" and not body.ok
    if r.fix_status != "pending" and not undo_ai:
        raise HTTPException(400, "No neighbour fix waiting for a check")
    claimer = db.get(User, r.claimed_by) if r.claimed_by else None
    if body.ok:
        r.fix_status = "verified"
        r.updates.append(StatusUpdate(admin_id=admin.id, old_status="fixed", new_status="fixed",
                                      comment=body.comment or "The city checked the neighbour's fix. Thank you!"))
    else:
        r.fix_status = None
        r.fix_ai, r.fix_ai_reason = None, None
        r.claimer = None
        r.claimed_at = None
        r.after_photo_url = None
        r.after_hash = None
        r.status = "reported"
        r.updates.append(StatusUpdate(admin_id=admin.id, old_status="fixed", new_status="reported",
                                      comment=body.comment or "The city couldn't confirm the fix, so the report is open again."))
    r.updated_at = now()
    db.commit()
    if body.ok and claimer and claimer.push_token:
        await send_many([claimer.push_token], "New fixer badge 🛠️",
                        f"The city accepted your fix of the {r.category.name.lower()}.", {"reportId": r.id})
    return detail(_report_full(db, report_id))


def _rewards(db: Session) -> list[schemas.RewardOut]:
    rows = db.execute(
        select(Report.claimed_by, func.count()).where(Report.fix_status == "verified").group_by(Report.claimed_by)
    ).all()
    result = []
    for uid, verified in rows:
        u = db.get(User, uid)
        if not u:
            continue
        earned = verified // REWARD_EVERY
        owed = max(0, earned - (u.rewards_paid or 0))
        result.append(schemas.RewardOut(
            user_id=u.id, name=u.name, email=u.email, neighbourhood=u.neighbourhood, verified=verified,
            rewards_earned=earned, rewards_paid=u.rewards_paid or 0, owed_eur=owed * REWARD_EUR,
        ))
    return sorted(result, key=lambda x: (-x.owed_eur, -x.verified))


@app.get("/admin/rewards", response_model=list[schemas.RewardOut], tags=["admin"])
def rewards(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Neighbour fixers, rewards owed first."""
    return _rewards(db)


@app.post("/admin/rewards/{user_id}/paid", response_model=schemas.RewardOut, tags=["admin"])
def reward_paid(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Record that the city paid this user's rewards. The payment itself happens outside MendMap."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    verified, _pending = _fixer_counts(db, user_id)
    u.rewards_paid = verified // REWARD_EVERY
    db.commit()
    for x in _rewards(db):
        if x.user_id == user_id:
            return x
    raise HTTPException(404, "No verified fixes for this user")


# Mounted last so the /admin/... API routes above take priority over the static panel.
if ADMIN_DIR.exists():
    app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
if PUBLIC_DIR.exists():
    app.mount("/city", StaticFiles(directory=PUBLIC_DIR, html=True), name="city")
