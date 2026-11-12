// MMRSlave dashboard. Plain JS, no build step.
import { t, t as tr, loc, area, tag, statLabel, dateLocale, getLang, setLang } from "./i18n.js";

const $ = (sel, root = document) => root.querySelector(sel);
const main = $("#main");
const SVGNS = "http://www.w3.org/2000/svg";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = {
  matches: [],
  status: null,
  geometry: null,
  match: null,        // current analysis
  replay: null,       // the whole game's positions, for the board
  curves: null,       // your and Immortal players' stats by minute
  matchId: null,
  selectedT: null,    // game second on the board
  activeMoment: null, // coach moment the board is paused on
  moments: [],
  play: { playing: false, speed: 1, last: 0 },
  autoPause: true,
  tab: "immortal",
  account: null,      // connected Steam account
  version: null,      // installed version and the last update check
  restarting: false,
};

// ------------------------------------------------------------------ helpers

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function clock(t) {
  if (t == null || Number.isNaN(t)) return "";
  const neg = t < 0;
  const s = Math.abs(Math.round(t));
  return `${neg ? "-" : ""}${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function parseClock(text) {
  const m = /(-?)(\d{1,3}):(\d{2})/.exec(text || "");
  if (!m) return null;
  return (m[1] ? -1 : 1) * (parseInt(m[2], 10) * 60 + parseInt(m[3], 10));
}

function fmt(n, digits = 0) {
  if (n == null) return "–";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function relDay(unix) {
  if (!unix) return "";
  const d = new Date(unix * 1000);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return t("Today");
  if (days === 1) return t("Yesterday");
  if (days < 7) return t("{n} days ago", { n: days });
  return d.toLocaleDateString(dateLocale(), { month: "short", day: "numeric" });
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch (e) { /* not json */ }
    throw new Error(detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

function svg(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

function loading(text) {
  return `<p class="loading-line"><svg viewBox="0 0 40 12" aria-hidden="true"><path d="M2 6 Q 12 1 20 6 T 38 6"/></svg>${esc(text)}</p>`;
}

const teamOf = (pid) => (pid < 5 ? 0 : 1);

// ------------------------------------------------------------------ theme

function setupTheme() {
  const btn = $("#themeBtn");
  const label = () => {
    const light = document.documentElement.dataset.theme === "light";
    btn.setAttribute("aria-label", light ? t("Switch to dark mode") : t("Switch to light mode"));
  };
  label();
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("mmrslave-theme", next); } catch (e) { /* storage blocked */ }
    label();
  });
}

// Text written in index.html carries data-i18n (its English text) and is translated here.
function translateStatic() {
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-label]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nLabel)));
  const light = document.documentElement.dataset.theme === "light";
  $("#themeBtn").setAttribute("aria-label", light ? t("Switch to dark mode") : t("Switch to light mode"));
  document.querySelectorAll("#langSwitch [data-lang]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === getLang()));
}

function setupLanguage() {
  translateStatic();
  document.querySelectorAll("#langSwitch [data-lang]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.lang === getLang()) return;
    setLang(b.dataset.lang);
    translateStatic();
    renderGames();
    renderBrainMeta();
    renderAccount();
    renderUpdatePill();
    if (state.match && state.matchId === state.match.match_id && $("#board")) renderMatch();
    else route();
  }));
}

// ------------------------------------------------------------------ rail

function renderGames() {
  const ul = $("#games");
  if (!state.matches.length) {
    ul.innerHTML = `<li class="games-empty">${state.account && !state.account.steam_id
      ? t("Sign in through Steam to see your games.") : t("No games yet. Fetch your latest games to start.")}</li>`;
    return;
  }
  ul.innerHTML = state.matches.map((m) => `
    <li><a class="game" href="#/match/${m.match_id}" data-id="${m.match_id}" ${m.match_id === state.matchId ? 'aria-current="page"' : ""}>
      <span>
        <span class="g-hero">${esc(m.hero)}</span><br>
        <span class="g-meta">pos ${esc(m.position ?? "?")} · ${esc(m.kda)} · ${esc(relDay(m.start_time))}</span>
        ${m.analyzed ? "" : `<br><span class="g-new">${t("not reviewed yet")}</span>`}
      </span>
      <span class="g-right">
        <span class="g-res ${m.won ? "won" : "lost"}">${m.won ? "W" : "L"}</span><br>
        <span class="g-meta num">${esc(m.duration)}</span>
      </span>
    </a></li>`).join("");
}

function markCurrentGame() {
  document.querySelectorAll(".game").forEach((a) => {
    if (Number(a.dataset.id) === state.matchId) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  for (const [el, prefix] of [[$("#brainLink"), "#/brain"], [$("#settingsLink"), "#/settings"]]) {
    if (location.hash.startsWith(prefix)) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  }
}

function renderBrainMeta() {
  const st = state.status;
  if (!st) return;
  const games = (st.summary || []).filter((r) => r.source === "immortal" && r.status === "parsed").reduce((a, r) => a + r.n, 0);
  const last = (st.history || []).at(-1);
  const acc = last?.winprob_accuracy != null ? t(" · win chance {p}% right", { p: Math.round(last.winprob_accuracy * 100) }) : "";
  $("#brainMeta").textContent = t("{games} Immortal games learned", { games: fmt(games) }) + acc;
}

async function refreshRail() {
  try {
    [state.matches, state.status] = await Promise.all([api("/api/matches"), api("/api/status")]);
  } catch (e) {
    $("#games").innerHTML = `<li class="games-empty">${t("Couldn't load your games: {e}", { e: esc(e.message) })}</li>`;
    return;
  }
  renderGames();
  renderBrainMeta();
  renderAccount();
}

// ------------------------------------------------------------------ background jobs

async function pollJob(name, onLine) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    let jobs;
    try { jobs = await api("/api/jobs"); } catch (e) { continue; }
    const job = jobs[name];
    if (!job) return { state: "error", log: ["the job disappeared"] };
    onLine(job.log.at(-1) || "working…");
    if (job.state !== "running") return job;
  }
}

function setupFetch() {
  const btn = $("#fetchBtn");
  const line = $("#fetchStatus");
  btn.addEventListener("click", async () => {
    btn.setAttribute("aria-busy", "true");
    btn.disabled = true;
    line.classList.remove("err");
    line.textContent = t("Asking OpenDota for your recent games…");
    try {
      await api("/api/fetch-mine", { method: "POST" });
      const job = await pollJob("fetch-mine", (msg) => { line.textContent = msg.replace(/^\[.*?\]\s*/, ""); });
      if (job.state === "error") {
        line.classList.add("err");
        line.textContent = (job.log.at(-1) || t("Fetching failed.")).replace(/^error:\s*/, t("Couldn't fetch: {e}", { e: "" }));
      } else {
        line.textContent = t("Up to date.");
        await refreshRail();
        if (!state.matchId && state.matches.length) location.hash = `#/match/${state.matches[0].match_id}`;
      }
    } catch (e) {
      line.classList.add("err");
      line.textContent = t("Couldn't fetch: {e}", { e: e.message });
    } finally {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
  });
}

// ------------------------------------------------------------------ routing

async function route() {
  const hash = location.hash || "#/";
  const m = /^#\/match\/(\d+)/.exec(hash);
  if (m) {
    await showMatch(Number(m[1]));
  } else if (hash.startsWith("#/brain")) {
    pause();
    state.matchId = null;
    showBrain();
  } else if (hash.startsWith("#/settings")) {
    showSettings();
  } else if (state.matches.length) {
    location.replace(`#/match/${state.matches[0].match_id}`);
    return;
  } else {
    state.matchId = null;
    showEmpty();
  }
  markCurrentGame();
}

function showEmpty() {
  if (state.account && !state.account.steam_id) {
    main.innerHTML = `
    <section class="state">
      <h1>${t("Connect your Steam account")}</h1>
      <p>${t("MMRSlave reviews your own ranked games. Sign in through Steam so it can find them; you sign in on Steam's own page and MMRSlave only learns your Steam ID.")}</p>
      <p><a class="btn btn-brand" href="/auth/steam/login">${t("Sign in through Steam")}</a></p>
    </section>`;
    return;
  }
  main.innerHTML = `
    <section class="state">
      <h1>${t("No games to review yet")}</h1>
      <p>${t("Press <b>{btn}</b> to download your last 20 ranked games. In Dota 2, keep <b>Settings → Social → Expose Public Match Data</b> on, or they can't be found.", { btn: t("Fetch my latest games") })}</p>
      <p>${t("From a terminal you can also run <code>python -m mmrslave mine</code>.")}</p>
    </section>`;
}

// ------------------------------------------------------------------ match view

async function showMatch(id) {
  state.matchId = id;
  markCurrentGame();
  if (!state.match || state.match.match_id !== id) {
    pause();
    main.innerHTML = `<section class="state">${loading(t("Reviewing this game… (the first look takes a few seconds)"))}</section>`;
    try {
      [state.match, state.replay] = await Promise.all([api(`/api/match/${id}`), api(`/api/match/${id}/replay`)]);
    } catch (e) {
      main.innerHTML = `<section class="state"><h1>${t("Couldn't open this game")}</h1><p>${esc(e.message)}</p>
        <p><button class="btn" type="button" id="retry">${t("Try again")}</button></p></section>`;
      $("#retry").addEventListener("click", () => { state.match = null; showMatch(id); });
      return;
    }
    state.curves = null;
    state.activeMoment = null;
    state.selectedT = null;
  }
  renderMatch();
}

function myPlayer(an) { return an.me != null ? an.players[an.me] : null; }

// Deaths say "Died to…" already; other moments carry their kind as a small tag after the title.
function kindTag(m) {
  const label = m.kind !== "death" && KIND_LABEL[m.kind];
  return label ? ` <span class="kind-tag">${esc(t(label))}</span>` : "";
}

const KIND_LABEL = {
  death: "Your death", missed_fight: "Fight you missed", tower_lost: "Tower lost",
  advantage_unused: "No objective", runes: "Runes", report: "Coach",
};

// Everything on the list is about you: your deaths, and the decisions you could have made
// differently. With a written report, its mistakes lead.
function buildMoments(an) {
  const myDeaths = an.deaths.filter((d) => d.victim === an.me);
  const deathMoment = (d, i) => ({
    id: `d${i}`, kind: "death", death: d, t: d.t - 1, clock: d.clock,
    title: t("Died to {killer} in {where}", { killer: d.killer_hero, where: area(d.where) }),
    cost: d.win_chance_cost_pct >= 1 ? `−${Math.round(d.win_chance_cost_pct)}%` : "",
    detail: deathDetail(an, d),
  });
  if (an.report?.your_mistakes?.length) {
    const nearestDeath = (t) => myDeaths.reduce((best, d) =>
      Math.abs(d.t - t) <= 25 && (!best || Math.abs(d.t - t) < Math.abs(best.t - t)) ? d : best, null);
    return an.report.your_mistakes.map((m, i) => {
      const at = parseClock(m.clock);
      const death = at != null ? nearestDeath(at) : null;
      return {
        id: `r${i}`, kind: death ? "death" : "report", t: death ? death.t - 1 : at, clock: m.clock, title: m.title, death,
        cost: death?.win_chance_cost_pct >= 1 ? `−${Math.round(death.win_chance_cost_pct)}%` : "",
        detail: `<p>${esc(m.what_happened)}</p><p><b>${t("Why it mattered:")}</b> ${esc(m.why_it_mattered)}</p>
                 <p><b>${t("Next time:")}</b> ${esc(m.do_instead)}</p>`,
      };
    }).sort((a, b) => (a.t ?? 1e9) - (b.t ?? 1e9));
  }
  const decisions = (an.decisions?.missed || []).map((d, i) => {
    const wc = d.evidence?.win_chance;
    return {
      id: `c${i}`, kind: d.kind, t: d.t, clock: d.clock, title: loc(d, "title"), x: d.x, y: d.y,
      cost: wc && wc[0] - wc[1] >= 2 ? `−${wc[0] - wc[1]}%` : "", soft: !(wc && wc[0] - wc[1] >= 2),
      detail: `${loc(d, "what_happened").map((p) => `<p>${esc(p)}</p>`).join("")}<p><b>${t("Next time:")}</b> ${esc(loc(d, "do_instead"))}</p>`,
    };
  });
  return [...myDeaths.map(deathMoment), ...decisions].sort((a, b) => a.t - b.t);
}

