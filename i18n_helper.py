"""
i18n helper for BambuLoop.
=========================

Loads locale JSON files from ./i18n/ and provides a single helper that
returns a {lang: text} dictionary for every loaded locale.

Adding a new language is just dropping `i18n/<lang>.json` into the
directory — no code changes needed.

Usage:
    from i18n_helper import t_dict

    return jsonify({
        "error": t_dict("error.no_file"),
        # The dict above contains one translated entry per locale JSON
        # present in the i18n/ directory (e.g. en, ko, zh, ...).
        # The frontend picks the right entry by `currentLang`.
    }), 400

    # With placeholders:
    return jsonify({
        "error": "z_collision_bottom_mode",        # machine code (stable English ID)
        "title":   t_dict("error.z_collision.bottom_mode.title"),
        "message": t_dict("error.z_collision.bottom_mode.message",
                          print_height=42.5, z_limit=42),
    }), 409
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Directory holding `<lang>.json` files. Adjacent to this module.
_I18N_DIR = Path(__file__).parent / "i18n"

# Default fallback language. Missing keys fall back to this locale, then to
# the literal key itself (so unknown keys are still visible during development).
_FALLBACK_LANG = "en"

# Loaded translations: {lang: {key: text}}.
_TRANSLATIONS: dict[str, dict[str, str]] = {}


def _load() -> None:
    """Load every `<lang>.json` from the i18n directory once."""
    if _TRANSLATIONS:
        return
    if not _I18N_DIR.is_dir():
        return
    for json_file in sorted(_I18N_DIR.glob("*.json")):
        lang = json_file.stem
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _TRANSLATIONS[lang] = data
        except (json.JSONDecodeError, OSError):
            # Skip malformed/unreadable files — i18n is non-critical for
            # backend operation, the key itself will surface as fallback.
            continue


def available_languages() -> list[str]:
    """Return the list of languages with a JSON file present."""
    _load()
    return sorted(_TRANSLATIONS.keys())


def t_dict(key: str, **placeholders: Any) -> dict[str, str]:
    """Return ``{lang: translated_text}`` for every loaded locale.

    Designed for API responses: hand the result to the frontend, which then
    selects the right entry by ``currentLang`` with a fallback to English.

    Resolution rules per language:
        1. If the language has the key, use its translation.
        2. Otherwise, fall back to the English translation if present.
        3. Otherwise, return the raw key (signals "missing translation").

    Placeholders are ``{name}`` tokens substituted with ``str(value)``.

    Args:
        key: Dot-notation key, e.g. ``"error.z_collision.bottom_mode.title"``.
        **placeholders: Values for ``{name}`` tokens inside the text.

    Returns:
        ``{"ko": "...", "en": "...", ...}`` covering every loaded locale.
        Always includes at least ``{"en": <key>}`` even when no JSON files
        have been loaded — never returns an empty dict.
    """
    _load()

    # Guarantee an English entry even if no locale files were loaded
    languages = set(_TRANSLATIONS.keys()) | {_FALLBACK_LANG}

    en_text = _TRANSLATIONS.get(_FALLBACK_LANG, {}).get(key, key)

    result: dict[str, str] = {}
    for lang in languages:
        raw = _TRANSLATIONS.get(lang, {}).get(key) or en_text
        # Substitute {placeholder} tokens. We use plain `.replace` rather than
        # `str.format` so that JSON braces in the source text (e.g. example
        # JSON snippets) are not interpreted as format spec.
        text = raw
        for ph_name, ph_value in placeholders.items():
            text = text.replace("{" + ph_name + "}", str(ph_value))
        result[lang] = text

    return result


def t(key: str, lang: str = _FALLBACK_LANG, **placeholders: Any) -> str:
    """Return the translated text for a single language (server-side use).

    Same fallback rules as :func:`t_dict`. Use this when you need a single
    string rather than a dict (e.g. for logging, CLI output, or for an
    explicit single-language render).
    """
    return t_dict(key, **placeholders).get(lang, key)
