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
    mjeshter_status: str | None = None   # pending, approved, rejected; None = never applied
    mjeshter_skills: list[str] = []      # verified skills (only when approved)


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
    address: str | None = None
    repeat_of: int | None = None
    photo_url: str | None
    photos: list[str] = []  # every photo, the cover first
    edited_at: datetime | None = None
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
    ai_description: str | None = None
    blurred: int | None = None   # faces and number plates blurred for privacy
    rating: int | None = None    # 1 = the reporter confirmed the fix
    reopened: int = 0            # times the reporter said it wasn't fixed
    skill_needed: str | None = None  # a job for a mjeshtër: plumbing, painting... or "any"


def _csv(v):
    if v is None:
        return []
    return [x for x in v.split(",") if x] if isinstance(v, str) else v


class MjeshterMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    _split = field_validator("skills", "verified_skills", "days", mode="before")(classmethod(lambda cls, v: _csv(v)))
    status: str
    skills: list[str]
    verified_skills: list[str]
    days: list[str]
    neighbourhood: str | None = None
    bio: str | None = None
    verified_by: str | None = None
    ai_verdict: str | None = None
    ai_reason_user: str | None = None
    admin_note: str | None = None
    created_at: datetime


class MjeshterPublic(BaseModel):
    id: int
    name: str
    skills: list[str]
    days: list[str]
    neighbourhood: str | None = None
    bio: str | None = None
    verified_by: str | None = None
    jobs_done: int = 0
    level: str = "starter"


class MjeshterAdmin(MjeshterMe):
    _split2 = field_validator("ai_skills", mode="before")(classmethod(lambda cls, v: _csv(v)))
    id: int
    user_id: int
    user_name: str = ""
    user_email: str = ""
    proof_mime: str | None = None
    ai_doc_type: str | None = None
    ai_name_on_doc: str | None = None
    ai_name_matches: bool | None = None
    ai_issuer: str | None = None
    ai_skills: list[str] = []
    ai_looks_genuine: bool | None = None
    ai_confidence: int | None = None
    ai_reason: str | None = None
    reviewed_at: datetime | None = None


class MjeshterEdit(BaseModel):
    days: list[str] = []
    neighbourhood: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=500)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AskOut(BaseModel):
    notified: int


class TranslateIn(BaseModel):
    lang: str = Field(min_length=2, max_length=5)
    strings: list[str] = Field(max_length=1500)


class TranslateOut(BaseModel):
    lang: str
    translations: dict[str, str]  # English text -> translation
    missing: int = 0              # still untranslated (the AI was busy): ask again later


class RateIn(BaseModel):
    ok: bool
    comment: str | None = Field(default=None, max_length=500)


class ReportDetail(ReportOut):
    adopted_by: list[str] = []
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
    description: str | None = None       # the AI's description of the photo, in the user's language
    blur_boxes: list[dict] = []          # faces and plates the server will blur


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
    avg_fix_days: float | None = None  # report -> fixed, on average
    fixed_in_week: float | None = None  # share of fixed reports fixed within 7 days
    came_back: int = 0  # reported again after a fix


class PublicStats(StatsOut):
    fix_rate: float
    neighbourhoods: list[NeighbourhoodStat]


class Job(ReportOut):
    """A crew job: an in-progress report, in driving order."""
    stop: int
    leg_m: float | None = None


class PartnerIn(BaseModel):
    partner: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    details: str | None = Field(default=None, max_length=500)
    emoji: str = Field(default="🎁", max_length=16)
    cost: int = Field(default=20, ge=1, le=1000)
    stock: int | None = Field(default=None, ge=0)
    active: bool = True


class PartnerOut(PartnerIn):
    id: int
    claimed: int = 0


class ClaimOut(BaseModel):
    id: int
    code: str
    reward_id: int
    partner: str
    title: str
    emoji: str
    cost: int
    used: bool
    created_at: datetime
    used_at: datetime | None = None
    user_name: str | None = None
    user_email: str | None = None


class RewardsOut(BaseModel):
    """Partner rewards and the fixer's badge wallet: every accepted fix is a badge to spend."""
    badges: int
    spent: int
    balance: int
    rewards: list[PartnerOut]
    claims: list[ClaimOut]


class FixerOut(BaseModel):
    """Neighbour-fixer progress: every verified fix is a badge, spent on partner rewards."""
    neighbourhood: str | None
    verified: int
    pending: int
    active: list[ReportOut]
    balance: int = 0                     # badges not spent yet
    spent: int = 0
    next_reward: PartnerOut | None = None  # cheapest reward still out of reach (or the cheapest one)
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


class CrewStats(BaseModel):
    """A crew member's own work record, shown on their profile instead of citizen badges."""
    open_jobs: int
    fixed_today: int
    fixed_week: int
    fixed_total: int
    avg_days_to_fix: float | None


# ---------- community chat ----------
class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    report_id: int | None = None
    lang: str = "en"  # for the reason, if the AI blocks the message


class ChatReport(BaseModel):
    id: int
    title: str
    status: str
    photo_url: str | None = None


class ChatEvent(BaseModel):
    id: int
    title: str
    starts_at: datetime
    place: str
    going: int
    me_going: bool = False
    cancelled: bool = False


class ChatOut(BaseModel):
    id: int
    room: str
    kind: str = "message"  # message | announcement | event
    event: ChatEvent | None = None
    text: str
    user_id: int
    user_name: str
    badge: str | None = None  # "city" (city staff) or "mjeshter" (verified skilled volunteer)
    report: ChatReport | None = None
    created_at: datetime
    mine: bool = False


