// Small DOM helpers shared by the stage renderers: elements, meters, tables with
// sortable headers and row drawers, and the action button (label + cost badge,
// disabled with its shortfall when unaffordable) every panel draws its actions with.

import { format, formatBasket } from "./format.js";
import { H } from "./labels.js";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// Attach a tooltip (main.js shows `data-tip` on hover and on keyboard focus). A node
// without text is left alone, so callers pass H(...) lookups unconditionally.
export function tip(node, text) {
  if (text) {
    node.dataset.tip = text;
    node.classList.add("has-tip");
  }
  return node;
}

export function getVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#999";
}

export function deltaClass(v) {
  return v > 0 ? "up" : v < 0 ? "down" : "muted";
}

export function meter(value, { cls = "", max = 1, width = null, title = null, tipText = null } = {}) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  const m = el("div", { class: "meter", style: width ? { width } : {}, title });
  m.append(el("div", { class: `fill ${cls}`, style: { width: pct + "%" } }));
  if (tipText) tip(m, tipText);
  return m;
}

// A stacked hairline bar: segments = [{share, color, title, hatch}]
export function stack(segments, { height = "8px", width = "100%" } = {}) {
  const bar = el("div", { class: "stack", style: { height, width } });
  for (const s of segments) {
    if (!(s.share > 0)) continue;
    const span = el("span", {
      style: { width: s.share * 100 + "%", background: s.color, color: s.color },
      class: s.hatch ? "hatch" : "",
      title: s.title,
    });
    if (s.hatch) span.style.background = "transparent";
    bar.append(span);
  }
  return bar;
}

// Two tiny bars per tier: attained over expected.
export function pairBars(a, e, { width = "44px" } = {}) {
  const max = Math.max(a, e, 1e-9);
  const wrap = el("div", { class: "stackv", style: { gap: "2px", width } });
  wrap.append(meter(a, { max, cls: "accent" }), meter(e, { max, cls: "" }));
  return wrap;
}

export function stat(label, value, delta, unit = "basket", tipText = null) {
  const s = el("div", { class: "stat" });
  s.append(tip(el("span", { class: "k", text: label }), tipText));
  s.append(el("span", { class: "v tabular", text: typeof value === "string" ? value : format(value, unit) }));
  if (delta !== undefined && delta !== null) {
    s.append(el("span", { class: `d tabular ${deltaClass(delta)}`, text: format(delta, "delta_" + unit) }));
  }
  return s;
}

export function panelHead(title, sub, tipText = null) {
  const h = el("div", { class: "panel-head" });
  h.append(tip(el("h2", { class: "panel-title", text: title }), tipText));
  if (sub) h.append(el("span", { class: "panel-sub", text: sub }));
  return h;
}

// `text` may be a string or a node (e.g. `tip(el("span", {text}), H(...))`).
export function sectionTitle(text, ...extra) {
  const h = el("div", { class: "section-title" });
  h.append(text instanceof Node ? text : el("span", { text }));
  if (extra.length) h.append(el("span", { class: "spacer" }), ...extra);
  return h;
}

// ---------- action buttons ----------

/**
 * offer: an ActionOffer from the snapshot. onDraft(offer, payloadOverride) posts it.
 * Shows the cost before the click; disabled with "needs X · have Y" when unaffordable.
 */
export function actionButton(offer, onDraft, { label = null, cls = "", payload = null, title = null } = {}) {
  const costText = offer.cost > 0 ? formatBasket(offer.cost) : "free";
  const btn = el("button", { class: `act ${cls} ${offer.affordable ? "" : "unaffordable"}`.trim() });
  btn.append(el("span", { class: "label", text: label ?? offer.label }));
  btn.append(el("span", { class: "cost tabular", text: costText }));
  if (!offer.affordable) {
    btn.disabled = true;
    const have = Math.max(0, offer.cost - offer.shortfall);
    btn.title =
      offer.reason === "insufficient A_S"
        ? `needs ${formatBasket(offer.cost)}, have ${formatBasket(have)}`
        : offer.reason || "not available";
  } else if (title) {
    btn.title = title;
  } else {
    tip(btn, H("action", offer.kind)); // what this order will do, when it is not obvious
  }
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    onDraft(offer, payload ? payload() : null, btn);
  });
  return btn;
}

