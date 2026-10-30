# Model selection

The platform's model list is only visible with our key during our slot: run
`python3 scripts/probe_models.py` (≈ 5–10 min, ~50 requests, paced under 20/min). It benchmarks
every chat model on our real tasks, tests the embedding model(s), probes the response ceiling,
records quota header names, appends a results section below and prints the `.env` lines.
Then: put the picks in `.env`, close the matching OPEN items in DECISIONS.md, and give the raw output
file to the `prompt-evaluator` agent. A native speaker checks the Darija answers by hand.

## What we need from each class
| Role | Must be good at | Matters less |
| --- | --- | --- |
| **Compact** (< 3B, most traffic) | valid JSON every time, following instructions, Arabic + French, speed | long reasoning |
| **Mid-size** (≤ 16B, scarce) | correct maths/science explanations, synthesis from chunks, Arabic & Darija writing quality, planning | speed (it runs mostly in background jobs) |
| **Embeddings** | **multilingual** (EN/FR/AR queries must find the same chunks), stable dimension | size |

## Likely candidates and how to rank them
Families commonly served in these size classes on CPU, best first for *our* use (Arabic, French,
JSON, maths). Use this to break ties or to judge models the probe scores equally.

**Compact**
1. **Qwen3-1.7B** (thinking disabled) or **Qwen2.5-1.5B-Instruct** — strongest small models for Arabic, French and JSON in this size class.
2. **SmolLM3-3B / Qwen2.5-3B / Llama-3.2-3B-Instruct** — if "3B" is served as compact: better reasoning, slower.
3. **Gemma-3-1B**, **Llama-3.2-1B** — fast but weak in Arabic and JSON. Only for triage or moderation if much faster.
4. Qwen3-0.6B / SmolLM2-360M — too weak for quiz generation; at most for language detection.

**Mid-size**
1. **Qwen3-14B** (thinking disabled) or **Qwen2.5-14B-Instruct** — best all-round pick: Arabic, French, maths, JSON, long-context synthesis.
2. **Gemma-3-12B** — strong multilingual writing (good for notes and Darija). Check maths.
3. **Phi-4 (14B)** — very strong maths and reasoning, weaker Arabic. Good for STEM explanations if the probe shows its Arabic is acceptable.
4. **Mistral-Nemo-12B / Ministral-8B** — strong French, average Arabic.
5. **Llama-3.1-8B / Qwen3-8B / Gemma-2-9B** — choose one of these if the 14B models are too slow on CPU (see the latency rule below).
6. Arabic-specialised models (ALLaM-7B, Jais) — pick for Arabic and Darija writing if listed and good on the probe, but check JSON reliability.

**Embeddings** — prefer **bge-m3** or **multilingual-e5** (base or large). Avoid English-only
models (all-MiniLM, nomic-embed-text v1) because Arabic queries would miss English chunks. The probe checks this
directly: an English sentence and its Arabic translation must score closer to each other than to an unrelated sentence.
Set the profile's `*_EMBEDDING_DIM` (e.g. `CLOUD_EMBEDDING_DIM`) to what the probe prints (bge-m3 = 1024, e5-base = 768, MiniLM = 384), because the
Qdrant collection is created with that size and changing it later means re-indexing.

## Rules of thumb on CPU
- A 14B model on CPU often produces only a few tokens per second, so a 600-token note can take minutes.
  That is fine for background jobs, but a waiting student needs a smaller output. **If the mid model's
  median latency on the probe exceeds 40 s, pick a 7–9B mid model**, or keep the 14B model and let
  only background tasks use it.
- **Qwen3 models "think" by default**, which wastes CPU time and can break JSON. The gateway sends
  `chat_template_kwargs: {"enable_thinking": false}` when `LLM_DISABLE_THINKING=true` and
  always strips `<think>…</think>` from replies. The probe tells you whether a model thinks.
- Keep `max_tokens` tight per task, at or below the ceiling the probe finds. Suggested budgets:
  tag 120 · tutor turn 220 · grade 300 · quiz (10 Q) 1,400, or two calls of 5 Q if the ceiling is lower · notes 700 · plan 400 · tip 160.
- If the platform exposes only one model per class, the probe still confirms its JSON, language and speed
  behaviour and records the quota headers. That information matters as much as the pick itself.

## Current picks
**Cloud (platform):** pending probe. Prefer the Qwen3 family if the platform lists it.
_Not yet probed. Mock values in `.env.example`. The probe appends its results below._

**Local (Ollama, dev only)** — never used in production or the demo (DECISIONS.md 2026-10-27)
| Role | Model | Fallback | Why |
| --- | --- | --- | --- |
| Compact | `qwen3:1.7b` | `qwen2.5:1.5b` | Top of our compact shortlist (Arabic, French, JSON); likely the same family as the cloud pick, so prompts transfer |
| Mid-size | `qwen3:14b`, or `qwen3:8b` under 16 GB RAM (our dev laptop: 15.4 GB → `qwen3:8b`) | `qwen2.5:14b` | Best all-round mid pick for maths, Arabic and synthesis; 8b keeps laptops usable |
| Embeddings | `bge-m3` (1024 dims) | — | Multilingual, so EN/FR/AR queries find the same chunks |

## Probe results (cloud) — 2026-10-30 18:06

Models listed: `llama3.2-3b`, `qwen2.5-3b`, `llama3.1-8b`, `mistral-7b`, `qwen2.5-coder-7b`, `deepseek-ocr`

| Model | Tier | Score | Median s | tok/s | Thinking | JSON mode | Failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `llama3.2-3b` | compact | 100% | 2.5 | 26.6 | no | True | — |
| `qwen2.5-3b` | compact | 86% | 4.0 | 10.0 | no | True | quiz_json |
| `llama3.1-8b` | mid | 100% | 3.6 | 13.4 | no | True | — |
| `mistral-7b` | mid | 86% | 7.9 | 15.1 | no | True | math |
| `qwen2.5-coder-7b` | mid | 86% | 4.9 | 14.2 | no | True | quiz_json |
| `deepseek-ocr` | unknown | 29% | 3.7 | 53.6 | no | True | quiz_json, tag_json, math, arabic, socratic |

Embeddings `pending-probe`: {"error": "HTTP 400"}

_20:50 follow-up (`scripts/probe_embeddings.py`):_ no embeddings model on our key. The proxy accepts only the ids in `/v1/models` (chat models only) and rejects bge-m3, e5, nomic, minilm, mxbai, jina and text-embedding-3-small with 400 "Invalid model name". OPEN in DECISIONS.md (to ask the organisers).

**Picked:** compact `llama3.2-3b` · mid `llama3.1-8b` · embeddings `None`

Quota headers: `X-Frame-Options`

Ceiling probe: `HTTP 200: {"id": "chatcmpl-00156c22-9455-461f-affe-cacaf10cb5a1", "created": 1793380009, "model": "llama3.2-3b", "object": "chat.completion", "choices": [{"finish_reason": "stop", "index": 0, "message": {"content": "Hi!", "role": "assistant", "provid`

Raw outputs: `scripts/out/probe-cloud-20261030-1806.json` (give this to the prompt-evaluator agent; check Darija by hand)
