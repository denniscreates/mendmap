"""AI features: photo check and voice-note transcription.

Photo check: looks at a report photo, suggests the category and a severity from 1 to 5,
and says whether it shows a street problem at all (selfies and random photos are caught
before they reach the city).

Transcription: turns a voice note into text in the language it was spoken (Albanian,
English, ...), so the city can read and search it.

Providers, chosen with MENDMAP_AI_PROVIDER (default "auto"):
- gemini: set GEMINI_API_KEY in backend/.env. Does the photo check and transcription.
          GEMINI_MODEL picks the model (default gemini-3.8-flash); when it is busy or slow,
          the next model in GEMINI_FALLBACK_MODELS is tried.
- claude: set ANTHROPIC_API_KEY in backend/.env. Does the photo check (no audio input).
- auto:   Gemini if GEMINI_API_KEY is set, otherwise Claude if ANTHROPIC_API_KEY is set.

Without credentials the photo check answers {"available": false} and the app skips it;
voice notes are kept as audio. MENDMAP_AI=off turns everything off.
"""
import base64
import io
import asyncio
import json
import hashlib
import logging
import os
import time

from PIL import Image

log = logging.getLogger("mendmap.ai")

CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_DEFAULT_FALLBACKS = "gemini-3.7-flash,gemini-3.5-flash,gemini-3.1-flash-lite"
GEMINI_TIMEOUT_MS = 20_000  # per model; a citizen is waiting on the photo check
GEMINI_HEDGE_S = 2.0  # no answer yet? start the next model too, and keep whichever answers first
GEMINI_TOTAL_S = 25.0  # give up after this long in total
CACHE_S = 3600  # the app checks the photo before sending, the server again after: answer once
GEMINI_BUSY_SKIP_S = 300  # skip a model that was busy for 5 minutes
CATEGORIES = ["pothole", "streetlight", "dumping", "accessibility", "other"]
# Skills a mjeshtër (skilled volunteer) can have.
SKILLS = ["plumbing", "electrics", "building", "painting", "carpentry", "gardening", "welding"]
DOC_TYPES = ["vocational_diploma", "trade_certificate", "professional_licence", "training_certificate",
             "employer_letter", "university_degree", "other_document", "not_a_document"]
VERDICTS = ["legit", "suspicious", "fake", "not_a_document"]
# What kind of picture it is. Only "real_photo" counts as evidence.
PHOTO_KINDS = ["real_photo", "screenshot", "photo_of_screen", "drawing", "ai_generated", "stock_or_web", "edited"]

SCHEMA = {
    "type": "object",
    "properties": {
        "is_street_problem": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "reason": {"type": "string"},
        "neighbour_safe": {"type": "boolean"},
        "safety_reason": {"type": "string"},
        "photo_kind": {"type": "string", "enum": PHOTO_KINDS},
        "kind_reason": {"type": "string"},
        "description": {"type": "string"},
        "skilled_ok": {"type": "boolean"},
        "skill_needed": {"type": "string", "enum": SKILLS + ["none"]},
        "blur_boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["face", "plate"]},
                    "box": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["image", "kind", "box"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_street_problem", "category", "severity", "reason", "neighbour_safe", "safety_reason",
                 "photo_kind", "kind_reason", "description", "blur_boxes",
                 "skilled_ok", "skill_needed"],
    "additionalProperties": False,
}
# Gemini's JSON schema support: plain ranges instead of an integer enum.
GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "is_street_problem": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "severity": {"type": "integer", "minimum": 1, "maximum": 5},
        "reason": {"type": "string"},
        "neighbour_safe": {"type": "boolean"},
        "safety_reason": {"type": "string"},
        "photo_kind": {"type": "string", "enum": PHOTO_KINDS},
        "kind_reason": {"type": "string"},
        "description": {"type": "string"},
        "skilled_ok": {"type": "boolean"},
        "skill_needed": {"type": "string", "enum": SKILLS + ["none"]},
        "blur_boxes": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["face", "plate"]},
                    "box": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["kind", "box"],
            }},
    },
    "required": ["is_street_problem", "category", "severity", "reason", "neighbour_safe", "safety_reason",
                 "photo_kind", "kind_reason", "description", "blur_boxes",
                 "skilled_ok", "skill_needed"],
}

