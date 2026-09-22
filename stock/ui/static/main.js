// Stock — the ledger front end (Doc 07). A small reactive store over the server's
// Snapshot: header, rail, stage (map | curves | one panel), Now column, footer.
// This file formats and draws; every number and every drafted action comes from the
// snapshot (stock/api/snapshot.py, stock/api/offers.py).

import { renderCurves } from "./curves.js";
import { format, formatBasket, formatYear } from "./format.js";
import { H, L, nameOf, setTables } from "./labels.js";
import { renderMap } from "./map.js";
import { renderCapital, renderIncidence, renderLedger, renderPolitics, renderRoutes, renderSecurity } from "./panels.js";
import { renderTree1, renderTree2 } from "./trees.js";
import { actionButton, el, getVar, tip } from "./ui.js";

const RAIL = [
  { id: "map", label: "Map", glyph: "◎", key: "M" },
  { id: "curves", label: "Curves", glyph: "∿", key: "C" },
  { id: "ledger", label: "Ledger", glyph: "≡", key: "L" },
  { id: "incidence", label: "Incidence", glyph: "⚖", key: "I" },
  { id: "capital", label: "Capital", glyph: "⌂", key: "K" },
  { id: "politics", label: "Politics", glyph: "§", key: "P" },
  { id: "routes", label: "Routes", glyph: "⇄", key: "R" },
  { id: "security", label: "Security", glyph: "⚔", key: "S" },
  { id: "tree1", label: "Tree I", glyph: "⑂", key: "W" },
  { id: "tree2", label: "Tree II", glyph: "⑃", key: "H" },
];

const PANELS = {
  ledger: renderLedger,
  incidence: renderIncidence,
  capital: renderCapital,
  politics: renderPolitics,
  routes: renderRoutes,
  security: renderSecurity,
  tree1: renderTree1,
  tree2: renderTree2,
};

const state = {
  snapshot: null,
  prevSnapshot: null,
  view: "map",
  selected: null, // {id, nation}
  hiddenNations: new Set(),
  sort: {},
  drawers: {},
  footerOverride: null,
  stageDirty: false,
  mapCleanup: null,
  reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  seenViews: new Set(JSON.parse(localStorage.getItem("stock.seenViews") || "[]")),
  lastSeat: null,
  gameOverDismissed: null, // the game_over payload the player chose to keep playing past
  turnInFlight: false, // a POST /turn is out; the End year button waits for it
  world: null, // the spec that names this world (random:SEED:LOCATIONS:NATIONS), from /scenario
};

const $ = (sel) => document.querySelector(sel);

// ---------- network ----------

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try {
    data = await r.json();
  } catch (e) {
    /* no body */
  }
  return { ok: r.ok, status: r.status, data };
}

async function fetchState() {
  const r = await fetch("/state");
  applySnapshot(await r.json());
}

async function fetchWorld() {
  const r = await fetch("/scenario");
  if (!r.ok) return;
  state.world = (await r.json()).name;
  renderWorld();
}

function renderWorld() {
  const el_ = $("#world");
  if (!el_) return;
  const spec = state.world || "";
  const parts = spec.split(":");
  // random:SEED:LOCATIONS:NATIONS reads as "world 101019 · 24 territories · 3 nations"
  el_.textContent =
    parts[0] === "random" && parts.length >= 4
      ? `world ${parts[1]} · ${parts[2]} territories · ${parts[3]} nations`
      : spec;
}

