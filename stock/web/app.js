// Stock — the client. It draws the snapshot and sends actions; it computes nothing
// the engine owns (design doc §19).
"use strict";

let S = null;            // the current snapshot
let sel = null;          // {type: "unit"|"node", id}
let overlay = "political";
let screen = null;
let seenLog = 0;         // log length already shown as moments
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 1) => (x == null ? "–" : Math.abs(x) >= 1000 ? Math.round(x).toLocaleString() : (+x).toFixed(d).replace(/\.0+$/, ""));
const sgn = (x, d = 1) => (x > 0 ? "▲ +" : x < 0 ? "▼ " : "") + fmt(x, d);
const cls = (x) => (x > 0.005 ? "up" : x < -0.005 ? "down" : "muted");
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const TERRAIN_FILL = { FOREST: "#6f8f5f", GRASSLAND: "#c2bb7c", VALLEY: "#94b87e", HILLS: "#a99a79",
  COAST: "#9dbac6", MARSH: "#7f9a8f", MOUNTAIN: "#8a8480" };
const FEATURE = { wild_herds: "wild herds", rare: "a rare resource", ore: "ore", coal: "coal" };
const ORDER_COLOUR = { labour: "#8a6d3b", proprietors: "#7a5b8c", stock: "#3b5b8c" };
const SOURCE_COLOUR = { hunting: "#6f8f5f", pasturage: "#c2bb7c", agriculture: "#94b87e", commerce: "#3b5b8c" };
const SEAT = { council: "Council", chiefdom: "Chiefdom", civil: "Civil Government", interregnum: "Interregnum" };

// --- server ------------------------------------------------------------------------

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { const t = await r.json().catch(() => ({})); toast(t.detail || `Error ${r.status}`); return null; }
  return r.json();
}
async function act(action) {
  const res = await api("/action", action);
  if (!res) return false;
  if (!res.ok) { toast(res.why); return false; }
  update(res.state);
  return true;
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 2600);
}

// --- tooltips ----------------------------------------------------------------------

document.addEventListener("mouseover", (e) => {
  const el = e.target.closest("[data-tip]");
  const tip = $("tip");
  if (!el) { tip.hidden = true; return; }
  tip.textContent = el.dataset.tip; tip.hidden = false;
});
document.addEventListener("mousemove", (e) => {
  const tip = $("tip");
  if (tip.hidden) return;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 330) + "px";
  tip.style.top = Math.min(e.clientY + 14, innerHeight - 120) + "px";
});
const tipOf = (obj) => Object.entries(obj || {}).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "number" ? sgnPlain(v) : v}`).join("\n");
const sgnPlain = (v) => (v > 0 ? "+" : "") + fmt(v, 2);

// --- top bar ------------------------------------------------------------------------

function renderTop() {
  const me = S.me;
  const modeIdx = ["hunting", "pasturage", "agriculture", "commerce"].indexOf(me.mode);
  const chall = me.mode_challenger ? `${me.mode_challenger} leads ${me.mode_streak}/3 turns` : SEAT[me.seat];
  $("mode-banner").innerHTML = `Age of ${esc(S.modes[modeIdx])}<span class="sub">${esc(chall)}</span>`;
  const wars = me.war.wars;
  $("war-badge").hidden = !wars.length;
  $("war-badge").innerHTML = wars.length ? `⚔ At war<span class="sub">${wars.map((w) => esc(nationName(w.with))).join(", ")}</span>` : "";
  $("war-badge").dataset.tip = armyTip(me);
  $("year").textContent = S.year < 0 ? `${-S.year} BC` : `AD ${S.year}`;
  $("turn").textContent = `Turn ${S.turn} of ${S.last_turn} · ${me.name}`;
  const b = me.breakdowns || {};
  const res = [
    ["Food", me.food, me.food_income, `Stored food, and this turn's surplus.\n${tipOf(b.food && b.food.by_source)}\nmade ${fmt(b.food?.made)} · eaten ${fmt(b.food?.eaten)}`],
    ["Stock", me.stock, me.stock_income, `Productive capital. Savings become stock in proportion to Security (${pct(me.security)}); the rest is hoarded.\n${tipOf(b.stock)}`],
    ["Treasury", me.treasury, me.treasury_income, me.seat === "civil" ? `Public revenue less spending.\n${tipOf(b.treasury && b.treasury.spent)}` : "No treasury before Civil Government."],
    ["Sway", me.sway, me.sway_income, `Your political currency. ${SEAT[me.seat]}: ${me.seat === "council" ? "Consensus" : me.seat === "chiefdom" ? "Prestige" : "Authority"}.\n${tipOf(b.sway)}`],
    ["Ingenuity", me.ingenuity, null, `Research per turn.\n${tipOf(b.ingenuity)}`],
    ["Extent", me.extent, null, `Extent of the market: hands in your largest connected market plus towns and routes. Division of labour ×${fmt(me.dol, 2)}.`],
    ["Hands", me.hands, null, `Your people, in hands. Herds ${fmt(me.herds, 0)}. Retainers ${fmt(me.retainers)}.`],
    ["Army", me.war.strength, null, armyTip(me)],
  ];
  $("resources").innerHTML = res.map(([k, v, d, tip]) => `<div class="res" data-tip="${esc(tip)}"><span class="k">${k}</span><span class="v">${fmt(v)}</span>${d == null ? "" : `<span class="d ${cls(d)}">${sgn(d)}</span>`}</div>`).join("");
  const mine = S.nations.find((n) => n.id === me.id);
  const leader = S.nations.filter((n) => n.met && n.alive).sort((a, b) => b.share - a.share)[0];
  const h = S.hegemony;
  const cd = S.winner ? `<span class="warn">${esc(S.winner.text)}</span>`
    : h.leader ? `<span class="warn">${esc(nationName(h.leader))} ascendant: ${h.countdown} turns to hegemony</span>` : "";
  const orbitNote = me.orbit_of ? ` · <span class="warn">in ${esc(nationName(me.orbit_of))}'s orbit</span>` : "";
  $("hegemony").innerHTML = `Produce ${pct(mine.share)} of 40% · orbit ${me.sphere.length}/${me.sphere_need}${orbitNote}<div class="bar"><i style="width:${pct(mine.share)}"></i><b style="left:40%"></b></div>${cd}`;
  const held = Object.entries(me.levers_on_us || {}).map(([a, l]) => `${nationName(a)} ${l.detail} (${l.kind})`).join("\n");
  $("hegemony").dataset.tip = `Hegemony: 40% of the world's produce and half the other peoples in your orbit (${me.sphere_need}), held for 10 turns, from turn 50. The others will combine against whoever gets there. Otherwise, at turn 150 the most opulent people wins, if it is in no one's orbit.\nIn our orbit: ${me.sphere.map(nationName).join(", ") || "nobody"}.${held ? `\nLevers over us:\n${held}` : ""}`;

}

function armyTip(me) {
  const lines = [`Strength of your armies: ${fmt(me.war.strength)}.`];
  if (me.war.wars.length) {
    lines.push("At war with " + me.war.wars.map((w) => `${S.nations.find((x) => x.id === w.with)?.name} (score ${w.score > 0 ? "+" : ""}${w.score})`).join(", "));
  } else lines.push("At peace.");
  lines.push(`War weariness ${fmt(me.war.weariness)} (adds to unrest).`);
  if (me.war.tributes.length) lines.push("We pay tribute: " + me.war.tributes.map((t) => `${t.turns} turns`).join(", "));
  if (me.war.tribute_in.length) lines.push("Tribute paid to us: " + me.war.tribute_in.map((t) => `${S.nations.find((x) => x.id === t.from)?.name}, ${t.turns} turns`).join(", "));
  return lines.join("\n");
}

// --- society: orders and the annual produce --------------------------------------------

function stack(parts, colours, total) {
  return `<div class="stack">${Object.entries(parts).filter(([, v]) => v > 0).map(([k, v]) => `<span style="width:${(100 * v) / total}%;background:${colours[k] || "var(--ink-2)"}" data-tip="${esc(k)}: ${fmt(v)} (${pct(v / total)})"></span>`).join("")}</div>`;
}
function renderSociety() {
  const me = S.me;
  let h = `<h3>Orders of society</h3>`;
  for (const [k, o] of Object.entries(me.orders)) {
    if (o.size <= 0 && k !== "labour") { h += `<div class="order muted small">${o.name}: none yet</div>`; continue; }
    const sat = o.satisfaction;
    h += `<div class="order" data-tip="${esc(`${o.name}: ${fmt(o.size)} hands.\nIncome ${fmt(o.income)} (${pct(o.share)} of produce).\nFood ${pct(sat.food)} · comforts ${pct(sat.comfort)} · standing ${pct(sat.standing)} of what they expect.\nClout is political weight: wealth, and numbers times organisation.`)}">
      <div class="row"><b style="color:${ORDER_COLOUR[k]}">${o.name}</b><span>${fmt(o.size)} hands</span></div>
      <div class="row small"><span>share ${pct(o.share)}</span><span>clout ${pct(o.clout)}</span></div>
      <div class="meter" data-tip="Contentment ${o.contentment}"><i style="width:${o.contentment}%;background:${o.contentment < 35 ? "var(--down)" : o.contentment > 60 ? "var(--up)" : "var(--ink-2)"}"></i></div>
      <div class="small muted">content ${o.contentment}</div></div>`;
  }
  const total = me.produce || 1;
  h += `<h3 data-tip="Where this turn's produce came from, who received it, and what became of it.">The annual produce · ${fmt(me.produce)}</h3>`;
  h += `<div class="flow"><div class="lbl">Sources</div>${stack(me.sources, SOURCE_COLOUR, total)}</div>`;
  h += `<div class="flow"><div class="lbl">Distribution — wages · profit · rent</div>${stack(me.split, { wages: ORDER_COLOUR.labour, profit: ORDER_COLOUR.stock, rent: ORDER_COLOUR.proprietors }, total)}</div>`;
  if (me.uses && me.uses.consumed) {
    const p = me.prices;
    const uses = { food: me.uses.consumed.food * p.food, wares: me.uses.consumed.wares * p.wares, luxuries: me.uses.consumed.luxuries * p.luxuries, saved: me.uses.saved, taxes: me.uses.taxes };
    const ut = Object.values(uses).reduce((a, b) => a + b, 0) || 1;
    h += `<div class="flow"><div class="lbl">Uses</div>${stack(uses, { food: "#94b87e", wares: "#3b4a8a", luxuries: "#8a3b4a", saved: "#8c7a3b", taxes: "#5a5a5a" }, ut)}</div>`;
  }
  h += `<div class="small muted" data-tip="Market prices in baskets (one person's food for a turn).">Prices: food ${fmt(me.prices.food, 2)} · wares ${fmt(me.prices.wares, 2)} · luxuries ${fmt(me.prices.luxuries, 2)}</div>`;
  h += `<div class="small muted">Wage ${fmt(me.wage, 2)} · bargaining ${fmt(me.bargaining, 2)} · per head ${fmt(me.per_head, 2)}</div>`;
  const feastTip = me.feast ? `Feast: ${me.feast}` : `Spend ${fmt(me.feast_cost, 0)} stored food on a feast: Sway +5, everyone's contentment +5, and a burst of births (+6% people next turn). The feast costs more the more people we have.`;
  h += `<div class="verbs"><button ${me.feast ? "disabled" : ""} data-tip="${esc(feastTip)}" onclick="act({kind:'feast'})">Feast</button>`;
  if (me.seat === "chiefdom") h += `<button ${me.found_government ? "disabled" : ""} data-tip="${esc(me.found_government || "Found a civil government: a treasury, taxes and courts. 20 Sway.")}" onclick="act({kind:'found_government'})">Found government</button>`;
  if (me.seat === "interregnum") h += `<button ${me.restore ? "disabled" : ""} data-tip="${esc(me.restore || "Restore the government: 30 Sway.")}" onclick="act({kind:'restore'})">Restore</button>`;
  h += `</div>`;
  $("society").innerHTML = h;
}