# Before/after check of a neighbour's fix.
FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "same_place": {"type": "boolean"},
        "problem_gone": {"type": "boolean"},
        "after_is_real_photo": {"type": "boolean"},
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["same_place", "problem_gone", "after_is_real_photo", "confidence", "reason"],
    "additionalProperties": False,
}
GEMINI_FIX_SCHEMA = {k: v for k, v in FIX_SCHEMA.items() if k != "additionalProperties"}

FIX_PROMPT = """You check "fixed it" claims in MendMap, a city app where residents fix small street problems and earn rewards for it.
Image 1 is the citizen's report photo (BEFORE). Image 2 is the photo the neighbour sent after fixing it (AFTER).
People sometimes cheat to get the reward: they send a photo of a different place, the same photo again, a photo from the internet, a screenshot, or a photo where the problem is still there.

Decide:
- same_place: true if both photos plausibly show the same spot (same surroundings, ground, walls, kerbs, objects), allowing for a different angle, zoom or time of day.
- problem_gone: true if the problem visible in BEFORE (rubbish, blocked ramp, etc.) is clearly gone or fixed in AFTER.
- after_is_real_photo: true if AFTER is a real camera photo taken on the street, not a screenshot, a photo of a screen, a drawing, an AI-generated or a stock/web image.
- confidence: 0 to 100, how sure you are that this is a genuine, completed fix (all three above true).
- reason: one short sentence for the city official, in English."""

PROMPT = """You check photos that citizens send to their city through MendMap, a street problem reporting app.

Decide:
- is_street_problem: true if the photo shows a problem in public space the city could fix (road damage, broken or dark streetlights, dumped rubbish, blocked or broken sidewalks and ramps, missing manhole covers, broken benches or signs, and similar). False for selfies, indoor photos, screenshots, or photos with no visible problem.
- category: pothole (road surface damage), streetlight (broken or dark street lighting), dumping (rubbish or rubble left illegally), accessibility (something that blocks wheelchairs, strollers or blind people: broken ramps, cars on the sidewalk, missing curb cuts), or other.
- severity: 1 = cosmetic, 2 = minor, 3 = should be fixed soon, 4 = dangerous for some people, 5 = immediate danger (for example an open manhole on a road).
- reason: one short sentence a citizen would understand, in English.
- neighbour_safe: true only if an ordinary resident could fix this safely on their own in an hour or two with simple tools (gloves, bags, a broom, a shovel): picking up litter or a small pile of rubbish, moving something that blocks a path or ramp, clearing leaves or snow, wiping small graffiti. False if it involves traffic or working on the road, digging or filling holes in the road, electricity or streetlights, heights or ladders, heavy objects or machinery, deep water, broken glass in large amounts, needles, chemicals, asbestos or other hazardous waste, or anything that needs a permit. When unsure, false.
- safety_reason: one short sentence explaining the neighbour_safe answer, in English.
- photo_kind: what kind of picture this is. real_photo = taken with a phone camera at the scene. screenshot = a screenshot of an app, map or website. photo_of_screen = a camera photo of a monitor or phone screen (moire, pixels, screen edges). drawing = illustration, cartoon, clip art or rendered graphic. ai_generated = an AI-made image (too smooth, warped text or objects, impossible details). stock_or_web = a professional stock or press photo, watermarks, or an image that looks taken from the internet. edited = a real photo that was clearly manipulated (pasted objects, heavy filters, added text). Be strict: citizens must send their own photo.
- kind_reason: one short sentence explaining photo_kind, in English."""