export function shortfallNote(offer) {
  if (offer.affordable || offer.reason !== "insufficient A_S") return null;
  const have = Math.max(0, offer.cost - offer.shortfall);
  return el("span", { class: "small down tabular", text: `needs ${formatBasket(offer.cost)} · have ${formatBasket(have)}` });
}

// ---------- tables ----------

/**
 * columns: [{key, label, get(row), format(v,row), numeric=true, tint(row)->'up'|'down'|'warn'|null, width}]
 * opts: {groupBy(row)->key, groupLabel(key, rows)->Node|string, drawer(row)->Node, sortState, onSort, rowKey(row)}
 */
export function table(rows, columns, opts = {}) {
  const t = el("table");
  const thead = el("thead");
  const trh = el("tr");
  const sort = opts.sortState || {};
  for (const c of columns) {
    const th = el("th", {
      class: `${c.numeric === false ? "left" : ""} ${sort.key === c.key ? "sorted " + (sort.asc ? "asc" : "") : ""}`.trim(),
      text: c.label,
      style: c.width ? { width: c.width } : {},
      title: c.title || null,
    });
    tip(th, c.tip || null);
    if (opts.onSort) {
      th.addEventListener("click", () => opts.onSort(c.key));
    }
    trh.append(th);
  }
  thead.append(trh);
  t.append(thead);
  const tbody = el("tbody");

  let ordered = rows.slice();
  if (sort.key) {
    const col = columns.find((c) => c.key === sort.key);
    if (col) {
      const getter = col.get || ((r) => r[col.key]);
      ordered.sort((a, b) => {
        const va = getter(a), vb = getter(b);
        const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
        return sort.asc ? cmp : -cmp;
      });
    }
  }

  const groups = new Map();
  if (opts.groupBy) {
    for (const r of ordered) {
      const g = opts.groupBy(r);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(r);
    }
  } else {
    groups.set(null, ordered);
  }

  for (const [g, groupRows] of groups) {
    if (g !== null) {
      const tr = el("tr", { class: "group-row" });
      const td = el("td", { colspan: columns.length, class: "left" });
      const label = opts.groupLabel ? opts.groupLabel(g, groupRows) : g;
      td.append(label instanceof Node ? label : String(label));
      tr.append(td);
      tbody.append(tr);
    }
    for (const row of groupRows) {
      const key = opts.rowKey ? opts.rowKey(row) : null;
      const tr = el("tr", { class: opts.drawer ? "clickable" : "" });
      for (const c of columns) {
        const v = c.get ? c.get(row) : row[c.key];
        const tint = c.tint ? c.tint(row) : null;
        const td = el("td", { class: `${c.numeric === false ? "left" : "tabular"} ${tint ? "tint-" + tint : ""}`.trim() });
        const content = c.render ? c.render(v, row) : c.format ? c.format(v, row) : v;
        if (content instanceof Node) td.append(content);
        else td.textContent = content ?? "";
        tr.append(td);
      }
      tbody.append(tr);
      if (opts.drawer) {
        const isOpen = key !== null && opts.openDrawers && opts.openDrawers.has(key);
        const drawerRow = el("tr", { class: "drawer", style: { display: isOpen ? "" : "none" } });
        const dtd = el("td", { colspan: columns.length });
        if (isOpen) dtd.append(opts.drawer(row));
        drawerRow.append(dtd);
        tbody.append(drawerRow);
        tr.addEventListener("click", () => {
          const open = drawerRow.style.display === "none";
          drawerRow.style.display = open ? "" : "none";
          if (open && !dtd.childElementCount) dtd.append(opts.drawer(row));
          if (opts.openDrawers && key !== null) {
            if (open) opts.openDrawers.add(key);
            else opts.openDrawers.delete(key);
          }
        });
      }
    }
  }
  t.append(tbody);
  return t;
}