// Start over on another world: a fresh seed, or the one typed in.
function showNewWorld(anchor) {
  const box = $("#confirm");
  box.innerHTML = "";
  box.append(el("div", { class: "title", text: "New world" }));
  box.append(el("div", { class: "small muted", text: "Leave the seed empty for a world nobody has seen." }));
  const row = el("div", { class: "row", style: { marginTop: "8px", gap: "6px" } });
  const seed = el("input", { type: "number", min: "1", step: "1", placeholder: "seed", style: { width: "96px" } });
  const nations = el("select");
  for (const n of [2, 3, 4, 5]) nations.append(el("option", { value: String(n), text: `${n} nations`, selected: n === 3 }));
  const size = el("select");
  for (const [n, label] of [[18, "small"], [24, "middling"], [32, "large"], [40, "vast"]]) {
    size.append(el("option", { value: String(n), text: label, selected: n === 24 }));
  }
  row.append(seed, size, nations);
  box.append(row);
  const buttons = el("div", { class: "buttons" });
  const cancel = el("button", { text: "Cancel" });
  const start = el("button", { class: "danger", text: "Start over" });
  cancel.addEventListener("click", () => box.classList.remove("open"));
  start.addEventListener("click", async () => {
    box.classList.remove("open");
    // no seed typed: draw one here so the chosen size and nations still apply
    const chosen = seed.value ? Number(seed.value) : Math.floor(1 + Math.random() * 999999);
    const res = await postJSON("/new", { scenario: `random:${chosen}:${size.value}:${nations.value}` });
    if (!res.ok) {
      flashFooter(`New world · not started · ${res.data && res.data.detail ? res.data.detail : "HTTP " + res.status}`);
      return;
    }
    state.selected = null;
    state.gameOverDismissed = null;
    applySnapshot(res.data);
    fetchWorld();
  });
  buttons.append(cancel, start);
  box.append(buttons);
  const rect = anchor.getBoundingClientRect();
  box.style.left = Math.min(window.innerWidth - 300, rect.left) + "px";
  box.style.top = Math.min(window.innerHeight - 140, rect.bottom + 6) + "px";
  box.classList.add("open");
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const snapshot = JSON.parse(ev.data);
    // /turn answers with the year it just ran and the socket carries the same one:
    // apply each year once, or every delta would compare a year with itself.
    if (state.snapshot && snapshot.header.year === state.snapshot.header.year) return;
    applySnapshot(snapshot);
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
  ws.onerror = () => ws.close();
}

function applySnapshot(snapshot) {
  state.prevSnapshot = state.snapshot;
  state.snapshot = snapshot;
  setTables(snapshot);
  // Doc 07 onboarding: the first year opens with the band's own node selected.
  if (!state.selected && snapshot.player && snapshot.player.home && snapshot.map.band_mode) {
    const home = snapshot.map.nodes.find((n) => n.id === snapshot.player.home);
    if (home) state.selected = { id: home.id, nation: home.nation };
  }
  render();
}

// ---------- actions: draft, confirm, boundary ----------

function showConfirm(anchor, offer, onYes) {
  const box = $("#confirm");
  box.innerHTML = "";
  box.append(el("div", { class: "title", text: offer.label }));
  box.append(el("div", { class: "small", text: `cost ${formatBasket(offer.cost)} · applies ${formatYear(state.snapshot.header.year + 1)} · cannot be withdrawn once applied` }));
  const buttons = el("div", { class: "buttons" });
  const cancel = el("button", { text: "Cancel" });
  const yes = el("button", { class: "danger", text: "Confirm" });
  cancel.addEventListener("click", () => box.classList.remove("open"));
  yes.addEventListener("click", () => {
    box.classList.remove("open");
    onYes();
  });
  buttons.append(cancel, yes);
  box.append(buttons);
  const rect = anchor.getBoundingClientRect();
  box.style.left = Math.min(window.innerWidth - 280, rect.left) + "px";
  box.style.top = Math.min(window.innerHeight - 120, rect.bottom + 6) + "px";
  box.classList.add("open");
}

async function draft(offer, payloadOverride, btn) {
  const send = async () => {
    if (btn) btn.disabled = true;
    const payload = payloadOverride || offer.payload;
    const res = await postJSON("/action", { nation: state.snapshot.player_nation, kind: offer.kind, payload });
    if (!res.ok) {
      const n = (res.data && res.data.numbers) || {};
      const why = res.data && res.data.reason ? res.data.reason : res.data && res.data.detail ? res.data.detail : `HTTP ${res.status}`;
      const nums = Object.entries(n).map(([k, v]) => `${L("symbol", k)} ${formatBasket(v)}`).join(" · ");
      flashFooter(`${offer.label} · not queued · ${why}${nums ? " · " + nums : ""}`);
      if (btn) btn.disabled = false;
    }
    setTimeout(fetchState, 120);
  };
  if (offer.confirm) showConfirm(btn || document.body, offer, send);
  else await send();
}