LANG_NAMES = {"en": "English", "sq": "Albanian", "hu": "Hungarian"}  # filled in from languages.LANGS below


MAX_PHOTOS = 5  # photos per report


def photo_prompt(lang: str = "en", count: int = 1) -> str:
    """The photo check prompt, with the description written in the app user's language.
    With several photos, they are judged together as one problem."""
    language = LANG_NAMES.get(lang, "English")
    many = "" if count <= 1 else f"""

The citizen sent {count} photos of the same problem (image 1 to image {count}, in that order), for example from different angles or a close-up.
Judge them together as one report: category, severity and description cover everything the photos show together (use the closest or clearest photo for sizes).
photo_kind is the worst of all the photos: if any one is not a real_photo, give that kind and say which image in kind_reason.
is_street_problem is true if the photos together show a street problem."""
    return PROMPT + many + f"""
- description: one or two short sentences describing the problem for the city, the way a citizen would write a report: what it is, roughly how big, and where in the picture (for example "A deep pothole about half a metre wide in the right lane, full of water."). Only what you can see; no guesses about causes. Write it in {language}. Empty string if it is not a street problem.
- skilled_ok: true if this is NOT safe for an ordinary neighbour, but a skilled volunteer tradesperson with their own tools could safely fix it in a few hours: for example a broken bench or railing, a loose paving slab on the pavement, a broken playground swing, a blocked drain grate, peeling paint, a broken fence, a damaged ramp. False if it needs traffic control or work on the road itself, live mains electricity or streetlights, gas, work higher than 2 metres, heavy machinery, a permit, or if an ordinary neighbour could already do it (neighbour_safe true). When unsure, false.
- skill_needed: the main skill a volunteer would need: plumbing, electrics, building (masonry, paving, concrete), painting, carpentry, gardening, welding; or none.
- blur_boxes: every human face and every readable vehicle number plate in the photos, so MendMap can blur them before the photos are public. image = which photo it is in (1 for the first photo). kind = face or plate. box = [ymin, xmin, ymax, xmax] in that photo, each scaled 0 to 1000. Empty list if there are none."""


TRANSCRIBE_PROMPT = """This is a voice note a citizen recorded while reporting a street problem in Prishtina, Kosovo.
Transcribe exactly what is said, in the language it is spoken (usually Albanian or English). Do not translate.
Return only the transcript text. If there is no speech, return an empty response."""

# Voice note file types the API accepts, by file extension.
AUDIO_MIME = {".m4a": "audio/mp4", ".aac": "audio/aac", ".mp3": "audio/mp3", ".wav": "audio/wav", ".webm": "audio/webm", ".3gp": "audio/3gpp"}

_claude = None
_gemini = None
_busy_until: dict[str, float] = {}  # model -> time until which it is skipped


def enabled() -> bool:
    return os.getenv("MENDMAP_AI", "on").lower() != "off"


def provider() -> str | None:
    """Which AI service to use, or None when none is configured."""
    if not enabled():
        return None
    choice = os.getenv("MENDMAP_AI_PROVIDER", "auto").lower()
    has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if choice == "gemini":
        return "gemini" if has_gemini else None
    if choice == "claude":
        return "claude"
    if has_gemini:
        return "gemini"
    # Claude can also sign in with `ant auth login`; set MENDMAP_AI_PROVIDER=claude for that.
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else None


