// The map (Doc 07): an engraved chart. Nodes are circles with a hairline ring in the
// nation's ink and a 25% fill, radius ∝ √population; edges are hairlines, rivers
// double lines, roads heavier; a dashed hull round each nation's contiguous
// locations; each nation's label carries three tiny bars (capital, consumption,
// production world shares). Band mode shows neighbouring grounds' numbers so
// "move or stay" is a comparison. Positions come from the server (crossing-free,
// stock/api/layout.py); this file only draws.

import { formatBasket, formatShare } from "./format.js";
import { GOOD_GLYPH, GOOD_ORDER, L, nameOf } from "./labels.js";
import { el, getVar } from "./ui.js";

const W = 1000, H = 600;

function hull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (const p of pts.reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

function components(nodeIds, adjacency) {
  const seen = new Set();
  const out = [];
  const set = new Set(nodeIds);
  for (const id of nodeIds) {
    if (seen.has(id)) continue;
    const comp = [];
    const stack = [id];
    seen.add(id);
    while (stack.length) {
      const cur = stack.pop();
      comp.push(cur);
      for (const n of adjacency.get(cur) || []) {
        if (set.has(n) && !seen.has(n)) {
          seen.add(n);
          stack.push(n);
        }
      }
    }
    out.push(comp);
  }
  return out;
}

export function renderMap(stage, state, actions) {
  const s = state.snapshot;
  const wrap = el("div", { id: "map-wrap" });
  const canvas = el("canvas", { class: "chart" });
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  wrap.append(canvas);
  const hover = el("div", { id: "hovercard" });
  wrap.append(hover);
  stage.append(wrap);

  const nodes = s.map.nodes;
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const adjacency = new Map();
  for (const e of s.map.edges) {
    if (!adjacency.has(e.a)) adjacency.set(e.a, []);
    if (!adjacency.has(e.b)) adjacency.set(e.b, []);
    adjacency.get(e.a).push(e.b);
    adjacency.get(e.b).push(e.a);
  }
  const ctx = canvas.getContext("2d");
  const hasContested = nodes.some((n) => n.contested);
  let raf = null;

  const nationOf = {};
  for (const n of nodes) {
    if (!n.nation) continue;
    (nationOf[n.nation] = nationOf[n.nation] || []).push(n.id);
  }
  const shareByNation = Object.fromEntries(s.map.nation_shares.map((x) => [x.nation, x]));

  function draw(t = 0) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const rule = getVar("--rule");
    const ink = getVar("--ink");
    const ink2 = getVar("--ink-2");
    const warn = getVar("--warn");
    const accent = getVar("--accent");

    // nation hulls (dashed) round each contiguous component
    for (const [nation, ids] of Object.entries(nationOf)) {
      const colour = byId[ids[0]].nation_color || ink2;
      for (const comp of components(ids, adjacency)) {
        const pts = [];
        for (const id of comp) {
          const n = byId[id];
          const r = n.radius + 14;
          for (let k = 0; k < 16; k++) {
            const a = (k / 16) * Math.PI * 2;
            pts.push([n.x + Math.cos(a) * r, n.y + Math.sin(a) * r]);
          }
        }
        const h = hull(pts);
        if (h.length < 3) continue;
        ctx.beginPath();
        h.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
        ctx.closePath();
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.strokeStyle = colour;
        ctx.globalAlpha = 0.75;
        ctx.lineJoin = "round";
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
        // nation label with three tiny bars at the top of the hull
        const top = h.reduce((m, p) => (p[1] < m[1] ? p : m), h[0]);
        const cx = h.reduce((acc, p) => acc + p[0], 0) / h.length;
        const share = shareByNation[nation];
        const label = nameOf.nation(nation);
        ctx.font = "600 12px " + getVar("--serif");
        ctx.textAlign = "center";
        ctx.textBaseline = "alphabetic";
        ctx.fillStyle = colour;
        const ly = top[1] - 14;
        ctx.fillText(label, cx, ly);
        if (share) {
          const bars = [share.capital, share.consumption, share.production];
          const bw = 5, gap = 2, bh = 8;
          const x0 = cx - (bars.length * (bw + gap) - gap) / 2;
          bars.forEach((v, i) => {
            const hgt = Math.max(1, Math.min(1, v) * bh);
            ctx.fillStyle = rule;
            ctx.fillRect(x0 + i * (bw + gap), ly + 3, bw, bh);
            ctx.fillStyle = colour;
            ctx.fillRect(x0 + i * (bw + gap), ly + 3 + (bh - hgt), bw, hgt);
          });
        }
      }
    }

    // edges
    for (const e of s.map.edges) {
      const a = byId[e.a], b = byId[e.b];
      if (!a || !b) continue;
      ctx.strokeStyle = e.road ? ink2 : rule;
      ctx.lineWidth = e.road ? 1.8 : 1;
      if (e.river) {
        const dx = b.y - a.y, dy = a.x - b.x;
        const len = Math.hypot(dx, dy) || 1;
        const ox = (dx / len) * 2, oy = (dy / len) * 2;
        ctx.strokeStyle = accent;
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        ctx.moveTo(a.x + ox, a.y + oy);
        ctx.lineTo(b.x + ox, b.y + oy);
        ctx.moveTo(a.x - ox, a.y - oy);
        ctx.lineTo(b.x - ox, b.y - oy);
        ctx.stroke();
        ctx.globalAlpha = 1;
      } else {
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }

    // nodes
    const pulse = 0.5 + 0.5 * Math.sin((t / 2000) * Math.PI * 2);
    for (const n of nodes) {
      const colour = n.nation_color || ink2;
      const selected = state.selected && state.selected.id === n.id;
      if (n.coast) {
        // dotted shoreline round a coastal node
        ctx.beginPath();
        ctx.setLineDash([1.5, 3]);
        ctx.arc(n.x, n.y, n.radius + 5, 0, Math.PI * 2);
        ctx.strokeStyle = ink2;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.7;
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
      }
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fillStyle = n.nation ? colour + "40" : getVar("--paper-2");
      ctx.fill();
      ctx.lineWidth = selected ? 2.5 : n.is_player ? 1.6 : 1.1;
      ctx.strokeStyle = n.nation ? colour : ink2;
      ctx.stroke();
      if (selected) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (n.contested) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius + 3 + pulse * 3, 0, Math.PI * 2);
        ctx.strokeStyle = warn;
        ctx.globalAlpha = 0.35 + 0.65 * (1 - pulse);
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (n.is_capital) {
        ctx.fillStyle = ink;
        ctx.fillRect(n.x - 2.5, n.y - n.radius - 9, 5, 5);
      }
      if (n.is_band) {
        // tent glyph above the band's node
        ctx.beginPath();
        ctx.moveTo(n.x, n.y - n.radius - 12);
        ctx.lineTo(n.x - 5, n.y - n.radius - 3);
        ctx.lineTo(n.x + 5, n.y - n.radius - 3);
        ctx.closePath();
        ctx.fillStyle = accent;
        ctx.fill();
      }
      // resource glyphs inside the selected node
      if (selected && n.resources.length) {
        ctx.fillStyle = ink;
        ctx.font = "9px " + getVar("--sans");
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(n.resources.map((r) => L("resource", r)[0]).join(""), n.x, n.y);
      }
      // name label
      ctx.font = (n.is_player ? "600 " : "") + "11px " + getVar("--serif");
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = n.nation ? ink : ink2;
      ctx.fillText(n.name || n.id, n.x, n.y + n.radius + 3);
      // band mode: ground numbers on the band's own and neighbouring grounds
      if (s.map.band_mode && (n.adjacent_to_player || n.is_player)) {
        ctx.font = "10px " + getVar("--sans");
        ctx.fillStyle = n.is_player ? accent : ink2;
        ctx.fillText(formatBasket(n.ground_quality), n.x, n.y + n.radius + 16);
      }
    }
    if (hasContested && !state.reducedMotion) raf = requestAnimationFrame(draw);
  }
  draw(performance.now());
  state.mapCleanup = () => raf && cancelAnimationFrame(raf);

  function nodeAt(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * W;
    const y = ((clientY - rect.top) / rect.height) * H;
    let best = null, bestD = Infinity;
    for (const n of nodes) {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d <= n.radius + 6 && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  }

  canvas.addEventListener("mousemove", (ev) => {
    const n = nodeAt(ev.clientX, ev.clientY);
    if (!n) {
      hover.style.display = "none";
      canvas.style.cursor = "default";
      return;
    }
    canvas.style.cursor = "pointer";
    hover.innerHTML = "";
    hover.append(el("div", { class: "t", text: n.name }));
    hover.append(
      el("div", { class: "sub", text: `${L("terrain", n.terrain)}${n.river ? " · river" : ""}${n.coast ? " · coast" : ""}${n.nation_name ? " · " + n.nation_name : " · unclaimed"}` })
    );
    const kv = el("div", { class: "kv" });
    kv.append(el("span", { class: "k", text: "Population" }), el("span", { class: "v tabular", text: formatBasket(n.population) }));
    if (s.map.band_mode) {
      kv.append(el("span", { class: "k", text: "Ground" }), el("span", { class: "v tabular", text: formatBasket(n.ground_quality) }));
      kv.append(el("span", { class: "k", text: "Depletion" }), el("span", { class: "v tabular", text: formatShare(n.depletion) }));
    }
    if (n.resources.length) {
      kv.append(el("span", { class: "k", text: "Resources" }), el("span", { class: "v", text: n.resources.map((r) => L("resource", r)).join(", ") }));
    }
    for (const r of n.records) {
      kv.append(el("span", { class: "k", text: L("class", r.cls) }), el("span", { class: "v tabular", text: formatBasket(r.size) }));
    }
    for (const p of n.producers) {
      kv.append(el("span", { class: "k", text: L("producer", p.kind) }), el("span", { class: "v", text: L("method", p.method) }));
    }
    hover.append(kv);
    const prices = el("div", { class: "prices" });
    for (const g of GOOD_ORDER) prices.append(el("span", { class: "g", text: GOOD_GLYPH[g], title: L("good", g) }));
    for (const g of GOOD_ORDER) prices.append(el("span", { class: "tabular", text: formatBasket(n.prices[g] ?? 0) }));
    hover.append(prices);
    const rect = wrap.getBoundingClientRect();
    const scale = rect.width / W;
    let left = n.x * scale + 16, top = n.y * scale + 12;
    if (left + 270 > rect.width) left = n.x * scale - 280;
    if (top + 220 > rect.height) top = Math.max(0, n.y * scale - 200);
    hover.style.left = left + "px";
    hover.style.top = top + "px";
    hover.style.display = "block";
  });
  canvas.addEventListener("mouseleave", () => (hover.style.display = "none"));
  canvas.addEventListener("click", (ev) => {
    const n = nodeAt(ev.clientX, ev.clientY);
    if (!n) return;
    actions.select(n);
    draw(performance.now());
  });
  canvas.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    const n = nodeAt(ev.clientX, ev.clientY);
    if (!n) return;
    actions.select(n);
    actions.openLedgerFor(n);
  });

  // legend: nations with their three share bars
  const legend = el("div", { id: "map-legend" });
  legend.append(el("div", { class: "muted", text: "capital · consumption · output" }));
  for (const sh of s.map.nation_shares) {
    const row = el("div", { class: "n" });
    row.append(el("span", { class: "dot", style: { background: sh.color } }));
    row.append(el("span", { text: sh.name || sh.nation }));
    const bars = el("span", { class: "bars", style: { color: sh.color } });
    for (const v of [sh.capital, sh.consumption, sh.production]) {
      bars.append(el("i", { style: { height: Math.max(1, Math.round(v * 10)) + "px" }, title: formatShare(v) }));
    }
    row.append(bars);
    legend.append(row);
  }
  wrap.append(legend);
}