function deathDetail(an, d) {
  const bits = [];
  if (d.tags?.length) bits.push(`<span class="tags">${d.tags.map((x) => `<span class="tag">${esc(tag(x))}</span>`).join("")}</span>`);
  const near = [];
  near.push(d.allies_nearby.length ? t("Allies nearby: {list}.", { list: d.allies_nearby.map(esc).join(", ") }) : t("No allies nearby."));
  if (d.enemies_nearby.length) near.push(t("Enemies on you: {list}.", { list: d.enemies_nearby.map(esc).join(", ") }));
  bits.push(`<p>${near.join(" ")}</p>`);
  if (d.enemies_missing_8s_before?.length) {
    bits.push(`<p>${t("Missing from your team's map just before: {list}.", { list: d.enemies_missing_8s_before
      .map((e) => `${esc(e.hero)} (${e.missing_s}s)`).join(", ") })}</p>`);
  }
  const wards = [];
  wards.push(d.own_observer_wards_covering ? t("{n} of your wards covered the spot", { n: d.own_observer_wards_covering }) : t("No ward of yours covered the spot"));
  if (d.enemy_observer_wards_covering) wards.push(t("{n} enemy ward saw you", { n: d.enemy_observer_wards_covering }));
  bits.push(`<p>${wards.join("; ")}. ${t("HP 10s before: {p}%.", { p: d.hp_10s_before_pct })}</p>`);
  if (d.risk) bits.push(`<p>${t("Death risk peaked at <b>{p}%</b> in the 30s before", { p: Math.round(d.risk.max_30s_before * 100) })}${
    d.risk.seconds_in_danger_before_death >= 3 ? t(", and you stayed in danger for {s}s", { s: d.risk.seconds_in_danger_before_death }) : ""}.</p>`);
  if (d.immortal_would_be?.length) {
    const top = d.immortal_would_be[0];
    bits.push(`<p>${t("From where you were 30s earlier, high-Immortal players most often went to <b>{where}</b> ({p}%); they ended up where you died {q}% of the time.",
      { where: esc(area(top.where)), p: Math.round(top.probability * 100), q: Math.round((d.immortal_probability_of_your_area ?? 0) * 100) })}</p>`);
  }
  return bits.join("");
}

function verdictHtml(an, moments) {
  const me = myPlayer(an);
  if (an.report) return `<h2>${esc(an.report.headline)}</h2><p>${esc(an.report.summary)}</p>${getLang() === "vi" ? `<p class="note">${t("The written review is in English.")}</p>` : ""}`;
  const sev = new Map((an.findings || []).map((f) => [`${f.kind}:${Math.round(f.t ?? -1)}`, f.severity]));
  const keyOf = (m) => m.kind === "death" ? `death:${Math.round(m.death.t)}` : `${m.kind}:${Math.round(m.t)}`;
  const worst = moments.slice().sort((a, b) => (sev.get(keyOf(b)) ?? 0) - (sev.get(keyOf(a)) ?? 0))[0];
  const result = an.won ? t("Won") : t("Lost");
  const head = worst
    ? t("{result} in {dur}. The moment to fix first: {clock}, {title}.", { result, dur: an.duration, clock: worst.clock,
        title: `${worst.title.charAt(0).toLowerCase()}${worst.title.slice(1)}` })
    : t("{result} in {dur} as {hero}.", { result, dur: an.duration, hero: me ? me.hero : "?" });
  const ready = state.status?.coach_ready;
  const note = ready
    ? t("The written review isn't here yet. Press <b>Re-run review</b> to write it.")
    : t("Written coaching is off. Set the <code>ANTHROPIC_API_KEY</code> environment variable and restart the dashboard to get a full review in plain words; the findings below work without it.");
  return `<h2>${esc(head)}</h2><p class="note">${note}</p>`;
}

const SPEEDS = [0.5, 1, 2, 4, 8];
const speedLabel = (v) => `${String(v).replace(".", ",")}x`;

function setSpeedControls() {
  const i = SPEEDS.indexOf(state.play.speed);
  const out = $("#speedVal");
  if (!out) return;
  out.textContent = speedLabel(state.play.speed);
  $("#speedDown").disabled = i <= 0;
  $("#speedUp").disabled = i >= SPEEDS.length - 1;
}

function stored(key, fallback) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
}
function store(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) { /* storage blocked */ } }

function renderMatch() {
  const an = state.match;
  const me = myPlayer(an);
  if (!me) {
    main.innerHTML = `<section class="state"><h1>${t("You're not in this game")}</h1><p>${t("Check which Steam account is connected in <a href=\"#/settings\">Settings</a>.")}</p></section>`;
    return;
  }
  const moments = buildMoments(an);
  state.moments = moments;
  const models = an.models_used || {};
  const sides = me.team === 0 ? "Radiant" : "Dire";
  const R = state.replay;
  const myIcon = R.heroes.find((h) => h.pid === an.me)?.icon;
  const tMin = R.t0, tMax = an.duration_s;
  if (!["immortal", "lane", "practice"].includes(state.tab)) state.tab = "immortal";
  const speed = SPEEDS.includes(stored("mmrslave-speed", 1)) ? stored("mmrslave-speed", 1) : 1;
  state.play.speed = speed;
  state.autoPause = stored("mmrslave-autopause", true) !== false;

  main.innerHTML = `
    <header class="match-head">
      <div class="mh-title">
        ${myIcon ? `<img class="mh-icon" src="${myIcon}" alt="" width="52" height="52">` : ""}
        <h1>${esc(me.hero)}</h1>
      </div>
      <dl class="mh-facts">
        <div class="mh-result ${an.won ? "won" : "lost"}"><dt>${t("Result")}</dt><dd>${an.won ? t("Won") : t("Lost")}</dd></div>
        <div><dt>${t("Position")}</dt><dd>${esc(me.position)}</dd></div>
        <div><dt>K/D/A</dt><dd>${me.kills}/${me.deaths}/${me.assists}</dd></div>
        <div><dt>${t("Duration")}</dt><dd>${esc(an.duration)}</dd></div>
        <div><dt>${t("Side")}</dt><dd>${sides}</dd></div>
        <div><dt>${t("Match")}</dt><dd>${an.match_id}</dd></div>
      </dl>
      <button class="btn btn-quiet" type="button" id="rerun">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/></svg>
        <span>${t("Re-run review")}</span></button>
    </header>
    <p class="job-line" id="rerunStatus" role="status" aria-live="polite"></p>
    <section class="verdict" aria-label="Coach's verdict">${verdictHtml(an, moments)}</section>

    <section class="stage" aria-labelledby="boardTitle">
      <div class="board-cap">
        <h2 class="section-title" id="boardTitle">${t("The board")}</h2>
        <p class="board-what" id="boardWhat"></p>
      </div>
      <div class="board-row">
        <aside class="team-gold radiant" id="gold0" aria-label="${t("Radiant gold")}"></aside>
        <div class="board-box">
          <svg class="board" id="board" viewBox="0 0 1000 1000" role="group" aria-label="${t("The map at the current moment of the game. Hover or focus a hero for details.")}"></svg>
          <div class="hero-card" id="heroCard" hidden aria-live="off"></div>
        </div>
        <aside class="team-gold dire" id="gold1" aria-label="${t("Dire gold")}"></aside>
      </div>
      <div class="player" role="group" aria-label="${t("Playback")}">
        <div class="timeline">
          <div class="scrub-marks" id="scrubMarks" aria-hidden="true"></div>
          <input type="range" class="scrub" id="scrub" min="${tMin}" max="${tMax}" step="1" aria-label="${t("Game time")}">
        </div>
        <div class="controls">
          <div class="ctl-group">
            <button class="ctl-btn" type="button" id="back10" aria-label="${t("Back 10 seconds")}">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11.5 6v12L3 12zM21 6v12l-8.5-6z"/></svg><span>10s</span></button>
            <button class="btn btn-brand play-btn" type="button" id="playBtn" aria-label="${t("Play")}">
              <svg class="i-play" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l12.5-7.5z"/></svg>
              <svg class="i-pause" viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 4.5v15M16.5 4.5v15"/></svg>
            </button>
            <button class="ctl-btn" type="button" id="fwd10" aria-label="${t("Forward 10 seconds")}">
              <span>10s</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6v12l8.5-6zM12.5 6v12L21 12z"/></svg></button>
            <span class="time-now num" id="timeNow"></span>
          </div>
          <div class="ctl-group">
            <div class="speed-ctl" role="group" aria-label="${t("Speed")}">
              <span class="speed-label">${t("Speed")}</span>
              <button class="ctl-btn step" type="button" id="speedDown" aria-label="${t("Slower")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"/></svg></button>
              <output class="speed-val num" id="speedVal" aria-live="polite">${speedLabel(speed)}</output>
              <button class="ctl-btn step" type="button" id="speedUp" aria-label="${t("Faster")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12M12 6v12"/></svg></button>
            </div>
            <label class="toggle"><input type="checkbox" id="autoPause" ${state.autoPause ? "checked" : ""}>
              <span>${t("Pause at coach moments")}</span></label>
          </div>
        </div>
      </div>
      <div class="callout" id="callout" hidden></div>
      ${an.has_visibility === false ? `<p class="lead">${t("This replay is from before fog-of-war was recorded, so the board shows every hero.")}</p>` : ""}
    </section>

    <div class="work">
      <section class="chart-wrap" aria-labelledby="wpTitle">
        <div class="chart-head">
          <h2 class="section-title" id="wpTitle">${t("Your team's win chance")}</h2>
          <span class="chart-now" id="chartNow"></span>
        </div>
        <div id="chartHost"></div>
      </section>
      <section class="moments" aria-labelledby="momTitle">
        <h2 class="section-title" id="momTitle">${an.won ? t("What you could have done better") : t("What you could have done differently")}</h2>
        ${moments.length ? moments.map((m) => `
          <button class="moment" type="button" aria-pressed="false" data-id="${m.id}">
            <span class="clock">${esc(m.clock)}</span>
            <span class="m-title">${esc(m.title)}${kindTag(m)}</span>
            <span class="m-cost ${m.soft ? "soft" : ""}">${esc(m.cost)}</span>
            <span class="m-detail">${m.detail}</span>
          </button>`).join("") : `<p class="lead">${t("Nothing stood out in this game.")}</p>`}
      </section>
    </div>

    <div class="tabs" role="tablist" aria-label="${t("More about this game")}">
      ${[["immortal", t("vs Immortal")], ["lane", t("Laning & items")], ["practice", t("Practice plan")]]
        .map(([id, label]) => `<button class="tab" role="tab" type="button" id="tab-${id}" aria-controls="panel-${id}"
          aria-selected="${state.tab === id}" tabindex="${state.tab === id ? 0 : -1}">${label}</button>`).join("")}
    </div>
    ${["immortal", "lane", "practice"].map((id) => `
      <section class="tab-panel" role="tabpanel" id="panel-${id}" aria-labelledby="tab-${id}" ${state.tab === id ? "" : "hidden"}></section>`).join("")}
    ${!models.win_probability ? `<p class="lead">${t("The win-chance model isn't trained yet: run <code>python -m mmrslave train</code>.")}</p>` : ""}
  `;

  renderChart(an);
  setupBoard(an);
  drawScrubMarks(an, moments, tMin, tMax);
  fillTabs(an);
  wireMatch(an);

  const active = state.activeMoment && moments.find((m) => m.id === state.activeMoment);
  if (active) selectMoment(active.id, false);
  else seek(state.selectedT ?? Math.min(0, tMax));
}

function drawScrubMarks(an, moments, tMin, tMax) {
  const host = $("#scrubMarks");
  host.innerHTML = moments.filter((m) => m.t != null).map((m) =>
    `<span class="mark ${m.kind === "death" ? "death" : ""}" style="left:${((m.t - tMin) / (tMax - tMin)) * 100}%"></span>`).join("");
}

function wireMatch(an) {
  main.querySelectorAll(".moment").forEach((b) => b.addEventListener("click", () => {
    const already = b.getAttribute("aria-pressed") === "true";
    if (already) { clearMoment(); return; }
    selectMoment(b.dataset.id, true);
  }));
  const scrub = $("#scrub");
  scrub.addEventListener("input", () => { pause(); clearMoment(); seek(Number(scrub.value)); });
  $("#back10").addEventListener("click", () => { clearMoment(); seek(state.selectedT - 10); });
  $("#fwd10").addEventListener("click", () => { clearMoment(); seek(state.selectedT + 10); });
  $("#playBtn").addEventListener("click", () => (state.play.playing ? pause() : play()));
  const step = (d) => {
    const i = Math.max(0, Math.min(SPEEDS.length - 1, SPEEDS.indexOf(state.play.speed) + d));
    state.play.speed = SPEEDS[i];
    store("mmrslave-speed", state.play.speed);
    setSpeedControls();
  };
  $("#speedDown").addEventListener("click", () => step(-1));
  $("#speedUp").addEventListener("click", () => step(1));
  setSpeedControls();
  $("#autoPause").addEventListener("change", (e) => { state.autoPause = e.target.checked; store("mmrslave-autopause", state.autoPause); });

  const tabs = [...main.querySelectorAll(".tab")];
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => showTab(tab.id.replace("tab-", "")));
    tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      showTab(next.id.replace("tab-", ""));
    });
  });

  $("#rerun").addEventListener("click", async () => {
    const btn = $("#rerun");
    const line = $("#rerunStatus");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    line.classList.remove("err");
    line.textContent = t("Reviewing the game again…");
    try {
      await api(`/api/match/${an.match_id}/analyze`, { method: "POST" });
      const job = await pollJob(`analyze:${an.match_id}`, (msg) => { line.textContent = msg; });
      if (job.state === "error") throw new Error((job.log.at(-1) || "").replace(/^error:\s*/, ""));
      state.match = null;
      await refreshRail();
      await showMatch(an.match_id);
    } catch (e) {
      line.classList.add("err");
      line.textContent = t("Couldn't re-run the review: {e}", { e: e.message });
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
  });
}