def _shrink(data: bytes) -> bytes:
    """Phone photos are large; 1568 px on the long side is plenty for this and keeps the request small."""
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _clean(result: dict, count: int = 1) -> dict:
    """Keep the answer inside what the app understands."""
    if result.get("category") not in CATEGORIES:
        result["category"] = "other"
    try:
        result["severity"] = min(5, max(1, int(result.get("severity") or 3)))
    except (TypeError, ValueError):
        result["severity"] = 3
    result["is_street_problem"] = bool(result.get("is_street_problem", True))
    if result.get("photo_kind") not in PHOTO_KINDS:
        result["photo_kind"] = "real_photo"
    result["description"] = str(result.get("description") or "").strip()[:600]
    result["blur_boxes"] = _boxes(result.get("blur_boxes"), count)
    if result.get("skill_needed") not in SKILLS:
        result["skill_needed"] = None
    result["skilled_ok"] = (bool(result.get("skilled_ok", False)) and result["is_street_problem"]
                            and result.get("photo_kind", "real_photo") in (None, "real_photo")
                            and not result.get("neighbour_safe"))
    # Never safe for neighbours when it isn't a real photo of a street problem, or the model didn't say.
    result["neighbour_safe"] = (bool(result.get("neighbour_safe", False)) and result["is_street_problem"]
                                and result["photo_kind"] == "real_photo")
    return {"available": True, **result}


def _boxes(raw, count: int = 1) -> list[dict]:
    """Faces and number plates to blur, as [ymin, xmin, ymax, xmax] on a 0-1000 scale, with the photo they're in
    (image, 1-based); bad boxes dropped."""
    out = []
    for b in raw if isinstance(raw, list) else []:
        try:
            kind = b.get("kind")
            y0, x0, y1, x1 = (min(1000, max(0, int(v))) for v in b.get("box"))
            image = int(b.get("image") or 1)
        except (AttributeError, TypeError, ValueError):
            continue
        if kind in ("face", "plate") and y1 > y0 and x1 > x0 and 1 <= image <= count:
            out.append({"image": image, "kind": kind, "box": [y0, x0, y1, x1]})
    return out[:60]


_cache: dict[str, tuple[float, dict]] = {}


async def check_photo(data: bytes | list[bytes], lang: str = "en") -> dict:
    """One photo or several photos of the same problem, judged together in one AI call."""
    which = provider()
    if which is None:
        return {"available": False}
    images = (data if isinstance(data, list) else [data])[:MAX_PHOTOS]
    lang = lang if lang in LANG_NAMES else "en"
    key = ",".join(hashlib.sha256(d).hexdigest() for d in images) + ":" + lang
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return dict(hit[1])
    result = await _check(which, images, photo_prompt(lang, len(images)))
    if result.get("available"):
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.monotonic(), result)
    return result


async def _check(which: str, images: list[bytes], prompt: str) -> dict:
    try:
        jpegs = [_shrink(d) for d in images]
    except Exception:
        return {"available": True, "is_street_problem": False, "reason": "This file isn't a photo."}
    if which == "gemini":
        return await _check_gemini(jpegs, prompt)
    return await _check_claude(jpegs, prompt)


# ---------- Gemini ----------

def _gemini_client():
    global _gemini
    if _gemini is None:
        from google import genai
        from google.genai import types

        _gemini = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            # No long retry loops on one busy model: fail fast and try the next model instead.
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)),
        )
    return _gemini


def _gemini_models() -> list[str]:
    first = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
    rest = os.getenv("GEMINI_FALLBACK_MODELS", GEMINI_DEFAULT_FALLBACKS)
    models = [first] + [m.strip() for m in rest.split(",") if m.strip()]
    return list(dict.fromkeys(models))  # keep order, drop duplicates


def _gemini_model() -> str:
    return _gemini_models()[0]


