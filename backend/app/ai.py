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
    },
    "required": ["is_street_problem", "category", "severity", "reason", "neighbour_safe", "safety_reason",
                 "photo_kind", "kind_reason"],
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
    },
    "required": ["is_street_problem", "category", "severity", "reason", "neighbour_safe", "safety_reason",
                 "photo_kind", "kind_reason"],
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


def _clean(result: dict) -> dict:
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
    # Never safe for neighbours when it isn't a real photo of a street problem, or the model didn't say.
    result["neighbour_safe"] = (bool(result.get("neighbour_safe", False)) and result["is_street_problem"]
                                and result["photo_kind"] == "real_photo")
    return {"available": True, **result}


_cache: dict[str, tuple[float, dict]] = {}


async def check_photo(data: bytes) -> dict:
    which = provider()
    if which is None:
        return {"available": False}
    key = hashlib.sha256(data).hexdigest()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return dict(hit[1])
    result = await _check(which, data)
    if result.get("available"):
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.monotonic(), result)
    return result


async def _check(which: str, data: bytes) -> dict:
    try:
        jpeg = _shrink(data)
    except Exception:
        return {"available": True, "is_street_problem": False, "reason": "This file isn't a photo."}
    if which == "gemini":
        return await _check_gemini(jpeg)
    return await _check_claude(jpeg)


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


async def _check_gemini(jpeg: bytes) -> dict:
    from google.genai import types

    response = await _gemini_generate(
        [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), PROMPT],
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
    return _clean(result)


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

async def _check_claude(jpeg: bytes) -> dict:
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
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.standard_b64encode(jpeg).decode()}},
                    {"type": "text", "text": PROMPT},
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
    return _clean(result)


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


async def _claude_json(images: list[bytes], prompt: str, schema: dict, what: str) -> str | None:
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