// Space plays and pauses, the arrow keys jump 10 s, wherever the focus isn't a control that
// needs those keys itself.
function setupKeys() {
  document.addEventListener("keydown", (e) => {
    if (!state.match || !$("#board") || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target.closest("input, select, textarea, [role=tab]")) return;
    if (e.key === " " && !e.target.closest("button")) { e.preventDefault(); state.play.playing ? pause() : play(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); clearMoment(); seek(state.selectedT - 10); }
    else if (e.key === "ArrowRight") { e.preventDefault(); clearMoment(); seek(state.selectedT + 10); }
  });
}

function showTab(id) {
  state.tab = id;
  main.querySelectorAll(".tab").forEach((t) => {
    const on = t.id === `tab-${id}`;
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1;
  });
  main.querySelectorAll(".tab-panel").forEach((p) => { p.hidden = p.id !== `panel-${id}`; });
  if (id === "immortal") loadCurves(state.match);
}

// ------------------------------------------------------------------ playback

function play() {
  if (!state.replay || !$("#board")) return;
  if (state.selectedT >= state.match.duration_s - 1) seek(state.replay.t0);
  state.play.playing = true;
  state.play.last = performance.now();
  setPlayButton();
  requestAnimationFrame(tick);
}

function pause() {
  state.play.playing = false;
  setPlayButton();
}

function setPlayButton() {
  const b = $("#playBtn");
  if (!b) return;
  b.classList.toggle("playing", state.play.playing);
  b.setAttribute("aria-label", state.play.playing ? t("Pause") : t("Play"));
}

function tick(now) {
  if (!state.play.playing || !$("#board")) return;
  const dt = Math.min(0.25, (now - state.play.last) / 1000);   // a background tab doesn't leap ahead
  state.play.last = now;
  const from = state.selectedT;
  let to = from + dt * state.play.speed;
  if (state.autoPause) {
    const m = state.moments.find((x) => x.t != null && x.t > from && x.t <= to && x.id !== state.activeMoment);
    if (m) { selectMoment(m.id, false); return; }
  }
  const end = state.match.duration_s;
  if (to >= end) { to = end; pause(); }
  // Leave a moment's note up for a few seconds of play, then clear it.
  const act = state.activeMoment && state.moments.find((x) => x.id === state.activeMoment);
  if (act && to > act.t + 6) clearMoment(false);
  seek(to);
  if (state.play.playing) requestAnimationFrame(tick);
}

function seek(t) {
  const an = state.match, R = state.replay;
  t = Math.max(R.t0, Math.min(an.duration_s, t));
  state.selectedT = t;
  const scrub = $("#scrub");
  if (scrub) {
    scrub.value = Math.round(t);
    scrub.style.setProperty("--p", `${((t - R.t0) / Math.max(1, an.duration_s - R.t0)) * 100}%`);
  }
  $("#timeNow").textContent = `${clock(t)} / ${an.duration}`;
  updateChartNow();
  drawFrame(t);
}

function selectMoment(id, user) {
  const m = state.moments.find((x) => x.id === id);
  if (!m) return;
  pause();
  state.activeMoment = id;
  main.querySelectorAll(".moment").forEach((b) => b.setAttribute("aria-pressed", b.dataset.id === id));
  const callout = $("#callout");
  callout.hidden = false;
  callout.innerHTML = `
    <div class="callout-head"><span class="clock">${esc(m.clock)}</span>
      <h3>${esc(m.title)}${kindTag(m)}</h3>
      ${m.cost ? `<span class="m-cost ${m.soft ? "soft" : ""}">${esc(m.cost)}</span>` : ""}</div>
    <div class="callout-body">${m.detail}</div>
    <div class="callout-actions"><button class="btn" type="button" id="calloutPlay">${t("Keep playing")}</button>
      <button class="btn btn-quiet" type="button" id="calloutClose">${t("Close")}</button></div>`;
  $("#calloutPlay").addEventListener("click", () => play());
  $("#calloutClose").addEventListener("click", () => clearMoment());
  if (m.t != null) seek(m.t);
  if (user) {
    const board = $("#board").getBoundingClientRect();
    if (board.top < 0 || board.bottom > window.innerHeight) {
      $(".stage").scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
    }
  }
}

function clearMoment(redraw = true) {
  if (!state.activeMoment) return;
  state.activeMoment = null;
  main.querySelectorAll(".moment").forEach((b) => b.setAttribute("aria-pressed", "false"));
  const c = $("#callout");
  if (c) { c.hidden = true; c.innerHTML = ""; }
  if (redraw && state.selectedT != null) drawFrame(state.selectedT);
}

// ------------------------------------------------------------------ win-chance chart

const CH = { w: 1000, h: 200, tickH: 22 };

function renderChart(an) {
  const host = $("#chartHost");
  const wc = an.win_chance;
  if (!wc) {
    host.innerHTML = `<p class="chart-empty">Win chance appears here once the model is trained
      (<code>python -m mmrslave train</code>). The board and the list below still work.</p>`;
    state.chart = null;
    return;
  }
  const t0 = wc.t[0], t1 = an.duration_s;
  const x = (t) => ((t - t0) / (t1 - t0)) * CH.w;
  const plotH = CH.h - CH.tickH;
  const y = (p) => (1 - p) * plotH;
  // Light smoothing (about 15 s) so the line shows the game's flow, not frame-to-frame model noise.
  const raw = wc.your_team;
  const smooth = raw.map((_, i) => {
    let sum = 0, n = 0;
    for (let k = Math.max(0, i - 2); k <= Math.min(raw.length - 1, i + 2); k++) { sum += raw[k]; n++; }
    return sum / n;
  });
  const pts = wc.t.map((t, i) => `${x(t).toFixed(1)},${y(smooth[i]).toFixed(1)}`).join(" ");
  // Past the point most training games had ended, draw the line dashed: it's a rough guess there.
  const cut = wc.reliable_until_s != null ? wc.t.findIndex((t) => t > wc.reliable_until_s) : -1;
  const solidPts = cut > 0 ? wc.t.slice(0, cut + 1).map((t, i) => `${x(t).toFixed(1)},${y(smooth[i]).toFixed(1)}`).join(" ") : pts;
  const roughPts = cut > 0 ? wc.t.slice(cut).map((t, i) => `${x(t).toFixed(1)},${y(smooth[cut + i]).toFixed(1)}`).join(" ") : null;
  const area = `M${x(wc.t[0])},${y(0.5)} L${pts.replace(/ /g, " L")} L${x(wc.t.at(-1))},${y(0.5)} Z`;

  const s = svg("svg", { class: "chart", viewBox: `0 0 ${CH.w} ${CH.h}`, preserveAspectRatio: "none", role: "img",
    "aria-label": t("Your team's win chance over the game; {r} at {d}", { r: an.won ? t("Won") : t("Lost"), d: an.duration }) });
  const defs = svg("defs", {}, s);
  const ca = svg("clipPath", { id: "clipAbove" }, defs); svg("rect", { x: 0, y: 0, width: CH.w, height: y(0.5) }, ca);
  const cb = svg("clipPath", { id: "clipBelow" }, defs); svg("rect", { x: 0, y: y(0.5), width: CH.w, height: plotH - y(0.5) }, cb);
  svg("path", { d: area, class: "above", "clip-path": "url(#clipAbove)" }, s);
  svg("path", { d: area, class: "below", "clip-path": "url(#clipBelow)" }, s);
  svg("line", { x1: 0, x2: CH.w, y1: y(0.5), y2: y(0.5), class: "mid" }, s);
  svg("polyline", { points: solidPts, class: "wp-line" }, s);
  if (roughPts) svg("polyline", { points: roughPts, class: "wp-line rough" }, s);
  for (const d of an.deaths) {
    if (d.t < t0) continue;
    const mine = teamOf(d.victim) === an.my_team;
    const cls = d.victim === an.me ? "me" : mine ? "ally" : "enemy";
    const top = cls === "enemy" ? CH.h - 10 : CH.h - CH.tickH + 3;
    svg("line", { x1: x(d.t), x2: x(d.t), y1: top, y2: CH.h, class: `tick ${cls}` }, s);
  }
  const hover = svg("line", { y1: 0, y2: plotH, class: "hover", visibility: "hidden" }, s);
  svg("line", { y1: 0, y2: CH.h, class: "cursor", id: "chartCursor", visibility: "hidden" }, s);

  host.replaceChildren(s);
  host.insertAdjacentHTML("beforeend", `
    <div class="chart-axis num"><span>${clock(t0)}</span><span>${clock((t0 + t1) / 2)}</span><span>${clock(t1)}</span></div>
    <div class="chart-legend">
      <span><svg width="14" height="12"><line x1="7" x2="7" y1="0" y2="12" stroke="var(--red)" stroke-width="3"/></svg>${t("your deaths")}</span>
      <span><svg width="14" height="12"><line x1="7" x2="7" y1="0" y2="12" stroke="var(--red)" stroke-width="2" stroke-dasharray="3 2"/></svg>${t("teammates' deaths")}</span>
      <span><svg width="14" height="12"><line x1="7" x2="7" y1="4" y2="12" stroke="var(--green)" stroke-width="1"/></svg>${t("enemy deaths")}</span>
      ${roughPts ? `<span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" stroke="var(--chalk)" stroke-width="2" stroke-dasharray="3 3"/></svg>${t("after {clock}: rough, few Immortal games last this long", { clock: clock(wc.reliable_until_s) })}</span>` : ""}
      <span>${t("Click anywhere to jump the board there.")}</span>
    </div>`);

  const toT = (ev) => {
    const r = s.getBoundingClientRect();
    return t0 + Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * (t1 - t0);
  };
  const valueAt = (t) => {
    let i = 0;
    while (i < wc.t.length - 1 && wc.t[i + 1] <= t) i++;
    return wc.your_team[i];   // the same numbers the moments list quotes; only the drawn line is smoothed
  };
  s.addEventListener("pointermove", (ev) => {
    const t = toT(ev);
    hover.setAttribute("x1", x(t)); hover.setAttribute("x2", x(t)); hover.setAttribute("visibility", "visible");
    $("#chartNow").innerHTML = `<b>${clock(t)}</b> · ${Math.round(valueAt(t) * 100)}%`;
  });
  s.addEventListener("pointerleave", () => { hover.setAttribute("visibility", "hidden"); updateChartNow(); });
  s.addEventListener("click", (ev) => { pause(); clearMoment(); seek(toT(ev)); });
  state.chart = { x, valueAt, t0, t1 };
}

function updateChartNow() {
  const c = state.chart;
  const el = $("#chartNow");
  if (!c || !el || state.selectedT == null) return;
  const t = Math.max(c.t0, state.selectedT);
  el.innerHTML = `<b>${clock(state.selectedT)}</b> · ${Math.round(c.valueAt(t) * 100)}%`;
  const cur = $("#chartCursor");
  cur.setAttribute("x1", c.x(t)); cur.setAttribute("x2", c.x(t));
  cur.setAttribute("visibility", "visible");
}

// ------------------------------------------------------------------ the board

// The board is 1000 units square. Its frame is the game's own minimap when the server could
// copy it from the Dota 2 install, otherwise the area the models' grid covers.
function boardXY(x, y) {
  const f = state.geometry.frame;
  return [((x - f.x0) / f.size) * 1000, 1000 - ((y - f.y0) / f.size) * 1000];
}

function setupBoard(an) {
  const b = $("#board");
  b.replaceChildren();
  const g = state.geometry;
  if (!g) return;
  b.classList.toggle("has-map", !!g.minimap);
  const defs = svg("defs", {}, b);
  const clip = svg("clipPath", { id: "iconClip", clipPathUnits: "objectBoundingBox" }, defs);
  svg("rect", { width: 1, height: 1, rx: 0.16 }, clip);
  svg("feColorMatrix", { type: "saturate", values: "0" }, svg("filter", { id: "grey" }, defs));
  // A soft dark edge so chalk lines stay readable over the busy map art.
  const halo = svg("filter", { id: "halo", filterUnits: "userSpaceOnUse", x: 0, y: 0, width: 1000, height: 1000 }, defs);
  svg("feDropShadow", { dx: 0, dy: 0, stdDeviation: 3, "flood-color": "#000", "flood-opacity": 0.85 }, halo);

  const base = svg("g", { "aria-hidden": "true" }, b);
  if (g.minimap) {
    svg("image", { href: g.minimap.url, x: 0, y: 0, width: 1000, height: 1000, preserveAspectRatio: "none" }, base);
  } else {
    const step = 1000 / g.grid;
    for (let i = 1; i < g.grid; i++) {
      svg("line", { x1: i * step, x2: i * step, y1: 0, y2: 1000, class: "gridline" }, base);
      svg("line", { y1: i * step, y2: i * step, x1: 0, x2: 1000, class: "gridline" }, base);
    }
    for (const box of Object.values(g.bases)) {
      const [a, c] = box.map(([x, y]) => boardXY(x, y));
      svg("rect", { x: Math.min(a[0], c[0]), y: Math.min(a[1], c[1]), width: Math.abs(c[0] - a[0]), height: Math.abs(c[1] - a[1]), rx: 30, class: "base" }, base);
    }
    if (g.river?.length) svg("polygon", { points: g.river.map(([x, y]) => boardXY(x, y).join(",")).join(" "), class: "river" }, base);
    for (const line of Object.values(g.lanes)) svg("polyline", { points: line.map(([x, y]) => boardXY(x, y).join(",")).join(" "), class: "lane" }, base);
    for (const f of Object.values(g.fountains || {})) {
      const [fx, fy] = boardXY(f.x, f.y);
      svg("circle", { cx: fx, cy: fy, r: 16, class: "fountain" }, base);
    }
  }
  // Layers, bottom to top. Heroes keep their elements between frames so playback stays smooth.
  const layers = {
    wards: svg("g", { "aria-hidden": "true" }, b),
    overlay: svg("g", { "aria-hidden": "true" }, b),
    trail: svg("path", { class: "trail", d: "" }, b),
    leaders: svg("g", { "aria-hidden": "true" }, b),
    heroes: svg("g", {}, b),
    top: svg("g", { "aria-hidden": "true" }, b),
  };
  const heroes = state.replay.heroes.map((h) => makeHero(h, an, layers.heroes));
  state.board = { layers, heroes, wardKey: null, overlayKey: null, order: "", gold: setupGold(an), card: null };
}

// Each team's gold beside the map, on its own side: Radiant (bottom-left base) on the left,
// Dire (top-right base) on the right. Built once; drawFrame only changes the numbers.
function setupGold(an) {
  const panels = [];
  for (const team of [0, 1]) {
    const el = $(`#gold${team}`);
    if (!el) continue;
    const yours = team === an.my_team;
    const rows = state.replay.heroes.filter((h) => h.team === team);
    el.innerHTML = `
      <p class="tg-name"><span class="tg-swatch ${yours ? "ally" : "enemy"}" aria-hidden="true"></span>${team === 0 ? "Radiant" : "Dire"} · ${yours ? t("your team") : t("enemy")}</p>
      <p class="tg-total"><svg class="coin" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/></svg><b class="num" data-k="total"></b></p>
      <p class="tg-sub">${t("unspent gold")}</p>
      <ul class="tg-list">${rows.map((h) => `
        <li class="${h.pid === an.me ? "you" : ""}" data-pid="${h.pid}">
          ${h.icon ? `<img src="${h.icon}" alt="" width="22" height="22">` : `<span class="tg-noicon" aria-hidden="true"></span>`}
          <span class="tg-hero">${esc(h.hero)}${h.pid === an.me ? ` ${t("(you)")}` : ""}</span>
          <b class="num" data-k="g${h.pid}"></b>
        </li>`).join("")}
      </ul>
      <p class="tg-sub">${t("net worth")} <b class="num" data-k="nw"></b></p>`;
    const cells = {};
    el.querySelectorAll("[data-k]").forEach((c) => { cells[c.dataset.k] = c; });
    panels.push({ team, pids: rows.map((h) => h.pid), cells });
  }
  return panels;
}

