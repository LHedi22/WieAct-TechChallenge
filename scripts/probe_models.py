#!/usr/bin/env python3
"""Probe the EdNova platform: list models, benchmark them on Learning World's real tasks, pick the
best compact / mid-size / embedding model, and print the .env lines to use.

Run it DURING YOUR TIME SLOT (python3 scripts/slot.py), from the repo root:

    python3 scripts/probe_models.py               # all chat models, full task set
    python3 scripts/probe_models.py --quick       # 3 tasks per model
    python3 scripts/probe_models.py --models qwen2.5-1.5b-instruct,qwen2.5-14b-instruct
    python3 scripts/probe_models.py --provider local   # Ollama on this machine, any time (dev only)

Standard library only. Reads the provider profile (CLOUD_* by default, LOCAL_* with --provider local:
<P>_BASE_URL, <P>_API_KEY, <P>_EMBEDDING_MODEL) from the environment or .env.
The key is never printed or written anywhere. Requests are sequential and spaced to stay under
20 requests/min and 2 concurrent; 429/503 Retry-After delays are respected.

Outputs:
  - console summary + recommended .env lines
  - docs/MODELS.md   (appends a "Probe results" section: model table, quota header names, ceilings)
  - scripts/out/probe-<timestamp>.json  (raw outputs for the prompt-evaluator agent; gitignored)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_GAP_S = float(os.environ.get("PROBE_GAP_S", "3.4"))  # 60/3.4 ≈ 17.6 req/min, under 20/min
EMBED_HINTS = ("embed", "bge", "e5-", "minilm", "nomic", "gte", "mxbai", "arctic-embed", "jina")
_last_call = 0.0
_secret = ""
_provider = "cloud"


# ----------------------------------------------------------------------------- config & http
def read_env() -> dict[str, str]:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("LLM_", "PROBE_", "CLOUD_", "LOCAL_"))})
    return env


def redact(text: str) -> str:
    return text.replace(_secret, "***") if _secret else text


def http(method: str, url: str, key: str, body: dict | None = None, timeout: int = 180):
    """Returns (status, headers_dict, json_or_text, seconds). Spaces calls; honours Retry-After."""
    global _last_call
    for attempt in range(4):
        wait = MIN_GAP_S - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        t0 = time.time()
        _last_call = t0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                status, headers = r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status, headers = e.code, dict(e.headers or {})
        except Exception as e:  # network / timeout
            return 0, {}, redact(f"{type(e).__name__}: {e}"), time.time() - t0
        dt = time.time() - t0
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = redact(raw[:2000])
        if status in (429, 503) and attempt < 3:
            ra = headers.get("Retry-After") or headers.get("retry-after")
            delay = float(ra) if ra and ra.replace(".", "").isdigit() else 5 * (attempt + 1)
            print(f"    … {status}, waiting {delay:.0f}s (Retry-After) and retrying")
            time.sleep(min(delay, 90))
            continue
        return status, headers, payload, dt
    return status, headers, payload, dt


# ----------------------------------------------------------------------------- helpers
def param_billions(model_id: str) -> float | None:
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])", model_id.replace("_", "-"))
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*[mM](?![a-zA-Z])", model_id)  # e.g. 135m / 500m
    return float(m.group(1)) / 1000 if m else None


def strip_think(text: str) -> tuple[str, bool]:
    had = "<think>" in text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(), had


def arabic_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("؀" <= c <= "ۿ" for c in letters) / len(letters) if letters else 0.0


def extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    return None


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ----------------------------------------------------------------------------- tasks
PASSAGE = (
    "Chapter 1 - Limits. The limit of f(x) as x approaches a is the value f(x) gets close to when x "
    "gets close to a, whether or not f(a) is defined. If direct substitution gives 0/0, the form is "
    "indeterminate: simplify first (factor, cancel, or rationalise). Example: (x^2-4)/(x-2) = x+2 for "
    "x != 2, so the limit as x->2 is 4. One-sided limits must agree for the limit to exist."
)

TASKS = {
    "quiz_json": dict(
        tier="both", max_tokens=700,
        messages=[
            {"role": "system", "content": "You write university quiz questions grounded ONLY in the given material. Reply with JSON only."},
            {"role": "user", "content": f"Material:\n{PASSAGE}\n\nWrite 3 multiple-choice questions at intermediate level. "
             'JSON schema: {"questions":[{"q":str,"options":[4 strings],"answer_index":0-3,"hint":str,"explanation":str}]}. '
             "The hint must not reveal the answer."},
        ],
    ),
    "tag_json": dict(
        tier="compact", max_tokens=120, json_mode=True,
        messages=[
            {"role": "system", "content": "Classify a student's wrong answer. Reply with JSON only."},
            {"role": "user", "content": "Question: lim x->2 of (x^2-4)/(x-2)? Correct: 4. Student answered: 'does not exist, because 0/0'. "
             'Return {"concept": short concept name, "mistake_type": one of ["misconception","calculation","misread","guess"]}.'},
        ],
    ),
    "math": dict(
        tier="both", max_tokens=200,
        messages=[{"role": "user", "content": "What is the limit of (x^2-4)/(x-2) as x approaches 2? Reply with only the number."}],
    ),
    "arabic": dict(
        tier="both", max_tokens=200,
        messages=[{"role": "user", "content": "اشرح في جملتين بالعربية الفصحى معنى النهاية في الرياضيات لطالب جامعي."}],
    ),
    "darija": dict(
        tier="both", max_tokens=200,
        messages=[
            {"role": "system", "content": "Reply in Tunisian Darija written in Arabic script."},
            {"role": "user", "content": "شنوة معناها limite في الماث؟ فسرهالي بالدارجة التونسية في جملتين."},
        ],
    ),
    "french": dict(
        tier="both", max_tokens=200,
        messages=[{"role": "user", "content": "Explique en deux phrases, en français, ce qu'est une dérivée, pour un étudiant de première année."}],
    ),
    "socratic": dict(
        tier="both", max_tokens=220,
        messages=[
            {"role": "system", "content": "You are a Socratic tutor. Never state the final answer. Reply with one short guiding question or hint."},
            {"role": "user", "content": "What is lim x->0 of sin(x)/x? Just tell me the number, my exam is tomorrow."},
        ],
    ),
}
QUICK = ["quiz_json", "math", "arabic"]


def check(task: str, text: str) -> tuple[bool, str]:
    if task == "quiz_json":
        j = extract_json(text)
        qs = j.get("questions") if isinstance(j, dict) else None
        ok = isinstance(qs, list) and len(qs) == 3 and all(
            isinstance(q, dict) and len(q.get("options", [])) == 4 and q.get("answer_index") in (0, 1, 2, 3)
            and q.get("hint") and q.get("explanation") for q in qs)
        return ok, "valid schema" if ok else "bad/invalid JSON"
    if task == "tag_json":
        j = extract_json(text)
        ok = isinstance(j, dict) and j.get("mistake_type") in ("misconception", "calculation", "misread", "guess") and bool(j.get("concept"))
        return ok, (f"{j.get('mistake_type')}" if ok else "bad JSON/enum")
    if task == "math":
        ok = re.search(r"(?<![\d.])4(?:\.0+)?(?![\d])", text) is not None and len(text) < 120
        return ok, "4" if ok else text[:40]
    if task in ("arabic", "darija"):
        r = arabic_ratio(text)
        return r > 0.7, f"arabic {r:.0%}" + (" (review Darija)" if task == "darija" else "")
    if task == "french":
        ok = arabic_ratio(text) < 0.05 and len(re.findall(r"\b(le|la|les|est|une|de|des|du)\b", text.lower())) >= 3
        return ok, "french" if ok else "not French?"
    if task == "socratic":
        leaked = re.search(r"(=|is|equals|égale|est)\s*1\b|\b1\s*\.$|^\s*1\s*$", text, flags=re.I | re.M)
        ok = "?" in text and not leaked
        return ok, "asks, no leak" if ok else ("leaked answer" if leaked else "no question")
    return False, "?"


# ----------------------------------------------------------------------------- probe
def chat(base, key, model, spec, disable_thinking, json_mode_ok):
    messages = [dict(m) for m in spec["messages"]]
    if "qwen3" in model.lower():  # Qwen3 soft switch, honoured by Ollama and vLLM alike
        sys_msg = next((m for m in messages if m["role"] == "system"), None)
        if sys_msg:
            sys_msg["content"] += " /no_think"
        else:
            messages.insert(0, {"role": "system", "content": "/no_think"})
    body = {"model": model, "messages": messages, "max_tokens": spec["max_tokens"], "temperature": 0.2, "stream": False}
    if disable_thinking and _provider == "cloud":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if spec.get("json_mode") and json_mode_ok is not False:
        body["response_format"] = {"type": "json_object"}
    status, headers, payload, dt = http("POST", f"{base}/chat/completions", key, body)
    json_mode_result = None
    if spec.get("json_mode") and json_mode_ok is not False:
        json_mode_result = status == 200
        if status == 400:  # retry without response_format
            body.pop("response_format")
            status, headers, payload, dt = http("POST", f"{base}/chat/completions", key, body)
    if status == 400 and disable_thinking and "chat_template_kwargs" in body:
        body.pop("chat_template_kwargs")
        status, headers, payload, dt = http("POST", f"{base}/chat/completions", key, body)
    return status, headers, payload, dt, json_mode_result


def main() -> None:
    global _secret, _provider
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=("cloud", "local"), default="cloud",
                    help="profile to probe: cloud = EdNova platform (in-slot only), local = Ollama (dev only)")
    ap.add_argument("--models", help="comma-separated model ids to test (default: all chat models)")
    ap.add_argument("--quick", action="store_true", help="3 tasks per model")
    ap.add_argument("--no-ceiling", action="store_true", help="skip the max_tokens ceiling probe")
    a = ap.parse_args()

    env = read_env()
    _provider = a.provider
    P = a.provider.upper()
    base = (env.get("PROBE_BASE_URL") or env.get(f"{P}_BASE_URL") or "").rstrip("/")
    key = env.get(f"{P}_API_KEY", "") or ("ollama" if a.provider == "local" else "")
    _secret = key if a.provider == "cloud" else ""
    if not base or not key:
        sys.exit(f"Set {P}_BASE_URL and {P}_API_KEY in .env (or the environment) first.")
    if a.provider == "cloud" and ("localhost" in base or "mock" in base):
        print(f"! {P}_BASE_URL is {base} (not the platform). Fix it in .env for a real probe.\n")

    print(f"Probing {base} …")
    status, headers, payload, dt = http("GET", f"{base}/models", key)
    if status != 200:
        sys.exit(f"GET /models failed: HTTP {status} {redact(str(payload))[:300]}\n"
                 + ("Outside your slot? Check: python3 scripts/slot.py" if a.provider == "cloud"
                    else "Is Ollama running? Try: ollama list"))
    models = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
    meta = {m.get("id"): {k: v for k, v in m.items() if k not in ("id", "object")} for m in payload.get("data", []) if isinstance(m, dict)}
    quota_headers = {k: v for k, v in headers.items() if re.search(r"ratelimit|quota|limit|remaining|retry|x-", k, re.I)
                     and k.lower() not in ("x-content-type-options",)}
    print(f"\n{len(models)} models:")
    for m in models:
        b = param_billions(m)
        print(f"  {m:55s} {'~%.1fB' % b if b else 'size ?':>8}  {json.dumps(meta.get(m))[:80]}")

    embed_models = [m for m in models if any(h in m.lower() for h in EMBED_HINTS)]
    chat_models = [m for m in models if m not in embed_models]
    if a.models:
        chat_models = [m for m in a.models.split(",") if m]
    tasks = QUICK if a.quick else list(TASKS)

    results: dict[str, dict] = {}
    for m in chat_models:
        size = param_billions(m)
        # Platform classes: compact < 3B, mid-size <= 16B. "3B" model names are ~3.1-3.2B in practice
        # and are usually served as compact, so treat <= 3.5B as compact.
        tier = "compact" if size is not None and size <= 3.5 else "mid" if size is not None and size <= 16.5 else "unknown"
        print(f"\n▶ {m}  ({tier})")
        r = {"size_b": size, "tier": tier, "tasks": {}, "latencies": [], "thinking": False, "json_mode": None, "errors": []}
        disable_thinking = "qwen3" in m.lower()
        for t in tasks:
            spec = TASKS[t]
            status, h, p, dt, jm = chat(base, key, m, spec, disable_thinking, r["json_mode"])
            if jm is not None:
                r["json_mode"] = jm
            if status != 200:
                msg = redact(json.dumps(p) if not isinstance(p, str) else p)[:200]
                r["errors"].append(f"{t}: HTTP {status} {msg}")
                r["tasks"][t] = {"ok": False, "note": f"HTTP {status}", "s": round(dt, 1)}
                print(f"    {t:10s} HTTP {status}  {msg[:90]}")
                continue
            msg = (p.get("choices") or [{}])[0].get("message", {})
            text = msg.get("content") or ""
            if msg.get("reasoning_content"):
                r["thinking"] = True
            text, had = strip_think(text)
            if had:
                r["thinking"] = True
                disable_thinking = True
            ok, note = check(t, text)
            usage = p.get("usage") or {}
            r["tasks"][t] = {"ok": ok, "note": note, "s": round(dt, 1), "out_tokens": usage.get("completion_tokens"), "text": text}
            r["latencies"].append(dt)
            if not quota_headers:
                quota_headers = {k: v for k, v in h.items() if re.search(r"ratelimit|quota|remaining", k, re.I)}
            print(f"    {t:10s} {'✓' if ok else '✗'} {dt:5.1f}s  {note}")
        r["score"] = sum(v["ok"] for v in r["tasks"].values()) / max(len(tasks), 1)
        r["median_s"] = round(statistics.median(r["latencies"]), 1) if r["latencies"] else None
        out_tok = [v.get("out_tokens") / v["s"] for v in r["tasks"].values() if v.get("out_tokens") and v["s"]]
        r["tok_per_s"] = round(statistics.median(out_tok), 1) if out_tok else None
        results[m] = r

    # embeddings
    emb = {}
    for m in embed_models or [env.get(f"{P}_EMBEDDING_MODEL", "")]:
        if not m or m.startswith("mock"):
            continue
        texts = ["limit of a function as x approaches a", "نهاية الدالة عندما يقترب x من a", "a recipe for chocolate cake"]
        status, h, p, dt = http("POST", f"{base}/embeddings", key, {"model": m, "input": texts})
        if status == 200 and isinstance(p, dict) and p.get("data"):
            v = [d["embedding"] for d in p["data"]]
            cross = cosine(v[0], v[1])
            unrelated = cosine(v[0], v[2])
            emb[m] = {"dim": len(v[0]), "s": round(dt, 2), "en_ar_sim": round(cross, 3), "unrelated_sim": round(unrelated, 3),
                      "multilingual": cross > unrelated + 0.05}
            print(f"\n▶ embeddings {m}: dim {len(v[0])}, EN↔AR {cross:.2f} vs unrelated {unrelated:.2f}, {dt:.1f}s")
        else:
            emb[m] = {"error": f"HTTP {status}"}
            print(f"\n▶ embeddings {m}: HTTP {status} {redact(str(p))[:150]}")

    # ceiling probe (one call on the smallest model)
    ceiling = None
    if not a.no_ceiling and a.provider == "cloud" and results:  # ceilings are a platform limit
        smallest = min(results, key=lambda k: results[k]["size_b"] or 99)
        status, h, p, dt = http("POST", f"{base}/chat/completions", key,
                                {"model": smallest, "messages": [{"role": "user", "content": "Say hi."}], "max_tokens": 100000})
        ceiling = f"HTTP {status}: {redact(json.dumps(p) if not isinstance(p, str) else p)[:300]}"
        print(f"\n▶ ceiling probe (max_tokens=100000 on {smallest}): {ceiling[:160]}")

    # pick
    def best(tier):
        c = [(m, r) for m, r in results.items() if r["tier"] == tier and r["median_s"] is not None]
        if not c:
            return None
        if tier == "compact":  # quality first, then speed
            return max(c, key=lambda x: (round(x[1]["score"], 2), -x[1]["median_s"]))[0]
        # mid: quality first, then prefer a model that answers in < 40 s median, then speed
        # mid: quality first, then must answer in < 40 s median, then the larger (more capable) model
        return max(c, key=lambda x: (round(x[1]["score"], 2), x[1]["median_s"] < 40, x[1]["size_b"] or 0, -x[1]["median_s"]))[0]

    compact, mid = best("compact"), best("mid")
    emb_pick = None
    if emb:
        ok = {m: e for m, e in emb.items() if "dim" in e}
        if ok:
            emb_pick = max(ok, key=lambda m: (ok[m]["multilingual"], ok[m]["en_ar_sim"] - ok[m]["unrelated_sim"]))
    thinking = any(results[m]["thinking"] for m in (compact, mid) if m)

    print("\n" + "=" * 72)
    print(f"{'model':45s} {'tier':8s} {'score':>6s} {'med s':>6s} {'tok/s':>6s} think json")
    for m, r in sorted(results.items(), key=lambda x: (x[1]["tier"], -x[1]["score"])):
        print(f"{m:45s} {r['tier']:8s} {r['score']:6.0%} {str(r['median_s']):>6s} {str(r['tok_per_s']):>6s} "
              f"{'yes' if r['thinking'] else 'no':5s} {r['json_mode']}")
    print("\nRecommended .env lines (paste into .env; never commit it):")
    lines = []
    if compact:
        lines.append(f"{P}_MODEL_COMPACT={compact}")
    if mid:
        lines.append(f"{P}_MODEL_MID={mid}")
    if emb_pick:
        lines += [f"{P}_EMBEDDING_MODEL={emb_pick}", f"{P}_EMBEDDING_DIM={emb[emb_pick]['dim']}"]
    lines.append(f"LLM_DISABLE_THINKING={'true' if thinking or any('qwen3' in (x or '').lower() for x in (compact, mid)) else 'false'}")
    print("  " + "\n  ".join(lines))
    if quota_headers:
        print("\nQuota-related headers seen:", ", ".join(f"{k}={v}" for k, v in quota_headers.items()))

    # write results
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = ROOT / "scripts" / "out"
    out.mkdir(parents=True, exist_ok=True)
    raw = out / f"probe-{a.provider}-{datetime.now():%Y%m%d-%H%M}.json"
    raw.write_text(json.dumps({"provider": a.provider, "base": f"{P}_BASE_URL", "models": models, "meta": meta, "results": results, "embeddings": emb,
                               "quota_headers": quota_headers, "ceiling": ceiling, "picked": {"compact": compact, "mid": mid, "embedding": emb_pick}},
                              ensure_ascii=False, indent=2))
    md = [f"\n## Probe results ({a.provider}) — {ts}\n", f"Models listed: {', '.join(f'`{m}`' for m in models)}\n",
          "| Model | Tier | Score | Median s | tok/s | Thinking | JSON mode | Failures |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m, r in sorted(results.items(), key=lambda x: (x[1]["tier"], -x[1]["score"])):
        fails = ", ".join(t for t, v in r["tasks"].items() if not v["ok"]) or "—"
        md.append(f"| `{m}` | {r['tier']} | {r['score']:.0%} | {r['median_s']} | {r['tok_per_s']} | {'yes' if r['thinking'] else 'no'} | {r['json_mode']} | {fails} |")
    for m, e in emb.items():
        md.append(f"\nEmbeddings `{m}`: {json.dumps(e)}")
    md.append(f"\n**Picked:** compact `{compact}` · mid `{mid}` · embeddings `{emb_pick}`")
    if quota_headers:
        md.append(f"\nQuota headers: {', '.join(f'`{k}`' for k in quota_headers)}")
    if ceiling:
        md.append(f"\nCeiling probe: `{ceiling[:250]}`")
    md.append(f"\nRaw outputs: `{raw.relative_to(ROOT)}` (give this to the prompt-evaluator agent; check Darija by hand)\n")
    with open(ROOT / "docs" / "MODELS.md", "a", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\nWrote docs/MODELS.md (appended) and {raw.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
