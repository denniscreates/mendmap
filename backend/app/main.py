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
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session, selectinload

from . import ai, bookings, chat, community, geo, languages, mailer, photos, schemas
from .auth import JWT_SECRET, admin_user, create_token, current_user, hash_password, verify_password
from .db import Base, SessionLocal, engine, get_db
from .insights import (
    ALERT_RADIUS_M, CLAIM_HOURS, MAX_ACTIVE_CLAIMS, NEIGHBOUR_FIXABLE, NEIGHBOURHOODS, 
    badges, can_do, distance_m, enrich, flag_list, is_flagged, level, neighbour_ok, neighbourhood, priority, route_order,
    photo_urls, skill_job,
)
from .models import (
    Category, Confirmation, Mjeshter, OtpCode, PartnerReward, Report, RewardClaim, StatusUpdate, User, migrate, now,
)
from .push import send_many, send_status_push
from .seed import demo_accounts, seed

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
PROOFS = ROOT / "private" / "proofs"  # mjeshtër documents: never served publicly
ADMIN_DIR = ROOT.parent / "admin"
PUBLIC_DIR = ROOT.parent / "public"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS = 5  # photos per report
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
    reminders = asyncio.create_task(community.reminder_loop())
    payouts = asyncio.create_task(bookings.release_loop())  # pays mjeshtrit when the resident doesn't answer
    catchup = asyncio.create_task(ai_catchup_loop())  # AI checks for reports posted while the AI was down
    yield
    reminders.cancel()
    payouts.cancel()
    catchup.cancel()


app = FastAPI(title="MendMap API", version="2.0.0", lifespan=lifespan)
app.include_router(chat.router)
app.include_router(chat.admin_router)
app.include_router(geo.router)
app.include_router(community.router)
app.include_router(bookings.router)
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
    db = object_session(report)
    if db is not None and report.address:
        d.adopted_by = community.adopter_names(db, report.address)
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
        paths = [p for p in (UPLOADS / Path(u).name for u in photo_urls(r)) if p.exists()]
    if not paths:
        return True
    originals = [p.read_bytes() for p in paths]
    res = await ai.check_photo(originals)  # all photos together: one description and severity for the problem
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
        r.ai_description = res.get("description") or None
        r.ai_skilled_ok = int(bool(res.get("skilled_ok")))
        r.ai_skill_needed = res.get("skill_needed")
        if not (r.description or "").strip() and r.ai_description and r.ai_is_problem:
            r.description = r.ai_description  # no text from the citizen: the AI describes the photo
        # Privacy: blur faces and number plates in the public photos (once; the fingerprint stays the original's).
        if r.blurred is None:
            boxes = res.get("blur_boxes") or []
            done = 0
            for i, (path, original) in enumerate(zip(paths, originals), start=1):
                mine = [b for b in boxes if b.get("image", 1) == i]
                blurred = photos.blur(original, mine)
                if blurred:
                    try:
                        path.write_bytes(blurred)
                        done += len(mine)
                    except OSError as exc:
                        logging.getLogger("mendmap").warning("Couldn't blur report %s: %s", report_id, exc)
            r.blurred = done
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
    await alert_mjeshtrit(report_id)
    # Gemini was busy: try again a little later (twice), so every report gets its AI check.
    for wait in AI_RETRY_S if not ok else ():
        await asyncio.sleep(wait)
        try:
            if await ai_review(report_id):
                break
        except Exception:
            pass


AI_RETRY_S = (90, 300)
AI_CATCHUP_S = 1800  # every 30 minutes, check reports the AI missed (e.g. the daily Gemini quota ran out)


async def ai_catchup_loop() -> None:
    """Reports posted while the AI was down get their check (description, severity, blurring) once it is back."""
    while True:
        await asyncio.sleep(AI_CATCHUP_S)
        if not ai.provider():
            continue
        try:
            with SessionLocal() as db:
                since = now() - timedelta(days=14)
                todo = db.scalars(select(Report.id).where(Report.photo_url.is_not(None), Report.ai_is_problem.is_(None),
                                                          Report.created_at >= since).order_by(Report.id).limit(20)).all()
            for rid in todo:
                if not await ai_review(rid):
                    break  # still busy: try again next round
        except Exception as exc:
            logging.getLogger("mendmap").warning("AI catch-up failed: %s", exc)


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