const fmtGold = (v) => Math.round(v).toLocaleString("en-US");
const fmtK = (v) => (v >= 10000 ? `${(v / 1000).toFixed(1)}k` : fmtGold(v));

function drawGold(t) {
  const R = state.replay;
  const i = Math.max(0, Math.min(R.n - 1, Math.floor(t - R.t0)));
  const put = (cell, text) => { if (cell && cell.textContent !== text) cell.textContent = text; };
  for (const p of state.board.gold) {
    let total = 0, nw = 0;
    for (const pid of p.pids) {
      const g = R.gold[pid][i];
      total += g; nw += R.nw[pid][i];
      put(p.cells[`g${pid}`], fmtGold(g));
    }
    put(p.cells.total, fmtGold(total));
    put(p.cells.nw, fmtK(nw));
  }
}

// Hero position at a (fractional) game second, smoothly between the once-a-second samples
// unless the hero died, respawned or teleported in between.
function sampleHero(pid, t) {
  const R = state.replay;
  const f = Math.max(0, Math.min(R.n - 1, t - R.t0));
  const i = Math.floor(f), j = Math.min(i + 1, R.n - 1), a = f - i;
  const xs = R.x[pid], ys = R.y[pid], hp = R.hp[pid];
  let x = xs[i], y = ys[i];
  if (a > 0 && hp[i] > 0 && hp[j] > 0 && Math.hypot(xs[j] - x, ys[j] - y) < 1200) {
    x += (xs[j] - x) * a;
    y += (ys[j] - y) * a;
  }
  return { x, y, i, hp: hp[i], mp: R.mp[pid][i], gold: R.gold[pid][i], alive: hp[i] > 0, vis: R.vis[pid][i] };
}

function drawFrame(t) {
  const B = state.board, an = state.match, R = state.replay;
  if (!B || !$("#board")) return;
  const myTeam = an.my_team;
  const L = B.layers;

  // Wards: redrawn only when the set on the map changes.
  const active = [];
  R.wards.forEach((w, i) => { if (w.t <= t && t < w.end) active.push(i); });
  const wardKey = active.join(",");
  if (wardKey !== B.wardKey) {
    B.wardKey = wardKey;
    L.wards.replaceChildren();
    for (const i of active) {
      const w = R.wards[i];
      const [wx, wy] = boardXY(w.x, w.y);
      const colour = w.team === myTeam ? "var(--ally)" : "var(--enemy)";
      if (w.type === "observer") {
        svg("circle", { cx: wx, cy: wy, r: (1600 / state.geometry.frame.size) * 1000, class: "ward-ring", stroke: colour }, L.wards);
        svg("circle", { cx: wx, cy: wy, r: 8, fill: colour, class: "ward" }, L.wards);
      } else {
        svg("rect", { x: wx - 7, y: wy - 7, width: 14, height: 14, fill: "none", stroke: colour, "stroke-width": 4, class: "ward", transform: `rotate(45 ${wx} ${wy})` }, L.wards);
      }
    }
  }

  // Your last 20 seconds, drawn like chalk; a teleport or a death starts a new stroke.
  const samples = [];
  for (let s = Math.ceil(t - 20); s < t; s++) if (s >= R.t0) samples.push(sampleHero(an.me, s));
  samples.push(sampleHero(an.me, t));
  let d = "", prev = null;
  for (const p of samples) {
    if (!p.alive) { prev = null; continue; }
    const [bx, by] = boardXY(p.x, p.y);
    const jump = !prev || Math.hypot(p.x - prev.x, p.y - prev.y) > 1200;
    d += `${jump ? "M" : "L"}${bx.toFixed(1)},${by.toFixed(1)}`;
    prev = p;
  }
  L.trail.setAttribute("d", d);

  // Overlays: in the 30 s before one of your deaths, where Immortal players went from your
  // spot and where you died; at a coach moment, the place it's about.
  const death = an.deaths.find((d) => d.victim === an.me && t >= d.t - 30 && t <= d.t + 3);
  const moment = state.activeMoment && state.moments.find((m) => m.id === state.activeMoment);
  const overlayKey = `${death ? death.t : ""}|${moment && !moment.death && moment.x != null ? moment.id : ""}`;
  if (overlayKey !== B.overlayKey) {
    B.overlayKey = overlayKey;
    L.overlay.replaceChildren();
    L.top.replaceChildren();
    if (death) drawDeathOverlay(death, L);
    if (moment && !moment.death && moment.x != null) {
      const [mx, my] = boardXY(moment.x, moment.y);
      svg("circle", { cx: mx, cy: my, r: 70, class: "spot-ring" }, L.top);
    }
  }

  // Heroes: the dead, enemies, teammates, then you on top.
  const rank = (s, h) => (s.alive ? 10 : 0) + (h.pid === an.me ? 3 : h.team === myTeam ? 2 : 1);
  const tokens = B.heroes.map((hb) => {
    const s = sampleHero(hb.h.pid, t);
    const [x, y] = boardXY(s.x, s.y);
    return { hb, s, x, y, x0: x, y0: y, size: hb.h.pid === an.me ? 62 : 52, pinned: hb.h.pid === an.me, rank: rank(s, hb.h) };
  }).sort((a, b) => a.rank - b.rank);
  spreadTokens(tokens);
  L.leaders.replaceChildren();
  for (const k of tokens) {
    // A nudged icon keeps a thin line to the spot the hero really stood on.
    if (Math.hypot(k.x - k.x0, k.y - k.y0) > 10) {
      svg("line", { x1: k.x0, y1: k.y0, x2: k.x, y2: k.y, class: "hero-leader" }, L.leaders);
      svg("circle", { cx: k.x0, cy: k.y0, r: 5, class: "hero-spot" }, L.leaders);
    }
    updateHero(k, an);
    k.hb.at = [k.x, k.y];
  }
  const order = tokens.map((k) => k.hb.h.pid).join(",");
  if (order !== B.order) {
    B.order = order;
    for (const k of tokens) L.heroes.appendChild(k.hb.g);
  }

  drawGold(t);
  if (B.card != null) drawCard(t);

  $("#boardWhat").textContent = death
    ? (t < death.t ? tr("{s}s before you died at {clock} · enemies as your team saw them", { s: Math.ceil(death.t - t), clock: death.clock })
      : tr("When you died at {clock} · enemies as your team saw them", { clock: death.clock }))
    : tr("Enemies as your team saw them");
}

function drawDeathOverlay(death, L) {
  const [dx, dy] = boardXY(death.x, death.y);
  svg("circle", { cx: dx, cy: dy, r: 48, class: "death-ring" }, L.top);
  if (!death.immortal_would_be?.length) return;
  const top = death.immortal_would_be[0];
  const centre = state.geometry.area_centers[state.match.my_team]?.[top.where];
  const from = sampleHero(state.match.me, death.t - 30);
  if (!centre || !from.alive) return;
  const [sx, sy] = boardXY(from.x, from.y);
  const [ex, ey] = boardXY(centre[0], centre[1]);
  const mx = (sx + ex) / 2 + (ey - sy) * 0.18, my = (sy + ey) / 2 - (ex - sx) * 0.18;
  svg("path", { d: `M${sx},${sy} Q${mx},${my} ${ex},${ey}`, class: "imm-arrow" }, L.overlay);
  const ang = Math.atan2(ey - my, ex - mx);
  svg("path", {
    d: `M${ex},${ey} L${ex - 30 * Math.cos(ang - 0.45)},${ey - 30 * Math.sin(ang - 0.45)} L${ex - 30 * Math.cos(ang + 0.45)},${ey - 30 * Math.sin(ang + 0.45)} Z`,
    class: "imm-head" }, L.overlay);
  const anchorLeft = ex < 520;
  const label = svg("text", { x: anchorLeft ? ex + 24 : ex - 24, y: ey + (ey < 120 ? 44 : -22), class: "imm-label",
    "text-anchor": anchorLeft ? "start" : "end" }, L.top);
  label.textContent = `Immortal: ${area(top.where)} (${Math.round(top.probability * 100)}%)`;
}