// --- the map ------------------------------------------------------------------------------

const nodeById = () => Object.fromEntries(S.nodes.map((n) => [n.id, n]));
const nationById = () => Object.fromEntries(S.nations.map((n) => [n.id, n]));
const radius = (n) => 9 + Math.sqrt(n.hands || 0) * 1.8;

function renderMap() {
  const nodes = nodeById(), nations = nationById();
  const svg = [];
  for (const e of S.edges) {
    const a = nodes[e.a], b = nodes[e.b];
    if (e.kind === "sea") {
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 18;
      svg.push(`<path class="edge-sea" fill="none" d="M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}"/>`);
    } else svg.push(`<line class="edge-${e.kind}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`);
  }
  for (const r of S.routes) {
    const a = nodes[r.a_node], b = nodes[r.b_node];
    if (!a || !b) continue;
    const tip = `${routeName(r)}\n${flowText(r)}`;
    svg.push(`<line class="route route-${r.kind} ${r.active ? "" : "blocked"} ${r.mine ? "mine" : ""}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" data-tip="${esc(tip)}"/>`);
  }
  const selUnit = sel && sel.type === "unit" ? S.units.find((u) => u.id === sel.id) : null;
  const reach = new Set(selUnit && selUnit.moves ? selUnit.moves.filter((m) => m.ok && m.attack == null).map((m) => m.to) : []);
  const supplied = overlay === "supply" ? supplyReach() : new Set();
  const strike = Object.fromEntries(selUnit && selUnit.moves ? selUnit.moves.filter((m) => m.ok && m.attack != null).map((m) => [m.to, m.attack]) : []);
  for (const n of S.nodes) {
    const r = radius(n);
    let fill = TERRAIN_FILL[n.terrain];
    let stroke = "var(--rule)", sw = 1;
    if (overlay === "political" && n.owner) { stroke = nations[n.owner]?.colour || "var(--ink)"; sw = 4; }
    if (overlay === "unrest" && n.visible && n.owner) fill = n.unrest > 70 ? "#c0503e" : n.unrest > 40 ? "#e0b04e" : "#94b87e";
    if (overlay === "produce" && n.visible && n.owner) {
      const v = n.produce != null ? n.produce : n.hands;  // our towns by produce; others by people
      const max = Math.max(...S.nodes.map((x) => (x.produce != null ? x.produce : x.hands || 0)), 1);
      const t = Math.min(1, v / max);
      fill = `rgb(${Math.round(240 - 150 * t)}, ${Math.round(220 - 60 * t)}, ${Math.round(150 - 90 * t)})`;
    }
    if (overlay === "supply") fill = supplied.has(n.id) ? "#94b87e" : n.visible ? "#c0503e" : fill;
    if (overlay === "orbits" && n.visible && n.owner) {
      const centre = nations[n.owner]?.orbit_of;
      fill = centre ? nations[centre]?.colour || fill : nations[n.owner]?.colour || fill;
      stroke = nations[n.owner]?.colour || stroke; sw = 4;
    }
    const feats = (n.features || []).filter((f) => f !== "wild_herds").map((f) => ({ rare: "✦", ore: "▲", coal: "■" }[f])).join("");
    const herdMark = (n.features || []).includes("wild_herds")
      ? `<text class="herd-mark" x="${n.x}" y="${n.y - r - (feats ? 13 : 3)}" text-anchor="middle">wild herds</text>` : "";
    const works = n.works ? n.works.length : 0;
    svg.push(`<g class="node ${n.visible ? "" : "fog"}" data-node="${n.id}" data-tip="${esc(nodeTip(n))}">
      <circle class="body" cx="${n.x}" cy="${n.y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>
      ${n.owner && works ? `<text class="node-sub" x="${n.x}" y="${n.y + 3}" text-anchor="middle">${works}⌂</text>` : ""}
      <text class="node-label" x="${n.x}" y="${n.y + r + 11}" text-anchor="middle">${esc(n.name)}</text>
      ${feats ? `<text class="node-sub" x="${n.x}" y="${n.y - r - 3}" text-anchor="middle">${feats}</text>` : ""}${herdMark}
    </g>`);
    if (reach.has(n.id)) svg.push(`<circle class="reach" cx="${n.x}" cy="${n.y}" r="${r + 6}"/>`);
    if (strike[n.id] != null) svg.push(`<circle class="strike" cx="${n.x}" cy="${n.y}" r="${r + 6}"/><text class="odds" x="${n.x}" y="${n.y - r - 12}" text-anchor="middle">${pct(strike[n.id])}</text>`);
    if (n.enemy) svg.push(`<circle class="enemy-ring" cx="${n.x}" cy="${n.y}" r="${r + 3}"/>`);
    if (n.conquered > 0 && n.visible) svg.push(`<text class="taken-mark" x="${n.x}" y="${n.y + r + 22}" text-anchor="middle">⚑ taken</text>`);
    if (n.siege) svg.push(`<circle class="siege-ring" cx="${n.x}" cy="${n.y}" r="${r + 9}"><title>Besieged: ${n.siege.turns} turns left</title></circle>`);
    if (n.forts) svg.push(`<text class="node-sub" x="${n.x + r + 2}" y="${n.y + 3}">${"▣".repeat(n.forts)}</text>`);
    if (sel && sel.type === "node" && sel.id === n.id) svg.push(`<circle class="selected-ring" cx="${n.x}" cy="${n.y}" r="${r + 5}"/>`);
  }
  // units: fanned out around their node
  const byNode = {};
  for (const u of S.units) (byNode[u.node] ||= []).push(u);
  for (const [nid, us] of Object.entries(byNode)) {
    const n = nodes[nid]; if (!n) continue;
    us.forEach((u, i) => {
      const ang = -Math.PI / 2 + (i - (us.length - 1) / 2) * 0.7;
      const x = n.x + Math.cos(ang) * (radius(n) + 12), y = n.y + Math.sin(ang) * (radius(n) + 12) + 4;
      const col = u.rebel ? "#222" : nations[u.nation]?.colour || "#555";
      const isSel = selUnit && selUnit.id === u.id;
      const edge = isSel ? "var(--warn)" : u.hostile ? "var(--down)" : "var(--paper)";
      const sw = isSel || u.hostile ? 3 : 1.5;
      const shape = u.military
        ? `<path d="M${x - 9},${y - 9} L${x + 9},${y - 9} L${x + 9},${y + 2} Q${x},${y + 12} ${x - 9},${y + 2} Z" fill="${col}" stroke="${edge}" stroke-width="${sw}"/>`
        : u.kind === "horde"
          ? `<circle cx="${x}" cy="${y}" r="9" fill="${col}" stroke="${edge}" stroke-width="${sw}"/>`
          : `<path d="M${x},${y - 10} L${x + 10},${y + 7} L${x - 10},${y + 7} Z" fill="${col}" stroke="${edge}" stroke-width="${sw}"/>`;
      const who = u.rebel ? "Rebels" : u.nation === S.me.id ? "Your" : esc(nations[u.nation]?.name) + "'s";
      const tip = `${who} ${u.name}: ${fmt(u.hands)} hands${u.herds ? `, ${fmt(u.herds, 0)} head of herds` : ""}\nStrength ${fmt(u.strength)}${u.military ? ` · cohesion ${u.cohesion}` : ""}${u.hostile ? "\nAt war with you" : ""}${u.moves_left != null ? `\nMoves ${u.moves_left}/${u.max_moves}` : ""}`;
      const label = u.military ? Math.round(u.strength) : Math.round(u.hands);
      svg.push(`<g class="unit" data-unit="${u.id}" data-tip="${esc(tip)}">${shape}<text x="${x}" y="${y + (u.military ? 1 : u.kind === "horde" ? 3 : 4)}" text-anchor="middle">${label}</text></g>`);
    });
  }
  $("map").innerHTML = svg.join("");
  fitMap();
}

