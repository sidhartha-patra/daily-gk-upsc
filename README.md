# 🎯 Daily GK & UPSC Trainer

A self-study web app that serves a **fresh set of 30 UPSC-standard general-knowledge
and world-affairs MCQs every single day**, each with a detailed explanation, and tracks
your learning progress (streaks, category mastery, mistakes to revise).

The questions are regenerated automatically every morning by a GitHub Actions workflow
using **GitHub Models** (free), committed to the repo, and served as a zero-backend static
site on **GitHub Pages**. A **Streamlit** view is included for a desktop/Python experience.

> **🔗 Live site:** https://sidhartha-patra.github.io/daily-gk-upsc/
> _(available a few minutes after Pages is enabled and the first `daily-quiz` workflow run completes)_

---

## ✨ Features

- **30 fresh MCQs daily** across 10 UPSC categories — Polity, History, Geography, Economy,
  Science & Tech, Environment, Current Affairs, International Relations, Art & Culture, Govt Schemes.
- **Detailed explanations** on every question to actually learn, not just test.
- **Instant feedback** — pick an option and see correct/incorrect with the reasoning.
- **Progress tracking** (in your browser, private to you):
  - 🔥 Daily streak & longest streak
  - 📊 Per-category mastery bars
  - 🗓️ GitHub-style activity heatmap
  - 🔁 Auto-collected **Review Mistakes** list
- **Archive** — practise any previous day's set.
- **Light/dark theme**, fully responsive, shareable link.
- **Never breaks**: if the LLM is unavailable, a curated fallback question bank keeps the
  daily set flowing.

## 🧠 How it works

```
                 ┌─────────────────────────────────────────────┐
   06:00 IST ───►│ .github/workflows/daily.yml (cron + manual) │
                 └───────────────────┬─────────────────────────┘
                                     ▼
            scripts/generate_quiz.py ── GitHub Models (openai/gpt-4o-mini)
                  │   1) REST API  (CI, GITHUB_TOKEN, models:read)
                  │   2) gh models CLI (local)
                  │   3) curated fallback bank  ◄── scripts/fallback_bank.json
                  ▼
            data/quiz-YYYY-MM-DD.json  +  data/latest.json  +  data/index.json
                  │  (committed back to main)
                  ▼
            GitHub Pages serves index.html + assets/  ──►  your browser
                                                            (progress in localStorage)
```

- The generator de-duplicates against recent days so questions stay unique.
- Pages is served from the `main` branch, so each daily commit auto-republishes the site.
- All learning progress is stored in your browser's `localStorage` — nothing is uploaded.

## 🚀 Run it locally

**Static web app** (no dependencies):

```bash
# 1. Generate a set for today (uses your `gh` login for GitHub Models)
python scripts/generate_quiz.py
#    …or without any LLM, purely from the curated bank:
python scripts/generate_quiz.py --no-llm

# 2. Serve the site
python -m http.server 8000
#    open http://localhost:8000
```

**Streamlit view:**

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## 🔧 Customize

| What | Where |
| --- | --- |
| Categories | `CATEGORIES` in `scripts/generate_quiz.py` (and `assets/app.js`, `streamlit_app.py`) |
| Questions per category | `--per-category` flag (default `3` → 30/day) |
| Model | `LLM_MODEL` env var or `--model` (default `openai/gpt-4o-mini`) |
| Daily run time | `cron` in `.github/workflows/daily.yml` (default `30 0 * * *` = 06:00 IST) |
| Fallback questions | `scripts/fallback_bank.json` |

## 🗂️ Data schema

Each `data/quiz-YYYY-MM-DD.json`:

```jsonc
{
  "date": "2026-06-07",
  "generated_at": "2026-06-07T06:00:00+05:30",
  "generator": "github-models:openai/gpt-4o-mini",
  "count": 30,
  "questions": [
    {
      "id": "2026-06-07-01",
      "category": "Polity",
      "difficulty": "easy",
      "topic": "Fundamental Rights",
      "question": "…",
      "options": ["…", "…", "…", "…"],
      "answer_index": 2,
      "explanation": "…"
    }
  ]
}
```

`data/latest.json` mirrors the newest day; `data/index.json` is the archive list.

## ⚠️ Disclaimer

Questions are AI-generated for self-study and may occasionally contain inaccuracies.
Always cross-check important facts with standard sources (NCERT, PIB, etc.). Educational use only.

## 📄 License

[MIT](./LICENSE)