// One hero: its icon on a dark tile inside a border in their side's colour (yellow you,
// green teammates, red enemies). Dashed and faded = your team couldn't see them; grey = dead.
function makeHero(h, an, parent) {
  const you = h.pid === an.me;
  const side = you ? "you" : h.team === an.my_team ? "ally" : "enemy";
  const size = you ? 62 : 52, half = size / 2;
  const g = svg("g", { class: `hero ${side}`, tabindex: 0, role: "button" }, parent);
  const title = { set textContent(v) { g.setAttribute("aria-label", v); } };
  g.addEventListener("pointerenter", (e) => { if (e.pointerType !== "touch") openCard(h.pid); });
  g.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") closeCard(h.pid); });
  g.addEventListener("click", () => (state.board?.card === h.pid ? closeCard(h.pid) : openCard(h.pid)));
  g.addEventListener("focus", () => openCard(h.pid));
  g.addEventListener("blur", () => closeCard(h.pid));
  svg("rect", { x: -half, y: -half, width: size, height: size, rx: 10, class: "hero-tile" }, g);
  let image = null;
  if (h.icon) {
    image = svg("image", { href: h.icon, x: -half + 3, y: -half + 3, width: size - 6, height: size - 6, "clip-path": "url(#iconClip)" }, g);
  } else {
    const initials = svg("text", { x: 0, y: 9, "text-anchor": "middle", class: "hero-initials" }, g);
    initials.textContent = h.hero.split(/[\s-]+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  }
  svg("rect", { x: -half, y: -half, width: size, height: size, rx: 10, class: "hero-border" }, g);
  // Health over mana, sitting on top of the portrait like in the game.
  const bars = svg("g", { class: "hero-bars", transform: `translate(${-half} ${-half - 23})` }, g);
  svg("rect", { x: -2, y: -2, width: size + 4, height: 20, rx: 3, class: "bar-back" }, bars);
  svg("rect", { x: 0, y: 0, width: size, height: 9, class: "bar-empty" }, bars);
  svg("rect", { x: 0, y: 11, width: size, height: 5, class: "bar-empty" }, bars);
  const hpBar = svg("rect", { x: 0, y: 0, width: size, height: 9, class: "bar-hp" }, bars);
  const mpBar = svg("rect", { x: 0, y: 11, width: size, height: 5, class: "bar-mp" }, bars);
  return { h, g, title, image, side, size, hpBar, mpBar, bars: "", state: "" };
}

function updateHero(k, an) {
  const { hb, s } = k;
  const ally = hb.h.team === an.my_team;
  const unseen = s.alive && !ally && s.vis === 0;
  hb.g.setAttribute("transform", `translate(${k.x.toFixed(1)} ${k.y.toFixed(1)})`);
  const bars = `${s.hp},${s.mp}`;
  if (bars !== hb.bars) {
    hb.bars = bars;
    hb.hpBar.setAttribute("width", ((hb.size * s.hp) / 100).toFixed(1));
    hb.mpBar.setAttribute("width", ((hb.size * s.mp) / 100).toFixed(1));
  }
  const st = `${s.alive ? 1 : 0}${unseen ? 1 : 0}|${s.hp}|${s.mp}|${s.gold}`;
  if (st === hb.state) return;
  const was = hb.state.slice(0, 2);
  hb.state = st;
  if (was !== st.slice(0, 2)) {
    hb.g.setAttribute("class", `hero ${hb.side}${s.alive ? "" : " dead"}${unseen ? " unseen" : ""}`);
    if (hb.image) { if (s.alive) hb.image.removeAttribute("filter"); else hb.image.setAttribute("filter", "url(#grey)"); }
  }
  hb.title.textContent = `${hb.h.hero}${hb.side === "you" ? ` ${t("(you)")}` : ""} · ${
    !s.alive ? t("dead") : `${t("{hp}% health · {mp}% mana", { hp: s.hp, mp: s.mp })}${unseen ? t(" · your team couldn't see them") : ""}`} · ${t("{g} gold", { g: fmtGold(s.gold) })}`;
}

// ------------------------------------------------------------------ hero card
// Hover (or focus, or tap) a portrait: that hero's numbers and items at the moment on the board.
// It stays open and keeps updating while the game plays.

function openCard(pid) {
  if (!state.board) return;
  state.board.card = pid;
  drawCard(currentT());
}

function closeCard(pid) {
  if (!state.board || state.board.card !== pid) return;
  state.board.card = null;
  const c = $("#heroCard");
  if (c) { c.hidden = true; c.dataset.key = ""; }
}

function currentT() {
  const v = Number($("#scrub")?.value);
  return state.selectedT ?? (Number.isFinite(v) ? v : state.replay.t0);
}

// The hero's inventory at second t: the last change at or before it.
function itemsAt(pid, t) {
  const list = state.replay.items?.[pid];
  if (!list?.length) return null;
  let lo = 0, hi = list.length - 1, at = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid][0] <= t) { at = list[mid]; lo = mid + 1; } else hi = mid - 1;
  }
  return at ? { main: at[1], neutral: at[2], backpack: at[3] } : { main: ["", "", "", "", "", ""], neutral: "", backpack: ["", "", ""] };
}

const itemLabel = (n) => n.replace(/^recipe_/, "recipe: ").replace(/_/g, " ");

function itemCell(name, cls = "") {
  if (!name) return `<span class="item empty ${cls}"></span>`;
  const url = state.replay.item_icons?.[name];
  const label = esc(itemLabel(name));
  return url
    ? `<img class="item ${cls}" src="${url}" alt="${label}" title="${label}">`
    : `<span class="item missing ${cls}" title="${label}" role="img" aria-label="${label}"></span>`;
}

function drawCard(t) {
  const B = state.board, R = state.replay, an = state.match;
  const pid = B.card, c = $("#heroCard");
  const hb = B.heroes.find((x) => x.h.pid === pid);
  if (!c || !hb) return;
  const s = sampleHero(pid, t), i = s.i;
  const inv = itemsAt(pid, Math.floor(t));
  const you = pid === an.me, ally = hb.h.team === an.my_team;
  const n = (v) => fmtGold(v);
  const key = [pid, i].join("|");
  if (c.dataset.key !== key) {
    c.dataset.key = key;
    const hp = R.hpv[pid][i], hpMax = R.hpmax[pid][i], mp = R.mpv[pid][i], mpMax = R.mpmax[pid][i];
    const items = inv == null
      ? `<p class="hc-note">${tr("Items weren't recorded for this game. <code>python -m mmrslave reparse</code> adds them while Valve still has the replay.")}</p>`
      : `<div class="hc-items">
           <div class="hc-main">${inv.main.map((x) => itemCell(x)).join("")}</div>
           ${itemCell(inv.neutral, "neutral")}
         </div>
         ${inv.backpack.some(Boolean) ? `<div class="hc-bp"><span>${tr("backpack")}</span>${inv.backpack.filter(Boolean).map((x) => itemCell(x, "small")).join("")}</div>` : ""}`;
    c.className = `hero-card ${you ? "you" : ally ? "ally" : "enemy"}`;
    c.innerHTML = `
      <div class="hc-head">
        ${hb.h.icon ? `<img src="${hb.h.icon}" alt="" width="34" height="34">` : ""}
        <div><b>${esc(hb.h.hero)}${you ? ` ${tr("(you)")}` : ""}</b><span>${ally ? tr("your team") : tr("enemy")} · ${clock(t)}${s.alive ? "" : ` · ${tr("dead")}`}</span></div>
      </div>
      <div class="hc-bars">
        <div class="hc-bar hp"><i style="width:${s.alive ? s.hp : 0}%"></i><span>${n(s.alive ? hp : 0)} / ${n(hpMax)}</span></div>
        <div class="hc-bar mp"><i style="width:${s.alive ? s.mp : 0}%"></i><span>${n(s.alive ? mp : 0)} / ${n(mpMax)}</span></div>
      </div>
      <dl class="hc-stats">
        <div><dt>Last hits / denies</dt><dd class="num">${R.lh[pid][i]} / ${R.dn[pid][i]}</dd></div>
        <div><dt>Net worth</dt><dd class="num">${n(R.nw[pid][i])}</dd></div>
        <div><dt>${tr("Unspent gold")}</dt><dd class="num">${n(R.gold[pid][i])}</dd></div>
      </dl>
      ${items}`;
  }
  placeCard(c, hb);
}

// Beside the portrait, on whichever side has room, kept inside the map.
function placeCard(c, hb) {
  c.hidden = false;
  const box = c.parentElement.getBoundingClientRect();
  const scale = box.width / 1000;
  const [x, y] = hb.at || [500, 500];
  const w = c.offsetWidth, h = c.offsetHeight, gap = 40 * scale + 10;
  let left = x * scale + gap;
  if (left + w > box.width - 6) left = x * scale - gap - w;
  left = Math.max(6, Math.min(box.width - w - 6, left));
  const top = Math.max(6, Math.min(box.height - h - 6, y * scale - h / 2));
  c.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
}

// Heroes in a fight stand on top of each other. Push overlapping icons apart (a little
// overlap is fine as long as every face shows); the pinned hero (you) stays where it stood.
function spreadTokens(tokens) {
  for (let round = 0; round < 40; round++) {
    let moved = false;
    for (let i = 0; i < tokens.length; i++) {
      for (let j = i + 1; j < tokens.length; j++) {
        const a = tokens[i], b = tokens[j];
        if (a.pinned && b.pinned) continue;
        let dx = b.x - a.x, dy = b.y - a.y;
        let d = Math.hypot(dx, dy);
        const need = ((a.size + b.size) / 2) * 0.8;
        if (d >= need) continue;
        if (d < 0.01) { dx = Math.cos(j * 2.4); dy = Math.sin(j * 2.4); d = 1; }   // same spot: fan out
        const push = need - d;
        const share = a.pinned ? 0 : b.pinned ? 1 : 0.5;
        a.x -= (dx / d) * push * share; a.y -= (dy / d) * push * share;
        b.x += (dx / d) * push * (1 - share); b.y += (dy / d) * push * (1 - share);
        moved = true;
      }
    }
    for (const t of tokens) {
      t.x = Math.min(1000 - t.size / 2, Math.max(t.size / 2, t.x));
      t.y = Math.min(1000 - t.size / 2, Math.max(t.size / 2, t.y));
    }
    if (!moved) break;
  }
}

// ------------------------------------------------------------------ tabs

function fillTabs(an) {
  $("#panel-immortal").innerHTML = `<p class="lead">${loading(t("Loading the Immortal curves…"))}</p>`;
  $("#panel-lane").innerHTML = laneHtml(an);
  $("#panel-practice").innerHTML = practiceHtml(an);
  if (state.tab === "immortal") loadCurves(an);
}

// ---- vs Immortal: your line (green) against Immortal players (yellow), one stat at a time

const CURVE_VIEWS = [
  { id: "nw", label: "Net worth", series: [{ key: "nw", name: "Net worth" }] },
  { id: "lhdn", label: "Last hits & denies", series: [{ key: "lh", name: "Last hits" }, { key: "dn", name: "Denies" }] },
  { id: "level", label: "Level", series: [{ key: "level", name: "Level" }] },
  { id: "kda", label: "K / D / A", series: [{ key: "kills", name: "Kills" }, { key: "deaths", name: "Deaths" }, { key: "assists", name: "Assists" }] },
  { id: "hero_damage", label: "Hero damage", series: [{ key: "hero_damage", name: "Hero damage" }] },
  { id: "building_damage", label: "Building damage", series: [{ key: "building_damage", name: "Building damage" }] },
];
// Shades within a side, plus a dash pattern so series never rely on colour alone.
const SHADES = { you: ["var(--you-1)", "var(--you-2)", "var(--you-3)"], imm: ["var(--imm-1)", "var(--imm-2)", "var(--imm-3)"] };
const DASH = [null, "7 5", "2 5"];

async function loadCurves(an) {
  if (state.curves?.match_id === an.match_id) { renderImmortal(an); return; }
  try {
    const c = await api(`/api/match/${an.match_id}/curves`);
    state.curves = { ...c, match_id: an.match_id };
  } catch (e) {
    $("#panel-immortal").innerHTML = `<p class="lead">${t("Couldn't load the Immortal curves: {e}", { e: esc(e.message) })}</p>`;
    return;
  }
  if (state.match?.match_id === an.match_id) renderImmortal(an);
}

function renderImmortal(an) {
  const panel = $("#panel-immortal");
  const c = state.curves;
  if (!state.curveView || !CURVE_VIEWS.some((v) => v.id === state.curveView)) state.curveView = stored("mmrslave-curve", "nw");
  if (!CURVE_VIEWS.some((v) => v.id === state.curveView)) state.curveView = "nw";
  panel.innerHTML = `
    <div class="curve-card">
      <p class="lead">${c.immortal
        ? t("You against high-Immortal players on the {cmp} ({n} games), minute by minute. The yellow band is the middle half of them; the yellow line is a typical one.",
            { cmp: esc(t(c.compared_with)), n: fmt(c.immortal_games) })
        : t("Immortal curves aren't built yet: run <code>python -m mmrslave benchmarks</code>.")}</p>
      <div class="seg" role="radiogroup" aria-label="${t("Stat to compare")}">
        ${CURVE_VIEWS.map((v) => `<button type="button" role="radio" class="seg-btn" data-view="${v.id}"
          aria-checked="${v.id === state.curveView}" tabindex="${v.id === state.curveView ? 0 : -1}">${v.label}</button>`).join("")}
      </div>
      <div class="curve-host" id="curveHost"></div>
    </div>
    <div class="general">
      <h3 class="section-title">${t("General stats")}</h3>
      ${generalStatsHtml(an)}
    </div>`;
  const btns = [...panel.querySelectorAll(".seg-btn")];
  const choose = (id, focus) => {
    state.curveView = id;
    store("mmrslave-curve", id);
    btns.forEach((b) => { const on = b.dataset.view === id; b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    drawCurves(an);
  };
  btns.forEach((b, i) => {
    b.addEventListener("click", () => choose(b.dataset.view, false));
    b.addEventListener("keydown", (e) => {
      const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      choose(btns[(i + step + btns.length) % btns.length].dataset.view, true);
    });
  });
  drawCurves(an);
  if (!state.curveResize) {
    let raf = 0;
    state.curveResize = new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { if ($("#curveHost")) drawCurves(state.match); }); });
  }
  state.curveResize.disconnect();
  state.curveResize.observe(panel);
}