// the view frames what has been explored, never less than a region's worth
function fitMap() {
  const xs = S.nodes.map((n) => n.x), ys = S.nodes.map((n) => n.y);
  let x0 = Math.min(...xs) - 60, x1 = Math.max(...xs) + 60, y0 = Math.min(...ys) - 60, y1 = Math.max(...ys) + 60;
  const minW = 420, minH = 260;
  if (x1 - x0 < minW) { const c = (x0 + x1) / 2; x0 = c - minW / 2; x1 = c + minW / 2; }
  if (y1 - y0 < minH) { const c = (y0 + y1) / 2; y0 = c - minH / 2; y1 = c + minH / 2; }
  fitBox = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  const v = view || fitBox;
  $("map").setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}

// zoom and pan: the wheel zooms about the pointer, dragging pans, ⤢ goes back to the whole map
let view = null, fitBox = null;
function setView(v) {
  const minW = fitBox.w / 8, maxW = fitBox.w * 1.5;
  const k = Math.min(Math.max(v.w, minW), maxW) / v.w;
  const cx = v.x + v.w / 2, cy = v.y + v.h / 2;
  view = { w: v.w * k, h: v.h * k, x: cx - (v.w * k) / 2, y: cy - (v.h * k) / 2 };
  $("map").setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
}
function zoomBy(f, px, py) {
  const v = view || fitBox;
  if (px == null) { px = v.x + v.w / 2; py = v.y + v.h / 2; }
  setView({ x: px - (px - v.x) * f, y: py - (py - v.y) * f, w: v.w * f, h: v.h * f });
}
function zoomTo(x, y, k) {
  const w = fitBox.w / k, h = fitBox.h / k;
  setView({ x: x - w / 2, y: y - h / 2, w, h });
}
function svgPoint(e) {
  const p = new DOMPoint(e.clientX, e.clientY).matrixTransform($("map").getScreenCTM().inverse());
  return [p.x, p.y];
}
$("map").addEventListener("wheel", (e) => {
  e.preventDefault();
  const [x, y] = svgPoint(e);
  zoomBy(e.deltaY > 0 ? 1.15 : 1 / 1.15, x, y);
}, { passive: false });
let drag = null;
$("map").addEventListener("pointerdown", (e) => { if (e.button === 0) drag = { x: e.clientX, y: e.clientY, moved: false, v: { ...(view || fitBox) } }; });
window.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!drag.moved && Math.hypot(dx, dy) < 5) return;
  drag.moved = true;
  $("map").classList.add("panning");
  const ctm = $("map").getScreenCTM();
  view = { ...drag.v, x: drag.v.x - dx / ctm.a, y: drag.v.y - dy / ctm.d };
  $("map").setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
});
window.addEventListener("pointerup", () => {
  if (drag && drag.moved) {  // a drag is not a click
    $("map").addEventListener("click", (e) => e.stopImmediatePropagation(), { capture: true, once: true });
  }
  drag = null;
  $("map").classList.remove("panning");
});
$("zoom-in").addEventListener("click", () => zoomBy(1 / 1.4));
$("zoom-out").addEventListener("click", () => zoomBy(1.4));
$("zoom-fit").addEventListener("click", () => { view = null; fitMap(); });

function groundText(n) {  // "River valley", not "River valley · river"
  const t = n.terrain_name.toLowerCase();
  return n.terrain_name + (n.river && !t.includes("river") ? " · river" : "") + (n.coast && !t.includes("coast") ? " · coast" : "");
}
function nodeTip(n) {
  const lines = [`${n.name} — ${n.terrain_name}${n.river ? ", on a river" : ""}${n.coast ? ", coast" : ""}`];
  const y = n.yields;
  lines.push(`game ${fmt(y.game, 1)} · grazing ${fmt(y.grazing, 1)} · arable ${fmt(y.arable, 2)}${y.fish ? ` · fish ${y.fish}` : ""}`);
  if (n.features.length) lines.push("Has " + n.features.map((f) => FEATURE[f]).join(", "));
  if (n.visible) {
    if (n.owner) lines.push(`Settled by ${S.nations.find((x) => x.id === n.owner)?.name}: ${fmt(n.hands)} hands`);
    if (n.game != null) lines.push(`Game left ${pct(n.game)}`);
    if (n.works && n.works.length) lines.push("Works: " + n.works.join(", "));
    if (n.herds) lines.push(`Herds ${fmt(n.herds, 0)}`);
  } else lines.push("(last seen)");
  return lines.join("\n");
}

$("map").addEventListener("click", (e) => {
  const u = e.target.closest("[data-unit]");
  const nd = e.target.closest("[data-node]");
  if (u) {
    const unit = S.units.find((x) => x.id === u.dataset.unit);
    if (unit && unit.nation === S.me.id) { sel = { type: "unit", id: unit.id }; renderAll(); return; }
  }
  if (nd) {
    const id = nd.dataset.node;
    const selUnit = sel && sel.type === "unit" ? S.units.find((x) => x.id === sel.id) : null;
    if (selUnit && selUnit.moves && selUnit.moves.some((m) => m.to === id)) {
      const m = selUnit.moves.find((m) => m.to === id);
      if (!m.ok) { toast(m.why); return; }
      if (m.attack != null && !confirm(`Attack ${nodeById()[id].name}? You can expect ${pct(m.attack)} of the field (luck ±15%).`)) return;
      act({ kind: "move", unit: selUnit.id, to: id }).then(() => { sel = { type: "unit", id: selUnit.id }; renderAll(); });
      return;
    }
    const mine = S.units.filter((x) => x.node === id && x.nation === S.me.id);
    sel = mine.length && !(sel && sel.type === "unit" && sel.id === mine[0].id) && !nodeById()[id].owner ? { type: "unit", id: mine[0].id } : { type: "node", id };
    renderAll();
  }
});

// --- selection card --------------------------------------------------------------------------

const VERB_TIP = {
  split: "Split the band in two (costs Sway): the way a people spreads.",
  follow: "Follow the wild herds this turn: half the band hunts less, but 3 turns of following halves the cost of Taming.",
  tame: "Tame the wild herds: the band becomes a horde, moving with its herds (2 moves).",
  settle: "Settle here: the band's hands become a settlement, planting fields on arable ground.",
};
// the selection card can be folded down to its title, to see more of the map
let selMin = false;
try { selMin = localStorage.getItem("stock-sel-min") === "1"; } catch (e) { /* storage may be blocked */ }
function toggleSelection() {
  selMin = !selMin;
  try { localStorage.setItem("stock-sel-min", selMin ? "1" : "0"); } catch (e) { /* ignore */ }
  renderSelection();
}
function renderSelection() {
  renderSelectionBody();
  const box = $("selection");
  box.classList.toggle("min", !!sel && selMin);
  if (sel) box.insertAdjacentHTML("afterbegin", `<button id="sel-toggle" class="small" onclick="toggleSelection()" title="${selMin ? "Show the card (M)" : "Fold the card away (M)"}">${selMin ? "▴ Show" : "▾ Hide"}</button>`);
}
function renderSelectionBody() {
  const box = $("selection");
  if (!sel) { box.innerHTML = `<span class="muted">Select a band on the map, or a settlement. Moves: click a band, then a ringed node.</span>`; return; }
  if (sel.type === "unit") {
    const u = S.units.find((x) => x.id === sel.id);
    if (!u) { sel = null; return renderSelectionBody(); }
    const n = nodeById()[u.node];
    if (u.military) { box.innerHTML = armyCard(u, n); return; }
    if (u.kind === "caravan" || u.kind === "merchantman") { box.innerHTML = traderCard(u, n); return; }
    let h = `<h2>${u.kind === "horde" ? "Horde" : "Band"} at ${esc(n.name)}</h2>`;
    h += `<div>${fmt(u.hands)} hands${u.herds ? ` · ${fmt(u.herds, 0)} head of herds` : ""} · moves ${u.moves_left}/${u.max_moves}${u.followed ? " · following the herds" : ""}</div>`;
    h += `<div class="verbs">`;
    for (const [k, why] of Object.entries(u.verbs)) {
      const label = { split: `Split (${u.split_cost} Sway)`, follow: "Follow the herds", tame: "Tame", settle: n.owner === S.me.id ? "Join settlement" : "Settle" }[k];
      h += `<button ${why ? "disabled" : ""} data-tip="${esc(why ? `${VERB_TIP[k]}\nNot now: ${why}` : VERB_TIP[k])}" onclick="act({kind:'${k}',unit:'${u.id}'})">${label}</button>`;
    }
    for (const other of u.merge_with) h += `<button onclick="act({kind:'merge',unit:'${u.id}',other:'${other}'})">Merge</button>`;
    for (const o of u.raise_options) h += `<button ${o.why ? "disabled" : ""} data-tip="${esc(raiseTip(o.kind, o.why))}" onclick="act({kind:'raise_unit',unit:'${u.id}',unit_kind:'${o.kind}'})">Raise ${esc(o.name)}</button>`;
    h += raidButtons(u);
    h += `</div><div class="small muted">A band that does not move hunts where it stands. Move by clicking a ringed neighbour.</div>`;
    box.innerHTML = h;
    return;
  }
  const n = nodeById()[sel.id];
  if (!n) { sel = null; return renderSelectionBody(); }
  let h = `<h2>${esc(n.name)} <span class="muted small">${groundText(n)}</span></h2>`;
  h += `<div class="small">${esc(nodeTip(n)).split("\n").slice(1).join(" · ")}</div>`;
  if (n.owner === S.me.id) {
    h += `<div class="works" style="margin-top:6px">${(n.works || []).map((w) => `<span class="work">${esc(S.works.find((x) => x.key === w)?.name || w)} <button class="small" data-tip="Pull it down to free the slot. Nothing is refunded." onclick="if(confirm('Pull down this ${esc(S.works.find((x) => x.key === w)?.name || w)}?'))act({kind:'demolish',node:'${n.id}',work:'${w}'})">✕</button></span>`).join("") || '<span class="muted">No works</span>'} <span class="muted small">${n.works.length}/${n.slots} slots · ${n.jobs} jobs for ${fmt(n.hands)} hands · unrest ${n.unrest}</span></div>`;
    if (n.siege) h += `<div class="warn">Besieged by ${esc(S.nations.find((x) => x.id === n.siege.by)?.name)}: falls in ${n.siege.turns} turns unless relieved.</div>`;
    h += `<div class="verbs"><button ${n.found_band ? "disabled" : ""} data-tip="${esc(n.found_band || "Send out a new band from this settlement to explore or settle elsewhere.")}" onclick="act({kind:'found_band',node:'${n.id}'})">Found a band</button>`;
    for (const [which, why] of Object.entries(n.send_trader || {})) {
      if (why && /^(a caravan|a merchantman)/.test(why)) continue;
      const name = which === "caravan" ? "Caravan" : "Merchantman";
      h += `<button ${why ? "disabled" : ""} data-tip="${esc(`${S.unit_types[which].description}\nCosts ${S.trader_cost[which]} Stock.${why ? `\nNot now: ${why}` : ""}`)}" onclick="act({kind:'send_trader',node:'${n.id}',trader:'${which}'})">Send ${name}</button>`;
    }
    for (const o of n.raise_options) {
      if (o.why && /needs the|needs [A-Z]/.test(o.why) && o.kind !== "warband") continue;
      h += `<button ${o.why ? "disabled" : ""} data-tip="${esc(raiseTip(o.kind, o.why))}" onclick="act({kind:'raise_unit',node:'${n.id}',unit_kind:'${o.kind}'})">Raise ${esc(o.name)}</button>`;
    }
    h += `</div>`;
    h += `<div class="build">${investButtons(n)}</div>`;
  }
  if (S.me.build_queue.length) h += `<h3>Investment queue <button class="small" onclick="openScreen('settlements')">all settlements ▸</button></h3>` + queueList();
  box.innerHTML = h;
}