function flashFooter(text) {
  state.footerOverride = text;
  renderFooter();
  setTimeout(() => {
    if (state.footerOverride === text) {
      state.footerOverride = null;
      renderFooter();
    }
  }, 4000);
}

// ---------- header ----------

function renderHeader() {
  const s = state.snapshot;
  const yearEl = $("#year");
  if (yearEl.textContent !== formatYear(s.header.year)) {
    yearEl.textContent = formatYear(s.header.year);
    yearEl.classList.remove("settle");
    void yearEl.offsetWidth;
    yearEl.classList.add("settle");
  }
  const turn = $("#turn");
  turn.disabled = state.turnInFlight;
  turn.querySelector(".label").textContent = `End year ${formatYear(s.header.year)}`;
  $("#player-name").textContent = s.player ? s.player.name : nameOf.nation(s.player_nation);
  $("#player-seat").textContent = s.player ? L("seat", s.player.seat) : "";

  const hl = $("#headline");
  hl.innerHTML = "";
  const prev = state.prevSnapshot;
  for (const h of s.header.headline) {
    const unit = h.key === "labour_share" ? "share" : "basket";
    const div = el("div", { class: "hl" });
    div.append(tip(el("span", { class: "label", text: h.label }), H("headline", h.key)));
    const row = el("div", { class: "hl-row" });
    const value = el("span", { class: "value tabular", text: format(h.value, unit) });
    const prevH = prev && prev.header.headline.find((x) => x.key === h.key);
    if (prevH && prevH.value !== h.value && !state.reducedMotion) value.classList.add("settle");
    row.append(value);
    const deltaClass = h.delta > 0 ? "up" : h.delta < 0 ? "down" : "muted";
    row.append(el("span", { class: `delta tabular ${deltaClass}`, text: format(h.delta, "delta_" + unit) }));
    const canvas = el("canvas", { width: 80, height: 28 });
    drawSparkline(canvas, h.sparkline);
    row.append(canvas);
    div.append(row);
    hl.append(div);
  }

  const band = s.header.hegemony_band;
  const bandEl = $("#hegemony-band");
  if (band && band.active) {
    bandEl.classList.add("active");
    const text = $("#hegemony-text");
    tip($("#hegemony-band"), H("panel", "hegemony_band"));
    text.innerHTML = "";
    text.append(el("span", { class: "serif", style: { color: band.nation_color || "inherit" }, text: band.nation_name || nameOf.nation(band.nation) }));
    text.append(" ");
    for (const f of band.flags) text.append(el("span", { class: "flag", style: { background: band.nation_color || getVar("--warn") }, title: nameOf.nation(f) }));
    text.append(el("span", { class: "tabular", text: ` ${band.years_remaining}y` }));
    const total = 50;
    const pct = Math.max(0, Math.min(100, (1 - band.years_remaining / total) * 100));
    $("#hegemony-fill").style.width = pct + "%";
    $("#hegemony-fill").style.background = band.nation_color || getVar("--warn");
  } else {
    bandEl.classList.remove("active");
  }
}

function drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!values || values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  ctx.beginPath();
  ctx.strokeStyle = getVar("--ink-2");
  ctx.lineWidth = 2;
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * (canvas.width - 4) + 2;
    const y = canvas.height - 3 - ((v - min) / span) * (canvas.height - 6);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// ---------- rail ----------

function unlockedViews() {
  const s = state.snapshot;
  const band = s.player && s.player.seat === "BAND";
  // Panels unfold as the seat changes: a band sees the map, the curves, the ledger and
  // the trees (Tree I is where its first fire and first field show up).
  return band ? new Set(["map", "curves", "ledger", "politics", "tree1", "tree2"]) : new Set(RAIL.map((r) => r.id));
}

