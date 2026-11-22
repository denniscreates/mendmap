"""Booking a mjeshtër for a paid job, with a price quote first.

1. A resident snaps a photo of the job, writes what's wrong and sends it to a verified mjeshtër.
2. The mjeshtër looks at the photo and answers with a fee (or declines).
3. The resident pays the fee by card or Apple Pay (Stripe PaymentSheet). MendMap keeps a commission
   (10% by default) and Stripe sends the rest to the mjeshtër's own Stripe account (Connect payouts).
4. When the job is done, either side marks it done.

Stripe is called over its REST API with httpx (no extra dependency). Settings in backend/.env:
- STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY: test keys (sk_test_..., pk_test_...) until you go live.
- STRIPE_WEBHOOK_SECRET: optional, for POST /stripe/webhook. Without it the app confirms each payment
  by asking Stripe directly (POST /bookings/{id}/confirm-payment).
- MENDMAP_COMMISSION: share MendMap keeps, default 0.10.
- MENDMAP_CURRENCY: default eur. MENDMAP_MERCHANT_COUNTRY: the Stripe account's country for Apple Pay, default DE.
- MENDMAP_DEMO_PAYMENTS=on: with no Stripe keys, "paying" just marks the booking paid. For testing only;
  never turn this on for real users.
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import schemas
from .auth import current_user
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
        commission_rate=commission_rate(),
    )


def _push(user: User, title: str, body: str, booking_id: int, bg: BackgroundTasks) -> None:
    if user.push_token:
        bg.add_task(send_many, [user.push_token], title, body, {"screen": "booking", "id": booking_id})


def _mark_paid(db: Session, b: Booking) -> bool:
    if b.status != "quoted":
        return False
    b.status, b.paid_at, b.updated_at = "paid", now(), now()
    b.commission_cents = split(b.fee_cents or 0)[0]
    db.commit()
    return True


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
        raise HTTPException(409, "A paid booking can't be cancelled here. Contact MendMap for a refund.")
    b.status, b.updated_at = "cancelled", now()
    db.commit()
    _push(b.worker, "Request cancelled", f"{_short(user.name)} cancelled the request", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/pay", response_model=schemas.PayOut)
async def pay(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start paying the quoted fee. Returns what Stripe's PaymentSheet needs (card and Apple Pay)."""
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
            _mark_paid(db, b)
            raise HTTPException(409, "This booking is already paid")
        if pi.get("amount") != b.fee_cents or pi.get("status") == "canceled":
            pi = None
    if pi is None:
        pi = await stripe_call("POST", "/payment_intents", {
            "amount": b.fee_cents, "currency": b.currency,
            "automatic_payment_methods": {"enabled": True},
            "application_fee_amount": commission,  # MendMap's share
            "transfer_data": {"destination": worker.stripe_account},  # the rest goes to the mjeshtër
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
    if b.status == "paid":
        return _out(b, user)
    if demo_on():
        paid = b.status == "quoted"
    else:
        if not stripe_on() or not b.payment_intent:
            raise HTTPException(409, "There's no payment to check")
        pi = await stripe_call("GET", f"/payment_intents/{b.payment_intent}")
        paid = pi.get("status") == "succeeded" and str(pi.get("metadata", {}).get("booking_id")) == str(b.id)
    if not paid:
        raise HTTPException(402, "The payment didn't go through")
    if _mark_paid(db, b):
        _push(b.worker, "Paid! You can do the job", f"{_short(user.name)} paid €{b.fee_cents / 100:.2f}", b.id, bg)
    return _out(b, user)


@router.post("/bookings/{booking_id}/done", response_model=schemas.BookingOut)
def mark_done(booking_id: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get(db, booking_id, user)
    if user.id not in (b.customer_id, b.worker_id):
        raise HTTPException(403, "Not your booking")
    if b.status != "paid":
        raise HTTPException(409, "Only a paid job can be marked done")
    b.status, b.done_at, b.updated_at = "done", now(), now()
    db.commit()
    other = b.worker if user.id == b.customer_id else b.customer
    _push(other, "Job done", f"Booking #{b.id} was marked done. Thank you!", b.id, bg)
    return _out(b, user)


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
            if b and b.payment_intent == obj.get("id") and _mark_paid(db, b):
                await send_many([b.worker.push_token] if b.worker.push_token else [], "Paid! You can do the job",
                                f"Booking #{b.id} was paid", {"screen": "booking", "id": b.id})
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
