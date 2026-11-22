"""Languages MendMap can show: English plus the official language of the country the user is in.

Albanian and Hungarian have hand-made translations in the app. Every other language is translated
by the AI the first time someone needs it (see translate()) and kept in i18n_cache/<lang>.json,
so each string is only translated once for everyone.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("mendmap")

# code -> English name (used in AI prompts)
LANGS = {
    "en": "English", "sq": "Albanian", "hu": "Hungarian", "nl": "Dutch", "it": "Italian", "de": "German",
    "fr": "French", "es": "Spanish", "pt": "Portuguese", "pl": "Polish", "cs": "Czech", "sk": "Slovak",
    "sl": "Slovenian", "hr": "Croatian", "bs": "Bosnian", "sr": "Serbian", "mk": "Macedonian", "bg": "Bulgarian",
    "ro": "Romanian", "el": "Greek", "tr": "Turkish", "da": "Danish", "sv": "Swedish", "nb": "Norwegian Bokmål",
    "fi": "Finnish", "is": "Icelandic", "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "mt": "Maltese",
    "ca": "Catalan", "ga": "Irish", "lb": "Luxembourgish", "fo": "Faroese", "kl": "Greenlandic", "uk": "Ukrainian",
    "ru": "Russian", "be": "Belarusian", "ka": "Georgian", "hy": "Armenian", "az": "Azerbaijani", "kk": "Kazakh",
    "uz": "Uzbek", "ky": "Kyrgyz", "tg": "Tajik", "tk": "Turkmen", "mn": "Mongolian", "ar": "Arabic",
    "he": "Hebrew", "fa": "Persian", "ps": "Pashto", "ur": "Urdu", "hi": "Hindi", "bn": "Bengali",
    "ne": "Nepali", "si": "Sinhala", "dv": "Dhivehi", "dz": "Dzongkha", "zh": "Simplified Chinese", "ja": "Japanese",
    "ko": "Korean", "th": "Thai", "vi": "Vietnamese", "lo": "Lao", "km": "Khmer", "my": "Burmese",
    "id": "Indonesian", "ms": "Malay", "tl": "Filipino", "tet": "Tetum", "sw": "Swahili", "am": "Amharic",
    "ti": "Tigrinya", "so": "Somali", "rw": "Kinyarwanda", "rn": "Kirundi", "mg": "Malagasy", "af": "Afrikaans",
    "st": "Sesotho", "tn": "Setswana", "ss": "Swati", "ny": "Chichewa", "sn": "Shona", "ht": "Haitian Creole",
    "gn": "Guarani", "sm": "Samoan", "to": "Tongan", "fj": "Fijian", "bi": "Bislama", "mi": "Māori",
    "mh": "Marshallese", "na": "Nauruan", "gil": "Gilbertese", "tvl": "Tuvaluan", "pau": "Palauan",
}
STATIC = {"en", "sq", "hu"}  # translated by hand in the app

CACHE = Path(__file__).resolve().parent.parent / "i18n_cache"
MAX_STRINGS = 1500
MAX_LEN = 600
BATCH = 120
_locks: dict[str, asyncio.Lock] = {}

PLACEHOLDER = re.compile(r"\{[a-zA-Z_]+\}")

PROMPT = """Translate the user interface texts of MendMap, a phone app where citizens report street problems (potholes, broken streetlights, rubbish) to their city, from English to {language}.

Rules:
- Natural, short phone-app wording a local would use. Keep the tone friendly and clear.
- Keep every placeholder in curly braces exactly as it is, e.g. {{n}}, {{name}}, {{area}}. Do not translate or remove them.
- Keep emoji, numbers and punctuation like ✓ · → as they are.
- Keep these names untranslated: MendMap, Mjeshtri, mjeshtër, Gemini, Google, Apple, Expo.
- Return every id with its translation.

Texts (id: text):
{texts}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        },
    },
    "required": ["items"],
}


def _load(lang: str) -> dict[str, str]:
    try:
        return json.loads((CACHE / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(lang: str, data: dict[str, str]) -> None:
    CACHE.mkdir(exist_ok=True)
    tmp = CACHE / f"{lang}.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE / f"{lang}.json")


def _ok(src: str, out: str) -> bool:
    """A translation must keep exactly the same placeholders."""
    return bool(out.strip()) and sorted(PLACEHOLDER.findall(src)) == sorted(PLACEHOLDER.findall(out))


async def _batch(lang: str, texts: list[str]) -> dict[str, str]:
    from . import ai  # imported here: ai.py reads LANGS from this module

    numbered = "\n".join(f"{i}: {json.dumps(t, ensure_ascii=False)}" for i, t in enumerate(texts))
    prompt = PROMPT.format(language=LANGS[lang], texts=numbered)
    text = None
    which = ai.provider()
    if which == "gemini":
        from google.genai import types
        response = await ai._gemini_generate(
            [prompt],
            types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA, temperature=0.2),
            "translation",
        )
        text = response.text if response is not None else None
    elif which == "claude":
        schema = {**SCHEMA, "additionalProperties": False}
        schema["properties"]["items"]["items"] = {**SCHEMA["properties"]["items"]["items"], "additionalProperties": False}
        text = await ai._claude_json([], prompt, schema, "translation")
    if not text:
        return {}
    try:
        items = json.loads(text).get("items", [])
    except (ValueError, AttributeError):
        return {}
    done = {}
    for it in items:
        try:
            i, out = int(it["id"]), str(it["text"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < len(texts) and _ok(texts[i], out):
            done[texts[i]] = out
    return done


async def translate(lang: str, strings: list[str]) -> tuple[dict[str, str], int]:
    """Translations for the given English strings (cached ones at once, new ones via the AI).
    Returns (translations, how many are still missing because the AI was busy)."""
    from . import ai

    strings = [s for s in dict.fromkeys(strings) if isinstance(s, str) and s.strip() and len(s) <= MAX_LEN][:MAX_STRINGS]
    lock = _locks.setdefault(lang, asyncio.Lock())
    async with lock:  # one translation run per language at a time
        cache = _load(lang)
        missing = [s for s in strings if s not in cache]
        if missing and ai.provider():
            sem = asyncio.Semaphore(3)  # a few batches at once, without hitting rate limits

            async def run(chunk):
                async with sem:
                    try:
                        return await _batch(lang, chunk)
                    except Exception as exc:  # one failed batch shouldn't lose the others
                        log.warning("Translation batch (%s) failed: %s", lang, exc)
                        return {}

            results = await asyncio.gather(*(run(missing[i:i + BATCH]) for i in range(0, len(missing), BATCH)))
            for r in results:
                cache.update(r)
            if any(results):
                _save(lang, cache)
    found = {s: cache[s] for s in strings if s in cache}
    return found, len(strings) - len(found)
