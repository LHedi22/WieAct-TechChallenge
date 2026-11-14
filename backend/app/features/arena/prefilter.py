"""Moderation pre-filter for peer questions (audit OPT-07): the clear cases are settled on the
server with no model call. Tunisian phone numbers, emails and street addresses → personal_data;
a short insult list (insults.json: EN, FR, AR, Darija in Arabic script and Arabizi, flagged
_review) → abusive. Anything else, including every unclear case, goes to MODERATE_POST."""

from __future__ import annotations

import json
import re
from pathlib import Path

WORDS: dict = json.loads((Path(__file__).with_name("insults.json")).read_text(encoding="utf-8"))

_PHONE = [
    re.compile(r"(?:\+|00)\s?216[\s.-]?\d{2}(?:[\s.-]?\d){6}"),  # +216 / 00216 prefix
    # 8 digits from 2-9 written like a number: 22 345 678 · 55.123.456 · 97 12 34 56
    re.compile(r"(?<![\d.,])[2-9]\d(?:[\s.-]\d{3}[\s.-]\d{3}|(?:[\s.-]\d{2}){3})(?![\d.,])"),
    # 8 plain digits right after a phone word
    re.compile(
        r"(?:num(?:é|e)ro|\bnum\b|\btel\b|tél|phone|whatsapp|\bcall\b|appelle|رقم|نومرو)"
        r"\D{0,20}(?<!\d)[2-9]\d{7}(?!\d)",
        re.IGNORECASE,
    ),
]
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]*\w")
_STREET = r"(?:rue|avenue|av\.|boulevard|impasse|street|road|نهج|شارع|زنقة)"
_ADDRESS = [
    re.compile(rf"\b\d{{1,4}}\s*,?\s*{_STREET}\s", re.IGNORECASE),  # 12 rue de Marseille
    re.compile(rf"\b{_STREET}\s+[^\d\n]{{2,40}}?\s\d{{1,4}}\b", re.IGNORECASE),  # Avenue … 40
]
_TASHKEEL = re.compile(r"[ً-ْٰـ]")
_FORMS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def _tokens(text: str) -> list[str]:
    text = _TASHKEEL.sub("", text.casefold()).translate(_FORMS)
    return re.findall(r"\w+", text)


_PHRASES = [tuple(_tokens(p)) for lang, ps in WORDS.items() if not lang.startswith("_") for p in ps]


def _has_phrase(tokens: list[str]) -> bool:
    for phrase in _PHRASES:
        n = len(phrase)
        if any(tuple(tokens[i : i + n]) == phrase for i in range(len(tokens) - n + 1)):
            return True
    return False


def check(text: str) -> str | None:
    """'personal_data', 'abusive', or None (let the model decide)."""
    if _EMAIL.search(text) or any(r.search(text) for r in (*_PHONE, *_ADDRESS)):
        return "personal_data"
    if _has_phrase(_tokens(text)):
        return "abusive"
    return None
