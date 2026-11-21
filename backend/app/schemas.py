from datetime import datetime
from typing import Literal

from pydantic import field_validator, BaseModel, ConfigDict, Field

Status = Literal["reported", "in_progress", "fixed"]


class Register(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=6, max_length=128)
    neighbourhood: str | None = Field(default=None, max_length=60)
    code: str | None = Field(default=None, max_length=12)  # one-time code sent to the email


class OtpSend(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    # register: refuse straight away if the email already has an account (no code wasted).
    purpose: Literal["register", "social"] = "register"


class OtpSent(BaseModel):
    sent: bool
    expires_in: int
    resend_in: int
    existing: bool = False  # social: this email already has an account, so it's a sign-in
    # Demo mode only (no email service configured): the code, so the app can show it.
    demo_code: str | None = None


class SocialIn(BaseModel):
    """Demo Google/Apple sign-in: the chosen account's email is confirmed with a one-time code."""
    provider: Literal["google", "apple"]
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    code: str = Field(min_length=4, max_length=12)
    neighbourhood: str | None = Field(default=None, max_length=60)


class NeighbourhoodIn(BaseModel):
    neighbourhood: str | None = Field(default=None, max_length=60)


class Login(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str
    home_lat: float | None = None
    home_lng: float | None = None
    neighbourhood: str | None = None


class HomeIn(BaseModel):
    """Set to null to turn "near you" alerts off."""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TokenOut(BaseModel):
    token: str
    user: UserOut
    is_new: bool = False


class PushTokenIn(BaseModel):
    push_token: str | None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    icon: str


class StatusUpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    old_status: str | None
    new_status: str
    comment: str | None
    created_at: datetime


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("ai_flags", mode="before")
    @classmethod
    def _split_flags(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [f for f in v.split(",") if f]
        return v
    id: int
    user_id: int
    category: CategoryOut
    description: str | None
    photo_url: str | None
    latitude: float
    longitude: float
    status: Status
    confirmations: int
    severity: int | None = None
    after_photo_url: str | None = None
    voice_url: str | None = None
    voice_text: str | None = None
    created_at: datetime
    updated_at: datetime
    distance_m: float | None = None
    # Computed, not stored (see insights.py)
    priority: int = 0
    priority_reasons: list[str] = []
    neighbourhood: str | None = None
    # Neighbour fix
    claimed_by: int | None = None
    claimed_by_name: str | None = None
    fix_status: str | None = None
    neighbour_fixable: bool = False
    claim_deadline: datetime | None = None  # a neighbour's job goes back to the map after this
    # Server-side AI check of the photo (all None until it has run).
    ai_is_problem: bool | None = None
    ai_category: str | None = None
    ai_severity: int | None = None
    ai_reason: str | None = None
    ai_neighbour_safe: bool | None = None
    ai_safety_reason: str | None = None
    ai_photo_kind: str | None = None
    ai_kind_reason: str | None = None
    # Fraud checks: flags is a list like ["fake_photo", "reused_photo"]; flagged = flags not cleared by an official.
    ai_flags: list[str] = []
    reused_from: int | None = None
    flagged: bool = False
    flag_cleared: bool = False
    fix_ai: str | None = None
    fix_ai_reason: str | None = None


class ReportDetail(ReportOut):
    updates: list[StatusUpdateOut]
    reporter_name: str | None = None


class StatusChange(BaseModel):
    status: Status
    comment: str | None = Field(default=None, max_length=1000)


class CategoryStat(BaseModel):
    category: str
    total: int
    reported: int
    in_progress: int
    fixed: int
    avg_days_to_fix: float | None


class StatsOut(BaseModel):
    total: int
    reported: int
    in_progress: int
    fixed: int
    avg_days_to_fix: float | None
    per_category: list[CategoryStat]


class PhotoCheck(BaseModel):
    """Result of the AI photo check. available=False when no Claude API credentials are set."""
    available: bool
    is_street_problem: bool = True
    category: str | None = None  # category icon key
    severity: int | None = None
    reason: str | None = None
    neighbour_safe: bool | None = None  # could a resident fix this safely?
    safety_reason: str | None = None
    photo_kind: str | None = None  # real_photo, screenshot, photo_of_screen, drawing, ai_generated, stock_or_web, edited
    kind_reason: str | None = None


class Badge(BaseModel):
    key: str
    earned: bool
    progress: int
    goal: int


class NeighbourhoodStat(BaseModel):
    name: str
    total: int
    fixed: int
    open: int
    fix_rate: float


class PublicStats(StatsOut):
    fix_rate: float
    neighbourhoods: list[NeighbourhoodStat]


class Job(ReportOut):
    """A crew job: an in-progress report, in driving order."""
    stop: int
    leg_m: float | None = None


class FixerOut(BaseModel):
    """Neighbour-fixer progress: every verified fix is a badge; every REWARD_EVERY badges earns a reward."""
    neighbourhood: str | None
    verified: int
    pending: int
    active: list[ReportOut]
    goal: int
    reward_eur: int
    rewards_earned: int
    rewards_paid: int
    level: str = "starter"           # starter, helper, fixer, hero, legend
    next_level_at: int | None = None  # badges needed for the next level
    claim_hours: int = 48
    max_active: int = 3
    available: list[ReportOut] = []   # open jobs in the fixer's own neighbourhood


class TopFixer(BaseModel):
    name: str
    neighbourhood: str | None
    badges: int
    level: str


class FixVerdict(BaseModel):
    ok: bool
    comment: str | None = Field(default=None, max_length=1000)


class RewardOut(BaseModel):
    user_id: int
    name: str
    email: str
    neighbourhood: str | None
    verified: int
    rewards_earned: int
    rewards_paid: int
    owed_eur: int


class CrewStats(BaseModel):
    """A crew member's own work record, shown on their profile instead of citizen badges."""
    open_jobs: int
    fixed_today: int
    fixed_week: int
    fixed_total: int
    avg_days_to_fix: float | None