// --- war ----------------------------------------------------------------------------------------

function raiseTip(kind, why) {
  const o = S.unit_types[kind] || {};
  const cost = [o.hands && `${o.hands} hands`, o.herds && `${o.herds} herds`, o.wares && `${o.wares} wares`, o.treasury && `${o.treasury} Treasury`].filter(Boolean).join(", ");
  return `${o.description || ""}\nStrength ${o.strength ?? "?"}${cost ? ` · takes ${cost}` : ""}${o.upkeep ? ` · ${o.upkeep} Treasury a turn` : ""}\nSoldiers eat but do not work.${why ? `\nNot now: ${why}` : ""}`;
}
function raidButtons(u) {
  return (u.raids || []).map((r) => {
    const who = S.nations.find((x) => x.id === r.victim)?.name || "them";
    return `<button data-tip="${esc(`Raid ${nodeById()[r.to].name}: take food, herds and hoards from ${who} without holding the ground. Odds ${pct(r.odds)}. They gain a just cause for war.`)}" onclick="act({kind:'raid',unit:'${u.id}',to:'${r.to}'})">Raid ${esc(nodeById()[r.to].name)} (${pct(r.odds)})</button>`;
  }).join("");
}
function armyCard(u, n) {
  let h = `<h2>${esc(u.name)} at ${esc(n.name)}</h2>`;
  h += `<div>${fmt(u.hands)} hands · strength ${fmt(u.strength)} · moves ${u.moves_left}/${u.max_moves} · ${u.supplied ? '<span class="up">supplied</span>' : '<span class="down">out of supply: losing cohesion</span>'}</div>`;
  h += `<div class="meter" style="max-width:260px" data-tip="Cohesion ${u.cohesion}: order and morale. Falls in battle, sieges and hunger; recovers in supply. Below 20 the unit is broken."><i style="width:${u.cohesion}%;background:${u.cohesion < 35 ? "var(--down)" : "var(--ink-2)"}"></i></div>`;
  const targets = u.moves.filter((m) => m.ok && m.attack != null);
  h += `<div class="verbs">`;
  for (const m of targets) h += `<button onclick="if(confirm('Attack ${esc(nodeById()[m.to].name)}? Expect ${pct(m.attack)} of the field.'))act({kind:'move',unit:'${u.id}',to:'${m.to}'})">Attack ${esc(nodeById()[m.to].name)} (${pct(m.attack)})</button>`;
  h += raidButtons(u);
  if (u.kind === "regiment") h += `<button ${u.upgrade ? "disabled" : ""} data-tip="${esc(u.upgrade || "Arm the regiment with firearms: 20 wares, 10 Treasury.")}" onclick="act({kind:'upgrade',unit:'${u.id}'})">Firearms</button>`;
  for (const other of u.merge_with) h += `<button onclick="act({kind:'merge',unit:'${u.id}',other:'${other}'})">Merge</button>`;
  h += `<button data-tip="Send the soldiers home to work." onclick="act({kind:'disband',unit:'${u.id}'})">Disband</button></div>`;
  h += `<div class="small muted">${esc(u.description)} Red rings: enemies you can attack, with your expected share of the field.</div>`;
  return h;
}

// --- trade and diplomacy --------------------------------------------------------------------------

const GOOD_GLYPH = { food: "food", wares: "wares", luxuries: "luxuries" };
const nationName = (id) => S.nations.find((x) => x.id === id)?.name || "?";
function routeName(r) {
  const kind = { barter: "Barter", caravan: "Caravan route", sea: "Sea route" }[r.kind];
  return r.mine ? `${kind} with ${nationName(r.partner)}${r.opened_by_us ? " (ours)" : ""}` : `${kind}: ${nationName(r.a)}–${nationName(r.b)}`;
}
function flowText(r) {
  if (!r.active) return "Blockaded: nothing moves.";
  const parts = Object.entries(r.flows).filter(([, q]) => Math.abs(q) > 0.005).map(([g, q]) => r.mine ? `${q > 0 ? "we sell" : "we buy"} ${fmt(Math.abs(q), 1)} ${GOOD_GLYPH[g]}` : `${fmt(Math.abs(q), 1)} ${g}`);
  return (parts.join(", ") || "no trade this turn: prices too close") + `\ncapacity ${r.capacity} · carriage ${pct(r.carriage)}${r.opened_by_us ? ` · our merchants' profit ${fmt(r.profit, 1)}` : ""}`;
}
function traderCard(u, n) {
  let h = `<h2>${esc(u.name)} at ${esc(n.name)}</h2><div>moves ${u.moves_left}/${u.max_moves}</div><div class="verbs">`;
  h += `<button ${u.open_route ? "disabled" : ""} data-tip="${esc(u.open_route ? `Not here: ${u.open_route}` : `Open a ${u.kind === "caravan" ? "caravan" : "sea"} route with ${nationName(n.owner)} here.`)}" onclick="act({kind:'open_route',unit:'${u.id}'})">Open route here</button>`;
  h += `</div><div class="small muted">${esc(u.description)} Move it by clicking a ringed node; merchants may enter foreign towns in peacetime.</div>`;
  return h;
}
function diplomacyButtons(n) {
  let h = "";
  for (const k of n.treaties || []) h += `<span class="up small">${esc(S.treaty_types[k].name)}</span> <button class="small" data-tip="End the ${esc(S.treaty_types[k].name.toLowerCase())}: relations suffer." onclick="act({kind:'cancel_treaty',nation:'${n.id}',treaty:'${k}'}).then(renderScreen)">✕</button> `;
  for (const [k, why] of Object.entries(n.propose || {})) {
    if ((n.treaties || []).includes(k) || (why && /^needs [A-Z]/.test(why) && !why.includes("Sway"))) continue;
    const t = S.treaty_types[k];
    h += `<button ${why ? "disabled" : ""} data-tip="${esc(`${t.effect}\nCosts ${t.sway} Sway if they accept.${why ? `\nNot now: ${why}` : ""}`)}" onclick="act({kind:'propose_treaty',nation:'${n.id}',treaty:'${k}'}).then(renderScreen)">Propose ${esc(t.name)}</button> `;
  }
  h += `<button ${n.gift ? "disabled" : ""} data-tip="${esc(n.gift || "Send 10 Stock (or food) as a gift: their relations with us +15.")}" onclick="act({kind:'gift',nation:'${n.id}'}).then(renderScreen)">Gift</button> `;
  h += n.embargoed ? '<span class="down small">embargo</span>' : `<button ${n.embargo ? "disabled" : ""} data-tip="${esc(n.embargo || "Embargo: close every route with them for 10 turns (10 Sway). They gain a just cause for war.")}" onclick="if(confirm('Embargo ${esc(n.name)}?'))act({kind:'embargo',nation:'${n.id}'}).then(renderScreen)">Embargo</button>`;
  return h;
}
function screenTrade() {
  const t = S.me.trade;
  const goods = ["food", "wares", "luxuries"];
  let h = `<h2>Trade</h2><p class="muted">Goods move from the market where they are cheaper to the one where they are dearer, up to each route's capacity, while the gap covers carriage. The gap is merchants' profit. Policy: <b>${esc(S.institutions.find((p) => p.key === "commerce").options.find((o) => o.active).name)}</b>. Route slots ${S.me.routes}/${S.me.route_slots}.</p>`;
  h += `<table class="plain"><tr><th></th>${goods.map((g) => `<th>${g}</th>`).join("")}</tr>`;
  h += `<tr><td>Imports</td>${goods.map((g) => `<td class="n">${fmt(t.imports[g], 1)}</td>`).join("")}</tr><tr><td>Exports</td>${goods.map((g) => `<td class="n">${fmt(t.exports[g], 1)}</td>`).join("")}</tr>`;
  h += `<tr><td>Prices here</td>${goods.map((g) => `<td class="n">${fmt(S.me.prices[g], 2)}</td>`).join("")}</tr></table>`;
  h += `<p>Merchants' profit ${fmt(t.profit, 1)} · tolls ${fmt(t.tolls, 1)} · tariffs ${fmt(t.tariff, 1)} · export bounties paid ${fmt(t.bounty, 1)}</p>`;
  h += `<h3>Routes</h3><table class="plain"><tr><th>Route</th><th>Capacity</th><th>This turn</th><th>State</th></tr>`;
  for (const r of S.routes.filter((x) => x.mine)) h += `<tr><td>${esc(routeName(r))}</td><td class="n">${r.capacity}</td><td class="small">${esc(flowText(r).split("\n")[0])}</td><td>${r.active ? '<span class="up">open</span>' : '<span class="down">blockaded</span>'}</td></tr>`;
  if (!S.routes.some((x) => x.mine)) h += `<tr><td colspan="4" class="muted">No routes yet. Barter with a people your band meets; later send a caravan from a Market Town or a merchantman from a Port.</td></tr>`;
  h += `</table><h3>Dependence</h3><p class="muted small">Share of our consumption bought from each people last turn, and the food we get from them. A people that relies on another for a quarter of any good, or a sixth of everything, falls into its orbit.</p><table class="plain"><tr><th>People</th><th>We depend on them</th><th>For food</th><th>They depend on us</th></tr>`;
  for (const n of S.nations.filter((x) => x.met && x.id !== S.me.id)) {
    const d = t.dependence[n.id] || 0, f = t.food_dependence[n.id] || 0;
    h += `<tr><td style="color:${n.colour}">${esc(n.name)}</td><td class="n ${d >= 0.15 ? "warn" : ""}">${pct(d)}</td><td class="n ${f >= 0.25 ? "warn" : ""}">${pct(f)}</td><td class="n">${pct(n.depends_on_us)}</td></tr>`;
  }
  return h + `</table>`;
}

