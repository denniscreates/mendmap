from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

STATUSES = ("reported", "in_progress", "fixed")
ROLES = ("citizen", "admin", "crew")


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # citizen = reports problems, admin = city dashboard, crew = field team that fixes them
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="user_role"), default="citizen")
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "Near you" alerts: reports within ALERT_RADIUS_M of this point.
    home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Neighbourhood the user lives in (asked at sign-up): they may fix problems there.
    neighbourhood: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Skilled volunteer profile (mjeshtër), if they applied. Loaded with the user.
    mjeshter: Mapped["Mjeshter | None"] = relationship(back_populates="user", lazy="selectin", uselist=False)

    def _mj(self):
        return None if "mjeshter" in inspect(self).unloaded else self.mjeshter

    @property
    def mjeshter_status(self) -> str | None:
        m = self._mj()
        return m.status if m else None

    @property
    def mjeshter_skills(self) -> list[str]:
        """Skills this user is a verified mjeshtër for (empty unless approved)."""
        m = self._mj()
        return [s for s in (m.verified_skills or "").split(",") if s] if m and m.status == "approved" else []

    # Neighbour-fix rewards already paid out (one reward per REWARD_EVERY verified fixes).
    rewards_paid: Mapped[int] = mapped_column(Integer, default=0)
    # How the account was made: email, google or apple (Google/Apple are demo sign-ins for now).
    auth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Paid jobs: the mjeshtër's Stripe Connect account (they get their share of each booking there).
    stripe_account: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payouts_ready: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    icon: Mapped[str] = mapped_column(String(50))


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repeat_of: Mapped[int | None] = mapped_column(Integer, nullable=True)  # reported again at a spot fixed recently
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)  # street the citizen picked, e.g. "Rr. Agim Ramadani"
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(Enum(*STATUSES, name="report_status"), default="reported", index=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5, suggested by the AI photo check
    after_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # taken by the crew when fixed
    voice_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # optional voice note
    voice_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # transcript, filled in by AI
    # Neighbour fix: a resident of the area takes the job.
    claimed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fix_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None | pending | verified
    # AI photo check, run on the server after the report is saved (None = not checked).
    ai_is_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_neighbour_safe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_safety_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_photo_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)  # real_photo, screenshot, drawing...
    ai_kind_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Fraud checks. ai_flags: comma-separated codes (fake_photo, not_problem, reused_photo:<id>).
    photo_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_description: Mapped[str | None] = mapped_column(Text, nullable=True)  # what the AI sees in the photo
    blurred: Mapped[int | None] = mapped_column(Integer, nullable=True)  # faces/plates blurred for privacy
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 = the reporter confirmed the fix
    reopened: Mapped[int] = mapped_column(Integer, default=0)  # times the reporter said "not fixed"
    # Skilled job: too much for an ordinary neighbour, but a skilled volunteer (mjeshtër) can do it.
    ai_skilled_ok: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_skill_needed: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mjeshter_asked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_flags: Mapped[str | None] = mapped_column(String(300), nullable=True)
    flag_cleared: Mapped[int] = mapped_column(Integer, default=0)  # an official looked and it's fine
    # AI check of a neighbour's fix: auto_verified, looks_fixed, not_fixed, different_place, fake
    fix_ai: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fix_ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    claimer: Mapped[User | None] = relationship(foreign_keys=[claimed_by])
    category: Mapped[Category] = relationship()
    updates: Mapped[list["StatusUpdate"]] = relationship(
        back_populates="report", order_by="StatusUpdate.created_at", cascade="all, delete-orphan"
    )


class StatusUpdate(Base):
    __tablename__ = "status_updates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    report: Mapped[Report] = relationship(back_populates="updates")
    admin: Mapped[User | None] = relationship()


class OtpCode(Base):
    """One-time sign-up code sent to an email address. Only a hash of the code is stored."""

    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Mjeshter(Base):
    """A skilled volunteer ("mjeshtër": plumber, painter, builder...) who fixes things on days the city
    doesn't work. They upload proof of their skill; the AI checks it, and the city can approve or reject."""

    __tablename__ = "mjeshtrit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    skills: Mapped[str] = mapped_column(String(200))  # what they say they can do (comma list)
    verified_skills: Mapped[str | None] = mapped_column(String(200), nullable=True)  # what was approved
    days: Mapped[str | None] = mapped_column(String(100), nullable=True)  # weekday_evenings, saturday, sunday, holidays
    neighbourhood: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, rejected
    verified_by: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ai, admin
    proof_path: Mapped[str | None] = mapped_column(String(300), nullable=True)  # private, never served publicly
    proof_mime: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ai_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)  # legit, suspicious, fake, not_a_document
    ai_doc_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_name_on_doc: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ai_name_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_issuer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ai_skills: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ai_looks_genuine: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # for the city, English
    ai_reason_user: Mapped[str | None] = mapped_column(Text, nullable=True)  # for the applicant, their language
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship(back_populates="mjeshter")


class PartnerReward(Base):
    """A reward offered by a partner brand (e.g. a free dinner for two). Admins add them; fixers pay in badges."""

    __tablename__ = "partner_rewards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partner: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    emoji: Mapped[str] = mapped_column(String(16), default="🎁")
    cost: Mapped[int] = mapped_column(Integer, default=20)  # badges
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)  # vouchers left; None = no limit
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RewardClaim(Base):
    """A voucher a fixer got for their badges. The partner checks the code; the city marks it used."""

    __tablename__ = "reward_claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reward_id: Mapped[int] = mapped_column(ForeignKey("partner_rewards.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    cost: Mapped[int] = mapped_column(Integer)  # badges spent, kept even if the reward's price changes later
    used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reward: Mapped[PartnerReward] = relationship()
    user: Mapped[User] = relationship()


