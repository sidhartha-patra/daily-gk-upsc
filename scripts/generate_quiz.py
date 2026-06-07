#!/usr/bin/env python3
"""Generate the daily UPSC / general-knowledge MCQ quiz.

Strategy (robust, never hard-fails so the site always updates):
  1. GitHub Models REST API   (https://models.github.ai/inference)  -- primary in CI
  2. ``gh models run`` CLI     (uses the user's ``gh auth``)          -- primary locally
  3. Curated fallback bank     (scripts/fallback_bank.json)           -- always available

Questions are generated per category, de-duplicated against the last few days, and
written to ``data/quiz-YYYY-MM-DD.json`` plus ``data/latest.json`` and an
``data/index.json`` archive that the web app and Streamlit app both read.

Run from the repo root:
    python scripts/generate_quiz.py
    python scripts/generate_quiz.py --date 2026-06-07 --no-llm
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("generate_quiz")

try:  # fetch_news lives alongside this script; network use is lazy and optional.
    from fetch_news import fetch_headlines, headlines_as_context
except Exception:  # noqa: BLE001
    fetch_headlines = None  # type: ignore[assignment]
    headlines_as_context = None  # type: ignore[assignment]

IST = timezone(timedelta(hours=5, minutes=30))
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
BANK_PATH = REPO_ROOT / "scripts" / "fallback_bank.json"

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"

# The ten UPSC-oriented categories. 3 questions each -> 30/day by default.
CATEGORIES = [
    "Polity",
    "History",
    "Geography",
    "Economy",
    "Science & Tech",
    "Environment",
    "Current Affairs",
    "International Relations",
    "Art & Culture",
    "Govt Schemes",
]

DIFFICULTIES = {"easy", "medium", "hard"}

SYSTEM_PROMPT = (
    "You are an expert UPSC Civil Services examination question setter for the "
    "Indian General Studies (Prelims) paper. You write factually accurate, "
    "exam-standard multiple-choice questions with exactly four options and a "
    "single correct answer. You always respond with strict JSON only."
)


# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #
def _extract_json(text: str):
    """Strip markdown fences and recover the first JSON object/array in *text*."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not parse JSON from model response")


