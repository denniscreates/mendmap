from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
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
    # Neighbour-fix rewards already paid out (one reward per REWARD_EVERY verified fixes).
    rewards_paid: Mapped[int] = mapped_column(Integer, default=0)
    # How the account was made: email, google or apple (Google/Apple are demo sign-ins for now).
    auth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
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


class Confirmation(Base):
    """Who pressed "I see this too", so one user can confirm a report only once."""

    __tablename__ = "report_confirmations"
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# Columns added after the first release. create_all() only creates missing tables,
# so existing databases get the new columns here.
NEW_COLUMNS = {
    "users": {"home_lat": "FLOAT", "home_lng": "FLOAT", "neighbourhood": "VARCHAR(60)", "rewards_paid": "INTEGER NOT NULL DEFAULT 0",
              "auth_provider": "VARCHAR(20)"},
    "reports": {
        "severity": "INTEGER", "after_photo_url": "VARCHAR(500)", "voice_url": "VARCHAR(500)", "voice_text": "TEXT",
        "claimed_by": "INTEGER", "claimed_at": "DATETIME", "fix_status": "VARCHAR(20)",
        "ai_is_problem": "INTEGER", "ai_category": "VARCHAR(30)", "ai_severity": "INTEGER", "ai_reason": "TEXT",
        "ai_neighbour_safe": "INTEGER", "ai_safety_reason": "TEXT",
        "ai_photo_kind": "VARCHAR(20)", "ai_kind_reason": "TEXT", "photo_hash": "VARCHAR(16)", "after_hash": "VARCHAR(16)",
        "ai_flags": "VARCHAR(300)", "flag_cleared": "INTEGER NOT NULL DEFAULT 0",
        "fix_ai": "VARCHAR(20)", "fix_ai_reason": "TEXT",
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