function renderRail() {
  const rail = $("#rail");
  const unlocked = unlockedViews();
  if (rail.childElementCount !== RAIL.length) {
    rail.innerHTML = "";
    for (const r of RAIL) {
      const b = el("button", { dataset: { view: r.id }, title: `${r.label} (${r.key})` });
      b.append(el("span", { class: "glyph", text: r.glyph }), el("span", { text: r.label }));
      b.addEventListener("click", () => setView(r.id));
      rail.append(b);
    }
  }
  rail.querySelectorAll("button").forEach((b) => {
    const id = b.dataset.view;
    b.classList.toggle("active", id === state.view);
    b.disabled = !unlocked.has(id);
    if (unlocked.has(id) && !state.seenViews.has(id)) {
      state.seenViews.add(id);
      localStorage.setItem("stock.seenViews", JSON.stringify([...state.seenViews]));
      b.classList.add("pulse-once");
      setTimeout(() => b.classList.remove("pulse-once"), 1500);
    }
  });
}

function setView(id) {
  if (!unlockedViews().has(id)) return;
  state.view = id;
  renderRail();
  renderStage();
}

// End the turn: the server runs one year and answers with the new snapshot.
async function endTurn() {
  if (state.turnInFlight) return;
  state.turnInFlight = true;
  $("#turn").disabled = true;
  try {
    const r = await fetch("/turn", { method: "POST" });
    if (r.ok) applySnapshot(await r.json());
  } finally {
    state.turnInFlight = false;
    $("#turn").disabled = false;
  }
}

function cycleView(delta) {
  const ids = RAIL.map((r) => r.id).filter((id) => unlockedViews().has(id));
  const i = ids.indexOf(state.view);
  setView(ids[(i + delta + ids.length) % ids.length]);
}

// ---------- stage ----------

function stageHasFocus() {
  const a = document.activeElement;
  return a && a !== document.body && $("#stage").contains(a) && ["INPUT", "SELECT", "TEXTAREA"].includes(a.tagName);
}

function renderStage() {
  if (stageHasFocus()) {
    state.stageDirty = true;
    return;
  }
  state.stageDirty = false;
  const stage = $("#stage");
  const scroll = stage.scrollTop;
  if (state.mapCleanup) {
    state.mapCleanup();
    state.mapCleanup = null;
  }
  stage.innerHTML = "";
  const ctx = { state, draft, rerender: renderStage };
  const stageActions = {
    select: selectNode,
    openLedgerFor: (n) => {
      state.drawers.ledger = state.drawers.ledger || new Set();
      setView("ledger");
    },
    footer: (text) => {
      state.footerOverride = text;
      renderFooter();
    },
    rerender: renderStage,
  };
  if (state.view === "map") renderMap(stage, state, stageActions);
  else if (state.view === "curves") renderCurves(stage, state, stageActions);
  else if (PANELS[state.view]) PANELS[state.view](stage, ctx);
  stage.scrollTop = scroll;
  renderGameOver(stage);
}

function renderGameOver(stage) {
  const s = state.snapshot;
  const me = s.nations.find((n) => n.id === s.player_nation);
  if (!s.game_over && !(me && me.ended)) return;
  const key = JSON.stringify([s.game_over, me && me.ended]);
  if (state.gameOverDismissed === key) return;
  const over = el("div", { id: "gameover", class: "open" });
  if (s.game_over) {
    over.append(el("h1", { text: "Hegemony" }));
    const a = s.game_over.winner_per_head, b = s.game_over.winner_labour_output;
    const perHead = a && s.curves.series.produce_per_head && s.curves.series.produce_per_head[a];
    over.append(el("div", { class: "winner" }, el("span", { text: nameOf.nation(a) }), " ", el("span", { class: "n", text: `produce per head ${perHead ? formatBasket(perHead[perHead.length - 1]) : ""}` })));
    over.append(el("div", { class: "winner" }, el("span", { text: nameOf.nation(b) }), " ", el("span", { class: "n", text: "labour output" })));
  } else {
    over.append(el("h1", { text: `${me.name || nameOf.nation(me.id)} has ended` }));
  }
  const kv = el("div", { class: "kv", style: { maxWidth: "420px", marginTop: "14px" } });
  for (const h of s.header.headline) {
    kv.append(el("span", { class: "k", text: h.label }), el("span", { class: "v tabular", text: format(h.value, h.key === "labour_share" ? "share" : "basket") }));
  }
  over.append(kv);
  const keep = el("button", { class: "primary", style: { marginTop: "18px" }, text: "Keep playing" });
  keep.addEventListener("click", () => {
    state.gameOverDismissed = key;
    over.remove();
  });
  over.append(keep);
  stage.append(over);
}

