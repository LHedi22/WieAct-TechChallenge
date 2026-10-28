"""Tolerant JSON extraction: small models wrap JSON in fences, add prose, trailing commas or drop
the last brace. If this fails, the gateway makes ONE compact "fix this JSON" call."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


def _balanced(text: str, start: int) -> str:
    """Slice from `start` to its matching bracket, closing any left open at the end."""
    stack: list[str] = []
    in_str = escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
            if not stack:
                return text[start : i + 1]
    return text[start:].rstrip().rstrip(",") + "".join(reversed(stack))


def extract_json(text: str) -> Any | None:
    """Parse the first JSON object/array in `text`, or None."""
    cleaned = _FENCE.sub("", strip_think(text)).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not starts:
        return None
    candidate = _TRAILING_COMMA.sub(r"\1", _balanced(cleaned, min(starts)))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


REPAIR_SYSTEM = (
    "You fix broken JSON. Return only the corrected JSON value, with the same keys and content. "
    "No explanation, no code fences."
)