class ChatMessage(Base):
    """A message in the community chat: one room for the whole city and one per neighbourhood."""

    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room: Mapped[str] = mapped_column(String(60), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)  # a shared report
    kind: Mapped[str] = mapped_column(String(20), default="message")  # message | announcement (city) | event
    event_id: Mapped[int | None] = mapped_column(ForeignKey("cleanup_events.id"), nullable=True)
    flags: Mapped[int] = mapped_column(Integer, default=0)  # how many people reported it
    hidden: Mapped[int] = mapped_column(Integer, default=0)  # 1 = deleted or hidden after reports
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    user: Mapped[User] = relationship(lazy="joined")


class ChatTranslation(Base):
    """A chat message translated by the AI into one language (done once, then shared)."""

    __tablename__ = "chat_translations"
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), primary_key=True)
    lang: Mapped[str] = mapped_column(String(8), primary_key=True)
    text: Mapped[str] = mapped_column(Text)


class CleanupEvent(Base):
    """A clean-up day ("aksion") neighbours organise: a time, a meeting point, who's coming.
    After it, the organiser ticks who came; each of them earns a badge."""

    __tablename__ = "cleanup_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room: Mapped[str] = mapped_column(String(60), index=True)  # neighbourhood, or "city"
    title: Mapped[str] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    place: Mapped[str] = mapped_column(String(200))  # meeting point
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    cancelled: Mapped[int] = mapped_column(Integer, default=0)
    reminded: Mapped[int] = mapped_column(Integer, default=0)  # the day-before reminder went out
    done: Mapped[int] = mapped_column(Integer, default=0)  # attendance was recorded
    organiser: Mapped[User] = relationship(lazy="joined")


class EventRsvp(Base):
    """ "I'm coming" to a clean-up day; attended = the organiser confirmed they came."""

    __tablename__ = "event_rsvps"
    event_id: Mapped[int] = mapped_column(ForeignKey("cleanup_events.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    attended: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    user: Mapped[User] = relationship(lazy="joined")


class StreetAdoption(Base):
    """A resident, school or business looks after a street: they hear about every new problem on it."""

    __tablename__ = "street_adoptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    street: Mapped[str] = mapped_column(String(200))  # as shown, e.g. "Rruga Agim Ramadani"
    key: Mapped[str] = mapped_column(String(200), index=True)  # normalised, see community.street_key
    sponsor: Mapped[str | None] = mapped_column(String(80), nullable=True)  # school or business name
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    user: Mapped[User] = relationship(lazy="joined")


class ChatFlag(Base):
    """Who reported a chat message, so each person counts once."""

    __tablename__ = "chat_flags"
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Confirmation(Base):
    """Who pressed "I see this too", so one user can confirm a report only once."""

    __tablename__ = "report_confirmations"
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# Columns added after the first release. create_all() only creates missing tables,
# so existing databases get the new columns here.
class Booking(Base):
    """A paid job: a resident asks a mjeshtër for a price (with a photo), the mjeshtër quotes, the resident pays.
    status: requested -> quoted -> paid -> done, or declined / cancelled."""

    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mjeshter_id: Mapped[int] = mapped_column(ForeignKey("mjeshtrit.id"))
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(300), nullable=True)  # private, never served publicly
    status: Mapped[str] = mapped_column(String(20), default="requested", index=True)
    fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commission_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)  # MendMap's share, set when paid
    currency: Mapped[str] = mapped_column(String(3), default="eur")
    quote_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer: Mapped[User] = relationship(foreign_keys=[customer_id], lazy="selectin")
    worker: Mapped[User] = relationship(foreign_keys=[worker_id], lazy="selectin")


NEW_COLUMNS = {
    "chat_messages": {"kind": "VARCHAR(20) NOT NULL DEFAULT 'message'", "event_id": "INTEGER"},
    "users": {"home_lat": "FLOAT", "home_lng": "FLOAT", "neighbourhood": "VARCHAR(60)", "rewards_paid": "INTEGER NOT NULL DEFAULT 0",
              "auth_provider": "VARCHAR(20)", "stripe_account": "VARCHAR(60)", "payouts_ready": "INTEGER NOT NULL DEFAULT 0"},
    "reports": {
        "severity": "INTEGER", "after_photo_url": "VARCHAR(500)", "voice_url": "VARCHAR(500)", "voice_text": "TEXT",
        "claimed_by": "INTEGER", "claimed_at": "DATETIME", "fix_status": "VARCHAR(20)",
        "ai_is_problem": "INTEGER", "ai_category": "VARCHAR(30)", "ai_severity": "INTEGER", "ai_reason": "TEXT",
        "ai_neighbour_safe": "INTEGER", "ai_safety_reason": "TEXT",
        "ai_photo_kind": "VARCHAR(20)", "ai_kind_reason": "TEXT", "photo_hash": "VARCHAR(16)", "after_hash": "VARCHAR(16)",
        "ai_flags": "VARCHAR(300)", "flag_cleared": "INTEGER NOT NULL DEFAULT 0",
        "fix_ai": "VARCHAR(20)", "fix_ai_reason": "TEXT",
        "address": "VARCHAR(200)", "repeat_of": "INTEGER", "ai_description": "TEXT", "blurred": "INTEGER", "rating": "INTEGER", "reopened": "INTEGER NOT NULL DEFAULT 0",
        "ai_skilled_ok": "INTEGER", "ai_skill_needed": "VARCHAR(20)", "mjeshter_asked_at": "DATETIME",
    },
}


def migrate(engine) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        if engine.dialect.name == "mysql":  # native ENUM needs the new role
            conn.execute(text("ALTER TABLE users MODIFY role ENUM('citizen','admin','crew') NOT NULL DEFAULT 'citizen'"))