def _norm(text: str) -> str:
    """Normalise question text for duplicate detection."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# --------------------------------------------------------------------------- #
# LLM callers
# --------------------------------------------------------------------------- #
def _call_rest(prompt: str, model: str, token: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "top_p": 0.95,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        GITHUB_MODELS_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _call_cli(prompt: str, model: str) -> str:
    full = f"{SYSTEM_PROMPT}\n\n{prompt}"
    proc = subprocess.run(  # noqa: S603
        ["gh", "models", "run", model, full],
        capture_output=True,
        text=True,
        timeout=150,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh models run failed")
    return proc.stdout


def _gh_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.run(  # noqa: S603
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=20
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


# --------------------------------------------------------------------------- #
# Prompt + validation
# --------------------------------------------------------------------------- #
def _build_prompt(category: str, count: int, date_str: str, avoid: list[str], news_context: str = "") -> str:
    avoid_block = ""
    if avoid:
        sample = "\n".join(f"- {q}" for q in avoid[:25])
        avoid_block = (
            "\nDo NOT repeat or trivially rephrase any of these recently used "
            f"questions:\n{sample}\n"
        )
    extra = ""
    if category == "Current Affairs" or category == "International Relations":
        extra = (
            " Prioritise developments and world affairs that are durable and "
            f"important as of {date_str} (recent weeks). Avoid questions that "
            "depend on a single day's fleeting headline."
        )
    news_block = ""
    if news_context and category in ("Current Affairs", "International Relations"):
        news_block = (
            "\nGround the questions in these REAL, recent news developments. Ignore "
            "trivial, sports or purely local items; focus on the nationally and "
            "internationally significant ones (policy, economy, governance, "
            f"diplomacy, science):\n{news_context}\n"
        )
    return (
        f"Generate exactly {count} fresh, unique UPSC-Prelims-standard "
        f"multiple-choice questions for the category: \"{category}\".{extra}\n"
        f"Today's date is {date_str}. Vary the difficulty across easy, medium and hard.\n"
        f"{avoid_block}{news_block}\n"
        "Respond with STRICT JSON only, shaped exactly like this:\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        f'      "category": "{category}",\n'
        '      "difficulty": "easy | medium | hard",\n'
        '      "topic": "short topic tag",\n'
        '      "question": "the question text",\n'
        '      "options": ["option A", "option B", "option C", "option D"],\n'
        '      "answer_index": 0,\n'
        '      "explanation": "2-4 sentence explanation of why the answer is '
        'correct, teaching the underlying concept"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules: exactly 4 options; answer_index is the 0-based index of the correct "
        "option; options must be plausible and mutually exclusive; the explanation "
        "must be factually accurate and self-contained."
    )


def _valid_question(q: object) -> bool:
    if not isinstance(q, dict):
        return False
    opts = q.get("options")
    if not isinstance(opts, list) or len(opts) != 4:
        return False
    if any(not isinstance(o, str) or not o.strip() for o in opts):
        return False
    ai = q.get("answer_index")
    if not isinstance(ai, int) or not 0 <= ai <= 3:
        return False
    if not isinstance(q.get("question"), str) or not q["question"].strip():
        return False
    if not isinstance(q.get("explanation"), str) or not q["explanation"].strip():
        return False
    return True


def _clean_question(q: dict, category: str) -> dict:
    difficulty = str(q.get("difficulty", "medium")).strip().lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"
    return {
        "category": category,
        "difficulty": difficulty,
        "topic": str(q.get("topic", "")).strip() or category,
        "question": q["question"].strip(),
        "options": [str(o).strip() for o in q["options"]],
        "answer_index": int(q["answer_index"]),
        "explanation": q["explanation"].strip(),
    }


# --------------------------------------------------------------------------- #
# History (de-duplication) + fallback bank
# --------------------------------------------------------------------------- #
def _recent_questions(days: int = 10) -> dict[str, list[str]]:
    """Map category -> list of recently used question texts."""
    out: dict[str, list[str]] = {}
    if not DATA_DIR.exists():
        return out
    files = sorted(DATA_DIR.glob("quiz-*.json"), reverse=True)[:days]
    for fp in files:
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for q in payload.get("questions", []):
            cat = q.get("category", "")
            out.setdefault(cat, []).append(q.get("question", ""))
    return out


def _load_bank() -> list[dict]:
    try:
        payload = json.loads(BANK_PATH.read_text(encoding="utf-8"))
        return payload.get("questions", [])
    except (OSError, json.JSONDecodeError):
        return []


def _seeded_shuffle(items: list, seed: int) -> list:
    """Deterministic Fisher-Yates so a given date always yields the same set."""
    import random

    rng = random.Random(seed)
    out = list(items)
    rng.shuffle(out)
    return out


def _shuffle_options(q: dict, seed: int) -> dict:
    """Shuffle option order deterministically and fix answer_index."""
    import random

    rng = random.Random(seed)
    correct = q["options"][q["answer_index"]]
    opts = list(q["options"])
    rng.shuffle(opts)
    out = dict(q)
    out["options"] = opts
    out["answer_index"] = opts.index(correct)
    return out


def _fallback_for(category: str, count: int, seed: int, used: set[str]) -> list[dict]:
    bank = [q for q in _load_bank() if q.get("category") == category]
    bank = _seeded_shuffle(bank, seed)
    picked: list[dict] = []
    for q in bank:
        if _norm(q["question"]) in used:
            continue
        if not _valid_question(q):
            continue
        cleaned = _clean_question(q, category)
        cleaned = _shuffle_options(cleaned, seed + len(picked))
        picked.append(cleaned)
        used.add(_norm(q["question"]))
        if len(picked) >= count:
            break
    # If the (small) bank is exhausted, allow reuse rather than returning short.
    if len(picked) < count:
        for q in bank:
            if len(picked) >= count:
                break
            if not _valid_question(q):
                continue
            picked.append(_shuffle_options(_clean_question(q, category), seed + len(picked)))
    return picked


# --------------------------------------------------------------------------- #
# Per-category generation
# --------------------------------------------------------------------------- #
def _generate_category(
    category: str,
    count: int,
    date_str: str,
    seed: int,
    recent: list[str],
    used: set[str],
    model: str,
    token: str | None,
    use_llm: bool,
    news_context: str = "",
) -> list[dict]:
    questions: list[dict] = []
    if use_llm:
        prompt = _build_prompt(category, count, date_str, recent, news_context)
        raw = None
        try:
            if token:
                raw = _call_rest(prompt, model, token)
            else:
                raise RuntimeError("no token for REST path")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] REST path failed: %s", category, exc)
            try:
                raw = _call_cli(prompt, model)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("[%s] gh CLI path failed: %s", category, exc2)
                raw = None
        if raw:
            try:
                parsed = _extract_json(raw)
                items = parsed.get("questions", parsed) if isinstance(parsed, dict) else parsed
                for q in items or []:
                    if not _valid_question(q):
                        continue
                    key = _norm(q["question"])
                    if key in used:
                        continue
                    questions.append(_clean_question(q, category))
                    used.add(key)
                    if len(questions) >= count:
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] parse failed: %s", category, exc)

    if len(questions) < count:
        need = count - len(questions)
        logger.info("[%s] topping up %d question(s) from fallback bank", category, need)
        questions.extend(_fallback_for(category, need, seed, used))

    return questions[:count]


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def _write_outputs(date_str: str, generator: str, questions: list[dict], news: list[dict] | None = None) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(questions, start=1):
        q["id"] = f"{date_str}-{i:02d}"

    category_counts: dict[str, int] = {}
    for q in questions:
        category_counts[q["category"]] = category_counts.get(q["category"], 0) + 1

    quiz = {
        "date": date_str,
        "generated_at": datetime.now(IST).isoformat(),
        "generator": generator,
        "categories": CATEGORIES,
        "category_counts": category_counts,
        "count": len(questions),
        "news": news or [],
        "questions": questions,
    }

    quiz_path = DATA_DIR / f"quiz-{date_str}.json"
    quiz_path.write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "latest.json").write_text(
        json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Rebuild the archive index from whatever quiz files exist.
    days = []
    for fp in sorted(DATA_DIR.glob("quiz-*.json"), reverse=True):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        days.append(
            {
                "date": payload.get("date"),
                "file": fp.name,
                "count": payload.get("count", 0),
                "generator": payload.get("generator", ""),
            }
        )
    index = {"updated_at": datetime.now(IST).isoformat(), "days": days}
    (DATA_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return quiz_path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate(date_str: str, per_category: int, model: str, use_llm: bool, use_news: bool = True) -> Path:
    seed_base = int(date_str.replace("-", ""))
    recent_map = _recent_questions()
    used: set[str] = set()
    for texts in recent_map.values():
        used.update(_norm(t) for t in texts)

    token = _gh_token() if use_llm else None
    if use_llm and not token:
        logger.info("No GitHub token found; will use gh CLI or fallback bank.")

    news_headlines: list[dict] = []
    news_context = ""
    if use_news and use_llm and fetch_headlines is not None:
        try:
            news_headlines = fetch_headlines()
            news_context = headlines_as_context(news_headlines) if news_headlines else ""
            logger.info("news: grounding current affairs with %d headlines", len(news_headlines))
        except Exception as exc:  # noqa: BLE001
            logger.warning("news: fetch failed, continuing without grounding: %s", exc)

    all_questions: list[dict] = []
    llm_used = False
    for idx, category in enumerate(CATEGORIES):
        seed = seed_base + idx
        before = len(used)
        qs = _generate_category(
            category=category,
            count=per_category,
            date_str=date_str,
            seed=seed,
            recent=recent_map.get(category, []),
            used=used,
            model=model,
            token=token,
            use_llm=use_llm,
            news_context=news_context,
        )
        # Heuristic: if we added brand-new (not bank-duplicate) keys, LLM likely worked.
        if use_llm and len(used) > before:
            llm_used = True
        all_questions.extend(qs)
        logger.info("[%s] %d question(s) ready", category, len(qs))

    news_out = [
        {
            "title": h["title"],
            "source": h["source"],
            "link": h.get("link", ""),
            "published": h["published"].isoformat() if h.get("published") else None,
        }
        for h in news_headlines
    ]
    generator = f"github-models:{model}" if (use_llm and llm_used) else "fallback-bank"
    path = _write_outputs(date_str, generator, all_questions, news_out)
    logger.info("Wrote %d questions -> %s (generator=%s)", len(all_questions), path, generator)
    return path


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate the daily UPSC/GK quiz.")
    parser.add_argument("--date", default=datetime.now(IST).strftime("%Y-%m-%d"))
    parser.add_argument("--per-category", type=int, default=3)
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", DEFAULT_MODEL))
    parser.add_argument("--no-llm", action="store_true", help="Use the fallback bank only.")
    parser.add_argument("--no-news", action="store_true", help="Skip live news grounding.")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        parser.error("--date must be YYYY-MM-DD")

    generate(
        date_str=args.date,
        per_category=args.per_category,
        model=args.model,
        use_llm=not args.no_llm,
        use_news=not args.no_news,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