async def _gemini_generate(contents, config, what: str):
    """Asks the first model; if it hasn't answered after GEMINI_HEDGE_S, asks the next one as well, and so on.
    The first good answer wins and the others are cancelled. Busy models (429/5xx, timeouts) are skipped
    for a while. Returns the response or None."""
    from google.genai import errors

    models = _gemini_models()
    now = time.monotonic()
    queue = [m for m in models if _busy_until.get(m, 0) <= now] or models  # all busy lately: try all again
    client = _gemini_client()

    async def ask(model: str):
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except asyncio.CancelledError:
            raise
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code in (429, 500, 502, 503, 504):
                log.warning("Gemini %s: %s is busy (%s)", what, model, code)
                _busy_until[model] = time.monotonic() + GEMINI_BUSY_SKIP_S
            else:
                log.warning("Gemini %s failed on %s (%s): %s", what, model, code, exc)
        except Exception as exc:  # timeouts and network errors
            log.warning("Gemini %s: %s did not answer (%s)", what, model, type(exc).__name__)
            _busy_until[model] = time.monotonic() + GEMINI_BUSY_SKIP_S
        return None

    loop = asyncio.get_running_loop()
    deadline = loop.time() + GEMINI_TOTAL_S
    running: dict[asyncio.Task, str] = {}
    try:
        while queue or running:
            if queue:
                m = queue.pop(0)
                running[asyncio.ensure_future(ask(m))] = m
            left = deadline - loop.time()
            if left <= 0:
                break
            # Wait for an answer; start the next model early unless nothing is left to start.
            done, _ = await asyncio.wait(running, timeout=min(GEMINI_HEDGE_S, left) if queue else left,
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                running.pop(task)
                if task.result() is not None:
                    return task.result()
        log.warning("Gemini %s: no model answered", what)
        return None
    finally:
        for task in running:
            task.cancel()


async def _check_gemini(jpegs: list[bytes], prompt: str) -> dict:
    from google.genai import types

    response = await _gemini_generate(
        [*(types.Part.from_bytes(data=j, mime_type="image/jpeg") for j in jpegs), prompt],
        types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=GEMINI_SCHEMA, temperature=0),
        "photo check",
    )
    if response is None:
        return {"available": False}
    try:
        result = json.loads(response.text or "")
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("Gemini photo check returned invalid JSON: %s", exc)
        return {"available": False}
    return _clean(result, len(jpegs))


async def transcribe(audio: bytes, extension: str) -> str | None:
    """Voice note -> text with Gemini. None when not configured or it fails."""
    if provider() != "gemini":
        return None
    from google.genai import types

    mime = AUDIO_MIME.get(extension.lower(), "audio/mp4")
    response = await _gemini_generate(
        [types.Part.from_bytes(data=audio, mime_type=mime), TRANSCRIBE_PROMPT],
        types.GenerateContentConfig(temperature=0),
        "transcription",
    )
    if response is None:
        return None
    text = (response.text or "").strip()
    return text[:4000] or None


# ---------- Claude ----------

async def _check_claude(jpegs: list[bytes], prompt: str) -> dict:
    global _claude
    import anthropic

    try:
        _claude = _claude or anthropic.AsyncAnthropic()
        response = await _claude.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines, the API retries on a suitable fallback model
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    *({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.standard_b64encode(j).decode()}} for j in jpegs),
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        log.info("AI photo check unavailable: %s", exc)
        return {"available": False}
    except anthropic.APIConnectionError as exc:
        log.warning("AI photo check could not reach the API: %s", exc)
        return {"available": False}
    except anthropic.APIStatusError as exc:
        log.warning("AI photo check failed (%s): %s", exc.status_code, exc)
        return {"available": False}
    except anthropic.AnthropicError as exc:  # e.g. no credentials configured at all
        log.info("AI photo check unavailable: %s", exc)
        return {"available": False}

    if response.stop_reason == "refusal":
        return {"available": False}
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        log.warning("AI photo check returned invalid JSON")
        return {"available": False}
    return _clean(result, len(jpegs))


# ---------- neighbour fix: before vs after ----------