def _check_lang(code: str | None) -> str | None:
    """A main language the app can show (English, a hand-made one, or one the AI translates)."""
    if code is None or not code.strip():
        return None
    if code not in languages.LANGS:
        raise HTTPException(422, "Unknown language")
    return code


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
            language=_check_lang(body.language),
        )
        db.add(user)
        db.commit()
    elif body.language and not user.language:
        user.language = _check_lang(body.language)
        db.commit()
    return {"token": create_token(user), "user": user, "is_new": is_new}


@app.post("/auth/register", response_model=schemas.TokenOut, status_code=201, tags=["auth"])
def register(body: schemas.Register, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    area = _check_area(body.neighbourhood)
    lang = _check_lang(body.language)
    _check_otp(db, email, body.code)
    user = User(
        name=body.name.strip(), email=email, password_hash=hash_password(body.password),
        neighbourhood=area, auth_provider="email", language=lang,
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


@app.get("/auth/demo-accounts", tags=["auth"])
def demo_accounts_list(db: Session = Depends(get_db)):
    """Demo accounts for judges and testers (one tap on the sign-in screen). Empty unless SEED_DEMO=1,
    and an account is left out once its password has been changed."""
    return demo_accounts(db)


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


@app.put("/me/language", response_model=schemas.UserOut, tags=["me"])
def set_language(body: schemas.LanguageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The person's main language: the app offers it everywhere, next to English and the local language."""
    u = db.get(User, user.id)
    u.language = _check_lang(body.language)
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


@app.post("/i18n/translate", response_model=schemas.TranslateOut, tags=["languages"])
async def translate_ui(body: schemas.TranslateIn):
    """The app's texts in the official language of the user's country (English + that language).
    Translated once by the AI, then served from the cache to everyone. Open without sign-in, so the
    sign-in screen is translated too; only known languages are accepted."""
    if body.lang not in languages.LANGS or body.lang in languages.STATIC:
        raise HTTPException(400, "This language isn't available")
    found, missing = await languages.translate(body.lang, body.strings)
    return schemas.TranslateOut(lang=body.lang, translations=found, missing=missing)


@app.get("/ai/status", tags=["reports"])
def ai_status():
    """Which AI features are switched on (no secrets are returned)."""
    which = ai.provider()
    return {"provider": which, "photo_check": which is not None, "transcription": which == "gemini"}


@app.post("/ai/check-photo", response_model=schemas.PhotoCheck, tags=["reports"])
async def check_photo(photo: list[UploadFile] = File(...), lang: str = Form("en"), _: User = Depends(current_user)):
    """AI photo check of one or more photos of the same problem: suggested category and severity, a description
    in the user's language, whether it shows a street problem, and the faces/plates that will be blurred."""
    if len(photo) > MAX_PHOTOS:
        raise HTTPException(400, f"Up to {MAX_PHOTOS} photos")
    images = []
    for p in photo:
        data = await p.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "Photo is larger than 10 MB")
        images.append(data)
    return await ai.check_photo(images, lang)


# ---------- reports ----------

@app.post("/reports", response_model=schemas.ReportOut, status_code=201, tags=["reports"])
async def create_report(
    background: BackgroundTasks,
    category_id: int = Form(...),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    description: str | None = Form(None, max_length=2000),
    address: str | None = Form(None, max_length=200),
    severity: int | None = Form(None, ge=1, le=5),
    photo: UploadFile | None = File(None),
    photos_: list[UploadFile] | None = File(None, alias="photos", description="More photos of the same problem (up to 4)"),
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
    extra = [p for p in (photos_ or []) if p.filename]
    if len(extra) + 1 > MAX_PHOTOS:
        raise HTTPException(400, f"Up to {MAX_PHOTOS} photos")
    extra_urls = [await save_photo(p) for p in extra]
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
        address=(address or "").strip() or None,
        photo_url=f"/uploads/{name}",
        extra_photos=",".join(extra_urls) or None,
        voice_url=voice_url,
        severity=severity,
        latitude=latitude,
        longitude=longitude,
        photo_hash=fp,
        ai_flags=f"reused_photo:{reused_from}" if reused_from else None,
        repeat_of=community.find_repeat(db, category_id, latitude, longitude),
    )
    report.updates.append(StatusUpdate(old_status=None, new_status="reported", comment="Report submitted"))
    db.add(report)
    db.commit()
    background.add_task(review_then_alert, report.id)
    background.add_task(community.alert_adopters, report.id)
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


async def save_photo(p: UploadFile) -> str:
    if (p.content_type or "") not in PHOTO_TYPES:
        raise HTTPException(415, "Photo must be JPEG, PNG, WebP or HEIC")
    return await save_upload(p, PHOTO_TYPES, MAX_PHOTO_BYTES, "photo")


@app.put("/reports/{report_id}", response_model=schemas.ReportDetail, tags=["reports"])
async def edit_report(
    report_id: int,
    background: BackgroundTasks,
    category_id: int | None = Form(None),
    description: str | None = Form(None, max_length=2000),
    address: str | None = Form(None, max_length=200),
    severity: int | None = Form(None, ge=0, le=5, description="0 clears it, so the AI's severity is used"),
    keep: str | None = Form(None, description="Photos to keep, comma separated urls in the new order. Leave out to keep all."),
    photos_: list[UploadFile] | None = File(None, alias="photos", description="New photos to add"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The reporter changes their post: text, street, category, severity, and photos (add, remove, reorder).
    Only while nobody is working on it yet. New photos are checked by the AI again."""
    r = db.scalar(report_query().where(Report.id == report_id))
    if not r:
        raise HTTPException(404, "Report not found")
    if r.user_id != user.id:
        raise HTTPException(403, "Only the person who reported it can edit it")
    if r.status != "reported" or r.claimed_by:
        raise HTTPException(409, "Someone is already working on this, so it can't be edited")
    if category_id is not None:
        if not db.get(Category, category_id):
            raise HTTPException(400, "Unknown category")
        r.category_id = category_id
    if description is not None:
        r.description = description.strip() or None
    if address is not None:
        r.address = address.strip() or None
    if severity is not None:
        r.severity = severity or (r.ai_severity if r.ai_is_problem else None)
    old = photo_urls(r)
    kept = old if keep is None else [u for u in dict.fromkeys(keep.split(",")) if u in old]
    new = [p for p in (photos_ or []) if p.filename]
    if len(kept) + len(new) > MAX_PHOTOS:
        raise HTTPException(400, f"Up to {MAX_PHOTOS} photos")
    if not kept and not new:
        raise HTTPException(400, "A photo is required")
    added = [await save_photo(p) for p in new]
    urls = kept + added
    if urls != old:
        for u in set(old) - set(urls):
            (UPLOADS / Path(u).name).unlink(missing_ok=True)
        if urls[0] != r.photo_url:  # a new cover photo: check it isn't someone else's picture
            data = (UPLOADS / Path(urls[0]).name).read_bytes()
            r.photo_hash = photos.fingerprint(data)
            reused_from = _find_same_photo(db, r.photo_hash, skip=r.id)
            flags = [f for f in flag_list(r) if not f.startswith("reused_photo:")]
            r.ai_flags = ",".join(flags + ([f"reused_photo:{reused_from}"] if reused_from else [])) or None
        r.photo_url, r.extra_photos = urls[0], ",".join(urls[1:]) or None
    r.edited_at = r.updated_at = now()
    db.commit()
    if added:
        r.blurred = None  # blur faces and plates in the new photos too
        db.commit()
        background.add_task(ai_review, r.id)
    db.expire(r)  # the session keeps objects after commit: reload the category too
    return detail(db.scalar(report_query().options(selectinload(Report.updates), selectinload(Report.user)).where(Report.id == r.id)))


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
    done = community.fixed_at(db)
    for rid, lat, lng, st, created, repeat in db.execute(
            select(Report.id, Report.latitude, Report.longitude, Report.status, Report.created_at, Report.repeat_of)):
        name = neighbourhood(lat, lng) or "Other"
        a = areas.setdefault(name, {"name": name, "total": 0, "fixed": 0, "open": 0, "came_back": 0, "_days": []})
        a["total"] += 1
        a["fixed" if st == "fixed" else "open"] += 1
        a["came_back"] += 1 if repeat else 0
        if st == "fixed" and rid in done:
            a["_days"].append(max(0.0, (done[rid] - created).total_seconds() / 86400))
    board = []
    for a in areas.values():
        days = a.pop("_days")
        board.append(schemas.NeighbourhoodStat(
            **a, fix_rate=round(a["fixed"] / a["total"], 2),
            avg_fix_days=round(sum(days) / len(days), 1) if days else None,
            fixed_in_week=round(sum(1 for d in days if d <= 7) / len(days), 2) if days else None,
        ))
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
# The city (or the AI) checks the photo; each verified fix is a fixer badge that the fixer can
# spend on partner rewards (see /rewards below).

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
    # Badges: checked fixes plus clean-up days the user came to (or organised well).
    return d.get("verified", 0) + community.event_badges(db, user_id), d.get("pending", 0)


@app.post("/reports/{report_id}/claim", response_model=schemas.ReportDetail, tags=["neighbour fix"])
async def claim(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """"I'll fix it": only for residents of the report's neighbourhood, and only safe categories."""
    if user.role != "citizen":
        raise HTTPException(403, "Only residents can take neighbour jobs")
    release_stale(db)
    r = _report_full(db, report_id)
    area = neighbourhood(r.latitude, r.longitude) or "the area"
    need = skill_job(r)
    if not neighbour_ok(r):
        if need:
            if user.mjeshter_status != "approved":
                raise HTTPException(400, "This job needs a verified mjeshtër")
            if not can_do(user.mjeshter_skills, need):
                raise HTTPException(400, "You don't have the skill this job needs")
        elif r.ai_neighbour_safe == 0 or r.ai_is_problem == 0:
            raise HTTPException(400, "The AI check says this isn't safe for neighbours")
        else:
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
                                  comment="A mjeshtër is fixing this." if need and not neighbour_ok(r) else "A neighbour is fixing this."))
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
        skills = user.mjeshter_skills
        available = sorted((out(r) for r in open_ if neighbour_ok(r) or can_do(skills, skill_job(r))),
                           key=lambda r: (r.neighbourhood != user.neighbourhood, -r.priority))
    lvl, nxt = level(verified)
    spent = _spent(db, user.id)
    return schemas.FixerOut(
        neighbourhood=user.neighbourhood, verified=verified, pending=pending, active=[out(r) for r in active],
        balance=max(0, verified - spent), spent=spent, next_reward=_next_reward(db, verified - spent),
        level=lvl, next_level_at=nxt, claim_hours=CLAIM_HOURS, max_active=MAX_ACTIVE_CLAIMS, available=available,
    )


@app.post("/reports/{report_id}/rate", response_model=schemas.ReportDetail, tags=["reports"])
def rate_fix(report_id: int, body: schemas.RateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The person who reported it says whether it's really fixed. "Not fixed" puts it back on the map,
    and a neighbour fix loses its badge, so nobody gets credit for a fix that didn't happen."""
    r = _report_full(db, report_id)
    if r.user_id != user.id:
        raise HTTPException(403, "Only the person who reported it can rate the fix")
    if r.status != "fixed":
        raise HTTPException(400, "You can rate it once it's fixed")
    if r.rating is not None:
        raise HTTPException(409, "You already rated this fix")
    if body.ok:
        r.rating = 1
        r.updates.append(StatusUpdate(old_status="fixed", new_status="fixed", comment="The reporter confirmed it's fixed 👍"))
    else:
        r.reopened = (r.reopened or 0) + 1
        r.status = "reported"
        note = (body.comment or "").strip()
        r.updates.append(StatusUpdate(old_status="fixed", new_status="reported",
                                      comment="The reporter says it isn't fixed yet" + (f": {note}" if note else ".")))
        if r.fix_status:  # a neighbour fix that didn't hold: no badge, and the job is open again
            r.fix_status = None
            r.claimed_by = r.claimed_at = None
            r.after_photo_url = r.after_hash = None
            r.fix_ai = r.fix_ai_reason = None
    r.updated_at = now()
    db.commit()
    return detail(_report_full(db, report_id))


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


# ---------- mjeshtrit: skilled volunteers ----------
# Plumbers, painters, builders... who fix things on days the city doesn't work (e.g. Sundays). They upload
# proof of their skill; the AI reads it and approves genuine documents, the rest wait for the city.
SKILLS = set(ai.SKILLS)
DAYS = {"weekday_evenings", "saturday", "sunday", "holidays"}
MJ_AUTO_MIN = 75  # AI confidence needed to approve a document without a person


def _mj_auto() -> bool:
    return os.getenv("MENDMAP_MJESHTER_AUTO", "on").lower() != "off"


def _csv_in(raw: str | list[str] | None, allowed: set[str]) -> list[str]:
    items = raw if isinstance(raw, list) else (raw or "").split(",")
    return sorted({x.strip() for x in items if x.strip() in allowed})


def _decide(res: dict, claimed: list[str]) -> tuple[str, str | None, list[str]]:
    """(status, verified_by, verified skills) from the AI's reading of the document."""
    if not res.get("available"):
        return "pending", None, []
    shown = [x for x in res["skills_shown"] if x in claimed]
    if res["verdict"] in ("fake", "not_a_document") and res["confidence"] >= 60:
        return "rejected", None, []
    if (_mj_auto() and res["verdict"] == "legit" and res["name_matches"] and res["looks_genuine"]
            and res["confidence"] >= MJ_AUTO_MIN and shown):
        return "approved", "ai", shown
    return "pending", None, []


def _mj_admin(m: Mjeshter) -> schemas.MjeshterAdmin:
    o = schemas.MjeshterAdmin.model_validate(m)
    o.user_name, o.user_email = m.user.name, m.user.email
    return o


@app.post("/mjeshtrit/apply", response_model=schemas.MjeshterMe, tags=["mjeshtrit"])
async def mjeshter_apply(
    skills: str = Form(..., description="comma list: plumbing, electrics, building, painting, carpentry, gardening, welding"),
    days: str = Form("", description="comma list: weekday_evenings, saturday, sunday, holidays"),
    neighbourhood: str | None = Form(None, max_length=60),
    bio: str | None = Form(None, max_length=500),
    lang: str = Form("en"),
    proof: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Sign up as a mjeshtër with proof of the skill (photo or PDF of a diploma, certificate, licence...).
    The AI checks the document right away: genuine ones are approved, unclear ones wait for the city."""
    if user.role != "citizen":
        raise HTTPException(403, "Only residents can become a mjeshtër")
    claimed = _csv_in(skills, SKILLS)
    if not claimed:
        raise HTTPException(400, "Pick at least one skill")
    if neighbourhood and neighbourhood not in NEIGHBOURHOODS:
        raise HTTPException(400, "Unknown neighbourhood")
    data = await proof.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The document is larger than 10 MB")
    mime = (proof.content_type or "").lower()
    if mime not in ai.PROOF_MIME:
        mime = "application/pdf" if data[:4] == b"%PDF" else "image/jpeg"
    PROOFS.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{'.pdf' if mime == 'application/pdf' else '.jpg'}"
    (PROOFS / name).write_bytes(data)

    res = await ai.check_proof(data, mime, user.name, claimed, lang)
    status_, by, verified = _decide(res, claimed)
    m = db.scalar(select(Mjeshter).where(Mjeshter.user_id == user.id))
    if m and m.status == "approved" and status_ != "approved":
        raise HTTPException(409, "You're already a verified mjeshtër")
    if m is None:
        m = Mjeshter(user_id=user.id, skills="")
        db.add(m)
    old = m.proof_path
    m.skills, m.days = ",".join(claimed), ",".join(_csv_in(days, DAYS))
    m.neighbourhood, m.bio = neighbourhood or user.neighbourhood, (bio or "").strip() or None
    m.status, m.verified_by, m.verified_skills = status_, by, ",".join(verified) or None
    m.proof_path, m.proof_mime = name, mime
    m.ai_verdict = res.get("verdict") if res.get("available") else "unavailable"
    m.ai_doc_type, m.ai_name_on_doc, m.ai_issuer = res.get("doc_type"), res.get("name_on_doc"), res.get("issuer")
    m.ai_name_matches = int(res["name_matches"]) if res.get("available") else None
    m.ai_looks_genuine = int(res["looks_genuine"]) if res.get("available") else None
    m.ai_skills = ",".join(res.get("skills_shown") or []) or None
    m.ai_confidence, m.ai_reason, m.ai_reason_user = res.get("confidence"), res.get("reason"), res.get("reason_user")
    m.admin_note, m.created_at = None, now()
    m.reviewed_at = now() if status_ != "pending" else None
    db.commit()
    if old and old != name:
        (PROOFS / old).unlink(missing_ok=True)
    return schemas.MjeshterMe.model_validate(m)


@app.get("/mjeshtrit/me", response_model=schemas.MjeshterMe | None, tags=["mjeshtrit"])
def mjeshter_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.scalar(select(Mjeshter).where(Mjeshter.user_id == user.id))
    return schemas.MjeshterMe.model_validate(m) if m else None


@app.put("/mjeshtrit/me", response_model=schemas.MjeshterMe, tags=["mjeshtrit"])
def mjeshter_edit(body: schemas.MjeshterEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Change the days you're free, your area or your bio. New skills need a new document."""
    m = db.scalar(select(Mjeshter).where(Mjeshter.user_id == user.id))
    if not m:
        raise HTTPException(404, "You haven't signed up as a mjeshtër")
    if body.neighbourhood and body.neighbourhood not in NEIGHBOURHOODS:
        raise HTTPException(400, "Unknown neighbourhood")
    m.days = ",".join(_csv_in(body.days, DAYS))
    m.neighbourhood = body.neighbourhood or m.neighbourhood
    m.bio = (body.bio or "").strip() or None
    db.commit()
    return schemas.MjeshterMe.model_validate(m)


@app.delete("/mjeshtrit/me", status_code=204, tags=["mjeshtrit"])
def mjeshter_leave(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.scalar(select(Mjeshter).where(Mjeshter.user_id == user.id))
    if m:
        if m.proof_path:
            (PROOFS / m.proof_path).unlink(missing_ok=True)
        db.delete(m)
        db.commit()


@app.get("/mjeshtrit", response_model=list[schemas.MjeshterPublic], tags=["mjeshtrit"])
def mjeshtrit_list(
    skill: str | None = None, day: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Verified mjeshtrit, people from your neighbourhood first, then by jobs done."""
    rows = db.scalars(select(Mjeshter).options(selectinload(Mjeshter.user)).where(Mjeshter.status == "approved")).all()
    result = []
    for m in rows:
        sk = [x for x in (m.verified_skills or "").split(",") if x]
        dd = [x for x in (m.days or "").split(",") if x]
        if (skill and skill not in sk) or (day and day not in dd):
            continue
        done, _pending = _fixer_counts(db, m.user_id)
        parts = m.user.name.split()
        short = parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")
        result.append(schemas.MjeshterPublic(
            id=m.id, name=short, skills=sk, days=dd, neighbourhood=m.neighbourhood, bio=m.bio,
            verified_by=m.verified_by, jobs_done=done, level=level(done)[0],
        ))
    return sorted(result, key=lambda x: (x.neighbourhood != user.neighbourhood, -x.jobs_done, x.name))


def _mjeshtrit_for(db: Session, need: str, area: str | None, skip_user: int | None = None) -> list[tuple[Mjeshter, User]]:
    rows = db.scalars(select(Mjeshter).options(selectinload(Mjeshter.user)).where(Mjeshter.status == "approved")).all()
    picked = [(m, m.user) for m in rows if can_do([x for x in (m.verified_skills or "").split(",") if x], need)
              and m.user_id != skip_user]
    return sorted(picked, key=lambda mu: mu[0].neighbourhood != area)


async def alert_mjeshtrit(report_id: int) -> None:
    """A new skilled job: tell the mjeshtrit with that skill in the same neighbourhood."""
    with SessionLocal() as db:
        r = db.get(Report, report_id)
        need = skill_job(r) if r else None
        if not need or r.status != "reported":
            return
        area = neighbourhood(r.latitude, r.longitude)
        tokens = [u.push_token for m, u in _mjeshtrit_for(db, need, area, r.user_id)
                  if u.push_token and area and (m.neighbourhood == area or u.neighbourhood == area)]
        cat = r.category.name.lower()
    if tokens:
        await send_many(tokens, "🔧 A job for a mjeshtër", f"A {cat} in {area} needs {need if need != 'any' else 'a skilled hand'}.",
                        {"reportId": report_id})


@app.post("/reports/{report_id}/ask-mjeshter", response_model=schemas.AskOut, tags=["mjeshtrit"])
async def ask_mjeshter(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """"Ask a mjeshtër": push the job to verified volunteers with the right skill (own area first)."""
    r = _report_full(db, report_id)
    need = skill_job(r)
    if not need:
        raise HTTPException(400, "This job isn't one for a mjeshtër")
    if r.status != "reported" or r.claimed_by:
        raise HTTPException(409, "Someone is already working on this")
    if r.mjeshter_asked_at and now() - r.mjeshter_asked_at < timedelta(hours=1):
        raise HTTPException(429, "A mjeshtër was already asked in the last hour")
    area = neighbourhood(r.latitude, r.longitude)
    found = _mjeshtrit_for(db, need, area, user.id)[:50]
    tokens = [u.push_token for _m, u in found if u.push_token]
    r.mjeshter_asked_at = now()
    db.commit()
    if tokens:
        await send_many(tokens, "🔧 Can you help?",
                        f"{user.name.split(' ')[0]} is asking a mjeshtër to fix a {r.category.name.lower()}"
                        + (f" in {area}" if area else "") + ".", {"reportId": r.id})
    return schemas.AskOut(notified=len(found))


@app.get("/admin/mjeshtrit", response_model=list[schemas.MjeshterAdmin], tags=["admin"])
def admin_mjeshtrit(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Everyone who applied, waiting ones first."""
    rows = db.scalars(select(Mjeshter).options(selectinload(Mjeshter.user))).all()
    order = {"pending": 0, "rejected": 1, "approved": 2}
    return [_mj_admin(m) for m in sorted(rows, key=lambda m: (order.get(m.status, 3), -m.created_at.timestamp()))]


@app.get("/admin/mjeshtrit/{mj_id}/proof", tags=["admin"])
def admin_mjeshter_proof(mj_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """The uploaded document (only for city staff)."""
    m = db.get(Mjeshter, mj_id)
    if not m or not m.proof_path or not (PROOFS / m.proof_path).exists():
        raise HTTPException(404, "No document")
    return FileResponse(PROOFS / m.proof_path, media_type=m.proof_mime or "application/octet-stream",
                        headers={"Cache-Control": "no-store"})


async def _mj_decide(db: Session, mj_id: int, approve: bool, note: str | None) -> schemas.MjeshterAdmin:
    m = db.get(Mjeshter, mj_id)
    if not m:
        raise HTTPException(404, "Not found")
    m.status = "approved" if approve else "rejected"
    m.verified_by = "admin" if approve else None
    m.verified_skills = m.skills if approve else None
    m.admin_note, m.reviewed_at = (note or "").strip() or None, now()
    db.commit()
    token = m.user.push_token
    if token:
        await send_many([token], "You're a verified mjeshtër ✓" if approve else "About your mjeshtër sign-up",
                        "You can now take skilled jobs and help your neighbourhood." if approve
                        else (m.admin_note or "The city couldn't verify your document. You can send another one."),
                        {"screen": "mjeshtrit"})
    return _mj_admin(m)


@app.post("/admin/mjeshtrit/{mj_id}/approve", response_model=schemas.MjeshterAdmin, tags=["admin"])
async def admin_mjeshter_approve(mj_id: int, body: schemas.NoteIn | None = None, _: User = Depends(admin_user),
                                 db: Session = Depends(get_db)):
    return await _mj_decide(db, mj_id, True, body.note if body else None)


@app.post("/admin/mjeshtrit/{mj_id}/reject", response_model=schemas.MjeshterAdmin, tags=["admin"])
async def admin_mjeshter_reject(mj_id: int, body: schemas.NoteIn | None = None, _: User = Depends(admin_user),
                                db: Session = Depends(get_db)):
    return await _mj_decide(db, mj_id, False, body.note if body else None)


# ---------- partner rewards ----------
# Partner brands (a restaurant, a cinema, a café) give rewards. Admins add them here; a fixer spends
# badges on one and gets a voucher code to show at the partner. No money moves through MendMap.
VOUCHER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread


def _spent(db: Session, user_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(RewardClaim.cost), 0)).where(RewardClaim.user_id == user_id)) or 0


def _claimed_counts(db: Session) -> dict[int, int]:
    return dict(db.execute(select(RewardClaim.reward_id, func.count()).group_by(RewardClaim.reward_id)).all())


def _partner_out(r: PartnerReward, claimed: int = 0) -> schemas.PartnerOut:
    return schemas.PartnerOut(id=r.id, partner=r.partner, title=r.title, details=r.details, emoji=r.emoji or "🎁",
                              cost=r.cost, stock=r.stock, active=bool(r.active), claimed=claimed)


def _claim_out(c: RewardClaim, with_user: bool = False) -> schemas.ClaimOut:
    return schemas.ClaimOut(
        id=c.id, code=c.code, reward_id=c.reward_id, partner=c.reward.partner, title=c.reward.title,
        emoji=c.reward.emoji or "🎁", cost=c.cost, used=bool(c.used), created_at=c.created_at, used_at=c.used_at,
        user_name=c.user.name if with_user else None, user_email=c.user.email if with_user else None,
    )


def _offered(db: Session) -> list[PartnerReward]:
    """Rewards a fixer can see: switched on and not sold out, cheapest first."""
    rows = db.scalars(select(PartnerReward).where(PartnerReward.active == 1).order_by(PartnerReward.cost, PartnerReward.id))
    return [r for r in rows if r.stock is None or r.stock > 0]


def _next_reward(db: Session, balance: int) -> schemas.PartnerOut | None:
    offered = _offered(db)
    if not offered:
        return None
    goal = next((r for r in offered if r.cost > balance), None) or offered[-1]
    return _partner_out(goal)


@app.get("/rewards", response_model=schemas.RewardsOut, tags=["rewards"])
def list_rewards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Partner rewards on offer, the user's badge balance and their vouchers."""
    verified, _pending = _fixer_counts(db, user.id)
    spent = _spent(db, user.id)
    counts = _claimed_counts(db)
    claims = db.scalars(select(RewardClaim).options(selectinload(RewardClaim.reward))
                        .where(RewardClaim.user_id == user.id).order_by(RewardClaim.created_at.desc())).all()
    return schemas.RewardsOut(
        badges=verified, spent=spent, balance=max(0, verified - spent),
        rewards=[_partner_out(r, counts.get(r.id, 0)) for r in _offered(db)],
        claims=[_claim_out(c) for c in claims],
    )


@app.post("/rewards/{reward_id}/claim", response_model=schemas.ClaimOut, status_code=201, tags=["rewards"])
def claim_reward(reward_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Spend badges on a partner reward and get a voucher code."""
    if user.role != "citizen":
        raise HTTPException(403, "Only residents can get rewards")
    r = db.get(PartnerReward, reward_id)
    if not r or not r.active:
        raise HTTPException(404, "This reward is no longer on offer")
    if r.stock is not None and r.stock <= 0:
        raise HTTPException(409, "This reward is sold out")
    verified, _pending = _fixer_counts(db, user.id)
    if verified - _spent(db, user.id) < r.cost:
        raise HTTPException(400, "Not enough badges for this reward yet")
    code = "MM-" + "".join(secrets.choice(VOUCHER_ALPHABET) for _ in range(6))
    while db.scalar(select(RewardClaim.id).where(RewardClaim.code == code)):
        code = "MM-" + "".join(secrets.choice(VOUCHER_ALPHABET) for _ in range(6))
    if r.stock is not None:
        r.stock -= 1
    c = RewardClaim(reward=r, user=user, code=code, cost=r.cost)
    db.add(c)
    db.commit()
    return _claim_out(c)


@app.get("/admin/partners", response_model=list[schemas.PartnerOut], tags=["admin"])
def admin_partners(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Every partner reward, including hidden and sold-out ones."""
    counts = _claimed_counts(db)
    rows = db.scalars(select(PartnerReward).order_by(PartnerReward.active.desc(), PartnerReward.cost)).all()
    return [_partner_out(r, counts.get(r.id, 0)) for r in rows]


@app.post("/admin/partners", response_model=schemas.PartnerOut, status_code=201, tags=["admin"])
async def add_partner(body: schemas.PartnerIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    r = PartnerReward(**body.model_dump(exclude={"active"}), active=int(body.active))
    db.add(r)
    db.commit()
    if body.active:
        tokens = list(db.scalars(select(User.push_token).where(User.role == "citizen", User.push_token.is_not(None))))
        if tokens:
            await send_many(tokens, f"New reward {r.emoji} {r.partner}",
                            f"{r.title} for {r.cost} fixer badges. Fix things nearby to earn it!", {"screen": "rewards"})
    return _partner_out(r)


@app.put("/admin/partners/{reward_id}", response_model=schemas.PartnerOut, tags=["admin"])
def edit_partner(reward_id: int, body: schemas.PartnerIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    r = db.get(PartnerReward, reward_id)
    if not r:
        raise HTTPException(404, "Reward not found")
    for k, v in body.model_dump(exclude={"active"}).items():
        setattr(r, k, v)
    r.active = int(body.active)
    db.commit()
    return _partner_out(r, _claimed_counts(db).get(r.id, 0))


@app.delete("/admin/partners/{reward_id}", status_code=204, tags=["admin"])
def delete_partner(reward_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Delete a reward. One that vouchers were already given for is hidden instead, so those vouchers stay valid."""
    r = db.get(PartnerReward, reward_id)
    if not r:
        raise HTTPException(404, "Reward not found")
    if db.scalar(select(RewardClaim.id).where(RewardClaim.reward_id == reward_id).limit(1)):
        r.active = 0
    else:
        db.delete(r)
    db.commit()


@app.get("/admin/reward-claims", response_model=list[schemas.ClaimOut], tags=["admin"])
def admin_claims(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Vouchers given out, newest first."""
    rows = db.scalars(select(RewardClaim).options(selectinload(RewardClaim.reward), selectinload(RewardClaim.user))
                      .order_by(RewardClaim.used, RewardClaim.created_at.desc())).all()
    return [_claim_out(c, with_user=True) for c in rows]


@app.post("/admin/reward-claims/{claim_id}/used", response_model=schemas.ClaimOut, tags=["admin"])
def claim_used(claim_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Record that the partner took the voucher, so it can't be used twice."""
    c = db.get(RewardClaim, claim_id)
    if not c:
        raise HTTPException(404, "Voucher not found")
    if not c.used:
        c.used, c.used_at = 1, now()
        db.commit()
    return _claim_out(c, with_user=True)


# Mounted last so the /admin/... API routes above take priority over the static panel.
if ADMIN_DIR.exists():
    app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
if PUBLIC_DIR.exists():
    app.mount("/city", StaticFiles(directory=PUBLIC_DIR, html=True), name="city")