// --- credit, orbits, reports ------------------------------------------------------------------

function creditSection(me) {
  const c = me.credit;
  let h = `<h3>Public credit</h3><p class="small muted">Borrow from our own Stock-holders (it crowds out private investment) or from another people (owe them more than five turns of revenue and we fall into their orbit). Interest is ${pct(c.rate)} a turn at our present debt.</p>`;
  h += `<p>Debt ${fmt(c.total)} · interest last turn ${fmt(c.service, 1)}${c.closed ? ` · <span class="down">credit closed until turn ${c.closed + 1}</span>` : ""}</p>`;
  if (c.debts.length) h += `<table class="plain"><tr><th>Lender</th><th>Owed</th><th>Rate</th><th>Since</th></tr>${c.debts.map((d) => `<tr><td>${d.lender === "domestic" ? "our Stock-holders" : esc(nationName(d.lender))}</td><td class="n">${fmt(d.principal)}</td><td class="n">${pct(d.rate)}</td><td class="n">${d.since}</td></tr>`).join("")}</table>`;
  const amt = Math.round(c.limit / 2);
  h += `<div class="verbs"><button ${c.borrow_home ? "disabled" : ""} data-tip="${esc(c.borrow_home || `Borrow ${amt} from our own Stock-holders.`)}" onclick="act({kind:'borrow',source:'domestic',amount:${amt}}).then(renderScreen)">Borrow ${amt} at home</button>`;
  h += `<button ${c.repay ? "disabled" : ""} data-tip="${esc(c.repay || "Repay what the Treasury can spare, foreign lenders first.")}" onclick="act({kind:'repay',amount:${Math.max(0, Math.floor(me.treasury))}}).then(renderScreen)">Repay</button>`;
  if (c.debts.length) h += `<button data-tip="Default: the debt is wiped; lenders lose it, our Stock-holders and foreign lenders turn on us, and no one lends for 10 turns." onclick="if(confirm('Default on ${fmt(c.total)} of debt?'))act({kind:'default'}).then(renderScreen)">Default</button>`;
  return h + `</div><p class="small muted">To borrow abroad, use the Peoples screen.</p>`;
}
function borrowButton(n) {
  if (S.me.seat !== "civil") return "";
  const amt = Math.round(S.me.credit.limit / 2);
  return ` <button ${n.lend ? "disabled" : ""} data-tip="${esc(n.lend || `Ask ${n.name} to lend us ${amt}. Owe them enough and we fall into their orbit.`)}" onclick="act({kind:'borrow',source:'${n.id}',amount:${amt}}).then(renderScreen)">Borrow</button>`;
}
function orbitCell(n) {
  const parts = [];
  if (n.orbit_of) parts.push(`<span class="warn">orbits ${esc(nationName(n.orbit_of))}</span>`);
  if (n.sphere && n.sphere.length) parts.push(`holds ${n.sphere.map((x) => esc(nationName(x))).join(", ")}`);
  const levers = Object.entries(n.levers_on_them || {}).map(([a, l]) => `${nationName(a)}: ${l.detail}`).join("\n");
  return `<span data-tip="${esc(levers || "No one holds a lever over them.")}">${parts.join(" · ") || "free"}</span>`;
}
function charts(keys) {
  const labels = { share: "Share of world produce", per_head: "Produce per head", labour_share: "Labour's share", freedom: "Freedom" };
  const met = S.nations.filter((n) => n.met && n.history && n.history.length > 1);
  return `<div class="charts">${keys.map((k) => {
    const all = met.flatMap((n) => n.history.map((h) => h[k]));
    const max = Math.max(...all, 1e-9), last = Math.max(...met.map((n) => n.history.length));
    const lines = met.map((n) => `<polyline fill="none" stroke="${n.colour}" stroke-width="${n.id === S.me.id ? 2.5 : 1.3}" points="${n.history.map((h, i) => `${(i / Math.max(last - 1, 1)) * 300},${100 - (h[k] / max) * 96}`).join(" ")}"><title>${esc(n.name)}</title></polyline>`).join("");
    const mark = k === "share" ? `<line x1="0" x2="300" y1="${100 - (0.4 / max) * 96}" y2="${100 - (0.4 / max) * 96}" stroke="var(--warn)" stroke-dasharray="3 3"/>` : "";
    return `<figure><figcaption class="small">${labels[k]}</figcaption><svg viewBox="0 0 300 100" width="300" height="100">${mark}${lines}</svg></figure>`;
  }).join("")}</div><div class="small">${met.map((n) => `<span style="color:${n.colour}">■ ${esc(n.name)}</span>`).join(" ")}</div>`;
}
function screenReports() {
  let h = `<h2>Reports</h2>${charts(["share", "per_head", "labour_share", "freedom"])}`;
  h += `<h3>Levers and orbits</h3><p class="small muted">A people is in the orbit of whoever holds the strongest lever over it: supplying a quarter of one good or a sixth of all it consumes (trade), holding five turns of its revenue in debt (credit), or taking tribute, protecting it, or occupying a quarter of its towns (force). Its satellites' satellites count too.</p><table class="plain"><tr><th>People</th><th>In the orbit of</th><th>Levers held over them</th><th>Their sphere</th></tr>`;
  for (const n of S.nations.filter((x) => x.met)) {
    const levers = Object.entries(n.levers_on_them || {}).map(([a, l]) => `${esc(nationName(a))}: ${esc(l.detail)} (${l.kind}, ${l.strength}×)`).join("<br>") || "—";
    h += `<tr><td style="color:${n.colour}">${esc(n.name)}</td><td>${n.orbit_of ? esc(nationName(n.orbit_of)) : "free"}</td><td class="small">${levers}</td><td>${(n.sphere || []).map((x) => esc(nationName(x))).join(", ") || "—"}</td></tr>`;
  }
  return h + `</table>`;
}

// --- the now column ---------------------------------------------------------------------------

// --- hints for a first game: one at a time, from what is on the board -----------------------------

let hintsOff = false;
try { hintsOff = localStorage.getItem("stock-hints") === "off"; } catch (e) { /* storage may be blocked */ }
function currentHint() {
  const me = S.me, mine = S.units.filter((u) => u.nation === me.id);
  const band = mine.find((u) => !u.military && u.kind === "band");
  const node = band ? S.nodes.find((n) => n.id === band.node) : null;
  const known = (k) => S.discoveries.find((d) => d.key === k)?.state === "known";
  const settled = S.nodes.some((n) => n.owner === me.id);
  if (S.turn > 60) return null;
  if (!me.researching) return "Choose a discovery: click the line under this box, or press D. Taming and Tillage open the way out of the hunt.";
  if (band && node && node.game != null && node.game < 0.45 && !settled) return `The game at ${node.name} is thinning (${pct(node.game)} left). Select your band and click a ringed neighbour to move on.`;
  if (band && node && node.features.includes("wild_herds") && !known("taming") && !band.followed) return "Wild herds graze here. Select your band and choose Follow the herds: three turns of it halves the cost of Taming.";
  if (band && node && node.features.includes("wild_herds") && known("taming")) return "You know Taming, and wild herds are here: select your band and choose Tame to become a horde.";
  if (band && known("tillage") && !settled) return "You know Tillage. Take a band to a river valley or coast and choose Settle: fields grow far more than the hunt.";
  if (settled && me.build_queue.length === 0 && me.stock >= 8) return "You have Stock to invest. Click your settlement and queue a work: green returns beat the rate of profit and are built by private stock.";
  if (S.nations.some((n) => n.met && n.id !== me.id) && known("barter") && me.routes === 0) return "You have met another people. Open Peoples (P) and choose Barter: both markets widen and knowledge flows.";
  if (me.seat === "chiefdom" && known("magistracy")) return "You know Magistracy. Found a government (left panel) to raise taxes and build a Treasury.";
  if (me.seat === "civil" && S.institutions.find((p) => p.key === "revenue").options.find((o) => o.active).key === "plunder") return "Your government has no taxes yet. Open Institutions (I) and choose a Revenue option to fill the Treasury.";
  return null;
}
function renderHint() {
  const h = hintsOff ? null : currentHint();
  const box = $("hint");
  box.hidden = !h;
  if (h) box.innerHTML = `<span>${esc(h)}</span> <button class="small" title="No more hints" onclick="hintsOff=true;try{localStorage.setItem('stock-hints','off')}catch(e){};renderHint()">✕</button>`;
}

