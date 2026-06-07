#!/usr/bin/env python3
"""Send the daily quiz digest email.

Standard-library only (smtplib + email). Reads ``data/latest.json`` and emails a
clean HTML digest: a call-to-action link, the category breakdown, two solved
warm-up questions, and the day's grounding headlines.

Configuration comes from environment variables (set these as GitHub repo secrets):
    SMTP_HOST   default smtp.gmail.com
    SMTP_PORT   default 465  (SSL; use 587 for STARTTLS)
    SMTP_USER   sender address / SMTP username        (required)
    SMTP_PASS   SMTP password or Gmail App Password    (required)
    EMAIL_TO    recipient(s), comma-separated          (required)
    EMAIL_FROM  From header        (default: SMTP_USER)
    SITE_URL    link in the email  (default: the GitHub Pages URL)

If the required variables are missing the script exits 0 (clean skip) so the
daily workflow never fails just because email isn't configured.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

logger = logging.getLogger("send_email")

REPO_ROOT = Path(__file__).resolve().parent.parent
LATEST = REPO_ROOT / "data" / "latest.json"
DEFAULT_SITE = "https://sidhartha-patra.github.io/daily-gk-upsc/"


def _esc(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load() -> dict | None:
    try:
        return json.loads(LATEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not read %s: %s", LATEST, exc)
        return None


def _plain_text(quiz: dict, site: str) -> str:
    lines = [
        f"Daily GK & UPSC Trainer — {quiz.get('date', '')}",
        f"{quiz.get('count', 0)} fresh questions are ready.",
        "",
        f"Practise today's set: {site}",
        "",
        "Categories: "
        + ", ".join(f"{k} ({v})" for k, v in quiz.get("category_counts", {}).items()),
    ]
    news = quiz.get("news") or []
    if news:
        lines += ["", "In the news today:"]
        lines += [f"- ({n['source']}) {n['title']}" for n in news[:5]]
    lines += ["", "Educational use only — AI-generated; verify important facts."]
    return "\n".join(lines)


def _pick_samples(quiz: dict, n: int = 2) -> list[dict]:
    qs = quiz.get("questions", [])
    out, seen = [], set()
    # Prefer variety: one from Current Affairs if present, then spread categories.
    for q in qs:
        if q.get("category") == "Current Affairs":
            out.append(q)
            seen.add(q["category"])
            break
    for q in qs:
        if len(out) >= n:
            break
        if q.get("category") not in seen:
            out.append(q)
            seen.add(q.get("category"))
    return out[:n]


def _html(quiz: dict, site: str) -> str:
    date = _esc(quiz.get("date", ""))
    count = quiz.get("count", 0)
    chips = "".join(
        f'<span style="display:inline-block;background:#eef3ff;color:#2f6fed;border-radius:999px;'
        f'padding:3px 10px;margin:2px;font-size:12px;font-weight:600">{_esc(k)} · {v}</span>'
        for k, v in quiz.get("category_counts", {}).items()
    )

    samples = ""
    for q in _pick_samples(quiz):
        opts = "".join(
            f'<li style="margin:2px 0;{"font-weight:700;color:#1f9d57" if i == q["answer_index"] else ""}">'
            f'{chr(65 + i)}. {_esc(o)}{" ✓" if i == q["answer_index"] else ""}</li>'
            for i, o in enumerate(q.get("options", []))
        )
        samples += (
            f'<div style="border:1px solid #e1e6ef;border-radius:12px;padding:14px 16px;margin:10px 0">'
            f'<div style="font-size:12px;color:#5c6b80;font-weight:700;text-transform:uppercase;letter-spacing:.4px">'
            f'{_esc(q.get("category", ""))} · {_esc(q.get("difficulty", ""))}</div>'
            f'<div style="font-weight:700;margin:6px 0">{_esc(q.get("question", ""))}</div>'
            f'<ol style="list-style:none;padding:0;margin:6px 0;font-size:14px">{opts}</ol>'
            f'<div style="font-size:13px;color:#5c6b80;margin-top:6px">{_esc(q.get("explanation", ""))}</div>'
            f"</div>"
        )

    news = quiz.get("news") or []
    news_html = ""
    if news:
        items = "".join(
            f'<li style="margin:5px 0">'
            + (
                f'<a href="{_esc(n["link"])}" style="color:#1a2230;text-decoration:none">{_esc(n["title"])}</a>'
                if str(n.get("link", "")).startswith("http")
                else _esc(n["title"])
            )
            + f' <span style="color:#8b97a8;font-size:12px">— {_esc(n["source"])}</span></li>'
            for n in news[:6]
        )
        news_html = (
            '<h3 style="font-size:15px;margin:22px 0 6px">📰 In the news today</h3>'
            f'<ul style="padding-left:18px;margin:0;font-size:14px;line-height:1.5">{items}</ul>'
        )

    return f"""\
<!DOCTYPE html><html><body style="margin:0;background:#f4f6fb;font-family:Segoe UI,Arial,sans-serif;color:#1a2230">
  <div style="max-width:640px;margin:0 auto;padding:24px 16px">
    <div style="background:linear-gradient(135deg,#2f6fed,#1a2230);border-radius:16px;padding:22px 24px;color:#fff">
      <div style="font-size:22px;font-weight:800">🎯 Daily GK &amp; UPSC Trainer</div>
      <div style="opacity:.9;margin-top:4px">{date} · {count} fresh questions across {len(quiz.get('category_counts', {}))} categories</div>
    </div>

    <div style="text-align:center;margin:20px 0">
      <a href="{_esc(site)}" style="display:inline-block;background:#2f6fed;color:#fff;text-decoration:none;
         padding:13px 26px;border-radius:10px;font-weight:700;font-size:15px">Take today's test →</a>
    </div>

    <div style="text-align:center;margin:8px 0 4px">{chips}</div>

    <h3 style="font-size:15px;margin:22px 0 6px">🔎 Two to warm up</h3>
    {samples}

    {news_html}

    <p style="color:#8b97a8;font-size:12px;margin-top:24px;line-height:1.5">
      You're receiving this because the daily-quiz workflow is configured to email you.
      To stop, disable the <b>daily-quiz</b> GitHub Action or remove the email secrets.<br>
      Questions are AI-generated for self-study and may contain errors — verify important facts. Educational use only.
    </p>
  </div>
</body></html>"""


def build_message(quiz: dict) -> EmailMessage:
    site = os.environ.get("SITE_URL") or DEFAULT_SITE
    sender = os.environ["SMTP_USER"]
    from_addr = os.environ.get("EMAIL_FROM") or sender
    to_addrs = [a.strip() for a in os.environ["EMAIL_TO"].split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"] = f"🎯 Daily GK & UPSC — {quiz.get('date', '')}: {quiz.get('count', 0)} new questions"
    msg["From"] = formataddr(("Daily GK & UPSC Trainer", from_addr))
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(_plain_text(quiz, site))
    msg.add_alternative(_html(quiz, site), subtype="html")
    return msg


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    required = ("SMTP_USER", "SMTP_PASS", "EMAIL_TO")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.info("Email not configured (missing %s) — skipping send.", ", ".join(missing))
        return 0

    quiz = _load()
    if not quiz:
        logger.info("No quiz data to email — skipping.")
        return 0

    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]

    msg = build_message(quiz)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, password)
                s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email: %s", exc)
        return 1

    logger.info("Daily digest emailed to %s", msg["To"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
