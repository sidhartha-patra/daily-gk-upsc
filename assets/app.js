/* Daily GK & UPSC Trainer — vanilla JS, no build step.
   Progress lives in localStorage; attempts are the single source of truth and all
   stats (streak, mastery, mistakes, heatmap) are derived from them. */
(() => {
  "use strict";

  const STORE_KEY = "dgk_v1";
  const CATEGORIES = [
    "Polity", "History", "Geography", "Economy", "Science & Tech",
    "Environment", "Current Affairs", "International Relations",
    "Art & Culture", "Govt Schemes",
  ];

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- storage
  const defaultStore = () => ({ version: 1, attempts: {}, learned: {}, settings: { theme: "dark" } });
  function loadStore() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return defaultStore();
      const parsed = JSON.parse(raw);
      return Object.assign(defaultStore(), parsed);
    } catch {
      return defaultStore();
    }
  }
  function saveStore() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); }
    catch { toast("Storage full — could not save."); }
  }

  // ---------------------------------------------------------------- state
  const store = loadStore();
  const state = {
    today: null,       // latest.json
    activeQuiz: null,  // quiz currently shown in the Today tab
    mode: "today",     // "today" | "archive"
    filter: null,      // active category filter
    archive: null,     // index.json
  };

  // ---------------------------------------------------------------- helpers
  const fmtDate = (d) => {
    try {
      return new Date(d + "T00:00:00").toLocaleDateString(undefined,
        { weekday: "long", year: "numeric", month: "long", day: "numeric" });
    } catch { return d; }
  };
  const addDays = (dateStr, n) => {
    const d = new Date(dateStr + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };
  const scoreClass = (pct) => (pct >= 70 ? "good" : pct >= 40 ? "mid" : "low");

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2600);
  }

  // ---------------------------------------------------------------- derived
  function completedDates() {
    return Object.keys(store.attempts)
      .filter((d) => store.attempts[d] && store.attempts[d].completed)
      .sort();
  }
  function currentStreak() {
    const done = new Set(completedDates());
    if (!done.size) return 0;
    let anchor = state.today ? state.today.date : completedDates().slice(-1)[0];
    if (!done.has(anchor)) {
      const prev = addDays(anchor, -1);
      if (done.has(prev)) anchor = prev; else return 0;
    }
    let streak = 0;
    let cur = anchor;
    while (done.has(cur)) { streak++; cur = addDays(cur, -1); }
    return streak;
  }
  function longestStreak() {
    const dates = completedDates();
    if (!dates.length) return 0;
    let best = 1, run = 1;
    for (let i = 1; i < dates.length; i++) {
      run = addDays(dates[i - 1], 1) === dates[i] ? run + 1 : 1;
      best = Math.max(best, run);
    }
    return best;
  }
  function totals() {
    let answered = 0, correct = 0;
    const cat = {};
    CATEGORIES.forEach((c) => (cat[c] = { attempted: 0, correct: 0 }));
    for (const d of Object.keys(store.attempts)) {
      const a = store.attempts[d];
      if (!a || !a.answers) continue;
      for (const qid of Object.keys(a.answers)) {
        const ans = a.answers[qid];
        answered++;
        if (ans.correct) correct++;
        if (cat[ans.category]) {
          cat[ans.category].attempted++;
          if (ans.correct) cat[ans.category].correct++;
        }
      }
    }
    return { answered, correct, cat };
  }
  function collectMistakes() {
    const out = {};
    for (const d of Object.keys(store.attempts)) {
      const a = store.attempts[d];
      if (!a || !a.answers) continue;
      for (const qid of Object.keys(a.answers)) {
        const ans = a.answers[qid];
        if (!ans.correct && ans.snapshot && !store.learned[qid]) {
          out[qid] = Object.assign({ id: qid, date: d, selected: ans.selected }, ans.snapshot);
        }
      }
    }
    return Object.values(out);
  }

  // ---------------------------------------------------------------- data load
  async function fetchJSON(url) {
    const res = await fetch(url + (url.includes("?") ? "" : `?t=${Date.now()}`), { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    return res.json();
  }
  async function loadToday() {
    try {
      state.today = await fetchJSON("data/latest.json");
      state.activeQuiz = state.today;
      state.mode = "today";
    } catch (e) {
      state.today = null;
    }
  }
  async function loadArchiveIndex() {
    try { state.archive = await fetchJSON("data/index.json"); }
    catch { state.archive = { days: [] }; }
  }

  // ---------------------------------------------------------------- attempts
  function getAttempt(date, create) {
    if (!store.attempts[date] && create) {
      store.attempts[date] = { date, answers: {}, completed: false, startedAt: Date.now(), score: 0, total: 0 };
    }
    return store.attempts[date];
  }
  function recordAnswer(quiz, q, selected) {
    const a = getAttempt(quiz.date, true);
    if (a.answers[q.id]) return; // already answered, options are locked
    const correct = selected === q.answer_index;
    const rec = { selected, correct, category: q.category, difficulty: q.difficulty };
    if (!correct) {
      rec.snapshot = {
        question: q.question, options: q.options, answer_index: q.answer_index,
        explanation: q.explanation, topic: q.topic, category: q.category,
      };
    }
    a.answers[q.id] = rec;
    a.total = quiz.questions.length;
    a.score = Object.values(a.answers).filter((x) => x.correct).length;
    if (Object.keys(a.answers).length >= quiz.questions.length) finishAttempt(quiz, true);
    saveStore();
  }
  function finishAttempt(quiz, silent) {
    const a = getAttempt(quiz.date, true);
    a.completed = true;
    a.finishedAt = Date.now();
    a.durationSec = Math.max(1, Math.round((a.finishedAt - (a.startedAt || a.finishedAt)) / 1000));
    a.score = Object.values(a.answers).filter((x) => x.correct).length;
    a.total = quiz.questions.length;
    saveStore();
    if (!silent) toast(`Saved! Score ${a.score}/${a.total}`);
    renderStreak();
  }

  // ---------------------------------------------------------------- render: today
  function renderToday() {
    const quiz = state.activeQuiz;
    const titleEl = $("#todayTitle"), metaEl = $("#todayMeta"), gen = $("#genBadge");
    const list = $("#quizList"), statusEl = $("#quizStatus"), footer = $("#quizFooter");

    if (!quiz) {
      titleEl.textContent = "Today's Test";
      metaEl.textContent = "";
      list.innerHTML = "";
      footer.hidden = true;
      statusEl.classList.remove("hidden");
      statusEl.innerHTML =
        "No quiz data found yet. If you just deployed, the first daily build may " +
        "not have run — open the <b>Actions</b> tab on GitHub and run the " +
        "<b>daily-quiz</b> workflow, or run <code>python scripts/generate_quiz.py</code> locally.";
      return;
    }
    statusEl.classList.add("hidden");

    titleEl.textContent = state.mode === "archive" ? "Practice — past set" : "Today's Test";
    metaEl.innerHTML = `${esc(fmtDate(quiz.date))} &middot; ${quiz.questions.length} questions across ${CATEGORIES.length} categories`;
    if (quiz.generator) {
      gen.hidden = false;
      gen.textContent = quiz.generator.startsWith("github-models") ? "AI-generated" : "curated set";
    }

    renderFilter();
    renderProgress();

    const attempt = store.attempts[quiz.date];
    list.innerHTML = "";

    // Result card if completed.
    if (attempt && attempt.completed) {
      list.appendChild(resultCard(quiz, attempt));
    }

    const shown = quiz.questions.filter((q) => !state.filter || q.category === state.filter);
    shown.forEach((q) => list.appendChild(questionCard(quiz, q, attempt)));
    footer.hidden = false;
    $("#resetBtn").textContent = state.mode === "archive" ? "Reset this set" : "Reset Today";
  }

  function resultCard(quiz, attempt) {
    const pct = Math.round((attempt.score / attempt.total) * 100) || 0;
    const card = el("div", "result-card");
    const byCat = {};
    Object.values(attempt.answers).forEach((a) => {
      byCat[a.category] = byCat[a.category] || { c: 0, t: 0 };
      byCat[a.category].t++;
      if (a.correct) byCat[a.category].c++;
    });
    const chips = Object.keys(byCat)
      .map((c) => `<span class="rb-item">${esc(c)}: ${byCat[c].c}/${byCat[c].t}</span>`)
      .join("");
    card.innerHTML =
      `<div class="sub">You scored</div>` +
      `<div class="result-score">${attempt.score}/${attempt.total}</div>` +
      `<div class="sub">${pct}% &middot; ${attempt.durationSec ? Math.round(attempt.durationSec / 60) + " min" : ""}</div>` +
      `<div class="result-breakdown">${chips}</div>`;
    return card;
  }

  function questionCard(quiz, q, attempt) {
    const answered = attempt && attempt.answers[q.id];
    const card = el("div", "q-card");
    const idx = quiz.questions.indexOf(q) + 1;
    const top = el("div", "q-top");
    top.innerHTML =
      `<span class="q-num">Q${idx}</span>` +
      `<span class="tag">${esc(q.category)}</span>` +
      `<span class="tag d-${esc(q.difficulty)}">${esc(q.difficulty)}</span>` +
      (q.topic ? `<span class="tag">${esc(q.topic)}</span>` : "");
    card.appendChild(top);
    card.appendChild(el("div", "q-text", esc(q.question)));

    const opts = el("div", "options");
    q.options.forEach((opt, i) => {
      const b = el("button", "option");
      b.innerHTML = `<span class="key">${String.fromCharCode(65 + i)}</span><span>${esc(opt)}</span>`;
      if (answered) {
        b.disabled = true;
        if (i === q.answer_index) b.classList.add("correct");
        else if (i === answered.selected) b.classList.add("wrong");
      } else {
        b.addEventListener("click", () => {
          recordAnswer(quiz, q, i);
          renderToday();
        });
      }
      opts.appendChild(b);
    });
    card.appendChild(opts);

    if (answered) {
      const right = answered.correct;
      const ex = el("div", "explain");
      ex.innerHTML =
        `<b>${right ? "✅ Correct" : "❌ Incorrect"}</b> — correct answer: ` +
        `<b>${String.fromCharCode(65 + q.answer_index)}. ${esc(q.options[q.answer_index])}</b><br>${esc(q.explanation)}`;
      card.appendChild(ex);
    }
    return card;
  }

  function renderProgress() {
    const quiz = state.activeQuiz;
    if (!quiz) return;
    let bar = $("#progressBar");
    if (!bar) {
      bar = el("div", "progress-bar");
      bar.id = "progressBar";
      bar.innerHTML =
        `<span class="progress-meta" id="pmLeft"></span>` +
        `<div class="progress-track"><div class="progress-fill" id="pmFill"></div></div>` +
        `<span class="progress-meta" id="pmRight"></span>`;
      $("#quizList").before(bar);
    }
    const a = store.attempts[quiz.date];
    const answered = a ? Object.keys(a.answers).length : 0;
    const correct = a ? Object.values(a.answers).filter((x) => x.correct).length : 0;
    const total = quiz.questions.length;
    $("#pmLeft").textContent = `${answered}/${total} answered`;
    $("#pmRight").textContent = `Score ${correct}`;
    $("#pmFill").style.width = `${(answered / total) * 100}%`;
  }

  function renderFilter() {
    const wrap = $("#categoryFilter");
    wrap.innerHTML = "";
    const mk = (label, val) => {
      const c = el("button", "chip" + (state.filter === val ? " active" : ""), esc(label));
      c.addEventListener("click", () => { state.filter = val; renderToday(); });
      return c;
    };
    wrap.appendChild(mk("All", null));
    CATEGORIES.forEach((c) => wrap.appendChild(mk(c, c)));
  }

  // ---------------------------------------------------------------- render: dashboard
  function renderDashboard() {
    const t = totals();
    const acc = t.answered ? Math.round((t.correct / t.answered) * 100) : 0;
    const stats = [
      { num: currentStreak(), lbl: "Day streak 🔥", cls: "accent" },
      { num: longestStreak(), lbl: "Longest streak", cls: "primary" },
      { num: completedDates().length, lbl: "Days practiced", cls: "" },
      { num: t.answered, lbl: "Questions answered", cls: "" },
      { num: `${acc}%`, lbl: "Overall accuracy", cls: "good" },
    ];
    $("#statGrid").innerHTML = stats
      .map((s) => `<div class="stat"><div class="num ${s.cls}">${s.num}</div><div class="lbl">${s.lbl}</div></div>`)
      .join("");

    $("#masteryList").innerHTML = CATEGORIES.map((c) => {
      const m = t.cat[c];
      const pct = m.attempted ? Math.round((m.correct / m.attempted) * 100) : 0;
      return (
        `<div class="m-row"><div class="m-name">${esc(c)}</div>` +
        `<div class="m-track"><div class="m-fill" style="width:${pct}%"></div></div>` +
        `<div class="m-pct">${m.attempted ? pct + "%" : "—"}</div></div>`
      );
    }).join("");

    renderHeatmap();

    const recent = completedDates().slice(-8).reverse();
    $("#recentList").innerHTML = recent.length
      ? recent.map((d) => {
          const a = store.attempts[d];
          const pct = a.total ? Math.round((a.score / a.total) * 100) : 0;
          return (
            `<div class="recent-row"><span>${esc(fmtDate(d))}</span>` +
            `<span class="pill ${scoreClass(pct)}">${a.score}/${a.total} &middot; ${pct}%</span></div>`
          );
        }).join("")
      : `<div class="empty">No attempts yet. Head to the <b>Today</b> tab to start!</div>`;
  }

  function renderHeatmap() {
    const weeks = 17, days = weeks * 7;
    const anchor = state.today ? state.today.date : new Date().toISOString().slice(0, 10);
    const grid = $("#heatmap");
    grid.innerHTML = "";
    // Align so the last column ends on the anchor's weekday.
    const start = addDays(anchor, -(days - 1));
    for (let i = 0; i < days; i++) {
      const d = addDays(start, i);
      const a = store.attempts[d];
      let lvl = 0;
      if (a && a.completed && a.total) {
        const pct = a.score / a.total;
        lvl = pct >= 0.8 ? 4 : pct >= 0.6 ? 3 : pct >= 0.4 ? 2 : 1;
      }
      const cell = el("div", `hm-cell l${lvl}`);
      cell.title = a ? `${d}: ${a.score}/${a.total}` : `${d}: no activity`;
      grid.appendChild(cell);
    }
  }

  // ---------------------------------------------------------------- render: archive
  function renderArchive() {
    const list = $("#archiveList");
    const days = (state.archive && state.archive.days) || [];
    if (!days.length) {
      list.innerHTML = `<div class="empty">No past sets yet — they'll appear here as the daily build runs.</div>`;
      return;
    }
    list.innerHTML = "";
    days.forEach((d) => {
      const a = store.attempts[d.date];
      const done = a && a.completed;
      const row = el("div", "archive-row");
      row.innerHTML =
        `<span>${esc(fmtDate(d.date))}<br><span class="muted" style="font-size:12px">${d.count} questions</span></span>` +
        (done
          ? `<span class="pill ${scoreClass(Math.round((a.score / a.total) * 100))}">${a.score}/${a.total}</span>`
          : `<span class="pill">Practise →</span>`);
      row.addEventListener("click", () => openArchiveDay(d));
      list.appendChild(row);
    });
  }

  async function openArchiveDay(day) {
    try {
      const quiz = await fetchJSON("data/" + day.file);
      state.activeQuiz = quiz;
      state.mode = "archive";
      state.filter = null;
      switchView("today");
      toast(`Loaded ${fmtDate(day.date)}`);
    } catch {
      toast("Could not load that set.");
    }
  }

  // ---------------------------------------------------------------- render: review
  function renderReview() {
    const list = $("#reviewList");
    const items = collectMistakes();
    if (!items.length) {
      list.innerHTML = `<div class="empty">🎉 No outstanding mistakes. Answer some questions and any you miss will show up here for revision.</div>`;
      return;
    }
    list.innerHTML = "";
    items.reverse().forEach((m) => {
      const card = el("div", "q-card");
      card.innerHTML =
        `<div class="q-top"><span class="tag">${esc(m.category)}</span>` +
        (m.topic ? `<span class="tag">${esc(m.topic)}</span>` : "") +
        `<span class="muted" style="font-size:12px;margin-left:auto">${esc(m.date)}</span></div>` +
        `<div class="q-text">${esc(m.question)}</div>`;
      const opts = el("div", "options");
      m.options.forEach((opt, i) => {
        const b = el("button", "option");
        b.disabled = true;
        if (i === m.answer_index) b.classList.add("correct");
        else if (i === m.selected) b.classList.add("wrong");
        b.innerHTML = `<span class="key">${String.fromCharCode(65 + i)}</span><span>${esc(opt)}</span>`;
        opts.appendChild(b);
      });
      card.appendChild(opts);
      card.appendChild(el("div", "explain",
        `<b>Correct: ${String.fromCharCode(65 + m.answer_index)}. ${esc(m.options[m.answer_index])}</b><br>${esc(m.explanation)}`));
      const learn = el("button", "btn ghost", "✓ Mark as learned");
      learn.style.marginTop = "12px";
      learn.addEventListener("click", () => {
        store.learned[m.id] = true;
        saveStore();
        renderReview();
        toast("Marked as learned");
      });
      card.appendChild(learn);
      list.appendChild(card);
    });
  }

  // ---------------------------------------------------------------- chrome
  function renderStreak() {
    $("#streakCount").textContent = currentStreak();
  }
  function renderSubtitle() {
    const sub = $("#subtitle");
    if (state.today) {
      sub.innerHTML = `Fresh set for <b>${esc(fmtDate(state.today.date))}</b>`;
    } else {
      sub.textContent = "Open a daily set to begin";
    }
  }

  function switchView(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    if (name === "today") renderToday();
    if (name === "dashboard") renderDashboard();
    if (name === "archive") renderArchive();
    if (name === "review") renderReview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", store.settings.theme || "dark");
  }

  // ---------------------------------------------------------------- events
  function wire() {
    $$(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));

    $("#themeBtn").addEventListener("click", () => {
      store.settings.theme = store.settings.theme === "dark" ? "light" : "dark";
      saveStore();
      applyTheme();
    });

    $("#shareBtn").addEventListener("click", async () => {
      const url = location.href;
      const data = { title: "Daily GK & UPSC Trainer", text: "Practise UPSC & world-affairs MCQs daily:", url };
      if (navigator.share) { try { await navigator.share(data); } catch {} }
      else {
        try { await navigator.clipboard.writeText(url); toast("Link copied!"); }
        catch { toast(url); }
      }
    });

    $("#finishBtn").addEventListener("click", () => {
      if (!state.activeQuiz) return;
      finishAttempt(state.activeQuiz, false);
      renderToday();
    });

    $("#resetBtn").addEventListener("click", () => {
      if (!state.activeQuiz) return;
      if (!confirm("Reset your answers for this set?")) return;
      delete store.attempts[state.activeQuiz.date];
      saveStore();
      renderToday();
      renderStreak();
      toast("Set reset");
    });

    $("#clearMistakesBtn").addEventListener("click", () => {
      if (!confirm("Mark all current mistakes as learned?")) return;
      collectMistakes().forEach((m) => (store.learned[m.id] = true));
      saveStore();
      renderReview();
    });

    $("#exportBtn").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(store, null, 2)], { type: "application/json" });
      const a = el("a");
      a.href = URL.createObjectURL(blob);
      a.download = "dgk-progress.json";
      a.click();
      URL.revokeObjectURL(a.href);
    });

    $("#wipeBtn").addEventListener("click", () => {
      if (!confirm("Delete ALL progress? This cannot be undone.")) return;
      store.attempts = {};
      store.learned = {};
      saveStore();
      switchView("dashboard");
      renderStreak();
      toast("All progress cleared");
    });
  }

  // ---------------------------------------------------------------- init
  async function init() {
    applyTheme();
    wire();
    renderStreak();
    await Promise.all([loadToday(), loadArchiveIndex()]);
    renderSubtitle();
    renderToday();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