// armies are supplied within two steps of our towns, and riders on open grazing
function supplyReach() {
  const adj = {};
  for (const e of S.edges) if (e.kind !== "sea") { (adj[e.a] ||= []).push(e.b); (adj[e.b] ||= []).push(e.a); }
  const out = new Set();
  let frontier = S.nodes.filter((n) => n.owner === S.me.id).map((n) => n.id);
  frontier.forEach((x) => out.add(x));
  for (let i = 0; i < 2; i++) {
    frontier = frontier.flatMap((x) => adj[x] || []).filter((x) => !out.has(x));
    frontier.forEach((x) => out.add(x));
  }
  return out;
}

function renderNow() {
  renderHint();
  const me = S.me;
  $("decisions").innerHTML = me.decisions.map((d) => `<div class="decision"><b class="serif">${esc(d.title)}</b><div class="small">${esc(d.text)}</div>${d.choices.map((c) => `<button data-tip="${esc(c.effect)}" onclick="act({kind:'decide',id:'${d.id}',choice:'${c.key}'})">${esc(c.label)}</button>`).join("")}</div>`).join("");
  const cur = me.researching ? S.discoveries.find((d) => d.key === me.researching) : null;
  $("research-now").innerHTML = cur
    ? `Researching <b>${esc(cur.name)}</b>: ${fmt(me.research_progress)} / ${fmt(me.research_cost)} (+${fmt(me.ingenuity)}/turn)${me.research_queue.length ? `<div class="small muted">then ${me.research_queue.slice(0, 3).map((k) => esc(S.discoveries.find((x) => x.key === k).name)).join(", ")}${me.research_queue.length > 3 ? ` +${me.research_queue.length - 3}` : ""}</div>` : ""}`
    : `<span class="warn">Choose a discovery ▸</span> <span class="muted">(${fmt(me.research_progress)} ingenuity banked)</span>`;
  $("log").innerHTML = S.log.slice().reverse().map((e) => `<div class="ev ${e.kind}"><div class="t">Turn ${e.turn}</div>${esc(e.text)}${e.quote ? `<q>${esc(e.quote)}</q>` : ""}</div>`).join("");
  $("end-turn").disabled = !!S.winner && false;
  $("end-turn").textContent = me.decisions.length ? "Answer the decision" : `End turn ${S.turn}`;
}

function showEnd() {
  if (!S.winner || showEnd.shown) return;
  showEnd.shown = true;
  const w = S.winner;
  const mine = w.nation === S.me.id;
  const how = w.kind === "hegemony" ? "by hegemony" : "by opulence";
  $("moment").innerHTML = `<div class="card" style="max-width:760px"><h2>${mine ? "Victory" : "The game is decided"} ${how}</h2><p class="serif">${esc(w.text)}</p>${charts(["share", "per_head"])}<p class="small muted">The curves are a record, not a score. You may keep playing.</p><button class="primary" onclick="$('moment').hidden=true">Keep playing</button> <button onclick="$('moment').hidden=true;openScreen('reports')">Reports</button></div>`;
  $("moment").hidden = false;
}
const CARD_KINDS = ["war", "captured", "exile", "eliminated", "peace", "moment", "mode", "regression", "victory",
  "plague", "coalition", "hegemony"];
const CARD_TITLE = { war: "War", captured: "A town changes hands", exile: "Exile", eliminated: "A people is no more",
  peace: "Peace", regression: "A regression", victory: "The end of the game", plague: "Plague",
  coalition: "The balance of power", hegemony: "Ascendancy" };
let cardQueue = [];
function showMoments(prevTurn) {
  cardQueue = S.log.filter((e) => e.turn === prevTurn && CARD_KINDS.includes(e.kind));
  nextCard();
}
function nextCard() {
  const e = cardQueue.shift();
  if (!e) { $("moment").hidden = true; return; }
  const grim = ["war", "captured", "exile", "eliminated"].includes(e.kind);
  const title = CARD_TITLE[e.kind] || "A moment";
  const more = cardQueue.length ? ` <span class="small muted">(${cardQueue.length} more)</span>` : "";
  $("moment").innerHTML = `<div class="card ${grim ? "grim" : ""}"><h2>${title}${more}</h2><p class="serif">${esc(e.text)}</p>${e.quote ? `<q>“${esc(e.quote)}”<br><span class="small">— Adam Smith, The Wealth of Nations</span></q>` : ""}<button class="primary" onclick="nextCard()">Continue</button></div>`;
  $("moment").hidden = false;
}

// --- screens ------------------------------------------------------------------------------------

function openScreen(name) { screen = name; renderScreen(); }
function closeScreen() { screen = null; $("screen").hidden = true; }
function renderScreen() {
  if (!screen) return;
  const body = { settlements: screenSettlements, discoveries: screenDiscoveries, institutions: screenInstitutions, treasury: screenTreasury, trade: screenTrade, nations: screenNations, reports: screenReports, book: screenBook }[screen]();
  $("screen-body").innerHTML = `<div class="screen-bar"><button class="close" onclick="closeScreen()" title="Close (Escape)">Close ✕</button></div>` + body;
  $("screen").hidden = false;
}

function screenDiscoveries() {
  const lanes = ["subsistence", "exchange", "force", "order"];
  const eras = ["Hunting", "Pasturage", "Agriculture", "Commerce"];
  const q = S.me.research_queue;
  let h = `<h2>Discoveries</h2><p class="muted">Ingenuity ${fmt(S.me.ingenuity)} a turn. Meeting a discovery's observation halves its cost; peoples you know who have it already make it cheaper still.<br>Click a discovery to study it, or to queue it (with whatever it needs first) if we are studying something already. Shift-click one we can study to take it up now. Click a queued one to drop it.</p>`;
  const cur = S.me.researching ? S.discoveries.find((x) => x.key === S.me.researching) : null;
  h += `<div class="rq"><b>Studying:</b> ${cur ? esc(cur.name) : '<span class="warn">nothing</span>'}${q.length ? " · <b>then</b>" : ""}${q.map((k, i) => `<span class="item">${i + 1}. ${esc(S.discoveries.find((x) => x.key === k).name)} <button class="small" title="Drop" onclick="act({kind:'unqueue_research',key:'${k}'}).then(renderScreen)">✕</button></span>`).join("")}</div>`;
  h += `<div class="web"><div></div>${eras.map((e) => `<div class="era">${e}</div>`).join("")}`;
  for (const lane of lanes) {
    h += `<div class="lane">${lane[0].toUpperCase() + lane.slice(1)}</div>`;
    for (let era = 1; era <= 4; era++) {
      h += `<div class="cell">`;
      for (const d of S.discoveries.filter((x) => x.lane === lane && x.era === era)) {
        const req = d.requires.map((g) => g.map((k) => S.discoveries.find((x) => x.key === k).name).join(" or ")).join(", and ");
        const qi = q.indexOf(d.key);
        const current = S.me.researching === d.key;
        const how = d.state === "known" || current ? "" : qi >= 0 ? "Click to drop it from the queue."
          : d.state === "available" && !S.me.researching ? "Click to study it." : "Click to queue it" + (d.state === "locked" ? " with what it needs." : "; shift-click to study it now.");
        const tip = `${d.unlocks}${req ? `\nNeeds: ${req}` : ""}${d.quote ? `\n\n“${d.quote}”` : ""}${how ? `\n\n${how}` : ""}`;
        const badge = current ? `<span class="badge">studying</span>` : qi >= 0 ? `<span class="badge">${qi + 1}</span>` : "";
        h += `<div class="disc ${d.state} ${current ? "current" : ""} ${qi >= 0 ? "queued" : ""}" data-tip="${esc(tip)}" ${how ? `onclick="discClick('${d.key}', event)"` : ""}>
          ${badge}<div class="name">${esc(d.name)}</div><div class="small">${esc(d.unlocks)}</div>
          ${d.state !== "known" ? `<div class="small">Cost ${fmt(d.cost)}${d.diffusion ? ` <span class="up">(−${pct(d.diffusion)} known by ${esc(d.known_by.join(", "))})</span>` : ""}</div>` : ""}
          ${d.observation && d.state !== "known" ? `<div class="small obs ${d.observed ? "met" : ""}">${d.observed ? "✓" : `${pct(d.progress)} ·`} ${esc(d.observation)}</div>` : ""}</div>`;
      }
      h += `</div>`;
    }
  }
  return h + `</div>`;
}

function discClick(key, e) {
  const d = S.discoveries.find((x) => x.key === key);
  let a;
  if (S.me.research_queue.includes(key)) a = { kind: "unqueue_research", key };
  else if (d.state === "available" && (!S.me.researching || e.shiftKey)) a = { kind: "research", key };
  else a = { kind: "queue_research", key };
  act(a).then(renderScreen);
}

// --- settlements: every town, what it could build, and the investment queue ---------------------

