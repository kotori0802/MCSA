"""UI language helpers. Copy tables load from resources/strings JSON."""
from __future__ import annotations

from typing import Any

from .strings.loader import STRINGS, lookup_qt

DEFAULT_LANG = "en"

# "zh" is Traditional Chinese (zh-TW); the code is kept because reports already use it.
SUPPORTED_LANGS: tuple[str, ...] = ("en", "zh")

LANG_LABELS: dict[str, str] = {
    "en": "English",
    "zh": "繁體中文",
}

_LANG_ALIASES: dict[str, str] = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "zh": "zh",
    "zh-tw": "zh",
    "zh-hant": "zh",
    "zh-hant-tw": "zh",
}


def normalize_lang(value: Any) -> str:
    """Map a stored or requested UI language to a supported code.

    Previously supported locales (fr, it, de, es, ja, ko) and anything
    unrecognised fall back to English.
    """
    if not isinstance(value, str):
        return DEFAULT_LANG
    key = value.strip().lower().replace("_", "-")
    return _LANG_ALIASES.get(key, DEFAULT_LANG)


def t(lang: str, key: str, **kwargs: Any) -> str:
    return lookup_qt(normalize_lang(lang), key, **kwargs)