function compact(v) {
  const a = Math.abs(v);
  if (a >= 10000) return `${fmt(v / 1000, a >= 100000 ? 0 : 1)}k`;
  return fmt(v, a < 10 && !Number.isInteger(v) ? 1 : 0);
}

function niceTicks(max, count = 4) {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  if (ticks.at(-1) < max) ticks.push(ticks.at(-1) + step);
  return ticks;
}

function drawCurves(an) {
  const host = $("#curveHost");
  if (!host) return;
  const c = state.curves;
  const view = CURVE_VIEWS.find((v) => v.id === state.curveView);
  const series = view.series.map((s, i) => ({
    ...s, i, you: c.you[s.key] || [], imm: c.immortal?.[s.key],
  }));
  const notes = [];
  if (series.some((s) => !s.you.length)) {
    notes.push(t("This game was saved before {stat} over time was recorded. Run <code>python -m mmrslave reparse</code> while Valve still has the replay (about 10 days).", { stat: esc(view.label.toLowerCase()) }));
  }
  const borrowed = series.filter((s) => (c.position_only || []).includes(s.key) && s.imm?.p50?.length);
  if (borrowed.length && c.compared_with === "same hero and position") {
    notes.push(t(borrowed.length > 1
      ? "Few Immortal games on this hero have {stats} over time yet, so those lines compare you with every Immortal player in your position ({n} games)."
      : "Few Immortal games on this hero have {stats} over time yet, so that line compares you with every Immortal player in your position ({n} games).",
      { stats: esc(borrowed.map((s) => s.name.toLowerCase()).join(", ")), n: fmt(borrowed[0].imm?.games ?? 0) }));
  }
  const missingImm = series.filter((s) => s.you.length && !(s.imm?.p50?.length));
  if (c.immortal && missingImm.length) {
    const games = missingImm[0].imm?.games ?? 0;
    notes.push(t("Not enough Immortal games with {stats} over time yet ({n} so far). New games are saved with it, so the yellow line appears as the collector runs and after <code>python -m mmrslave benchmarks</code>.",
      { stats: esc(missingImm.map((s) => s.name.toLowerCase()).join(", ")), n: fmt(games) }));
  }

  const W = Math.max(300, host.clientWidth || 800), H = W < 560 ? 240 : 320;
  const pad = { l: 52, r: 18, t: 14, b: 30 };
  const minutes = Math.max(1, ...series.map((s) => s.you.length - 1), ...series.map((s) => (s.imm?.p50?.length || 1) - 1));
  const shownMin = Math.min(minutes, Math.max(...series.map((s) => s.you.length - 1), 1));
  const maxV = Math.max(1, ...series.flatMap((s) => [...s.you, ...((s.imm?.p75 || []).slice(0, shownMin + 1))]));
  const ticks = niceTicks(maxV);
  const top = ticks.at(-1);
  const X = (m) => pad.l + (m / shownMin) * (W - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - v / top) * (H - pad.t - pad.b);
  const line = (vals) => vals.slice(0, shownMin + 1).map((v, m) => `${m ? "L" : "M"}${X(m).toFixed(1)},${Y(v).toFixed(1)}`).join("");

  const s = svg("svg", { class: "curves", width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": t("{label}: you against high-Immortal players, by minute", { label: view.label }) });
  for (const v of ticks) {
    svg("line", { x1: pad.l, x2: W - pad.r, y1: Y(v), y2: Y(v), class: "grid" }, s);
    svg("text", { x: pad.l - 8, y: Y(v) + 4, "text-anchor": "end", class: "axis" }, s).textContent = compact(v);
  }
  const xStep = shownMin > 40 ? 10 : 5;
  for (let m = 0; m <= shownMin; m += xStep) {
    svg("text", { x: X(m), y: H - 8, "text-anchor": "middle", class: "axis" }, s).textContent = `${m}:00`;
  }
  const single = series.length === 1;
  for (const sr of series) {
    if (single && sr.imm?.p25?.length) {
      const n = Math.min(sr.imm.p25.length, shownMin + 1);
      const upper = sr.imm.p75.slice(0, n).map((v, m) => `${X(m).toFixed(1)},${Y(v).toFixed(1)}`);
      const lower = sr.imm.p25.slice(0, n).map((v, m) => `${X(m).toFixed(1)},${Y(v).toFixed(1)}`).reverse();
      svg("polygon", { points: [...upper, ...lower].join(" "), class: "band" }, s);
    }
  }
  for (const sr of series) {
    if (sr.imm?.p50?.length) svg("path", { d: line(sr.imm.p50), class: "cline", stroke: SHADES.imm[sr.i], "stroke-dasharray": DASH[sr.i] }, s);
  }
  for (const sr of series) {
    if (sr.you.length) svg("path", { d: line(sr.you), class: "cline you", stroke: SHADES.you[sr.i], "stroke-dasharray": DASH[sr.i] }, s);
  }
  // End dots and labels for the single-stat views; the legend carries the rest.
  if (single) {
    const sr = series[0];
    const ends = [];
    if (sr.you.length) ends.push({ m: Math.min(sr.you.length - 1, shownMin), v: sr.you[Math.min(sr.you.length - 1, shownMin)], fill: SHADES.you[0], text: t("You") });
    if (sr.imm?.p50?.length) { const m = Math.min(sr.imm.p50.length - 1, shownMin); ends.push({ m, v: sr.imm.p50[m], fill: SHADES.imm[0], text: "Immortal" }); }
    for (const e of ends) svg("circle", { cx: X(e.m), cy: Y(e.v), r: 4.5, fill: e.fill, class: "end-dot" }, s);
    if (ends.length === 2 && Math.abs(Y(ends[0].v) - Y(ends[1].v)) < 16 && Math.abs(X(ends[0].m) - X(ends[1].m)) < 60) ends.pop();
    for (const e of ends) {
      const right = X(e.m) > W - 90;
      svg("text", { x: X(e.m) + (right ? -9 : 9), y: Y(e.v) - 9, "text-anchor": right ? "end" : "start", class: "end-label" }, s).textContent = e.text;
    }
  }
  const cross = svg("line", { y1: pad.t, y2: H - pad.b, class: "crosshair", visibility: "hidden" }, s);
  const dots = svg("g", {}, s);

  const legend = `<div class="curve-legend">${series.map((sr) => `
      <span><svg width="26" height="10" aria-hidden="true"><line x1="1" x2="25" y1="5" y2="5" stroke="${SHADES.you[sr.i]}" stroke-width="2.5" ${DASH[sr.i] ? `stroke-dasharray="${DASH[sr.i]}"` : ""}/></svg>${t("You")} · ${esc(sr.name)}</span>
      ${sr.imm?.p50?.length ? `<span><svg width="26" height="10" aria-hidden="true"><line x1="1" x2="25" y1="5" y2="5" stroke="${SHADES.imm[sr.i]}" stroke-width="2.5" ${DASH[sr.i] ? `stroke-dasharray="${DASH[sr.i]}"` : ""}/></svg>Immortal · ${esc(sr.name)}</span>` : ""}`).join("")}
      ${single && series[0].imm?.p25?.length ? `<span><svg width="18" height="10" aria-hidden="true"><rect width="18" height="10" rx="2" fill="var(--imm-1)" opacity=".18"/></svg>${t("middle half of Immortal players")}</span>` : ""}
    </div>`;
  const tableRows = [];
  for (let m = 0; m <= shownMin; m += 5) tableRows.push(m);
  if (tableRows.at(-1) !== shownMin) tableRows.push(shownMin);
  const table = `<details class="curve-table"><summary>${t("Show as a table")}</summary><div class="table-scroll"><table>
      <tr><th>${t("Minute")}</th>${series.map((sr) => `<th class="n">${t("You")} · ${esc(sr.name)}</th><th class="n">Immortal · ${esc(sr.name)}</th>`).join("")}</tr>
      ${tableRows.map((m) => `<tr><td class="num">${m}:00</td>${series.map((sr) => `<td class="n">${sr.you[m] != null ? fmt(sr.you[m], 1) : "–"}</td>
        <td class="n">${sr.imm?.p50?.[m] != null ? fmt(sr.imm.p50[m], 1) : "–"}</td>`).join("")}</tr>`).join("")}
    </table></div></details>`;

  host.innerHTML = `<div class="curve-plot"></div>${legend}${notes.map((n) => `<p class="lead note-line">${n}</p>`).join("")}${table}`;
  const plot = host.querySelector(".curve-plot");
  plot.appendChild(s);
  const tip = document.createElement("div");
  tip.className = "curve-tip";
  tip.hidden = true;
  plot.appendChild(tip);

  s.addEventListener("pointermove", (ev) => {
    const r = s.getBoundingClientRect();
    const m = Math.round(Math.max(0, Math.min(1, (ev.clientX - r.left - pad.l) / (r.width - pad.l - pad.r))) * shownMin);
    cross.setAttribute("x1", X(m)); cross.setAttribute("x2", X(m)); cross.setAttribute("visibility", "visible");
    dots.replaceChildren();
    tip.replaceChildren();
    const head = document.createElement("div");
    head.className = "tip-head";
    head.textContent = `${m}:00`;
    tip.appendChild(head);
    for (const sr of series) {
      for (const [side, vals] of [["you", sr.you], ["imm", sr.imm?.p50]]) {
        const v = vals?.[m];
        if (v == null) continue;
        svg("circle", { cx: X(m), cy: Y(v), r: 4.5, fill: SHADES[side][sr.i], class: "end-dot" }, dots);
        const row = document.createElement("div");
        row.className = "tip-row";
        row.innerHTML = `<svg width="16" height="8" aria-hidden="true"><line x1="0" x2="16" y1="4" y2="4" stroke="${SHADES[side][sr.i]}" stroke-width="3" ${DASH[sr.i] ? `stroke-dasharray="${DASH[sr.i]}"` : ""}/></svg>`;
        const val = document.createElement("b");
        val.textContent = fmt(v, v < 100 && !Number.isInteger(v) ? 1 : 0);
        const name = document.createElement("span");
        name.textContent = `${side === "you" ? t("You") : "Immortal"} · ${sr.name}`;
        row.append(val, name);
        tip.appendChild(row);
      }
    }
    tip.hidden = false;
    const px = (X(m) / W) * r.width;
    tip.style.left = `${px > r.width / 2 ? px - tip.offsetWidth - 14 : px + 14}px`;
  });
  s.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dots.replaceChildren(); tip.hidden = true; });
}

const GENERAL = ["gpm", "xpm", "ka_per_30", "deaths_per_30", "dead_pct", "fight_participation", "hero_damage_per_min",
  "tower_damage_per_min", "obs_per_30", "sen_per_30", "wards_killed_per_30"];

function pctBar(better) {
  const colour = better >= 50 ? "var(--green)" : better >= 25 ? "var(--yellow)" : "var(--red)";
  const x = 4 + (better / 100) * 112;
  return `<span class="pct"><svg viewBox="0 0 120 14" aria-hidden="true">
      <line class="base" x1="4" x2="116" y1="7" y2="7"/><line class="median" x1="60" x2="60" y1="2" y2="12"/>
      <line class="you" x1="${x}" x2="${x}" y1="1" y2="13" stroke="${colour}"/></svg>
    <span class="num">${t("better than {p}%", { p: better })}</span></span>`;
}

