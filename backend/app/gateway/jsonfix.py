"""Tolerant JSON extraction: small models wrap JSON in fences, add prose, trailing commas, drop
the last brace or the commas between array items. If this fails, the gateway makes ONE compact
"fix this JSON" call."""

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


def _missing_commas(text: str) -> str:
    """Insert the comma small models drop between array items: `} {`, `] [`, `} [`, `] {`
    (outside strings). llama3.2-3b does this on quizzes, and the repair call echoes it back."""
    out: list[str] = []
    in_str = escape = False
    closed = False  # the last non-space character outside a string was } or ]
    for c in text:
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            out.append(c)
            continue
        if c.isspace():
            out.append(c)
            continue
        if closed and c in "{[":
            out.append(",")
        closed = c in "}]"
        if c == '"':
            in_str = True
        out.append(c)
    return "".join(out)


def _objects(text: str) -> list[dict[str, Any]]:
    """Every complete JSON object in `text`, left to right, skipping stray `,` `}` `]`."""
    found: list[dict[str, Any]] = []
    i = 0
    while (i := text.find("{", i)) != -1:
        piece = _balanced(text, i)
        try:
            value = json.loads(_TRAILING_COMMA.sub(r"\1", piece))
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(value, dict):
            found.append(value)
        i += len(piece)
    return found


def _spilled(value: Any, rest: str) -> Any:
    """`{"items": [{...}]}, {...}, {...}`: the array was closed too early and the other items
    follow it (llama3.2-3b on quizzes, 9 Nov). Append the trailing objects that look like the
    list's items (same first key) to that list."""
    if not (isinstance(value, dict) and len(value) == 1 and "{" in rest):
        return value
    ((key, items),) = value.items()
    if not (isinstance(items, list) and items and isinstance(items[0], dict) and items[0]):
        return value
    marker = next(iter(items[0]))
    extra = [o for o in _objects(rest) if marker in o]
    return {key: items + extra} if extra else value


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
    piece = _balanced(cleaned, min(starts))
    rest = cleaned[min(starts) + len(piece) :]
    candidate = _TRAILING_COMMA.sub(r"\1", piece)
    try:
        return _spilled(json.loads(candidate), rest)
    except json.JSONDecodeError:
        pass
    try:
        return _spilled(json.loads(_missing_commas(candidate)), rest)
    except json.JSONDecodeError:
        return None


REPAIR_SYSTEM = (
    "You fix broken JSON. Return only the corrected JSON value, with the same keys and content. "
    "No explanation, no code fences."
)
