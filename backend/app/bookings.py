"""Booking a mjeshtër for a paid job, with a price quote first, and the money held until the job is done.

1. A resident snaps a photo of the job, writes what's wrong and sends it to a verified mjeshtër.
2. The mjeshtër looks at the photo and answers with a fee (or declines).
3. The resident pays the fee by card or Apple Pay (Stripe PaymentSheet). The money stays with MendMap.
4. The mjeshtër does the job and taps "I finished the job".
5. The resident taps "Job done": MendMap keeps its commission (10% by default) and sends the rest to the
   mjeshtër's own Stripe account. If the resident doesn't answer within AUTO_RELEASE_DAYS of the mjeshtër
   finishing, the money is sent automatically.
6. If something is wrong, the resident taps "Report a problem" instead. The money stays held and a city admin
   decides in the dashboard: pay the mjeshtër, or refund the resident in full.

Stripe pattern: "separate charges and transfers". The payment lands on MendMap's account (with a transfer_group),
and the payout is a Transfer to the mjeshtër's Connect account, linked to the charge (source_transaction).

Stripe is called over its REST API with httpx (no extra dependency). Settings in backend/.env:
- STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY: test keys (sk_test_..., pk_test_...) until you go live.
- STRIPE_WEBHOOK_SECRET: optional, for POST /stripe/webhook. Without it the app confirms each payment
  by asking Stripe directly (POST /bookings/{id}/confirm-payment).
- MENDMAP_COMMISSION: share MendMap keeps, default 0.10.
- MENDMAP_AUTO_RELEASE_DAYS: days after "I finished the job" before the money is sent anyway, default 3.
- MENDMAP_CURRENCY: default eur. MENDMAP_MERCHANT_COUNTRY: the Stripe account's country for Apple Pay, default DE.
- MENDMAP_DEMO_PAYMENTS=on: with no Stripe keys, "paying" just marks the booking paid. For testing only;
  never turn this on for real users.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import schemas
from .auth import admin_user, current_user
from .db import SessionLocal, get_db
from .models import Booking, Mjeshter, User, now
from .push import send_many

log = logging.getLogger("mendmap.bookings")
router = APIRouter(tags=["bookings"])

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "private" / "bookings"  # photos of people's homes: only the two people in the booking see them
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
MAX_PHOTO = 12 * 1024 * 1024
MAX_OPEN = 5  # open requests per resident
MIN_FEE, MAX_FEE = 5, 5000  # euros
STRIPE = "https://api.stripe.com/v1"
OPEN = ("requested", "quoted")


# ---------- settings ----------
def _secret() -> str | None:
    return os.getenv("STRIPE_SECRET_KEY") or None


def _publishable() -> str | None:
    return os.getenv("STRIPE_PUBLISHABLE_KEY") or None


def stripe_on() -> bool:
    return bool(_secret() and _publishable())


def demo_on() -> bool:
    return not stripe_on() and os.getenv("MENDMAP_DEMO_PAYMENTS", "off").lower() == "on"


def commission_rate() -> float:
    try:
        return min(0.5, max(0.0, float(os.getenv("MENDMAP_COMMISSION", "0.10"))))
    except ValueError:
        return 0.10


def auto_release_days() -> float:
    try:
        return max(0.0, float(os.getenv("MENDMAP_AUTO_RELEASE_DAYS", "3")))
    except ValueError:
        return 3.0


def currency() -> str:
    return os.getenv("MENDMAP_CURRENCY", "eur").lower()


def split(fee_cents: int) -> tuple[int, int]:
    """(MendMap's commission, what the mjeshtër gets) in cents."""
    fee = round(fee_cents * commission_rate())
    return fee, fee_cents - fee


# ---------- Stripe over REST ----------
def _form(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's nested form encoding: {"a": {"b": 1}} -> a[b]=1."""
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            out += _form(v, key)
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


async def stripe_call(method: str, path: str, data: dict | None = None, idem: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_secret()}"}
    if idem:
        headers["Idempotency-Key"] = idem
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.request(method, STRIPE + path, data=_form(data or {}), headers=headers)
    except httpx.HTTPError as exc:
        log.warning("Stripe %s %s failed: %s", method, path, exc)
        raise HTTPException(502, "The payment service didn't answer. Try again.")
    body = r.json() if r.content else {}
    if r.status_code >= 400:
        log.warning("Stripe %s %s -> %s: %s", method, path, r.status_code, body.get("error", {}).get("message"))
        raise HTTPException(502, "The payment service refused the request. Try again later.")
    return body


# ---------- helpers ----------
def _short(name: str) -> str:
    parts = name.split()
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def _get(db: Session, booking_id: int, user: User) -> Booking:
    b = db.get(Booking, booking_id)
    if not b or (user.id not in (b.customer_id, b.worker_id) and user.role != "admin"):
        raise HTTPException(404, "Booking not found")
    return b


def _release_at(b: Booking):
    return b.worker_done_at + timedelta(days=auto_release_days()) if b.worker_done_at and b.status == "paid" else None


def _out(b: Booking, me: User) -> schemas.BookingOut:
    commission, worker_gets = split(b.fee_cents) if b.fee_cents else (None, None)
    if b.commission_cents is not None:  # what was actually charged
        commission, worker_gets = b.commission_cents, (b.fee_cents or 0) - b.commission_cents
    return schemas.BookingOut(
        id=b.id, status=b.status, description=b.description, address=b.address, report_id=b.report_id,
        has_photo=bool(b.photo_path), fee_cents=b.fee_cents, commission_cents=commission, worker_gets_cents=worker_gets,
        currency=b.currency, quote_note=b.quote_note, decline_note=b.decline_note,
        customer_name=_short(b.customer.name), worker_name=_short(b.worker.name), mjeshter_id=b.mjeshter_id,
        skill=b.skill, as_role="worker" if me.id == b.worker_id else "customer",
        created_at=b.created_at, quoted_at=b.quoted_at, paid_at=b.paid_at, done_at=b.done_at,
        commission_rate=commission_rate(), worker_done_at=b.worker_done_at, auto_release_at=_release_at(b),
        problem_note=b.problem_note, admin_note=b.admin_note, released_at=b.released_at, refunded_at=b.refunded_at,
    )


def _admin_out(b: Booking, me: User) -> schemas.BookingAdmin:
    o = schemas.BookingAdmin(**_out(b, me).model_dump())
    o.customer_name, o.worker_name = b.customer.name, b.worker.name
    o.customer_email, o.worker_email = b.customer.email, b.worker.email
    o.pay_mode, o.payment_intent, o.transfer_id, o.refund_id = b.pay_mode, b.payment_intent, b.transfer_id, b.refund_id
    return o


def _push(user: User, title: str, body: str, booking_id: int, bg: BackgroundTasks | None) -> None:
    if not user.push_token:
        return
    args = ([user.push_token], title, body, {"screen": "booking", "id": booking_id})
    if bg is not None:
        bg.add_task(send_many, *args)
    else:
        asyncio.get_event_loop().create_task(send_many(*args))


def _mark_paid(db: Session, b: Booking, mode: str, charge: str | None = None) -> bool:
    if b.status != "quoted":
        return False
    b.status, b.paid_at, b.updated_at, b.pay_mode = "paid", now(), now(), mode
    b.charge_id = charge or b.charge_id
    b.commission_cents = split(b.fee_cents or 0)[0]
    db.commit()
    return True


async def release(db: Session, b: Booking, who: str) -> None:
    """Send the mjeshtër their share. MendMap's commission stays on its own Stripe balance."""
    if b.status not in ("paid", "disputed"):
        raise HTTPException(409, "There's no held payment to send")
    commission = b.commission_cents if b.commission_cents is not None else split(b.fee_cents or 0)[0]
    gets = (b.fee_cents or 0) - commission
    if b.pay_mode == "stripe":
        if not stripe_on():
            raise HTTPException(503, "Payments aren't set up on this server yet")
        if not b.worker.stripe_account:
            raise HTTPException(409, "This mjeshtër can't receive payments yet")
        if not b.charge_id:
            pi = await stripe_call("GET", f"/payment_intents/{b.payment_intent}")
            b.charge_id = pi.get("latest_charge")
        tr = await stripe_call("POST", "/transfers", {
            "amount": gets, "currency": b.currency, "destination": b.worker.stripe_account,
            "source_transaction": b.charge_id, "transfer_group": f"booking-{b.id}",
            "metadata": {"booking_id": b.id, "released_by": who},
        }, idem=f"release-{b.id}")
        b.transfer_id = tr.get("id")
    b.status, b.released_at, b.done_at, b.updated_at = "done", now(), now(), now()
    b.commission_cents = commission
    db.commit()
    log.info("Booking %s: %s cents sent to the mjeshtër (%s)", b.id, gets, who)


async def refund(db: Session, b: Booking, who: str) -> None:
    """Give the resident all their money back. MendMap keeps nothing."""
    if b.status not in ("paid", "disputed"):
        raise HTTPException(409, "Only a held payment can be refunded here")
    if b.pay_mode == "stripe":
        if not stripe_on():
            raise HTTPException(503, "Payments aren't set up on this server yet")
        rf = await stripe_call("POST", "/refunds", {
            "payment_intent": b.payment_intent, "metadata": {"booking_id": b.id, "refunded_by": who},
        }, idem=f"refund-{b.id}")
        b.refund_id = rf.get("id")
    b.status, b.refunded_at, b.updated_at, b.commission_cents = "refunded", now(), now(), 0
    db.commit()
    log.info("Booking %s refunded (%s)", b.id, who)


# ---------- the booking flow ----------
@router.post("/bookings", response_model=schemas.BookingOut, status_code=201)
async def create_booking(
    bg: BackgroundTasks,
    mjeshter_id: int = Form(...),
    description: str = Form(..., min_length=5, max_length=1000),
    photo: UploadFile = File(...),
    address: str | None = Form(None, max_length=200),
    report_id: int | None = Form(None),
    skill: str | None = Form(None, max_length=20),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Ask a mjeshtër for a price. The photo shows them how big the job is."""
    m = db.get(Mjeshter, mjeshter_id)
    if not m or m.status != "approved":
        raise HTTPException(404, "This mjeshtër isn't available")
    if m.user_id == user.id:
        raise HTTPException(400, "You can't book yourself")
    if user.role == "crew":
        raise HTTPException(403, "Crew accounts can't book a mjeshtër")
    open_n = len(db.scalars(select(Booking.id).where(Booking.customer_id == user.id, Booking.status.in_(OPEN))).all())
    if open_n >= MAX_OPEN:
        raise HTTPException(429, "You already have 5 open requests. Wait for answers first.")
    ext = PHOTO_TYPES.get((photo.content_type or "").split(";")[0])
    if not ext:
        raise HTTPException(415, "Unsupported photo type")
    data = await photo.read()
    if not data:
        raise HTTPException(400, "The photo is empty")
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "The photo is too large")
    PHOTOS.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (PHOTOS / name).write_bytes(data)
    verified = [x for x in (m.verified_skills or "").split(",") if x]
    b = Booking(
        customer_id=user.id, worker_id=m.user_id, mjeshter_id=m.id, description=description.strip(),
        address=(address or "").strip() or None, report_id=report_id, photo_path=name,
        skill=skill if skill in verified else (verified[0] if len(verified) == 1 else None), currency=currency(),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    _push(m.user, "New job request", f"{_short(user.name)}: {b.description[:90]}", b.id, bg)
    return _out(b, user)


@router.get("/bookings", response_model=list[schemas.BookingOut])
def my_bookings(as_role: str | None = Query(None, alias="as", pattern="^(customer|worker)$"),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Booking)
    if as_role == "customer":
        q = q.where(Booking.customer_id == user.id)
    elif as_role == "worker":
        q = q.where(Booking.worker_id == user.id)
    else:
        q = q.where(or_(Booking.customer_id == user.id, Booking.worker_id == user.id))
    return [_out(b, user) for b in db.scalars(q.order_by(Booking.updated_at.desc()).limit(100)).all()]


@router.get("/bookings/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(_get(db, booking_id, user), user)


@router.get("/bookings/{booking_id}/photo")
def booking_photo(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Only the resident, the mjeshtër and admins can see the photo."""
    b = _get(db, booking_id, user)
    path = PHOTOS / Path(b.photo_path or "").name
    if not b.photo_path or not path.is_file():
        raise HTTPException(404, "No photo")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/bookings/{booking_id}/quote", response_model=schemas.BookingOut)
async def quote(booking_id: int, body: schemas.QuoteIn, bg: BackgroundTasks,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The mjeshtër names the fee. They can change it until the resident pays."""
    b = _get(db, booking_id, user)
    if user.id != b.worker_id:
        raise HTTPException(403, "Only the mjeshtër can send the price")
    if b.status not in OPEN:
        raise HTTPException(409, "This request is closed")
    if not MIN_FEE <= body.fee <= MAX_FEE:
        raise HTTPException(400, f"The fee must be between {MIN_FEE} and {MAX_FEE} euros")
    if stripe_on():
        await _refresh_payouts(db, user)
        if not user.payouts_ready:
            raise HTTPException(409, "Set up payouts first, so you can get paid")
        if b.payment_intent:  # the resident may be paying the old price right now: don't lose that payment
            pi = await stripe_call("GET", f"/payment_intents/{b.payment_intent}")
            if pi.get("status") == "succeeded":
                _mark_paid(db, b, "stripe", pi.get("latest_charge"))
                raise HTTPException(409, "This booking is already paid")
            if pi.get("status") in ("processing", "requires_capture", "requires_action"):
                raise HTTPException(409, "The resident is paying right now. Try again in a minute.")
            if pi.get("status") != "canceled":  # so the old price can't be paid any more
                try:
                    await stripe_call("POST", f"/payment_intents/{b.payment_intent}/cancel", {})
                except HTTPException:
                    pass
    b.fee_cents = round(body.fee * 100)
    b.quote_note = (body.note or "").strip() or None
    b.status, b.quoted_at, b.updated_at = "quoted", now(), now()
    b.payment_intent = None  # a new price needs a new payment
    db.commit()
    _push(b.customer, "You got a price", f"{_short(user.name)}: €{body.fee:.2f}", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/decline", response_model=schemas.BookingOut)
def decline(booking_id: int, body: schemas.NoteIn, bg: BackgroundTasks,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get(db, booking_id, user)
    if user.id != b.worker_id:
        raise HTTPException(403, "Only the mjeshtër can decline")
    if b.status not in OPEN:
        raise HTTPException(409, "This request is closed")
    b.status, b.decline_note, b.updated_at = "declined", (body.note or "").strip() or None, now()
    db.commit()
    _push(b.customer, "Request declined", f"{_short(user.name)} can't take this job", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel(booking_id: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get(db, booking_id, user)
    if user.id != b.customer_id:
        raise HTTPException(403, "Only the person who asked can cancel")
    if b.status not in OPEN:
        raise HTTPException(409, "A paid job can't be cancelled. Tap “Report a problem” instead.")
    b.status, b.updated_at = "cancelled", now()
    db.commit()
    _push(b.worker, "Request cancelled", f"{_short(user.name)} cancelled the request", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/pay", response_model=schemas.PayOut)
async def pay(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start paying the quoted fee. Returns what Stripe's PaymentSheet needs (card and Apple Pay).
    The money lands on MendMap's account and is held there until the job is done."""
    b = _get(db, booking_id, user)
    if user.id != b.customer_id:
        raise HTTPException(403, "Only the person who asked can pay")
    if b.status != "quoted" or not b.fee_cents:
        raise HTTPException(409, "There's no price to pay yet")
    commission, _ = split(b.fee_cents)
    base = dict(amount_cents=b.fee_cents, commission_cents=commission, currency=b.currency,
                merchant_country=os.getenv("MENDMAP_MERCHANT_COUNTRY", "DE").upper())
    if demo_on():
        return schemas.PayOut(mode="demo", **base)
    if not stripe_on():
        raise HTTPException(503, "Payments aren't set up on this server yet")
    worker = b.worker
    await _refresh_payouts(db, worker)
    if not worker.payouts_ready:
        raise HTTPException(409, "This mjeshtër can't receive payments yet")
    pi = None
    if b.payment_intent:  # reuse the payment started earlier, unless the price changed
        pi = await stripe_call("GET", f"/payment_intents/{b.payment_intent}")
        if pi.get("status") == "succeeded":
            _mark_paid(db, b, "stripe", pi.get("latest_charge"))
            raise HTTPException(409, "This booking is already paid")
        if pi.get("amount") != b.fee_cents or pi.get("status") == "canceled":
            pi = None
    if pi is None:
        pi = await stripe_call("POST", "/payment_intents", {
            "amount": b.fee_cents, "currency": b.currency,
            "automatic_payment_methods": {"enabled": True},
            "transfer_group": f"booking-{b.id}",  # the payout to the mjeshtër comes later, when the job is done
            "description": f"MendMap booking #{b.id}",
            "metadata": {"booking_id": b.id, "customer_id": user.id, "worker_id": worker.id},
        }, idem=f"booking-{b.id}-{b.fee_cents}-{int(b.quoted_at.timestamp()) if b.quoted_at else 0}")
        b.payment_intent = pi["id"]
        db.commit()
    return schemas.PayOut(mode="stripe", client_secret=pi["client_secret"], publishable_key=_publishable(), **base)


@router.post("/bookings/{booking_id}/confirm-payment", response_model=schemas.BookingOut)
async def confirm_payment(booking_id: int, bg: BackgroundTasks,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Called by the app after the payment sheet closes. Checks with Stripe that the money really came in."""
    b = _get(db, booking_id, user)
    if user.id != b.customer_id:
        raise HTTPException(403, "Only the person who asked can pay")
    if b.status != "quoted":
        return _out(b, user)
    if demo_on():
        ok, mode, charge = True, "demo", None
    else:
        if not stripe_on() or not b.payment_intent:
            raise HTTPException(409, "There's no payment to check")
        pi = await stripe_call("GET", f"/payment_intents/{b.payment_intent}")
        ok = (pi.get("status") == "succeeded" and str(pi.get("metadata", {}).get("booking_id")) == str(b.id)
              and pi.get("amount") == b.fee_cents)
        mode, charge = "stripe", pi.get("latest_charge")
    if not ok:
        raise HTTPException(402, "The payment didn't go through")
    if _mark_paid(db, b, mode, charge):
        _push(b.worker, "Paid! You can do the job",
              f"{_short(user.name)} paid €{b.fee_cents / 100:.2f}. MendMap holds it until the job is done.", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/finished", response_model=schemas.BookingOut)
def worker_finished(booking_id: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The mjeshtër says the job is finished. The resident then confirms, or the money is sent after a few days."""
    b = _get(db, booking_id, user)
    if user.id != b.worker_id:
        raise HTTPException(403, "Only the mjeshtër can say the job is finished")
    if b.status != "paid":
        raise HTTPException(409, "Only a paid job can be finished")
    if not b.worker_done_at:
        b.worker_done_at, b.updated_at = now(), now()
        db.commit()
        days = auto_release_days()
        _push(b.customer, "Is the job done?",
              f"{_short(user.name)} says it's finished. Confirm, or report a problem within {days:g} days.", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/done", response_model=schemas.BookingOut)
async def mark_done(booking_id: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The resident confirms the job is done: the mjeshtër gets paid."""
    b = _get(db, booking_id, user)
    if user.id != b.customer_id:
        raise HTTPException(403, "Only the person who booked can confirm the job")
    if b.status != "paid":
        raise HTTPException(409, "Only a paid job can be marked done")
    await release(db, b, "customer")
    _push(b.worker, "You got paid", f"{_short(user.name)} confirmed the job. €{(b.fee_cents - b.commission_cents) / 100:.2f} is on its way.", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/problem", response_model=schemas.BookingOut)
def report_problem(booking_id: int, body: schemas.ProblemIn, bg: BackgroundTasks,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The resident isn't happy: the money stays held and a city admin decides (pay out or refund)."""
    b = _get(db, booking_id, user)
    if user.id != b.customer_id:
        raise HTTPException(403, "Only the person who booked can report a problem")
    if b.status != "paid":
        raise HTTPException(409, "You can report a problem only while the payment is held")
    b.status, b.problem_note, b.updated_at = "disputed", body.note.strip(), now()
    db.commit()
    _push(b.worker, "The resident reported a problem",
          f"{_short(user.name)}: {b.problem_note[:80]}. MendMap will look at it.", b.id, bg)
    admins = db.scalars(select(User.push_token).where(User.role == "admin", User.push_token.is_not(None))).all()
    if admins:
        bg.add_task(send_many, list(admins), "Booking problem", f"Booking #{b.id}: {b.problem_note[:80]}",
                    {"screen": "booking", "id": b.id})
    return _out(b, user)


# ---------- automatic payout when the resident doesn't answer ----------
async def release_due() -> int:
    """Send the money for jobs the mjeshtër finished AUTO_RELEASE_DAYS ago without an answer from the resident."""
    cutoff = now() - timedelta(days=auto_release_days())
    sent = 0
    with SessionLocal() as db:
        due = db.scalars(select(Booking).where(Booking.status == "paid", Booking.worker_done_at.is_not(None),
                                               Booking.worker_done_at <= cutoff)).all()
        for b in due:
            try:
                await release(db, b, "auto")
            except HTTPException as exc:
                log.warning("Auto payout of booking %s failed: %s", b.id, exc.detail)
                db.rollback()
                continue
            sent += 1
            for u, text in ((b.worker, "The money for your job is on its way."),
                            (b.customer, f"No problem was reported, so {_short(b.worker.name)} was paid.")):
                if u.push_token:
                    await send_many([u.push_token], "Job paid", text, {"screen": "booking", "id": b.id})
    return sent


async def release_loop() -> None:
    while True:
        try:
            await release_due()
        except Exception as exc:  # never let the loop die
            log.warning("Automatic payouts failed: %s", exc)
        await asyncio.sleep(600)


# ---------- city admins: held money, problems, payouts and refunds ----------
@router.get("/admin/bookings", response_model=list[schemas.BookingAdmin], tags=["admin"])
def admin_bookings(status: str | None = None, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(Booking)
    if status:
        q = q.where(Booking.status.in_(status.split(",")))
    rows = db.scalars(q.order_by(Booking.updated_at.desc()).limit(300)).all()
    first = {"disputed": 0, "paid": 1}
    return [_admin_out(b, me) for b in sorted(rows, key=lambda b: first.get(b.status, 2))]


@router.get("/admin/bookings/summary", response_model=schemas.BookingSummary, tags=["admin"])
def admin_bookings_summary(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).where(Booking.status.in_(("paid", "disputed", "done", "refunded")))).all()
    s = schemas.BookingSummary(currency=currency(), commission_rate=commission_rate(), auto_release_days=auto_release_days(),
                               stripe=stripe_on(), demo=demo_on())
    for b in rows:
        fee = b.fee_cents or 0
        if b.status in ("paid", "disputed"):
            s.held_cents += fee
            s.held += 1
            s.disputed += b.status == "disputed"
        elif b.status == "done":
            s.paid_out_cents += fee - (b.commission_cents or 0)
            s.earned_cents += b.commission_cents or 0
            s.done += 1
        else:
            s.refunded_cents += fee
            s.refunded += 1
    return s


@router.post("/admin/bookings/{booking_id}/release", response_model=schemas.BookingAdmin, tags=["admin"])
async def admin_release(booking_id: int, body: schemas.NoteIn, bg: BackgroundTasks,
                        me: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Decide for the mjeshtër: send them their share."""
    b = _get(db, booking_id, me)
    b.admin_note = (body.note or "").strip() or b.admin_note
    await release(db, b, "admin")
    _push(b.worker, "You got paid", "MendMap sent the money for your job.", b.id, bg)
    _push(b.customer, "Booking closed", b.admin_note or "MendMap looked at the problem and paid the mjeshtër.", b.id, bg)
    return _admin_out(b, me)


@router.post("/admin/bookings/{booking_id}/refund", response_model=schemas.BookingAdmin, tags=["admin"])
async def admin_refund(booking_id: int, body: schemas.NoteIn, bg: BackgroundTasks,
                       me: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Decide for the resident: give all their money back."""
    b = _get(db, booking_id, me)
    b.admin_note = (body.note or "").strip() or b.admin_note
    await refund(db, b, "admin")
    _push(b.customer, "You got a refund", b.admin_note or "MendMap refunded your payment in full.", b.id, bg)
    _push(b.worker, "Booking refunded", b.admin_note or "MendMap refunded the resident for this job.", b.id, bg)
    return _admin_out(b, me)


# ---------- Stripe webhook (optional) ----------
def _signed(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", "0"))
    except ValueError:
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    sigs = [v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p) if k == "v1"]
    return any(hmac.compare_digest(expected, s) for s in sigs)


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(404, "Not found")
    payload = await request.body()
    if not _signed(payload, request.headers.get("stripe-signature", ""), secret):
        raise HTTPException(400, "Bad signature")
    event = json.loads(payload)
    obj = event.get("data", {}).get("object", {})
    with SessionLocal() as db:
        if event.get("type") == "payment_intent.succeeded":
            bid = obj.get("metadata", {}).get("booking_id")
            b = db.get(Booking, int(bid)) if bid and str(bid).isdigit() else None
            if b and b.payment_intent == obj.get("id") and _mark_paid(db, b, "stripe", obj.get("latest_charge")):
                await send_many([b.worker.push_token] if b.worker.push_token else [], "Paid! You can do the job",
                                f"Booking #{b.id} was paid. MendMap holds it until the job is done.",
                                {"screen": "booking", "id": b.id})
        elif event.get("type") == "account.updated":
            u = db.scalar(select(User).where(User.stripe_account == obj.get("id")))
            if u:
                u.payouts_ready = int(bool(obj.get("charges_enabled") and obj.get("payouts_enabled")))
                db.commit()
    return {"ok": True}


# ---------- payouts for mjeshtrit (Stripe Connect Express) ----------
async def _refresh_payouts(db: Session, user: User) -> None:
    if not stripe_on() or not user.stripe_account:
        return
    acct = await stripe_call("GET", f"/accounts/{user.stripe_account}")
    ready = int(bool(acct.get("charges_enabled") and acct.get("payouts_enabled")))
    if ready != (user.payouts_ready or 0):
        user.payouts_ready = ready
        db.commit()


def _base_url(request: Request) -> str:
    return (os.getenv("MENDMAP_PUBLIC_URL") or str(request.base_url)).rstrip("/")


@router.get("/payouts/me", response_model=schemas.PayoutsOut)
async def payouts_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    await _refresh_payouts(db, user)
    return schemas.PayoutsOut(configured=stripe_on(), demo=demo_on(), started=bool(user.stripe_account),
                              ready=bool(user.payouts_ready) or demo_on(), commission_rate=commission_rate())


@router.post("/payouts/onboard", response_model=schemas.LinkOut)
async def payouts_onboard(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A Stripe page where the mjeshtër adds their bank account and ID. Stripe pays them out from then on."""
    if user.mjeshter_status != "approved":
        raise HTTPException(403, "Only verified mjeshtrit can get paid")
    if not stripe_on():
        raise HTTPException(503, "Payments aren't set up on this server yet")
    if not user.stripe_account:
        acct = await stripe_call("POST", "/accounts", {
            "type": "express", "email": user.email,
            "capabilities": {"card_payments": {"requested": True}, "transfers": {"requested": True}},
            "business_type": "individual", "metadata": {"mendmap_user": user.id},
        }, idem=f"acct-{user.id}")
        user.stripe_account = acct["id"]
        db.commit()
    base = _base_url(request)
    link = await stripe_call("POST", "/account_links", {
        "account": user.stripe_account, "type": "account_onboarding",
        "refresh_url": f"{base}/payouts/again", "return_url": f"{base}/payouts/return",
    })
    return schemas.LinkOut(url=link["url"])


_PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>MendMap</title><body style="font-family:system-ui;background:#070d1f;color:#e9edf7;display:grid;
place-items:center;min-height:90vh;text-align:center;padding:24px"><div><h2>{title}</h2><p>{body}</p></div>"""


@router.get("/payouts/return", include_in_schema=False, response_class=HTMLResponse)
def payouts_return():
    return _PAGE.format(title="All set", body="Close this page and go back to MendMap.")


@router.get("/payouts/again", include_in_schema=False, response_class=HTMLResponse)
def payouts_again():
    return _PAGE.format(title="The link expired", body="Go back to MendMap and tap “Set up payouts” again.")