function selectNode(n) {
  state.selected = { id: n.id, nation: n.nation };
  renderHere();
  renderFooter();
}

// ---------- now column ----------

function renderNow() {
  const s = state.snapshot;
  const now = s.now;
  const countdownSection = $("#countdown-section");
  if (now.countdown !== null && now.countdown !== undefined) {
    countdownSection.style.display = "block";
    $("#countdown").innerHTML = "";
    $("#countdown").append(el("span", { class: "serif", text: "Hegemony countdown " }), el("span", { class: "tabular warn", text: `${now.countdown}y` }));
    tip($("#countdown"), H("panel", "countdown"));
  } else {
    countdownSection.style.display = "none";
  }
  tip($("#warning-section-h"), H("panel", "warning_band"));
  tip($("#queued-section-h"), H("panel", "queued"));
  $("#warning-fill").style.width = Math.round(now.warning_fill * 100) + "%";
  $("#warning-fill").style.background = now.regression_warning ? "var(--down)" : "var(--warn)";
  $("#warning-text").textContent = now.regression_warning ? "regression" : now.warning_fill > 0 ? format(now.warning_fill, "share") : "";

  renderHere();

  const queued = $("#queued");
  queued.innerHTML = "";
  $("#queued-count").textContent = now.queued.length ? String(now.queued.length) : "";
  if (!now.queued.length) queued.append(el("div", { class: "muted small", text: "Nothing queued." }));
  for (const q of now.queued) {
    const chip = el("div", { class: "chip" });
    const label = el("span", { class: "l" });
    label.append(document.createTextNode(q.label));
    label.append(el("span", { class: "sub tabular", text: `${q.cost > 0 ? "−" + formatBasket(q.cost) + " · " : ""}applies ${formatYear(q.applies_year)}` }));
    const x = el("button", { text: "✕", title: "Withdraw before the boundary" });
    x.addEventListener("click", async () => {
      await postJSON(`/action/${q.id}/withdraw`, {});
      fetchState();
    });
    chip.append(label, x);
    queued.append(chip);
  }

  const events = $("#events");
  events.innerHTML = "";
  for (const e of [...now.events].reverse()) {
    const card = el("div", { class: `event-card ${e.location ? "link" : ""}` });
    card.append(el("span", { class: "event-dot", style: { background: e.nation_color } }));
    const body = el("span");
    body.append(el("span", { class: "event-year tabular", text: formatYear(e.year) }));
    body.append(document.createTextNode(e.text));
    if (e.nation !== s.player_nation) body.append(" ", el("span", { class: "event-nation", text: e.nation_name || nameOf.nation(e.nation) }));
    card.append(body);
    if (e.location) {
      card.title = nameOf.location(e.location);
      card.addEventListener("click", () => {
        const node = s.map.nodes.find((n) => n.id === e.location);
        if (node) {
          selectNode(node);
          setView("map");
        }
      });
    }
    events.append(card);
  }

}