function focusNode(id) {
  sel = { type: "node", id };
  closeScreen();
  const n = nodeById()[id];
  if (n) zoomTo(n.x, n.y, 2);
  renderAll();
}
function investButtons(n) {
  const shown = (n.buildable || []).filter((b) => !(b.why && /^needs [A-Z]/.test(b.why) && !b.why.includes("Treasury") && !b.why.includes("Civil")));
  const full = shown.find((b) => b.why && b.why.startsWith("no free slot"));
  if (full && shown.every((b) => b.why && b.why.startsWith("no free slot"))) {
    return `<span class="muted small">Every slot is taken (${esc(full.why.replace("no free slot ", "").replace(/[()]/g, ""))}). More hands open more slots, or pull down a work.</span>`;
  }
  let h = "";
  for (const b of shown) {
    const ret = b.return != null ? `<span class="ret ${b.return >= (S.me.breakdowns.stock?.rate_of_profit || 0.12) ? "up" : "down"}">${pct(b.return)}</span>` : "";
    const w = S.works.find((x) => x.key === b.key);
    const tip = `${w.description}\nCost ${b.cost} ${b.public ? "Treasury" : "Stock"}.${b.return != null ? `\nExpected return ${pct(b.return)} against a rate of profit of ${pct(S.me.breakdowns.stock?.rate_of_profit)}: below it, investors want a bounty.` : ""}${b.why ? `\nNot now: ${b.why}` : ""}`;
    h += `<button ${b.why ? "disabled" : ""} data-tip="${esc(tip)}" onclick="act({kind:'build',node:'${n.id}',work:'${b.key}'})${screen ? ".then(renderScreen)" : ""}">${esc(b.name)} · ${b.cost}${b.public ? "T" : ""} ${ret}</button>`;
  }
  return h;
}
function queueList() {
  const q = S.me.build_queue;
  if (!q.length) return `<p class="muted small">Nothing queued. Queue a work below: Stock builds it when there is enough, in queue order.</p>`;
  const again = screen ? ".then(renderScreen)" : "";
  return `<table class="plain">` + q.map((it, i) => `<tr><td>${i + 1}.</td><td><b>${esc(S.works.find((x) => x.key === it.work)?.name)}</b> at <span class="place" onclick="focusNode('${it.node}')">${esc(nodeById()[it.node]?.name)}</span></td><td class="muted small">${esc(it.status)}</td><td>
    <button class="small" ${i ? "" : "disabled"} title="Earlier" onclick="act({kind:'reorder_queue',index:${i},to:${i - 1}})${again}">▲</button>
    <button class="small" ${i < q.length - 1 ? "" : "disabled"} title="Later" onclick="act({kind:'reorder_queue',index:${i},to:${i + 1}})${again}">▼</button>
    <button class="small" title="Drop" onclick="act({kind:'unqueue',index:${i}})${again}">✕</button></td></tr>`).join("") + `</table>`;
}
function screenSettlements() {
  const me = S.me;
  const mine = S.nodes.filter((n) => n.owner === me.id).sort((a, b) => b.hands - a.hands);
  let h = `<h2>Settlements</h2><p class="muted">Stock ${fmt(me.stock)} (${sgn(me.stock_income)} a turn) · rate of profit ${pct(me.breakdowns.stock?.rate_of_profit)}${me.seat === "civil" ? ` · Treasury ${fmt(me.treasury)}` : ""}. Green returns beat the rate of profit and private Stock builds them; red ones need a bounty from the Treasury. Works marked T are paid by the Treasury at once.</p>`;
  h += `<h3>Investment queue</h3>` + queueList();
  h += `<h3>Our settlements</h3>`;
  if (!mine.length) h += `<p class="muted">We have no settlement yet: settle a band first.</p>`;
  else {
    h += `<table class="plain lands"><tr><th>Place</th><th>Hands</th><th>Produce</th><th>Works</th><th>Unrest</th><th>Invest</th></tr>`;
    for (const n of mine) {
      const works = (n.works || []).map((w) => esc(S.works.find((x) => x.key === w)?.name || w)).join(", ") || '<span class="muted">none</span>';
      h += `<tr><td><a onclick="focusNode('${n.id}')">${esc(n.name)}</a><div class="small muted">${groundText(n)}${n.features.length ? " · " + n.features.map((f) => FEATURE[f]).join(", ") : ""}</div>${n.siege ? `<div class="small warn">besieged</div>` : ""}</td>
        <td class="n">${fmt(n.hands)}<div class="small muted">${n.jobs} jobs</div></td><td class="n">${fmt(n.produce)}</td>
        <td>${works}<div class="small muted">${n.works.length}/${n.slots} slots</div></td><td class="n ${n.unrest > 70 ? "down" : n.unrest > 40 ? "warn" : ""}">${n.unrest}</td>
        <td><div class="build">${investButtons(n)}</div></td></tr>`;
    }
    h += `</table>`;
  }
  const others = S.nodes.filter((n) => n.owner !== me.id && (n.visible || n.owner || n.features.length))
    .sort((a, b) => (a.owner || "~").localeCompare(b.owner || "~") || a.name.localeCompare(b.name));
  h += `<h3>Other places we know</h3><table class="plain"><tr><th>Place</th><th>Ground</th><th>Held by</th><th>Hands</th><th>Has</th></tr>`;
  for (const n of others) {
    const owner = n.owner ? S.nations.find((x) => x.id === n.owner) : null;
    h += `<tr><td><a class="place" onclick="focusNode('${n.id}')">${esc(n.name)}</a>${n.visible ? "" : ' <span class="muted small">(last seen)</span>'}</td><td class="small">${groundText(n)}</td>
      <td>${owner ? `<span style="color:${owner.colour}">${esc(owner.name)}</span>${n.enemy ? ' <span class="down small">enemy</span>' : ""}` : '<span class="muted">open ground</span>'}</td>
      <td class="n">${n.owner && n.hands != null ? fmt(n.hands) : ""}</td><td class="small">${n.features.map((f) => FEATURE[f]).join(", ")}</td></tr>`;
  }
  return h + `</table>`;
}

async function forecastOption(pillar, option, el) {
  const res = await api("/forecast", { kind: "institution", pillar, option });
  if (!res) return;
  if (!res.ok) { el.textContent = res.why; return; }
  const d = res.delta;
  const names = { food: "food", stock: "stock", treasury: "treasury", sway: "sway", produce: "produce", labour_contentment: "Labour", proprietors_contentment: "Proprietors", stock_contentment: "Stock-holders" };
  el.innerHTML = "Forecast: " + Object.entries(d).filter(([, v]) => Math.abs(v) >= 0.05).map(([k, v]) => `<span class="${cls(v)}">${names[k] || k} ${sgnPlain(v)}</span>`).join(" · ") || "no visible change next turn";
}
function screenInstitutions() {
  let h = `<h2>Institutions</h2><p class="muted">One option per pillar. Changing costs Sway: more when the orders that oppose it hold clout, less when supporters do. The change comes into force next turn; a pillar then rests five turns.</p><div class="pillars">`;
  for (const p of S.institutions) {
    h += `<div><h3>${esc(p.name)}${p.cooldown ? ` <span class="muted small">rests ${p.cooldown}</span>` : ""}</h3>`;
    for (const o of p.options) {
      const who = (xs) => xs.map((x) => `<span style="color:${ORDER_COLOUR[x]}">${S.me.orders[x].name}</span>`).join(", ");
      h += `<div class="opt ${o.active ? "active" : ""} ${o.pending ? "pending" : ""}"><b class="serif">${esc(o.name)}</b>${o.active ? " · in force" : o.pending ? " · next turn" : ""}
        <div class="small">${esc(o.effect)}</div>
        ${o.supports.length ? `<div class="small">For: ${who(o.supports)}</div>` : ""}${o.opposes.length ? `<div class="small">Against: ${who(o.opposes)}</div>` : ""}
        ${o.active || o.pending ? "" : o.why ? `<div class="small muted">${esc(o.why)}</div>` : `<button onclick="act({kind:'institution',pillar:'${p.key}',option:'${o.key}'}).then(renderScreen)">Enact · ${o.cost} Sway</button> <button onclick="forecastOption('${p.key}','${o.key}',this.nextElementSibling)">Forecast</button><div class="fc"></div>`}</div>`;
    }
    h += `</div>`;
  }
  return h + `</div>`;
}

function screenTreasury() {
  const me = S.me;
  if (me.seat !== "civil") return `<h2>Treasury</h2><p>No treasury yet. A people needs owners of herds or land before it needs a magistrate: become a chiefdom, discover Magistracy, then found a government.</p>`;
  const t = me.tax || {};
  let h = `<h2>Treasury · ${fmt(me.treasury)}</h2><h3>Revenue: ${esc(S.institutions.find((p) => p.key === "revenue").options.find((o) => o.active).name)}</h3>`;
  h += `<div class="verbs">${["light", "moderate", "heavy"].map((r) => `<button class="${me.tax_rate === r ? "on" : ""}" onclick="act({kind:'tax',rate:'${r}'}).then(renderScreen)">${r}</button>`).join("")}</div>`;
  h += `<p>Collected last turn: ${fmt(t.collected)}</p><table class="plain"><tr><th>Order</th><th>Pays nominally</th><th>Actually bears</th></tr>`;
  for (const o of ["labour", "proprietors", "stock"]) h += `<tr><td>${me.orders[o].name}</td><td class="n">${fmt(t.nominal?.[o], 2)}</td><td class="n">${fmt(t.actual?.[o], 2)}</td></tr>`;
  h += `</table><p class="muted small">Who hands over the money is not always who ends up poorer: an excise on necessaries raises what labour must be paid, and part of it comes back out of profit and rent.</p><h3>Spending</h3><table class="plain">`;
  const tips = { justice: "Security, labour's organisation, fewer riots, better tax collection.", instruction: "Offsets the dulling of divided labour; Ingenuity.", court: "Sway." };
  for (const line of ["justice", "instruction", "court"]) h += `<tr><td data-tip="${tips[line]}">${line}</td><td>${[0, 1, 2, 3].map((lv) => `<button class="${me.budget[line] === lv ? "on" : ""}" onclick="act({kind:'budget',line:'${line}',level:${lv}}).then(renderScreen)">${lv}</button>`).join(" ")}</td><td class="n">${fmt(me.breakdowns.treasury?.spent?.[line], 1)}</td></tr>`;
  return h + `</table>` + creditSection(me);
}