async def check_fix(before: bytes, after: bytes) -> dict:
    """Compares the report photo with the neighbour's after photo.
    {"available": False} without AI; otherwise same_place, problem_gone, after_is_real_photo, confidence 0-100, reason."""
    which = provider()
    if which is None:
        return {"available": False}
    try:
        a, b = _shrink(before), _shrink(after)
    except Exception:
        return {"available": True, "same_place": False, "problem_gone": False, "after_is_real_photo": False,
                "confidence": 0, "reason": "One of the files isn't a photo."}
    if which == "gemini":
        from google.genai import types

        response = await _gemini_generate(
            [types.Part.from_bytes(data=a, mime_type="image/jpeg"), types.Part.from_bytes(data=b, mime_type="image/jpeg"), FIX_PROMPT],
            types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=GEMINI_FIX_SCHEMA, temperature=0),
            "fix check",
        )
        text = response.text if response is not None else None
    else:
        text = await _claude_json([a, b], FIX_PROMPT, FIX_SCHEMA, "fix check")
    if not text:
        return {"available": False}
    try:
        res = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"available": False}
    try:
        conf = int(res.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0
    return {
        "available": True,
        "same_place": bool(res.get("same_place")),
        "problem_gone": bool(res.get("problem_gone")),
        "after_is_real_photo": bool(res.get("after_is_real_photo")),
        "confidence": max(0, min(100, conf)),
        "reason": str(res.get("reason") or "")[:500],
    }


async def _claude_json(images: list[bytes], prompt: str, schema: dict, what: str, pdf: bytes | None = None) -> str | None:
    global _claude
    import anthropic

    try:
        _claude = _claude or anthropic.AsyncAnthropic()
        response = await _claude.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{
                "role": "user",
                "content": [
                    *({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.standard_b64encode(img).decode()}} for img in images),
                    *([{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                      "data": base64.standard_b64encode(pdf).decode()}}] if pdf else []),
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except anthropic.AnthropicError as exc:
        log.warning("Claude %s failed: %s", what, exc)
        return None
    if response.stop_reason == "refusal":
        return None
    return next((b.text for b in response.content if b.type == "text"), None)


# ---------- mjeshtër proof: is the skill document genuine? ----------
PROOF_SCHEMA = {
    "type": "object",
    "properties": {
        "is_document": {"type": "boolean"},
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "name_on_doc": {"type": "string"},
        "name_matches": {"type": "boolean"},
        "issuer": {"type": "string"},
        "skills_shown": {"type": "array", "items": {"type": "string", "enum": SKILLS}},
        "looks_genuine": {"type": "boolean"},
        "verdict": {"type": "string", "enum": VERDICTS},
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
        "reason_user": {"type": "string"},
    },
    "required": ["is_document", "doc_type", "name_on_doc", "name_matches", "issuer", "skills_shown",
                 "looks_genuine", "verdict", "confidence", "reason", "reason_user"],
    "additionalProperties": False,
}
GEMINI_PROOF_SCHEMA = {k: v for k, v in PROOF_SCHEMA.items() if k != "additionalProperties"}
PROOF_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}


def proof_prompt(name: str, skills: list[str], lang: str = "en") -> str:
    language = LANG_NAMES.get(lang, "English")
    return f"""You verify proof documents for MendMap "mjeshtrit": skilled volunteers (tradespeople) who fix small things in public spaces in Prishtina, Kosovo, on days the city crews don't work.
The applicant says their name is "{name}" and that they can do: {", ".join(skills)}.
They uploaded a document to prove it, for example a vocational school diploma (shkollë profesionale), a trade or craft certificate, a professional licence (such as an electrician's licence), a training course certificate, or a letter from an employer. It may be in Albanian, Serbian, English or another language.

Decide:
- is_document: true if this is a photo or scan of a real document (paper certificate, diploma, licence card, letter). False for selfies, street photos, screenshots of chats, memes or blank pages.
- doc_type: vocational_diploma, trade_certificate, professional_licence, training_certificate, employer_letter, university_degree, other_document, or not_a_document.
- name_on_doc: the person's name as written on it, or "" if there is none.
- name_matches: true if name_on_doc is clearly the same person as "{name}" (ignore accents such as ë/e and ç/c, the order of the names and middle names).
- issuer: who issued it (school, company, institution), or "".
- skills_shown: which of these skills the document really shows the person has: plumbing, electrics, building, painting, carpentry, gardening, welding. Only skills the document supports.
- looks_genuine: false if there are signs of forgery: edited or pasted text, mismatched fonts, a name that looks typed over, missing stamps or signatures where an official document has them, a template or sample ("SPECIMEN", "SAMPLE", "Lorem ipsum", "Emri Mbiemri"), an AI-generated or drawn image, or a screenshot of a website or a document found online.
- verdict: legit = a genuine document showing this person has at least one of the claimed skills. suspicious = it could be genuine but something doesn't fit (the name doesn't match, it's hard to read, the skills are unclear, an unusual issuer). fake = clear signs of forgery, a template, or an AI-made or drawn document. not_a_document = not a document at all.
- confidence: 0 to 100, how sure you are of the verdict.
- reason: one short sentence for the city official, in English.
- reason_user: the same in {language}, kind and clear, for the applicant.
Be strict: this person will work in public spaces with the city's trust. When unsure, choose suspicious, never legit. Never repeat personal ID numbers."""


