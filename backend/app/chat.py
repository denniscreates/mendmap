"""Community chat: one room for the whole city and one per neighbourhood.

Messages are checked by the AI before they are posted (insults, hate, spam, private data).
Neighbours can report a message; after FLAGS_TO_HIDE reports it is hidden. Admins can delete any message.
The app polls for new messages (?after=<last id>), which works through the Expo tunnel too.
"""
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai, schemas
from .auth import admin_user, current_user
from .db import get_db
from .insights import NEIGHBOURHOODS, neighbourhood
from .models import ChatFlag, ChatMessage, ChatTranslation, CleanupEvent, EventRsvp, Report, User, now
from .push import send_many

router = APIRouter(prefix="/chat", tags=["chat"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

CITY = "city"
CITY_NAME = "Prishtina"
FLAGS_TO_HIDE = 3
PAGE = 50
RATE_N, RATE_S = 5, 30  # at most 5 messages in 30 seconds
_sent: dict[int, deque] = defaultdict(deque)


def _room(room: str) -> str:
    if room != CITY and room not in NEIGHBOURHOODS:
        raise HTTPException(404, "This chat room doesn't exist")
    return room


def _out(m: ChatMessage, me: User) -> schemas.ChatOut:
    u = m.user
    badge = "city" if u.role in ("admin", "crew") else ("mjeshter" if u.mjeshter_status == "approved" else None)
    event = getattr(m, "_event", None)
    report = None
    if m.report_id:
        r = m._report  # set by _with_reports
        if r is not None:
            area = neighbourhood(r.latitude, r.longitude)
            title = r.category.name.capitalize() + (f" · {area}" if area else "")
            report = schemas.ChatReport(id=r.id, title=title, status=r.status, photo_url=r.photo_url)
    return schemas.ChatOut(id=m.id, room=m.room, kind=m.kind or "message", event=event, text=m.text, user_id=u.id,
                           user_name=u.name, badge=badge, report=report, created_at=m.created_at, mine=u.id == me.id)


def _with_reports(db: Session, msgs: list[ChatMessage], me: User | None = None) -> list[ChatMessage]:
    """Loads the shared reports and clean-up days the messages point to (one query each)."""
    ids = {m.report_id for m in msgs if m.report_id}
    found = {r.id: r for r in db.scalars(select(Report).where(Report.id.in_(ids)))} if ids else {}
    ev_ids = {m.event_id for m in msgs if m.event_id}
    events, going, mine = {}, {}, set()
    if ev_ids:
        events = {e.id: e for e in db.scalars(select(CleanupEvent).where(CleanupEvent.id.in_(ev_ids)))}
        going = dict(db.execute(select(EventRsvp.event_id, func.count()).where(EventRsvp.event_id.in_(ev_ids))
                                .group_by(EventRsvp.event_id)).all())
        if me is not None:
            mine = set(db.scalars(select(EventRsvp.event_id).where(EventRsvp.event_id.in_(ev_ids), EventRsvp.user_id == me.id)))
    for m in msgs:
        m._report = found.get(m.report_id)
        e = events.get(m.event_id)
        m._event = schemas.ChatEvent(id=e.id, title=e.title, starts_at=e.starts_at, place=e.place, going=going.get(e.id, 0),
                                     me_going=e.id in mine, cancelled=bool(e.cancelled)) if e else None
    return msgs


def post_message(db: Session, room: str, user: User, text: str, kind: str = "message", event_id: int | None = None) -> ChatMessage:
    """Adds a message without the AI check (city announcements, clean-up day notices)."""
    m = ChatMessage(room=room, user_id=user.id, text=text, kind=kind, event_id=event_id)
    db.add(m)
    db.flush()
    return m


def residents(db: Session, room: str) -> list[str]:
    """Push tokens of the people a room is for: its neighbourhood's residents, or every citizen for the city room."""
    q = select(User.push_token).where(User.role == "citizen", User.push_token.is_not(None))
    if room != CITY:
        q = q.where(User.neighbourhood == room)
    return list(db.scalars(q))


@router.get("/rooms", response_model=list[schemas.ChatRoom])
def rooms(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The city room first, then the user's neighbourhood, then the others (busiest first)."""
    visible = ChatMessage.hidden == 0
    last_ids = dict(db.execute(select(ChatMessage.room, func.max(ChatMessage.id)).where(visible).group_by(ChatMessage.room)).all())
    today = dict(db.execute(
        select(ChatMessage.room, func.count()).where(visible, ChatMessage.created_at >= now() - timedelta(hours=24))
        .group_by(ChatMessage.room)
    ).all())
    last = {m.room: m for m in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(last_ids.values())))} if last_ids else {}
    out = []
    for rid in [CITY, *NEIGHBOURHOODS]:
        m = last.get(rid)
        out.append(schemas.ChatRoom(
            id=rid, name=CITY_NAME if rid == CITY else rid, mine=rid == user.neighbourhood,
            last_id=m.id if m else None, last_text=m.text if m else None, last_name=m.user.name if m else None,
            last_at=m.created_at if m else None, today=today.get(rid, 0),
        ))
    head, rest = out[0], out[1:]
    rest.sort(key=lambda r: (not r.mine, -(r.today), -(r.last_id or 0), r.name))
    return [head, *rest]


@router.get("/rooms/{room}/messages", response_model=list[schemas.ChatOut])
def messages(
    room: str,
    after: int | None = Query(None, description="Only messages newer than this id (polling)"),
    before: int | None = Query(None, description="Only messages older than this id (scrolling back)"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Oldest first. Without after/before: the latest PAGE messages."""
    room = _room(room)
    q = select(ChatMessage).where(ChatMessage.room == room, ChatMessage.hidden == 0)
    if after is not None:
        msgs = list(db.scalars(q.where(ChatMessage.id > after).order_by(ChatMessage.id).limit(200)))
    else:
        if before is not None:
            q = q.where(ChatMessage.id < before)
        msgs = list(reversed(db.scalars(q.order_by(ChatMessage.id.desc()).limit(PAGE)).all()))
    return [_out(m, user) for m in _with_reports(db, msgs, user)]


@router.get("/rooms/{room}/hidden", response_model=list[int])
def hidden_since(room: str, after: int = Query(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ids from `after` on that were hidden or deleted, so open chats can remove them."""
    room = _room(room)
    return list(db.scalars(select(ChatMessage.id).where(ChatMessage.room == room, ChatMessage.hidden == 1,
                                                        ChatMessage.id >= after)))


@router.post("/rooms/{room}/messages", response_model=schemas.ChatOut, status_code=201)
async def send(room: str, body: schemas.ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = _room(room)
    text = " ".join(body.text.split()) if "\n" not in body.text else body.text.strip()
    if not text:
        raise HTTPException(422, "Write a message first")
    sent = _sent[user.id]
    t = time.monotonic()
    while sent and t - sent[0] > RATE_S:
        sent.popleft()
    if len(sent) >= RATE_N:
        raise HTTPException(429, "You're sending messages too fast. Wait a moment.")
    if body.report_id is not None and db.get(Report, body.report_id) is None:
        raise HTTPException(404, "Report not found")
    check = await ai.moderate_chat(text, body.lang)
    if check["ok"] is False:
        raise HTTPException(422, check["reason"] or "This message breaks the community rules")
    sent.append(t)
    m = ChatMessage(room=room, user_id=user.id, text=text, report_id=body.report_id)
    db.add(m)
    db.commit()
    db.refresh(m)
    return _out(_with_reports(db, [m], user)[0], user)


@router.post("/messages/{message_id}/flag", response_model=schemas.FlagOut)
def flag(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Report a message. Hidden after FLAGS_TO_HIDE reports, or at once when city staff report it."""
    m = db.get(ChatMessage, message_id)
    if m is None or m.hidden:
        raise HTTPException(404, "Message not found")
    if m.user_id == user.id:
        raise HTTPException(400, "You can't report your own message")
    if db.get(ChatFlag, (m.id, user.id)) is None:
        db.add(ChatFlag(message_id=m.id, user_id=user.id))
        m.flags += 1
    if m.flags >= FLAGS_TO_HIDE or user.role == "admin":
        m.hidden = 1
    db.commit()
    return schemas.FlagOut(flags=m.flags, hidden=bool(m.hidden))


@router.delete("/messages/{message_id}", status_code=204)
def delete(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(ChatMessage, message_id)
    if m is None or m.hidden:
        raise HTTPException(404, "Message not found")
    if m.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You can only delete your own messages")
    m.hidden = 1
    db.commit()


@router.post("/messages/{message_id}/translate", response_model=schemas.TranslateChatOut)
async def translate(message_id: int, body: schemas.TranslateChatIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """See translation: the AI translates a message into the reader's language (once per language)."""
    m = db.get(ChatMessage, message_id)
    if m is None or m.hidden:
        raise HTTPException(404, "Message not found")
    if body.lang not in ai.LANG_NAMES:
        raise HTTPException(400, "This language isn't available")
    done = db.get(ChatTranslation, (m.id, body.lang))
    if done:
        return schemas.TranslateChatOut(text=done.text)
    text = await ai.translate_text(m.text, body.lang)
    if not text:
        raise HTTPException(503, "Translation isn't available right now. Try again later.")
    if db.get(ChatTranslation, (m.id, body.lang)) is None:
        db.add(ChatTranslation(message_id=m.id, lang=body.lang, text=text[:2000]))
        db.commit()
    return schemas.TranslateChatOut(text=text)


# ---------- city staff ----------
def _admin_out(m: ChatMessage) -> schemas.ChatAdmin:
    return schemas.ChatAdmin(id=m.id, room=m.room, kind=m.kind or "message", text=m.text, user_id=m.user_id,
                             user_name=m.user.name, user_email=m.user.email, flags=m.flags, hidden=bool(m.hidden),
                             created_at=m.created_at)


@admin_router.get("/chat", response_model=list[schemas.ChatAdmin])
def admin_messages(flagged: bool = True, room: str | None = None, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Reported (or hidden) messages, for moderation. flagged=false lists the latest messages."""
    q = select(ChatMessage)
    if room:
        q = q.where(ChatMessage.room == room)
    if flagged:
        q = q.where((ChatMessage.flags > 0) | (ChatMessage.hidden == 1)).order_by(
            ChatMessage.hidden, ChatMessage.flags.desc(), ChatMessage.id.desc())
    else:
        q = q.order_by(ChatMessage.id.desc())
    return [_admin_out(m) for m in db.scalars(q.limit(200))]


@admin_router.post("/chat/{message_id}/hide", response_model=schemas.ChatAdmin)
def admin_hide(message_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = db.get(ChatMessage, message_id)
    if m is None:
        raise HTTPException(404, "Message not found")
    m.hidden = 1
    db.commit()
    return _admin_out(m)


@admin_router.post("/chat/{message_id}/restore", response_model=schemas.ChatAdmin)
def admin_restore(message_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """The reports were wrong: show the message again and clear its reports."""
    m = db.get(ChatMessage, message_id)
    if m is None:
        raise HTTPException(404, "Message not found")
    m.hidden, m.flags = 0, 0
    for f in db.scalars(select(ChatFlag).where(ChatFlag.message_id == m.id)):
        db.delete(f)
    db.commit()
    return _admin_out(m)


@admin_router.post("/announcements", response_model=list[schemas.ChatAdmin], status_code=201)
def announce(body: schemas.AnnouncementIn, tasks: BackgroundTasks, user: User = Depends(admin_user),
             db: Session = Depends(get_db)):
    """A city announcement (road works, water cuts, clean-up times) in one or more rooms, with a push."""
    rooms = list(dict.fromkeys(_room(r) for r in body.rooms))
    text = body.text.strip()
    msgs = [post_message(db, r, user, text, kind="announcement") for r in rooms]
    db.commit()
    if body.push:
        tokens = list(dict.fromkeys(t for r in rooms for t in residents(db, r)))
        title = "📢 Prishtina" if CITY in rooms else "📢 " + ", ".join(rooms)[:60]
        tasks.add_task(send_many, tokens, title, text[:180], {"screen": "chat", "room": rooms[0]})
    return [_admin_out(m) for m in msgs]
