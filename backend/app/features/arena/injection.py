"""Prompt-injection signals in student text (audit N-1), in English, French, Arabic and Darija.

This is a ROUTING signal, not the defence: a flagged answer goes to a mid review before anything
is awarded, the grading prompts fence the answer as untrusted data, and every rubric level needs
evidence copied from the answer (evidence that sits inside a flagged instruction doesn't count).
Patterns aim at instructions to the grader (ignore the rules, give a score, "you are now…"),
never at the topic words a real explanation uses."""

from __future__ import annotations

import re
import unicodedata

_AR_DIACRITICS = re.compile("[ً-ْٰـ]")  # harakat, dagger alef, tatweel
_AR_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def normalise(text: str) -> str:
    """Case-folded, NFKC, Arabic letter variants unified, diacritics and punctuation dropped
    (sentence ends kept as "."), whitespace collapsed. Used for detection and evidence matching."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = _AR_DIACRITICS.sub("", t).translate(_AR_LETTERS)
    t = re.sub(r"[.!?؟\n]+", " . ", t)  # sentence ends stay: a flagged clause stops there
    t = re.sub(r"[^\w\s/.]", " ", t)  # keep letters, digits, "_", "/" (20/20) and "."
    return " ".join(t.split())


def plain(text: str) -> str:
    """normalise() without the sentence marks: for comparing quotes."""
    return " ".join(normalise(text).replace(".", " ").split())


# After normalise() the only sentence mark left is ".", so a clause is "[^.]".
_NEAR = r"[^.]{0,40}"
_REST = r"[^.]*"
_SCORE = r"(?:100|cent|١٠٠|full marks?|max(?:imum)?|20 ?/ ?20|10 ?/ ?10|100 ?/ ?100)"
_RULES_EN = r"(?:instructions?|rules|prompt|rubric|guidelines)"
_RULES_FR = r"(?:instructions?|consignes?|r[eè]gles|prompt|bar[eè]me)"
_RULES_AR = r"(?:التعليمات|تعليماتك|تعليمات|الاوامر|القواعد|التوجيهات)"
_FULL_AR = r"(?:100|١٠٠|العلامه الكامله|الدرجه الكامله|علامه كامله|عشرين على عشرين|20/20)"

_PATTERNS = [
    # English
    rf"\b(?:ignore|disregard|forget|override)\b{_NEAR}\b{_RULES_EN}\b{_REST}",
    rf"\b(?:give|award|assign|grant|rate|score|mark)\b{_NEAR}{_SCORE}{_REST}",
    rf"\b(?:you are now|act as|pretend (?:to be|you are)|new instructions|system prompt)\b{_REST}",
    # French
    rf"\b(?:ignore[rz]?|oublie[rz]?|n.?applique pas)\b{_NEAR}\b{_RULES_FR}\b{_REST}",
    rf"\b(?:donne[rz]?|attribue[rz]?|mets?|mettez|accorde[rz]?)\b{_NEAR}{_SCORE}{_REST}",
    rf"\b(?:tu es maintenant|fais comme si|nouvelles instructions|note maximale){_REST}",
    # Arabic (normalised: no diacritics, unified alef / ya / ta marbuta)
    rf"(?:تجاهل|انس|انسي|لا تتبع|تخط){_NEAR}{_RULES_AR}{_REST}",
    rf"(?:اعط|اعطي|امنح|ضع){_NEAR}{_FULL_AR}{_REST}",
    rf"(?:انت الان|تصرف ك){_REST}",
    # Darija
    rf"(?:فسخ|نسى|انسى|ما تعملش ب|ما تتبعش){_NEAR}{_RULES_AR}{_REST}",
    rf"(?:عطي|عطيني|حط|حطلي){_NEAR}(?:{_FULL_AR}|النقطه الكل){_REST}",
]
_RE = [re.compile(p) for p in _PATTERNS]


def spans(text: str) -> list[str]:
    """The normalised instruction-like clauses found in `text` (empty when none)."""
    t = normalise(text)
    return [m.group(0).strip() for r in _RE for m in r.finditer(t)]


def detect(text: str) -> bool:
    return bool(spans(text))


def without_injection(text: str) -> str:
    """The normalised text with every flagged clause removed: evidence must come from the rest."""
    t = normalise(text)
    for r in _RE:
        t = r.sub(" ", t)
    return " ".join(t.replace(".", " ").split())