def _clean_proof(r: dict) -> dict:
    verdict = r.get("verdict") if r.get("verdict") in VERDICTS else "suspicious"
    try:
        conf = min(100, max(0, int(r.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0
    shown = [x for x in (r.get("skills_shown") or []) if x in SKILLS]
    return {
        "available": True,
        "is_document": bool(r.get("is_document")),
        "doc_type": r.get("doc_type") if r.get("doc_type") in DOC_TYPES else "other_document",
        "name_on_doc": str(r.get("name_on_doc") or "")[:160],
        "name_matches": bool(r.get("name_matches")),
        "issuer": str(r.get("issuer") or "")[:200],
        "skills_shown": shown,
        "looks_genuine": bool(r.get("looks_genuine")),
        "verdict": verdict,
        "confidence": conf,
        "reason": str(r.get("reason") or "")[:500],
        "reason_user": str(r.get("reason_user") or r.get("reason") or "")[:500],
    }


async def check_proof(data: bytes, mime: str, name: str, skills: list[str], lang: str = "en") -> dict:
    """Reads a skill document (photo or PDF) and judges whether it's genuine and proves the skills."""
    which = provider()
    if which is None:
        return {"available": False}
    prompt = proof_prompt(name, skills, lang)
    pdf = data if mime == "application/pdf" else None
    if pdf is None:
        try:
            data, mime = _shrink(data), "image/jpeg"
        except Exception:
            return _clean_proof({"verdict": "not_a_document", "confidence": 100, "doc_type": "not_a_document",
                                 "reason": "The file isn't a photo or a PDF.", "reason_user": "The file isn't a photo or a PDF."})
    text = None
    if which == "gemini":
        from google.genai import types
        response = await _gemini_generate(
            [types.Part.from_bytes(data=data, mime_type=mime), prompt],
            types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=GEMINI_PROOF_SCHEMA,
                                        temperature=0),
            "proof check",
        )
        text = response.text if response is not None else None
    else:
        text = await _claude_json([] if pdf else [data], prompt, PROOF_SCHEMA, "proof check", pdf=pdf)
    if not text:
        return {"available": False}
    try:
        return _clean_proof(json.loads(text))
    except (json.JSONDecodeError, ValueError, AttributeError):
        log.warning("Proof check returned invalid JSON")
        return {"available": False}


# ---------- community chat: keep it friendly ----------
CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["ok", "reason"],
    "additionalProperties": False,
}
GEMINI_CHAT_SCHEMA = {k: v for k, v in CHAT_SCHEMA.items() if k != "additionalProperties"}
CHAT_TIMEOUT_S = 8.0  # people are waiting to see their message


def chat_prompt(text: str, lang: str = "en") -> str:
    return f"""You moderate the community chat of MendMap, a city app where neighbours in Prishtina, Kosovo talk about street problems (potholes, lights, rubbish), fixing them together and their neighbourhood.
The message can be in any language.

Block it (ok=false) only if it contains: insults or harassment of a person, hate or threats, sexual content, spam or advertising, scams, or someone's private data (phone number, home address, ID numbers).
Allow (ok=true) everything else, including complaints about the city, strong opinions, slang, jokes and off-topic small talk.

reason: if blocked, one short friendly sentence in {LANG_NAMES.get(lang, "English")} telling the sender why. If allowed, "".

Message: {json.dumps(text, ensure_ascii=False)}"""


async def moderate_chat(text: str, lang: str = "en") -> dict:
    """{"ok": True/False, "reason": str}; ok is None when no AI answered (the message is then allowed,
    and neighbours can still report it)."""
    which = provider()
    if not which:
        return {"ok": None, "reason": ""}
    prompt = chat_prompt(text, lang)
    try:
        if which == "gemini":
            from google.genai import types

            response = await asyncio.wait_for(_gemini_generate(
                [prompt],
                types.GenerateContentConfig(response_mime_type="application/json",
                                            response_json_schema=GEMINI_CHAT_SCHEMA, temperature=0),
                "chat moderation",
            ), CHAT_TIMEOUT_S)
            raw = response.text if response is not None else None
        else:
            raw = await asyncio.wait_for(_claude_json([], prompt, CHAT_SCHEMA, "chat moderation"), CHAT_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("Chat moderation timed out")
        return {"ok": None, "reason": ""}
    try:
        r = json.loads(raw or "")
        return {"ok": bool(r["ok"]), "reason": str(r.get("reason") or "")[:300]}
    except (ValueError, KeyError, TypeError):
        return {"ok": None, "reason": ""}


# ---------- small text jobs: translate a chat message, write the city's weekly summary ----------
TEXT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


async def _text_job(prompt: str, what: str, timeout: float = 20.0) -> str | None:
    """One prompt -> one text, with Gemini (hedged) or Claude. None when no AI answered."""
    which = provider()
    if not which:
        return None
    try:
        if which == "gemini":
            from google.genai import types

            response = await asyncio.wait_for(_gemini_generate(
                [prompt],
                types.GenerateContentConfig(response_mime_type="application/json",
                                            response_json_schema={k: v for k, v in TEXT_SCHEMA.items() if k != "additionalProperties"},
                                            temperature=0.2),
                what,
            ), timeout)
            raw = response.text if response is not None else None
        else:
            raw = await asyncio.wait_for(_claude_json([], prompt, TEXT_SCHEMA, what), timeout)
        out = str(json.loads(raw or "")["text"]).strip()
        return out or None
    except (asyncio.TimeoutError, ValueError, KeyError, TypeError):
        return None


async def translate_text(text: str, lang: str) -> str | None:
    language = LANG_NAMES.get(lang, "English")
    return await _text_job(
        f"Translate this message from a neighbourhood chat in Prishtina, Kosovo into {language}. "
        f"Keep names, street names, emoji and the casual tone. If it is already in {language}, return it unchanged.\n\n"
        f"Message: {json.dumps(text, ensure_ascii=False)}",
        "chat translation", timeout=12.0,
    )


async def city_summary(facts: dict, lang: str = "en") -> str | None:
    language = LANG_NAMES.get(lang, "English")
    return await _text_job(
        f"You write the weekly summary for the city team of Prishtina, Kosovo from MendMap data (citizens report street problems).\n"
        f"Write 4 to 6 short sentences in {language}: what happened, where it is worst (areas and streets), what waits too long, "
        f"repairs that did not hold, and one concrete suggestion for next week. Plain text, no lists, no headings, numbers as digits.\n\n"
        f"Data (JSON): {json.dumps(facts, ensure_ascii=False, default=str)}",
        "city summary", timeout=30.0,
    )


def _all_languages() -> None:
    """Descriptions and proof-check reasons can be written in any language the app offers."""
    from .languages import LANGS
    LANG_NAMES.update(LANGS)


_all_languages()