class ChatRoom(BaseModel):
    id: str  # "city" or a neighbourhood name
    name: str
    mine: bool = False  # the user's own neighbourhood
    last_id: int | None = None
    last_text: str | None = None
    last_name: str | None = None
    last_at: datetime | None = None
    today: int = 0  # messages in the last 24 hours


class FlagOut(BaseModel):
    flags: int
    hidden: bool


# ---------- street search ----------
class Place(BaseModel):
    name: str  # "Rruga Agim Ramadani" or "Sheshi Nënë Tereza"
    detail: str | None = None  # area, or street for a place
    kind: str  # "street" | "place"
    latitude: float
    longitude: float


# ---------- chat extras ----------
class TranslateChatIn(BaseModel):
    lang: str = Field(min_length=2, max_length=8)


class TranslateChatOut(BaseModel):
    text: str


class AnnouncementIn(BaseModel):
    rooms: list[str] = Field(min_length=1)  # "city" = everyone
    text: str = Field(min_length=1, max_length=1000)
    push: bool = True


class ChatAdmin(BaseModel):
    id: int
    room: str
    kind: str
    text: str
    user_id: int
    user_name: str
    user_email: str
    flags: int
    hidden: bool
    created_at: datetime


# ---------- clean-up days ----------
class EventIn(BaseModel):
    room: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=3, max_length=120)
    details: str | None = Field(default=None, max_length=1000)
    starts_at: datetime  # UTC
    place: str = Field(min_length=2, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class EventPerson(BaseModel):
    user_id: int
    name: str
    attended: bool = False


class EventOut(BaseModel):
    id: int
    room: str
    title: str
    details: str | None
    starts_at: datetime
    place: str
    latitude: float | None
    longitude: float | None
    organiser_id: int
    organiser_name: str
    going: int
    me_going: bool = False
    mine: bool = False
    cancelled: bool = False
    done: bool = False
    past: bool = False
    people: list[EventPerson] = []  # only for the organiser (to tick who came)


class AttendanceIn(BaseModel):
    user_ids: list[int]


# ---------- adopt a street ----------
class AdoptIn(BaseModel):
    street: str = Field(min_length=2, max_length=200)
    sponsor: str | None = Field(default=None, max_length=80)


class AdoptionOut(BaseModel):
    id: int
    street: str
    sponsor: str | None
    open: int = 0  # open problems on the street right now
    created_at: datetime


class Adopter(BaseModel):
    name: str  # first name, or the sponsor's name


# ---------- city summary & top 10 ----------
class TopReport(BaseModel):
    id: int
    title: str
    address: str | None
    neighbourhood: str | None
    status: str
    confirmations: int
    photo_url: str | None
    created_at: datetime


class SummaryOut(BaseModel):
    days: int
    text: str | None  # the AI's summary; None when no AI is set up
    new: int
    fixed: int
    waiting_long: int  # open for more than 10 days
    came_back: int
    top_areas: list[tuple[str, int]]
    top_streets: list[tuple[str, int]]


# ---------- paid bookings ----------
class BookingOut(BaseModel):
    id: int
    status: str  # requested, quoted, declined, cancelled, paid (held), disputed, done (paid out), refunded
    description: str
    address: str | None = None
    report_id: int | None = None
    has_photo: bool = False
    fee_cents: int | None = None
    commission_cents: int | None = None
    worker_gets_cents: int | None = None
    commission_rate: float = 0.10
    currency: str = "eur"
    quote_note: str | None = None
    decline_note: str | None = None
    customer_name: str
    worker_name: str
    mjeshter_id: int
    skill: str | None = None
    as_role: str  # customer or worker: which side the caller is on
    created_at: datetime
    quoted_at: datetime | None = None
    paid_at: datetime | None = None
    done_at: datetime | None = None
    worker_done_at: datetime | None = None  # the mjeshtër said "I finished the job"
    auto_release_at: datetime | None = None  # when the money is sent if the resident doesn't answer
    problem_note: str | None = None
    admin_note: str | None = None
    released_at: datetime | None = None
    refunded_at: datetime | None = None


class BookingAdmin(BookingOut):
    customer_email: str | None = None
    worker_email: str | None = None
    pay_mode: str | None = None
    payment_intent: str | None = None
    transfer_id: str | None = None
    refund_id: str | None = None


class BookingSummary(BaseModel):
    currency: str
    commission_rate: float
    auto_release_days: float
    stripe: bool
    demo: bool
    held: int = 0
    held_cents: int = 0
    disputed: int = 0
    done: int = 0
    paid_out_cents: int = 0
    earned_cents: int = 0  # MendMap's commission on finished jobs
    refunded: int = 0
    refunded_cents: int = 0


class ProblemIn(BaseModel):
    note: str = Field(..., min_length=5, max_length=1000)


class QuoteIn(BaseModel):
    fee: float  # euros
    note: str | None = Field(None, max_length=500)


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=500)


class PayOut(BaseModel):
    mode: str  # stripe or demo
    client_secret: str | None = None
    publishable_key: str | None = None
    amount_cents: int
    commission_cents: int
    currency: str
    merchant_country: str


class PayoutsOut(BaseModel):
    configured: bool  # Stripe keys are set on the server
    demo: bool
    started: bool
    ready: bool
    commission_rate: float


class LinkOut(BaseModel):
    url: str