function generalStatsHtml(an) {
  const me = myPlayer(an);
  const comp = an.vs_immortal?.[an.me];
  const show = (k, v) => k === "fight_participation" ? `${Math.round(v * 100)}%` : k === "dead_pct" ? `${fmt(v, 1)}%` : fmt(v, v < 100 ? 1 : 0);
  const tiles = GENERAL.filter((k) => comp?.stats?.[k]).map((k) => {
    const r = comp.stats[k];
    return `<div class="tile"><span class="tile-label">${esc(statLabel(k, r.label.charAt(0).toUpperCase() + r.label.slice(1)))}</span>
      <span class="tile-value">${show(k, r.value)}</span>
      <span class="tile-sub">${t("Immortal typical {v}", { v: show(k, r.immortal_median) })}</span>${pctBar(r.better_than_pct_of_immortals)}</div>`;
  }).join("");
  const totals = [
    me.obs_placed != null ? t("{o} observer and {s} sentry wards placed", { o: me.obs_placed, s: me.sen_placed }) : null,
    me.wards_killed != null ? t(me.wards_killed === 1 ? "{n} enemy ward destroyed" : "{n} enemy wards destroyed", { n: me.wards_killed }) : null,
    me.fight_participation != null ? t("in {p}% of your team's kills", { p: Math.round(me.fight_participation * 100) }) : null,
    me.hero_damage != null ? t("{n} hero damage", { n: fmt(me.hero_damage) }) : null,
    me.tower_damage != null ? t("{n} building damage", { n: fmt(me.tower_damage) }) : null,
    me.stuns ? t("{s}s of stuns", { s: fmt(me.stuns, 1) }) : null,
    me.camps_stacked ? t("{n} camps stacked", { n: me.camps_stacked }) : null,
  ].filter(Boolean);
  return `${totals.length ? `<p class="lead">${t("This game: {list}.", { list: esc(totals.join(" · ")) })}</p>` : ""}
    ${tiles ? `<div class="tiles">${tiles}</div><p class="lead">${t("The bar shows how many Immortal players on the {cmp} you did better than; the middle tick is a typical one.", { cmp: esc(t(Object.values(comp.stats)[0].compared_with)) })}</p>`
      : `<p class="lead">${t("Immortal benchmarks aren't built yet, or there aren't enough Immortal games on this hero. Run <code>python -m mmrslave benchmarks</code> after collecting more games.")}</p>`}`;
}

function laneHtml(an) {
  const lane = an.laning?.[an.me];
  const comp = an.vs_immortal?.[an.me];
  let html = "";
  if (lane) {
    const you = lane.at_10_min;
    html += `<div><h3 class="section-title">${t("Your lane at 10:00")}</h3>
      <div class="table-scroll"><table><tr><th>${t("Hero")}</th><th class="n">Last hits</th><th class="n">Net worth</th><th class="n">Level</th></tr>
      <tr class="me"><td class="hero-cell">${t("You")}</td><td class="n">${you.lh}</td><td class="n">${fmt(you.nw)}</td><td class="n">${you.level}</td></tr>
      ${lane.lane_opponents.map((o) => `<tr><td><span class="hero-cell">${esc(o.hero)}</span><span class="sub">${t("enemy pos {p}", { p: esc(o.position) })}</span></td>
        <td class="n">${o.lh}</td><td class="n">${fmt(o.nw)}</td><td class="n">${o.level}</td></tr>`).join("")}
      </table></div>
      <p class="lead">${t("{k} kills and {d} deaths before 10:00", { k: lane.kills_before_10, d: lane.deaths_before_10 })}${lane.lane_efficiency_pct != null ? ` · lane efficiency ${lane.lane_efficiency_pct}%` : ""}.</p></div>`;
  } else {
    html += `<p class="lead">${t("The game ended before 10:00.")}</p>`;
  }
  const items = comp?.items;
  if (items?.timings?.length) {
    html += `<div><h3 class="section-title">${t("Item timings vs Immortal ({cmp})", { cmp: esc(t(items.compared_with)) })}</h3>
      <div class="table-scroll"><table><tr><th>Item</th><th class="n">${t("You")}</th><th class="n">${t("Typical Immortal")}</th><th class="n">${t("Difference")}</th></tr>
      ${items.timings.map((it) => `<tr><td>${esc(it.item)}</td><td class="n">${esc(it.your_time)}</td><td class="n">${esc(it.immortal_median)}</td>
        <td class="n ${it.minutes_behind >= 3 ? "lost" : it.minutes_behind <= -2 ? "won" : ""}">${t("{n} min", { n: `${it.minutes_behind > 0 ? "+" : ""}${fmt(it.minutes_behind, 1)}` })}</td></tr>`).join("")}
      </table></div></div>`;
  }
  if (items?.commonly_built_but_skipped?.length) {
    html += `<div><h3 class="section-title">${t("Immortal players usually build these on this hero")}</h3><ul class="list">
      ${items.commonly_built_but_skipped.slice(0, 5).map((s) => `<li><h3>${esc(s.item)}</h3><p>${t("{p}% of Immortal games over 30 minutes, usually by {t}.", { p: s.immortal_build_rate_pct, t: esc(s.immortal_median) })}</p></li>`).join("")}
      </ul></div>`;
  }
  return `<div class="two-col">${html}</div>`;
}

function practiceHtml(an) {
  const myDeaths = an.deaths.filter((d) => d.victim === an.me);
  const counts = new Map();
  for (const d of myDeaths) for (const t of d.tags || []) {
    const key = t.replace(/\d+s/, "Ns");
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const patterns = [...counts.entries()].filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]);
  const patternHtml = patterns.length
    ? `<div><h3 class="section-title">${t("Patterns in your {n} deaths", { n: myDeaths.length })}</h3><ul class="list">${patterns.map(([x, n]) =>
        `<li><h3>${t("{n} of {m}: {tag}", { n, m: myDeaths.length, tag: esc(tag(x.replace("Ns", "a few seconds"))) })}</h3></li>`).join("")}</ul></div>`
    : "";
  const kinds = new Map();
  for (const d of an.decisions?.missed || []) kinds.set(d.kind, (kinds.get(d.kind) || 0) + 1);
  const k = (key) => kinds.get(key) || 0;
  const decisionHtml = kinds.size ? `<div><h3 class="section-title">${t("Decisions to work on")}</h3><ul class="list">
      ${k("missed_fight") ? `<li><h3>${t(k("missed_fight") > 1 ? "{n} fights you could have reached in time" : "{n} fight you could have reached in time", { n: k("missed_fight") })}</h3><p>${t("Keep an eye on the minimap while farming; when your team commits near a tower you can TP to, go, then farm again.")}</p></li>` : ""}
      ${k("tower_lost") ? `<li><h3>${t(k("tower_lost") > 1 ? "{n} towers lost while you were away" : "{n} tower lost while you were away", { n: k("tower_lost") })}</h3><p>${t("Keep a TP scroll and use it when 2+ enemies hit a tower, or push the opposite lane so they have to choose.")}</p></li>` : ""}
      ${k("advantage_unused") ? `<li><h3>${t(k("advantage_unused") > 1 ? "{n} times enemies were dead and nothing was taken" : "{n} time enemies were dead and nothing was taken", { n: k("advantage_unused") })}</h3><p>${t("After a won fight, look at the death timers and walk to the nearest tower or Roshan before farming.")}</p></li>` : ""}
      ${k("runes") ? `<li><h3>${t("The enemy controlled the power runes")}</h3><p>${t("Check the river rune at the even minutes when your wave is pushed.")}</p></li>` : ""}
    </ul></div>` : "";
  const good = an.decisions?.converted || [];
  const goodHtml = good.length ? `<div><h3 class="section-title">${t("Advantages your team used")}</h3><ul class="list">${good.map((g) =>
    `<li><h3><span class="clock">${esc(g.clock)}</span>${esc(loc(g, "title"))}</h3></li>`).join("")}</ul></div>` : "";
  if (!an.report) {
    return `<div class="two-col"><div>${decisionHtml}${patternHtml || (decisionHtml ? "" : `<p class="lead">${t("No repeated pattern in your deaths this game.")}</p>`)}</div>
      <div>${goodHtml}<p class="lead">${t("A practice plan written for this game appears here once written coaching is on (set <code>ANTHROPIC_API_KEY</code>, then press Re-run review).")}</p></div></div>`;
  }
  const r = an.report;
  return `<div class="two-col">
    <div><h3 class="section-title">${t("Practise next")}</h3><ul class="list">${r.practice_focus.map((p) =>
      `<li><h3>${esc(p.habit)}</h3><p>${esc(p.how_to_practice)}</p></li>`).join("")}</ul>${decisionHtml}</div>
    <div>${r.what_you_did_well?.length ? `<h3 class="section-title">${t("What you did well")}</h3><ul class="list">${r.what_you_did_well.map((w) =>
      `<li><p>${esc(w)}</p></li>`).join("")}</ul>` : ""}${goodHtml}${patternHtml}</div>
  </div>`;
}

// ------------------------------------------------------------------ coach brain

async function showBrain() {
  main.innerHTML = `<section class="state">${loading(t("Checking what the coach has learned…"))}</section>`;
  let st;
  try { st = state.status = await api("/api/status"); } catch (e) {
    main.innerHTML = `<section class="state"><h1>${t("Couldn't load the coach's status")}</h1><p>${esc(e.message)}</p></section>`;
    return;
  }
  renderBrainMeta();
  const count = (src, status) => (st.summary || []).filter((r) => r.source === src && (!status || r.status === status)).reduce((a, r) => a + r.n, 0);
  const learned = count("immortal", "parsed");
  const queued = count("immortal", "url") + count("immortal", "found") + count("immortal", "downloaded");
  const hist = st.history || [];
  // Each model may have been retrained on its own, so take the newest run that measured it.
  const latest = (key) => [...hist].reverse().find((h) => h[key] != null)?.[key];
  const last = { winprob_accuracy: latest("winprob_accuracy"), risk_auc: latest("risk_auc"), move_top5: latest("move_top5") };
  const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);

  let chart = "";
  const pts = hist.filter((h) => h.winprob_accuracy != null);
  if (pts.length >= 2) {
    // One point per training run, oldest on the left, labelled with how many games it learned from.
    const W = 1000, H = 230, padX = 70, top = 24, bottom = 186;
    const px = (i) => padX + (i / (pts.length - 1)) * (W - 2 * padX);
    const py = (a) => bottom - ((Math.max(0.5, Math.min(1, a)) - 0.5) / 0.5) * (bottom - top);
    chart = `<div><h2 class="section-title">${t("Win-chance accuracy as the coach learns")}</h2>
      <svg viewBox="0 0 ${W} ${H}" class="brain-chart" role="img" aria-label="${t("Win-chance accuracy for each training run")}">
        <line class="mid" x1="${padX}" x2="${W - padX}" y1="${py(0.5)}" y2="${py(0.5)}"/>
        <text class="axis" x="${padX - 12}" y="${py(0.5) + 5}" text-anchor="end">50%</text>
        <text class="axis" x="${padX - 12}" y="${py(1) + 5}" text-anchor="end">100%</text>
        <polyline class="line" points="${pts.map((h, i) => `${px(i)},${py(h.winprob_accuracy)}`).join(" ")}"/>
        ${pts.map((h, i) => `<circle cx="${px(i)}" cy="${py(h.winprob_accuracy)}" r="6"/>
          <text class="val" x="${px(i)}" y="${py(h.winprob_accuracy) - 14}" text-anchor="middle">${pct(h.winprob_accuracy)}</text>
          <text class="axis" x="${px(i)}" y="${H - 14}" text-anchor="middle">${t("{n} games", { n: fmt(h.train_matches) })}</text>`).join("")}
      </svg><p class="lead">${t("Accuracy on games the model never saw, after each training run. 50% is a coin flip.")}</p></div>`;
  }

  main.innerHTML = `
    <header class="match-head"><div class="mh-title"><h1>${t("Coach brain")}</h1></div>
      <p class="match-meta">${t("Learned from <b class=\"num\">{n}</b> high-Immortal games", { n: fmt(learned) })}${queued ? t(" · {n} more queued", { n: fmt(queued) }) : ""}${t(" · your games: {n}", { n: fmt(count("mine", "parsed") + count("local", "parsed")) })}</p></header>
    <section class="verdict"><h2>${learned < 1000
      ? t("Still early: the coach gets much sharper past a few thousand games.")
      : t("Trained on enough games to trust the big swings.")}</h2>
      <p>${t("Valve keeps replays for about 10 days, so new Immortal games are collected continuously and the models are retrained as they arrive. Run <code>python -m mmrslave auto</code> (or leave <code>collect</code> running) to keep it learning.")}</p></section>
    <div class="brain-grid">
      <article class="brain-model ${st.models?.winprob ? "" : "off"}"><h2>${t("Win chance")}</h2>
        <span class="score num">${pct(last.winprob_accuracy)}</span>
        <p>${t("How often it picks the eventual winner at a random moment of a game it never saw. Used to price every death and find the turning points.")}</p></article>
      <article class="brain-model ${st.models?.context ? "" : "off"}"><h2>${t("Death risk")}</h2>
        <span class="score num">${last.risk_auc != null ? last.risk_auc.toFixed(2) : "–"}</span>
        <p>${t("How well it tells moments right before a death from safe ones (0.5 = guessing, 1.0 = perfect), using only what the hero's team could see.")}</p></article>
      <article class="brain-model ${st.models?.context ? "" : "off"}"><h2>${t("Where Immortals go")}</h2>
        <span class="score num">${pct(last.move_top5)}</span>
        <p>${t("How often the real spot a player reached 30 seconds later is among its five best guesses on the map.")}</p></article>
    </div>
    ${chart}
    <div>
      <h2 class="section-title">${t("Training runs")}</h2>
      ${hist.length ? `<div class="table-scroll"><table><tr><th>${t("When")}</th><th class="n">${t("Games")}</th><th class="n">${t("Win chance")}</th><th class="n">${t("Death risk")}</th><th class="n">${t("Where Immortals go")}</th></tr>
        ${hist.slice().reverse().map((h) => `<tr><td>${esc(h.trained_at)}</td><td class="n">${fmt(h.train_matches)}</td><td class="n">${pct(h.winprob_accuracy)}</td>
          <td class="n">${h.risk_auc != null ? h.risk_auc.toFixed(2) : "–"}</td><td class="n">${pct(h.move_top5)}</td></tr>`).join("")}</table></div>`
        : `<p class="lead">${t("No training runs yet. Run <code>python -m mmrslave train</code>.")}</p>`}
    </div>
    <p class="lead">${st.coach_ready ? t("Written coaching: on.") : t("Written coaching: off. Set the <code>ANTHROPIC_API_KEY</code> environment variable and restart the dashboard to turn it on.")}</p>`;
}