function spark(hist, key, colour) {
  if (!hist || hist.length < 2) return "";
  const vals = hist.map((h) => h[key]); const max = Math.max(...vals, 1e-9);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 200},${40 - (v / max) * 38}`).join(" ");
  return `<svg width="200" height="42"><polyline fill="none" stroke="${colour}" stroke-width="1.5" points="${pts}"/></svg>`;
}
function screenNations() {
  let h = `<h2>Peoples</h2><table class="plain"><tr><th>People</th><th>Age</th><th>Seat</th><th>Hands</th><th>Army</th><th>World share</th><th>Per head</th><th>Relations</th><th>Orbit</th><th>Produce</th><th></th></tr>`;
  for (const n of S.nations) {
    if (!n.met) { h += `<tr><td class="muted">${esc(n.name)}</td><td colspan="9" class="muted">not yet met</td></tr>`; continue; }
    let btn = n.id === S.me.id ? "" : n.at_war ? "" : n.trading ? '<span class="up">bartering</span> ' : `<button ${n.barter ? "disabled" : ""} data-tip="${esc(n.barter || "Open a barter route: both markets widen, knowledge flows, relations improve.")}" onclick="act({kind:'barter',nation:'${n.id}'}).then(renderScreen)">Barter</button> `;
    if (n.id !== S.me.id && n.at_war) {
      btn += `<span class="down">At war · score ${n.war_score > 0 ? "+" : ""}${n.war_score}</span> `;
      const terms = { white: "Peace as things stand", tribute: "Demand tribute", submit: "Offer tribute" };
      for (const [k, label] of Object.entries(terms)) btn += `<button ${n.peace[k] ? "disabled" : ""} data-tip="${esc(n.peace[k] || `Offer: ${label.toLowerCase()} (${k === "white" ? "no tribute" : "10% of produce for 10 turns"}).`)}" onclick="act({kind:'offer_peace',nation:'${n.id}',terms:'${k}'}).then(renderScreen)">${label}</button> `;
    } else if (n.id !== S.me.id) {
      const cost = n.cause ? "a just cause: free" : `${S.me.war_cost} Sway, no cause`;
      btn += `<button ${n.declare ? "disabled" : ""} data-tip="${esc(n.declare || `Declare war on ${n.name} (${cost}). Trade with them stops; their army strength is ${n.strength}.`)}" onclick="if(confirm('Declare war on ${esc(n.name)}?'))act({kind:'declare_war',nation:'${n.id}'}).then(renderScreen)">Declare war</button>`;
      if (n.truce) btn += ` <span class="muted small">truce to turn ${n.truce}</span>`;
    }
    if (n.id !== S.me.id) btn += diplomacyButtons(n) + borrowButton(n);
    h += `<tr><td><b style="color:${n.colour}">${esc(n.name)}</b></td><td>${esc(n.mode)}</td><td>${SEAT[n.seat]}</td><td class="n">${fmt(n.hands)}</td><td class="n">${fmt(n.strength)}</td><td class="n">${pct(n.share)}</td><td class="n">${fmt(n.per_head, 2)}</td><td class="n">${n.id === S.me.id ? "" : fmt(n.relations, 0)}</td><td class="small">${orbitCell(n)}</td><td>${spark(n.history, "produce", n.colour)}</td><td>${btn}</td></tr>`;
  }
  h += `</table><h3>Your three curves</h3><p class="muted small">Produce per head · labour's share of produce · freedom. Not a score: a record.</p>`;
  h += `<div>${spark(S.me.history, "per_head", "var(--accent)")} ${spark(S.me.history, "labour_share", ORDER_COLOUR.labour)} ${spark(S.me.history, "freedom", "var(--up)")}</div>`;
  return h;
}

function screenBook() {
  const entries = [
    ["The four stages", "A people's mode of subsistence is whichever of hunting, herds, fields or commerce yields the most. What can be owned decides what can be accumulated, and so what the people become. Modes can fall back."],
    ["Stock", "Capital: what is saved and set to work. Stock-holders save most of their profit, proprietors little of their rent, labourers only from pay above need. Savings become stock in proportion to Security; the rest is hoarded."],
    ["Extent of the market", "The hands your market reaches: settlements joined by rivers, roads and ports, plus towns and trade routes. The division of labour grows with it, and manufactories and workshops with that."],
    ["Wages, profit, rent", "Each work's produce pays wages first, then the ordinary profit on the stock in it, and the remainder is rent to whoever owns the ground. Who owns it is an institution."],
    ["Retainers or luxuries", "Proprietors spend their surplus on standing. With nothing to buy, they keep retainers: idle hands, armed, owing loyalty to them rather than to you. Give them luxuries and they dismiss them."],
    ["The invisible hand", "Under free labour, hands move to the best-paid work themselves; you cannot place them, only change what pays. Under serfdom you place them yourself, at three-quarters of the output."],
    ["Who really pays", "The nominal payer of a tax and the one who ends up poorer are often different. The Treasury screen shows both."],
    ["Hegemony and opulence", "A people with 40% of the world's produce and half the others in its orbit for ten turns wins by hegemony. Otherwise, at the last turn, the people with the most produce per head wins by opulence."],
  ];
  entries.push(
    ["War", "Soldiers are hands taken from work: an army is paid for in produce as well as in Treasury. Each kind of army suits a kind of society; shepherds' riders rule the open grass, walls and hills blunt them, and a standing army with firearms beats everything. Armies more than two steps from our towns, or crowded, lose cohesion."],
    ["Trade", "Goods move from where they are cheap to where they are dear while the gap pays for carriage. The gap is the merchants' profit, and it goes to whoever opened the route. Every route widens both markets; a people that buys much of what it eats from one partner depends on it."],
    ["Public credit", "A state may borrow from its own Stock-holders, which leaves less to invest, or abroad, which puts it in the lender's power. Interest rises with the debt. A default wipes the debt and the state's credit with it."],
    ["Orbits", "Supply a quarter of a people's food or wares, hold five turns of its revenue in debt, or take its tribute, and it is in your orbit. A leader with 40% of the world's produce and half the peoples in its sphere starts a countdown to hegemony, and the rest combine against it."],
    ["Events", "Harvests fail, plagues come along the trade routes, workmen invent, landowners petition to enclose, banks break. Each comes as a card with choices; the AI answers the same cards."],
    ["Keys", "Space or Enter ends the turn. Tab selects your next unit; M folds the selection card away and back. S settlements, D discoveries, I institutions, T treasury, R trade, P peoples, O reports, B this book, ? keys, Escape closes a screen."],
  );
  return `<h2>Commonplace Book</h2>` + entries.map(([t, b]) => `<h3>${t}</h3><p style="max-width:720px">${b}</p>`).join("");
}

// --- wiring -------------------------------------------------------------------------------------

function renderAll() { renderTop(); renderSociety(); renderMap(); renderSelection(); renderNow(); renderScreen(); }
function update(state) { S = state; renderAll(); }

document.querySelectorAll("#screens [data-screen]").forEach((b) => b.addEventListener("click", () => (screen === b.dataset.screen ? closeScreen() : openScreen(b.dataset.screen))));
document.querySelectorAll("#overlays [data-overlay]").forEach((b) => b.addEventListener("click", () => {
  overlay = b.dataset.overlay;
  document.querySelectorAll("#overlays button").forEach((x) => x.classList.toggle("on", x === b));
  renderMap();
}));
$("research-now").addEventListener("click", () => openScreen("discoveries"));
$("new-world").addEventListener("click", async () => {
  const spec = prompt("World: random, or random:SEED:NODES:NATIONS", "random");
  if (spec == null) return;
  const s = await api("/new", { spec });
  if (s) { sel = null; view = null; update(s); }
});
async function endTurn() {
  if (S.me.decisions.length) { toast("Answer the waiting decision first."); return; }
  const prev = S.turn;
  $("end-turn").disabled = true;
  const s = await api("/turn", {});
  $("end-turn").disabled = false;
  if (s) { update(s); showMoments(prev); showEnd(); }
}
$("end-turn").addEventListener("click", endTurn);
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem("stock-theme")); } catch (e) { /* storage may be blocked */ }
$("theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const t = dark ? "light" : "dark";
  applyTheme(t);
  try { localStorage.setItem("stock-theme", t); } catch (e) { /* ignore */ }
});
$("help").addEventListener("click", () => { screen = "book"; renderScreen(); });
$("regent").addEventListener("click", async () => {
  if (!confirm("Let a regent rule for 10 turns? The AI will take every decision for us.")) return;
  $("regent").disabled = true;
  const s = await api("/regent", { turns: 10 });
  $("regent").disabled = false;
  if (s) { update(s); showEnd(); }
});
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const endKey = e.key === "Enter" || e.key === " " || e.code === "Space";
  if (endKey) e.preventDefault();  // Space would otherwise also press the focused button
  if (endKey && !$("moment").hidden) { nextCard(); return; }
  if (endKey && screen) return;  // not while a screen is open
  if (endKey) endTurn();
  if (e.key === "Escape") { closeScreen(); $("moment").hidden = true; }
  if (e.key === "?") { screen = "book"; renderScreen(); }
  if (!screen && e.key.toLowerCase() === "m" && sel) toggleSelection();
  if (!screen && (e.key === "+" || e.key === "=")) zoomBy(1 / 1.4);
  if (!screen && (e.key === "-" || e.key === "_")) zoomBy(1.4);
  if (!screen && e.key === "0") { view = null; fitMap(); }
  const k = { s: "settlements", d: "discoveries", i: "institutions", t: "treasury", r: "trade", p: "nations", o: "reports", b: "book" }[e.key.toLowerCase()];
  if (k) (screen === k ? closeScreen() : openScreen(k));
  if (e.key === "Tab") {
    e.preventDefault();
    const mine = S.units.filter((u) => u.nation === S.me.id);
    if (!mine.length) return;
    const i = sel && sel.type === "unit" ? mine.findIndex((u) => u.id === sel.id) : -1;
    sel = { type: "unit", id: mine[(i + 1) % mine.length].id }; renderAll();
  }
});

api("/state").then((s) => {
  if (!s) return;
  const mine = s.units.find((u) => u.nation === s.me.id);
  if (mine) sel = { type: "unit", id: mine.id };
  update(s);
});
