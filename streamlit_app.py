"""Streamlit view for the Daily GK / UPSC Trainer.

Reads the same ``data/*.json`` the static site uses (so the daily GitHub Actions
build feeds both) and persists attempt summaries to a local SQLite database
(``data/progress.db``) following the project's "CREATE TABLE IF NOT EXISTS" style.

Run from the repo root:
    pip install -r requirements.txt
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "progress.db"

CATEGORIES = [
    "Polity", "History", "Geography", "Economy", "Science & Tech",
    "Environment", "Current Affairs", "International Relations",
    "Art & Culture", "Govt Schemes",
]


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_index() -> list[dict]:
    idx = _read_json(DATA_DIR / "index.json") or {}
    return idx.get("days", [])


def load_quiz(file_name: str) -> dict | None:
    return _read_json(DATA_DIR / file_name)


# --------------------------------------------------------------------------- #
# Persistence (SQLite, lazy schema)
# --------------------------------------------------------------------------- #
def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            quiz_date TEXT PRIMARY KEY,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS category_stats (
            category TEXT PRIMARY KEY,
            attempted INTEGER NOT NULL DEFAULT 0,
            correct INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def save_attempt(quiz_date: str, score: int, total: int, per_cat: dict[str, tuple[int, int]]) -> None:
    conn = _db()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO attempts (quiz_date, score, total, attempted_at) VALUES (?, ?, ?, ?)",
            (quiz_date, score, total, datetime.now().isoformat(timespec="seconds")),
        )
        for cat, (att, cor) in per_cat.items():
            conn.execute(
                """
                INSERT INTO category_stats (category, attempted, correct) VALUES (?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET
                    attempted = attempted + excluded.attempted,
                    correct = correct + excluded.correct
                """,
                (cat, att, cor),
            )
    conn.close()


def read_stats() -> tuple[list[tuple], list[tuple]]:
    conn = _db()
    attempts = conn.execute(
        "SELECT quiz_date, score, total, attempted_at FROM attempts ORDER BY quiz_date DESC"
    ).fetchall()
    cats = conn.execute(
        "SELECT category, attempted, correct FROM category_stats ORDER BY category"
    ).fetchall()
    conn.close()
    return attempts, cats


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def render_quiz(quiz: dict) -> None:
    st.caption(
        f"{quiz['date']} · {quiz['count']} questions · "
        f"{'AI-generated' if str(quiz.get('generator', '')).startswith('github-models') else 'curated set'}"
    )

    chosen = st.multiselect("Filter categories", CATEGORIES, default=[])
    questions = [q for q in quiz["questions"] if not chosen or q["category"] in chosen]

    with st.form(key=f"quiz-{quiz['date']}"):
        picks: dict[str, int | None] = {}
        for i, q in enumerate(questions, start=1):
            st.markdown(f"**Q{i}. {q['question']}**")
            st.caption(f"{q['category']} · {q['difficulty']} · {q.get('topic', '')}")
            labels = [f"{chr(65 + j)}. {opt}" for j, opt in enumerate(q["options"])]
            choice = st.radio("Select an answer", labels, index=None, key=f"{quiz['date']}-{q['id']}", label_visibility="collapsed")
            picks[q["id"]] = labels.index(choice) if choice is not None else None
            st.divider()
        submitted = st.form_submit_button("Submit & grade", type="primary")

    if not submitted:
        return

    score = 0
    per_cat: dict[str, list[int]] = {}
    for q in questions:
        sel = picks.get(q["id"])
        if sel is None:
            continue
        correct = sel == q["answer_index"]
        score += int(correct)
        pc = per_cat.setdefault(q["category"], [0, 0])
        pc[0] += 1
        pc[1] += int(correct)

    answered = sum(1 for q in questions if picks.get(q["id"]) is not None)
    st.success(f"You scored {score}/{answered} ({round(100 * score / answered) if answered else 0}%).")

    save_attempt(quiz["date"], score, answered, {k: (v[0], v[1]) for k, v in per_cat.items()})

    st.markdown("### Review & explanations")
    for i, q in enumerate(questions, start=1):
        sel = picks.get(q["id"])
        right = sel == q["answer_index"]
        icon = "✅" if right else ("⬜" if sel is None else "❌")
        with st.expander(f"{icon} Q{i}. {q['question']}", expanded=not right and sel is not None):
            for j, opt in enumerate(q["options"]):
                marker = ""
                if j == q["answer_index"]:
                    marker = " ✅ (correct)"
                elif j == sel:
                    marker = " ❌ (your answer)"
                st.markdown(f"- {chr(65 + j)}. {opt}{marker}")
            st.info(q["explanation"])


def render_dashboard() -> None:
    attempts, cats = read_stats()
    if not attempts:
        st.info("No attempts saved yet. Take today's quiz to start tracking progress.")
        return

    total_q = sum(a[2] for a in attempts)
    total_c = sum(a[1] for a in attempts)
    acc = round(100 * total_c / total_q) if total_q else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Days practised", len(attempts))
    c2.metric("Questions answered", total_q)
    c3.metric("Overall accuracy", f"{acc}%")

    st.markdown("### Category mastery")
    for cat, att, cor in cats:
        pct = (cor / att) if att else 0.0
        st.markdown(f"**{cat}** — {cor}/{att} ({round(pct * 100)}%)")
        st.progress(pct)

    st.markdown("### Recent attempts")
    st.dataframe(
        {
            "Date": [a[0] for a in attempts],
            "Score": [f"{a[1]}/{a[2]}" for a in attempts],
            "When": [a[3] for a in attempts],
        },
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Daily GK & UPSC Trainer", page_icon="🎯", layout="centered")
    st.title("🎯 Daily GK & UPSC Trainer")

    days = load_index()
    if not days:
        st.warning(
            "No quiz data found. Run `python scripts/generate_quiz.py` (or trigger the "
            "`daily-quiz` GitHub Action) to create today's set."
        )
        return

    tab_quiz, tab_dash = st.tabs(["📝 Practice", "📊 Dashboard"])

    with tab_quiz:
        labels = [f"{d['date']} ({d['count']} Qs)" for d in days]
        pick = st.sidebar.selectbox("Choose a day", labels, index=0)
        day = days[labels.index(pick)]
        quiz = load_quiz(day["file"])
        if quiz:
            render_quiz(quiz)
        else:
            st.error("Could not load that day's quiz file.")

    with tab_dash:
        render_dashboard()

    st.sidebar.caption("Questions are AI-generated for self-study. Verify important facts.")


if __name__ == "__main__":
    main()