// ------------------------------------------------------------------ Steam account

async function refreshAccount() {
  try { state.account = await api("/api/account"); } catch (e) { state.account = state.account || { steam_id: null }; }
  renderAccount();
}

function avatarHtml(p, cls = "acc-avatar") {
  return p?.avatar ? `<img class="${cls}" src="${esc(p.avatar)}" alt="" referrerpolicy="no-referrer"
      onerror="this.replaceWith(Object.assign(document.createElement('span'), {className: '${cls} none', textContent: '?'}))">`
    : `<span class="${cls} none" aria-hidden="true">?</span>`;
}

function accountName(acc) {
  return acc.profile?.name || t("Steam ID {id}", { id: acc.steam_id });
}

function renderAccount() {
  const box = $("#account");
  const acc = state.account;
  const connected = Boolean(acc?.steam_id);
  $("#fetchBtn").hidden = !connected;
  if (!acc) { box.innerHTML = ""; return; }
  if (connected) {
    const rank = state.status?.rank;
    box.innerHTML = `<a class="account-card" href="#/settings" title="${esc(t("Steam account"))}">
      ${avatarHtml(acc.profile)}
      <span><span class="acc-name">${esc(accountName(acc))}</span>
      <span class="acc-meta">${esc(rank || t("Steam connected"))}</span></span></a>`;
  } else {
    box.innerHTML = `<a class="btn btn-brand" href="/auth/steam/login">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4.5H5.5v15H10M14.5 8l4 4-4 4M18.5 12H9"/></svg>
        <span>${t("Sign in through Steam")}</span></a>
      <p class="account-note">${t("You sign in on Steam's own page. MMRSlave only learns your Steam ID, never your password.")}</p>`;
  }
}

// Steam sends the window back here after signing in: /?steam=connected#/ or /?steam_error=...#/
function handleSteamReturn() {
  const q = new URLSearchParams(location.search);
  if (!q.has("steam") && !q.has("steam_error")) return;
  history.replaceState(null, "", "/" + (location.hash || "#/"));
  if (q.get("steam_error")) {
    renderAccount();
    const note = $("#account .account-note");
    if (note) { note.classList.add("err"); note.textContent = t("Steam sign-in didn't finish: {e}", { e: t(q.get("steam_error")) }); }
    return;
  }
  // First sign-in: go and find this account's games straight away.
  if (!state.matches.length) $("#fetchBtn").click();
}

async function disconnectSteam() {
  if (!confirm(t("Disconnect this Steam account? Your downloaded games stay on this PC."))) return;
  await api("/api/account/disconnect", { method: "POST" });
  state.match = null;
  await Promise.all([refreshAccount(), refreshRail()]);
  showSettings();
}

// ------------------------------------------------------------------ updates

async function refreshVersion() {
  try { state.version = await api("/api/version"); } catch (e) { return; }
  renderUpdatePill();
  if (state.version.job?.state === "running") watchUpdate();
}

function renderUpdatePill() {
  const pill = $("#updatePill");
  const v = state.version;
  const busy = v?.job?.state === "running" || state.restarting;
  const available = v?.check?.available;
  pill.hidden = !(busy || available);
  pill.classList.toggle("busy", Boolean(busy));
  pill.textContent = busy ? t("Updating…") : t("New version available");
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(dateLocale(), { day: "numeric", month: "short", year: "numeric" });
}

function updateBoxHtml() {
  const v = state.version;
  if (!v) return `<div class="update-box">${loading(t("Checking GitHub…"))}</div>`;
  if (state.restarting) return `<div class="update-box new">${loading(t("Restarting on the new version…"))}</div>`;
  const job = v.job;
  if (job?.state === "running") return `<div class="update-box new">${loading(t(job.log.at(-1) || "Installing…"))}</div>`;
  const jobErr = job?.state === "error"
    ? `<p class="err">${esc(t("The update failed: {e}", { e: t((job.log.at(-1) || "").replace(/^error:\s*/, "")) }))}</p>` : "";
  if (v.error) return `<div class="update-box">${jobErr}<p class="err">${esc(t(v.error))}</p></div>`;
  const c = v.check;
  if (!c) return `<div class="update-box">${jobErr}${loading(t("Checking GitHub…"))}</div>`;
  const checked = t("Checked at {time}.", { time: new Date(c.checked_at * 1000).toLocaleTimeString(dateLocale(), { hour: "2-digit", minute: "2-digit" }) });
  if (!c.available) {
    return `<div class="update-box">${jobErr}<p class="update-head">${t("You have the newest version.")}</p><p class="set-note">${checked}</p></div>`;
  }
  const changes = c.changes?.length ? `<ul class="changes">${c.changes.map((x) =>
    `<li><code>${esc(x.sha)}</code><span>${esc(x.message)}</span></li>`).join("")}</ul>` : "";
  let action;
  if (c.needs_full_download) {
    action = `<p class="set-note warn">${t("This version adds new libraries, so it needs the full download. Unzip it over this copy (your games and settings stay) and open MMRSlave again.")}</p>
      <div class="set-actions"><a class="btn btn-brand" href="${esc(c.releases_url)}" target="_blank" rel="noopener">${t("Download the new version")}</a></div>`;
  } else if (c.can_install) {
    action = `<div class="set-actions"><button class="btn btn-brand" type="button" id="installUpdate">${t("Install and restart")}</button></div>`;
  } else {
    action = `<p class="set-note">${t("This copy wasn't installed from GitHub, so it can't update itself.")}</p>`;
  }
  const head = c.ahead_by
    ? t("New version {v} from {date}: {n} changes", { v: c.latest.short, date: fmtDate(c.latest.date), n: c.ahead_by })
    : t("New version {v} from {date}", { v: c.latest.short, date: fmtDate(c.latest.date) });
  return `<div class="update-box new">${jobErr}<p class="update-head">${esc(head)}</p>${changes}${action}<p class="set-note">${checked}</p></div>`;
}

function renderUpdateBox() {
  const box = $("#updateBox");
  if (!box) return;
  box.innerHTML = updateBoxHtml();
  $("#installUpdate")?.addEventListener("click", installUpdate);
}

async function installUpdate() {
  try {
    const job = await api("/api/update/install", { method: "POST" });
    state.version = { ...state.version, job };
    renderUpdateBox();
    renderUpdatePill();
    watchUpdate();
  } catch (e) {
    state.version = { ...state.version, error: e.message };
    renderUpdateBox();
  }
}

let watchingUpdate = false;
async function watchUpdate() {
  if (watchingUpdate) return;
  watchingUpdate = true;
  const before = state.version?.installed?.sha;
  const job = await pollJob("update", (msg) => {
    if (state.version) state.version.job = { ...(state.version.job || {}), state: "running", log: [msg] };
    renderUpdateBox();
  });
  watchingUpdate = false;
  if (job.state === "error" || !/Restarting/.test(job.log.at(-1) || "")) {
    await refreshVersion();
    renderUpdateBox();
    return;
  }
  // The server restarts on the new code; reload once it answers with the new version.
  state.restarting = true;
  renderUpdatePill();
  renderUpdateBox();
  for (let i = 0; i < 180; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const p = await api("/api/ping");
      if (p.version !== before || i > 20) { location.reload(); return; }
    } catch (e) { /* still restarting */ }
  }
  state.restarting = false;
  renderUpdateBox();
}

// ------------------------------------------------------------------ settings page

async function showSettings() {
  pause();
  state.matchId = null;
  if (!$(".settings")) main.innerHTML = `<section class="state">${loading(t("Loading settings…"))}</section>`;
  await Promise.all([refreshAccount(), state.version ? null : refreshVersion()]);
  if (!location.hash.startsWith("#/settings")) return;
  const acc = state.account || {};
  const v = state.version;
  const inst = v?.installed || {};
  const modeNote = {
    bundle: t("Updates come from GitHub: only the changed code and the coach's training, a few MB."),
    git: t("Running from a Git clone: updating runs <code>git pull</code>."),
    source: t("This copy wasn't installed from GitHub, so it can't update itself."),
  }[inst.mode] || "";
  const accountHtml = acc.steam_id ? `
      <div class="set-account">${avatarHtml(acc.profile)}
        <div><span class="acc-name">${esc(accountName(acc))}</span>
        <span class="acc-meta">${esc([state.status?.rank, `Steam ID ${acc.steam_id}`].filter(Boolean).join(" · "))}</span></div></div>
      ${acc.profile && !acc.profile.known ? `<p class="set-note warn">${t("OpenDota doesn't know this account yet. In Dota 2, turn on <b>Settings → Social → Expose Public Match Data</b>, play a game, then fetch your games.")}</p>` : ""}
      <div class="set-actions">
        <a class="btn btn-quiet" href="/auth/steam/login">${t("Switch account")}</a>
        <button class="btn btn-quiet" type="button" id="disconnectSteam">${t("Disconnect")}</button>
      </div>`
    : `<p class="set-note">${t("Connect your Steam account so MMRSlave can find your ranked games. You sign in on Steam's own page: MMRSlave only learns your Steam ID, never your password, and can't do anything with your account.")}</p>
      <div class="set-actions"><a class="btn btn-brand" href="/auth/steam/login">${t("Sign in through Steam")}</a></div>`;

  main.innerHTML = `
    <header class="match-head"><div class="mh-title"><h1>${t("Settings")}</h1></div></header>
    <div class="settings">
      <section aria-labelledby="setSteam">
        <h2 class="section-title" id="setSteam">${t("Steam account")}</h2>
        ${accountHtml}
        <p class="set-note">${t("Your games are found through OpenDota. In Dota 2, keep <b>Settings → Social → Expose Public Match Data</b> on.")}</p>
      </section>
      <section aria-labelledby="setUpdates">
        <h2 class="section-title" id="setUpdates">${t("Updates")}</h2>
        <p class="version-line">${t("Version")} <b>${esc(inst.short || "?")}</b>${inst.date ? ` · ${esc(fmtDate(inst.date))}` : ""}</p>
        <p class="set-note">${modeNote}</p>
        <div id="updateBox" role="status" aria-live="polite"></div>
        <div class="set-actions">
          <button class="btn btn-quiet" type="button" id="checkUpdates" ${inst.mode === "source" ? "disabled" : ""}>${t("Check for updates")}</button>
        </div>
        <label class="toggle"><input type="checkbox" id="autoUpdate" ${v?.auto_update ? "checked" : ""} ${inst.mode === "source" ? "disabled" : ""}>
          ${t("Install updates automatically when MMRSlave starts")}</label>
      </section>
    </div>`;
  renderUpdateBox();
  $("#disconnectSteam")?.addEventListener("click", disconnectSteam);
  $("#checkUpdates").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    state.version = { ...state.version, check: null, error: null, job: null };
    renderUpdateBox();
    try { state.version = await api("/api/update/check", { method: "POST" }); } catch (err) { state.version = { ...state.version, error: err.message }; }
    btn.disabled = false;
    btn.removeAttribute("aria-busy");
    renderUpdateBox();
    renderUpdatePill();
  });
  $("#autoUpdate").addEventListener("change", async (e) => {
    try {
      state.version = await api("/api/settings/updates", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ auto_update: e.target.checked }),
      });
    } catch (err) { e.target.checked = !e.target.checked; }
  });
}

// ------------------------------------------------------------------ start

async function start() {
  setupTheme();
  setupLanguage();
  setupFetch();
  setupKeys();
  window.addEventListener("hashchange", route);
  try { state.geometry = await api("/api/geometry"); } catch (e) { state.geometry = null; }
  await Promise.all([refreshRail(), refreshAccount()]);
  refreshVersion();
  // The server looks for a new version in the background when it starts; pick up the answer.
  (async () => {
    for (let i = 0; i < 15 && state.version && !state.version.check && !state.version.error; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      await refreshVersion();
      renderUpdateBox();
    }
  })();
  await route();
  handleSteamReturn();
}

start();