// The "here" card: what the selection (or, for a band, its own ground) can do now.
function renderHere() {
  const s = state.snapshot;
  const here = $("#here");
  here.innerHTML = "";
  const band = s.map.band_mode;
  const byId = Object.fromEntries(s.map.nodes.map((n) => [n.id, n]));
  const home = s.player && s.player.home ? byId[s.player.home] : null;
  const sel = state.selected ? byId[state.selected.id] : null;

  if (band && home) {
    const head = el("div", { class: "section-h" });
    head.append(el("span", { class: "serif", style: { fontSize: "13px", color: "var(--ink)" }, text: `${s.player.name} · band at ${home.name}` }));
    head.append(el("span", { class: "spacer" }));
    head.append(el("span", { class: "tabular", text: `consensus ${formatBasket(s.panels.politics.A_S)}` }));
    here.append(head);
    // move-or-stay comparison: own ground vs every neighbouring ground
    const grid = el("div", { class: "ground" });
    grid.append(
      el("span", { class: "h", text: "ground" }),
      tip(el("span", { class: "h", text: "game+grazing" }), H("panel", "ground")),
      el("span", { class: "h", text: "held by" })
    );
    const rows = [home, ...s.map.nodes.filter((n) => n.adjacent_to_player)].sort((a, b) => b.ground_quality - a.ground_quality);
    for (const n of rows) {
      const me = n.id === home.id;
      grid.append(el("span", { class: me ? "me" : "", text: (me ? "stay · " : "") + n.name }));
      grid.append(el("span", { class: `tabular right ${me ? "me" : ""}`, text: formatBasket(n.ground_quality) }));
      grid.append(el("span", { class: "muted small right", text: n.nation ? n.nation_name : "—" }));
    }
    here.append(grid);
    const offers = el("div", { class: "offers" });
    const bandOffers = s.actions.filter((o) => o.group === "band");
    if (!bandOffers.length) offers.append(el("div", { class: "muted small", text: "Nothing to do here." }));
    for (const o of bandOffers) offers.append(actionButton(o, draft));
    here.append(offers);
    return;
  }

  if (!sel) {
    here.append(el("div", { class: "section-h" }, el("span", { text: "Selected territory" })));
    here.append(el("div", { class: "muted small", text: "Click a territory on the map." }));
    return;
  }
  const head = el("div", { class: "section-h" });
  head.append(el("span", { class: "serif", style: { fontSize: "13px", color: "var(--ink)" }, text: sel.name }));
  head.append(el("span", { class: "spacer" }));
  head.append(el("span", { class: "small", text: sel.nation_name || "unclaimed" }));
  here.append(head);
  const kv = el("div", { class: "kv", style: { marginBottom: "6px" } });
  kv.append(el("span", { class: "k", text: "Population" }), el("span", { class: "v tabular", text: formatBasket(sel.population) }));
  kv.append(el("span", { class: "k", text: "Terrain" }), el("span", { class: "v", text: L("terrain", sel.terrain) }));
  if (sel.resources.length) kv.append(el("span", { class: "k", text: "Resources" }), el("span", { class: "v", text: sel.resources.map((r) => L("resource", r)).join(", ") }));
  here.append(kv);
  const offers = el("div", { class: "offers" });
  const local = s.actions.filter((o) => o.location === sel.id);
  if (!local.length) offers.append(el("div", { class: "muted small", text: "No action targets this territory." }));
  for (const o of local) {
    if (o.kind === "PRICE_CONTROL") {
      offers.append(actionButton(o, draft, { label: `Cap provisions at ${formatBasket(o.payload.price)}` }));
    } else offers.append(actionButton(o, draft));
  }
  here.append(offers);
}

function renderFooter() {
  const sel = $("#selection");
  sel.innerHTML = "";
  if (state.footerOverride) {
    sel.textContent = state.footerOverride;
    return;
  }
  if (!state.selected || !state.snapshot) {
    sel.textContent = "No selection";
    return;
  }
  const n = state.snapshot.map.nodes.find((x) => x.id === state.selected.id);
  if (!n) {
    sel.textContent = "No selection";
    return;
  }
  sel.append(el("span", { class: "name", text: n.name }));
  const parts = [n.nation_name || "unclaimed", `population ${formatBasket(n.population)}`, L("terrain", n.terrain)];
  if (n.records.length) parts.push(n.records.map((r) => `${L("class", r.cls)} ${formatBasket(r.size)}`).join(", "));
  sel.append(el("span", { class: "tabular", text: parts.join(" · ") }));
}

// ---------- render ----------

function render() {
  if (!state.snapshot) return;
  const seat = state.snapshot.player ? state.snapshot.player.seat : null;
  if (state.lastSeat !== null && state.lastSeat !== seat && !unlockedViews().has(state.view)) state.view = "map";
  state.lastSeat = seat;
  renderHeader();
  renderRail();
  renderStage();
  renderNow();
  renderFooter();
}

// ---------- tooltips ----------
// One floating box for every `data-tip` (ui.js `tip()`): shown after a short hover,
// at once on keyboard focus, hidden on leave, blur, scroll and Escape.

const tipBox = el("div", { id: "tooltip", role: "tooltip" });
document.body.append(tipBox);
let tipTarget = null;
let tipTimer = null;

function showTip(target) {
  const text = target.dataset.tip;
  if (!text) return;
  tipBox.textContent = text;
  tipBox.classList.add("open");
  const r = target.getBoundingClientRect();
  const box = tipBox.getBoundingClientRect();
  const margin = 8;
  let left = Math.min(Math.max(margin, r.left), window.innerWidth - box.width - margin);
  let top = r.bottom + 6;
  if (top + box.height > window.innerHeight - margin) top = Math.max(margin, r.top - box.height - 6);
  tipBox.style.left = `${Math.round(left)}px`;
  tipBox.style.top = `${Math.round(top)}px`;
}

function hideTip() {
  clearTimeout(tipTimer);
  tipTimer = null;
  tipTarget = null;
  tipBox.classList.remove("open");
}

document.addEventListener("mouseover", (ev) => {
  const t = ev.target.closest ? ev.target.closest("[data-tip]") : null;
  if (t === tipTarget) return;
  hideTip();
  if (!t) return;
  tipTarget = t;
  tipTimer = setTimeout(() => showTip(t), 350);
});
document.addEventListener("mouseout", (ev) => {
  if (tipTarget && !tipTarget.contains(ev.relatedTarget)) hideTip();
});
document.addEventListener("focusin", (ev) => {
  const t = ev.target.closest ? ev.target.closest("[data-tip]") : null;
  hideTip();
  if (t) {
    tipTarget = t;
    showTip(t);
  }
});
document.addEventListener("focusout", () => hideTip());
document.addEventListener("scroll", () => hideTip(), true);
document.addEventListener("mousedown", () => hideTip());

// ---------- controls ----------

$("#turn").addEventListener("click", endTurn);
$("#new-world").addEventListener("click", (ev) => {
  ev.stopPropagation();
  showNewWorld(ev.currentTarget);
});

document.addEventListener("focusout", () => {
  if (state.stageDirty) setTimeout(() => !stageHasFocus() && renderStage(), 50);
});

document.addEventListener("click", (ev) => {
  const box = $("#confirm");
  if (box.classList.contains("open") && !box.contains(ev.target)) box.classList.remove("open");
});

document.addEventListener("keydown", (ev) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName)) return;
  if (ev.key === "Escape") {
    hideTip();
    $("#confirm").classList.remove("open");
    return;
  }
  if (ev.code === "Space" || (ev.key === "Enter" && !$("#confirm").classList.contains("open"))) {
    ev.preventDefault();
    endTurn();
  } else if (ev.key === "Tab") {
    ev.preventDefault();
    cycleView(ev.shiftKey ? -1 : 1);
  } else {
    const r = RAIL.find((x) => x.key.toLowerCase() === ev.key.toLowerCase());
    if (r && !ev.ctrlKey && !ev.metaKey && !ev.altKey) setView(r.id);
  }
});

const savedTheme = localStorage.getItem("stock.theme");
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
function isDark() {
  const t = document.documentElement.dataset.theme;
  if (t) return t === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}
$("#theme-toggle").textContent = isDark() ? "Day" : "Night";
$("#theme-toggle").addEventListener("click", () => {
  const dark = isDark();
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  localStorage.setItem("stock.theme", document.documentElement.dataset.theme);
  $("#theme-toggle").textContent = dark ? "Night" : "Day";
  render();
});

const savedDensity = localStorage.getItem("stock.density") || "comfortable";
document.documentElement.dataset.density = savedDensity;
$("#density-toggle").textContent = savedDensity === "compact" ? "Comfortable" : "Compact";
$("#density-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.density === "compact" ? "comfortable" : "compact";
  document.documentElement.dataset.density = next;
  localStorage.setItem("stock.density", next);
  $("#density-toggle").textContent = next === "compact" ? "Comfortable" : "Compact";
});

fetchState().then(connectWS);
fetchWorld();
