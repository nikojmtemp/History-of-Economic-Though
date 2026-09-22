// The six panels (Doc 07): a serif title, a summary row of the three most important
// numbers, then a dense table with hairline rules, right-aligned tabular numbers,
// sortable headers and a drawer per row. Anything that crosses a threshold is
// tinted. Every action is drafted in place with its cost shown before the click.

import { format, formatBasket, formatRate, formatShare, formatYear } from "./format.js";
import { GOOD_GLYPH, GOOD_ORDER, GOOD_VAR, H, L, lawHelp, lawLabel, nameOf } from "./labels.js";
import {
  actionButton,
  deltaClass,
  el,
  getVar,
  meter,
  pairBars,
  panelHead,
  sectionTitle,
  shortfallNote,
  stack,
  stat,
  table,
  tip,
} from "./ui.js";

const ASSET_ORDER = ["land_shares", "fixed_assets", "stock_in_place", "herd", "tools", "hoard", "bonds", "loans_out"];

// Baskets by good as a stacked bar in the goods' colours, with the total.
function goodsStrip(byGood, { width = "90px" } = {}) {
  const total = sum(Object.values(byGood));
  const wrap = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } });
  if (!(total > 0)) {
    wrap.append(el("span", { class: "muted tabular", text: "—" }));
    return wrap;
  }
  const segs = GOOD_ORDER.filter((g) => byGood[g] > 0).map((g) => ({
    share: byGood[g] / total,
    color: getVar(GOOD_VAR[g]),
    title: `${L("good", g)} ${formatBasket(byGood[g])}`,
  }));
  wrap.append(stack(segs, { width }), el("span", { class: "tabular", text: formatBasket(total) }));
  return wrap;
}

// Quantities by good as glyph + number, e.g. ◆ 2 890 · ▲ 510.
function goodsList(byGood, fmt = formatBasket) {
  const parts = GOOD_ORDER.filter((g) => byGood[g] > 0);
  if (!parts.length) return el("span", { class: "muted", text: "—" });
  const wrap = el("span", { class: "tabular" });
  parts.forEach((g, i) => {
    if (i) wrap.append(document.createTextNode(" · "));
    wrap.append(el("span", { style: { color: getVar(GOOD_VAR[g]) }, text: GOOD_GLYPH[g], title: L("good", g) }));
    wrap.append(document.createTextNode(" " + fmt(byGood[g])));
  });
  return wrap;
}

// Classes with a number each, e.g. Tenant farmers 113 · Labourers 40.
function classList(byClass, fmt = formatBasket) {
  const entries = Object.entries(byClass).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return el("span", { class: "muted", text: "—" });
  return el("span", { class: "tabular", text: entries.map(([cls, v]) => `${L("class", cls)} ${fmt(v)}`).join(" · ") });
}

// A territory's year in one line: what its producers made, what its people spent,
// what stayed unsold (panels.territories).
function territoryLine(ctx, loc) {
  const t = (ctx.state.snapshot.panels.territories || []).find((x) => x.location === loc);
  if (!t) return null;
  const line = el("span", { class: "muted small tabular" });
  line.append(
    tip(el("span", { text: `made ${formatBasket(t.made_value)}` }), H("flow", "made")),
    document.createTextNode(" · "),
    tip(el("span", { text: `spent ${formatBasket(t.spent_total)}` }), H("flow", "spent")),
    document.createTextNode(" · "),
    tip(el("span", { class: t.unsold_value > t.made_value ? "warn" : "", text: `unsold ${formatBasket(t.unsold_value)}` }), H("flow", "unsold"))
  );
  if (t.shortfall_total > 0) {
    line.append(document.createTextNode(" · "), tip(el("span", { class: "down", text: `short ${formatBasket(t.shortfall_total)}` }), H("column", "shortfall")));
  }
  return line;
}

function sum(xs) {
  return xs.reduce((a, b) => a + b, 0);
}

function offersOf(state, pred) {
  return state.snapshot.actions.filter(pred);
}

function sortable(ctx, panel) {
  const st = (ctx.state.sort[panel] = ctx.state.sort[panel] || {});
  return {
    sortState: st,
    onSort: (key) => {
      if (st.key === key) st.asc = !st.asc;
      else Object.assign(st, { key, asc: false });
      ctx.rerender();
    },
  };
}

function drawers(ctx, panel) {
  return (ctx.state.drawers[panel] = ctx.state.drawers[panel] || new Set());
}

// ---------------------------------------------------------------------------
// 1. Ledger
// ---------------------------------------------------------------------------

export function renderLedger(stage, ctx) {
  const rows = ctx.state.snapshot.panels.ledger;
  stage.append(panelHead("Ledger", "records by territory · class × place"));
  const population = sum(rows.map((r) => r.size));
  const wealth = sum(rows.map((r) => sum(Object.values(r.wealth_by_asset))));
  const shortfall = sum(rows.map((r) => r.shortfall));
  const summary = el("div", { class: "summary-row" });
  summary.append(
    stat("Population", population, undefined, "basket", H("column", "people")),
    stat("Wealth", wealth, undefined, "basket", H("column", "wealth_by_asset")),
    stat("Unmet need", shortfall, undefined, "basket", H("column", "shortfall"))
  );
  summary.append(stat("Records", String(rows.length)));
  stage.append(summary);
  if (!rows.length) {
    stage.append(el("div", { class: "muted", text: "No records yet." }));
    return;
  }
  const priceOffers = offersOf(ctx.state, (o) => o.kind === "PRICE_CONTROL");
  const columns = [
    { key: "cls", label: "Class", numeric: false, get: (r) => L("class", r.cls) },
    { key: "size", label: "People", format: formatBasket, tip: H("column", "people") },
    {
      key: "works_at",
      label: "Works at",
      numeric: false,
      tip: H("column", "works_at"),
      get: (r) => sum(Object.values(r.works_at)),
      render: (v, r) => {
        const entries = Object.entries(r.works_at).sort((a, b) => b[1] - a[1]);
        if (!entries.length) return el("span", { class: "muted", text: r.sources.length ? "owns" : "—" });
        return el("span", { class: "tabular", text: entries.map(([k, jobs]) => `${L("producer", k)} ${formatBasket(jobs)}`).join(" · ") });
      },
    },
    {
      key: "income",
      label: "Income",
      format: formatBasket,
      tip: H("column", "income"),
      tint: (r) => (r.size > 0 && r.income > 0 && r.income / r.size < 1 ? "warn" : null),
    },
    { key: "spend", label: "Spends on", tip: H("column", "spends_on"), get: (r) => sum(Object.values(r.spend_by_good)), render: (v, r) => goodsStrip(r.spend_by_good) },
    {
      key: "wealth",
      label: "Wealth by asset",
      tip: H("column", "wealth_by_asset"),
      get: (r) => sum(Object.values(r.wealth_by_asset)),
      render: (v, r) => {
        const wrap = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } });
        const total = v || 1;
        const ink = getVar("--ink");
        const segs = ASSET_ORDER.filter((a) => r.wealth_by_asset[a] > 0).map((a, i) => ({
          share: r.wealth_by_asset[a] / total,
          color: ink,
          title: `${L("asset", a)} ${formatBasket(r.wealth_by_asset[a])}`,
          hatch: i % 2 === 1,
        }));
        wrap.append(stack(segs, { width: "90px" }), el("span", { class: "tabular", text: formatBasket(v) }));
        return wrap;
      },
    },
    { key: "hoard", label: "Hoard", format: formatBasket, tip: H("column", "hoard") },
    {
      key: "need",
      label: "Need met · subsistence / comfort / standing",
      tip: H("column", "need_met"),
      get: (r) => -r.shortfall,
      render: (v, r) => {
        const wrap = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "6px" } });
        for (const t of ["subsistence", "comfort", "standing"]) wrap.append(pairBars(r.A[t], r.E[t], { width: "36px" }));
        return wrap;
      },
    },
    { key: "shortfall", label: "Shortfall", format: formatBasket, tint: (r) => (r.shortfall > 0 ? "warn" : null), tip: H("column", "shortfall") },
    { key: "walk_away", label: "Walk-away", format: formatRate, tint: (r) => (r.walk_away < 0.2 ? "down" : null), tip: H("column", "walk_away") },
    { key: "authority", label: "Authority", format: formatBasket, tip: H("column", "authority") },
  ];
  stage.append(
    table(rows, columns, {
      ...sortable(ctx, "ledger"),
      groupBy: (r) => r.location,
      groupLabel: (loc, groupRows) => {
        const row = el("div", { class: "row" });
        row.append(el("span", { text: nameOf.location(loc) }));
        row.append(el("span", { class: "muted small tabular", text: `${formatBasket(sum(groupRows.map((r) => r.size)))} people` }));
        const flowLine = territoryLine(ctx, loc);
        if (flowLine) row.append(el("span", { class: "muted small", text: "·" }), flowLine);
        row.append(el("span", { class: "grow" }));
        const offer = priceOffers.find((o) => o.payload.location === loc);
        if (offer) {
          const input = el("input", { type: "number", step: "0.05", min: "0", value: offer.payload.price.toFixed(2), title: "ceiling price of provisions" });
          input.addEventListener("click", (e) => e.stopPropagation());
          row.append(
            el("span", { class: "small muted", text: "Provisions ceiling" }),
            input,
            actionButton(offer, ctx.draft, { label: "Cap price", payload: () => ({ ...offer.payload, price: Number(input.value) }) })
          );
        }
        return row;
      },
      rowKey: (r) => `${r.location}|${r.cls}`,
      openDrawers: drawers(ctx, "ledger"),
      drawer: (r) => {
        const d = el("div", { class: "grid-3" });
        // production → income: what each producer paid this class
        const inc = el("div", { class: "kv" });
        for (const src of r.sources) {
          const parts = [];
          if (src.wages > 0) parts.push(`${r.works_at[src.producer] ? "labour" : "wages"} ${formatBasket(src.wages)}`);
          if (src.profit > 0) parts.push(`profit ${formatBasket(src.profit)}`);
          if (src.rent > 0) parts.push(`rent ${formatBasket(src.rent)}`);
          inc.append(el("span", { class: "k", text: L("producer", src.producer) }), el("span", { class: "v tabular", text: parts.join(" · ") }));
        }
        if (!r.sources.length) inc.append(el("span", { class: "k muted", text: "no producer pays this class here" }), el("span"));
        if (r.sources.length) inc.append(el("span", { class: "k", text: "Paid" }), el("span", { class: "v tabular", text: formatBasket(r.paid) }));
        if (r.taxed > 0) inc.append(tip(el("span", { class: "k", text: "Taxed" }), H("column", "taxed")), el("span", { class: "v tabular down", text: `−${formatBasket(r.taxed)}` }));
        inc.append(el("span", { class: "k", text: "Income" }), el("span", { class: "v tabular", text: formatBasket(r.income) }));
        d.append(el("div", {}, tip(el("div", { class: "small muted", text: "Income by source" }), H("column", "income")), inc));
        // income → consumption: what it bought, what it kept
        const sp = el("div", { class: "kv" });
        for (const g of GOOD_ORDER) {
          if (!(r.spend_by_good[g] > 0)) continue;
          sp.append(el("span", { class: "k", style: { color: getVar(GOOD_VAR[g]) }, text: `${GOOD_GLYPH[g]} ${L("good", g)}` }), el("span", { class: "v tabular", text: formatBasket(r.spend_by_good[g]) }));
        }
        sp.append(el("span", { class: "k", text: "Saved" }), el("span", { class: "v tabular", text: formatBasket(r.saved) }));
        d.append(el("div", {}, tip(el("div", { class: "small muted", text: "Spending by good" }), H("column", "spends_on")), sp));
        const kv = el("div", { class: "kv" });
        for (const t of ["subsistence", "comfort", "standing"]) {
          kv.append(tip(el("span", { class: "k", text: L("tier", t) }), H("tier", t.toUpperCase())), el("span", { class: "v tabular", text: `${formatBasket(r.A[t])} of ${formatBasket(r.E[t])}` }));
        }
        d.append(el("div", {}, tip(el("div", { class: "small muted", text: "Attained of expected" }), H("column", "need_met")), kv));
        const standing = el("div");
        standing.append(el("div", { class: "small muted", text: "Standing allocation · attendance vs luxuries" }));
        standing.append(
          stack(
            [
              { share: r.standing_split.attendance, color: getVar(GOOD_VAR.ATTENDANCE), title: `Attendance ${formatShare(r.standing_split.attendance)}` },
              { share: r.standing_split.luxuries, color: getVar(GOOD_VAR.LUXURIES), title: `Luxuries ${formatShare(r.standing_split.luxuries)}` },
            ],
            { height: "10px" }
          )
        );
        standing.append(el("div", { class: "small tabular", text: `${formatShare(r.standing_split.attendance)} · ${formatShare(r.standing_split.luxuries)}` }));
        d.append(standing);
        const assets = el("div", { class: "kv" });
        for (const a of ASSET_ORDER) {
          if (!(r.wealth_by_asset[a] > 0)) continue;
          assets.append(el("span", { class: "k", text: L("asset", a) }), el("span", { class: "v tabular", text: formatBasket(r.wealth_by_asset[a]) }));
        }
        d.append(el("div", {}, el("div", { class: "small muted", text: "Wealth" }), assets));
        return d;
      },
    })
  );
}

// ---------------------------------------------------------------------------
// 2. Incidence
// ---------------------------------------------------------------------------

export function renderIncidence(stage, ctx) {
  const p = ctx.state.snapshot.panels;
  const s = ctx.state;
  stage.append(panelHead("Incidence", "who is assessed, who bears it · lagged one year", H("panel", "incidence")));
  const collected = sum(p.incidence.map((c) => c.collected));
  const cost = sum(p.incidence.map((c) => c.cost));
  const summary = el("div", { class: "summary-row" });
  summary.append(
    stat("Collected", collected, undefined, "basket", H("column", "collected")),
    stat("Collection cost", cost, undefined, "basket", H("column", "collection_cost"))
  );
  for (const sym of ["r_market", "r_legal", "r_sovereign"]) {
    summary.append(stat(L("symbol", sym), formatRate(p[sym]), undefined, "basket", H("symbol", sym)));
  }
  stage.append(summary);

  const rateOffers = offersOf(s, (o) => o.kind === "SET_TAX_RATE");
  if (!p.incidence.length) {
    stage.append(el("div", { class: "muted", text: s.snapshot.player.seat === "BAND" ? "A band levies nothing." : "No instrument enacted. Enact a revenue law in Politics." }));
  }
  const cards = el("div", { class: "grid-2" });
  for (const card of p.incidence) {
    const c = el("div", { class: "card" });
    const title = el("div", { class: "card-title" });
    title.append(tip(el("span", { text: card.label || lawLabel(card.instrument) }), lawHelp(card.instrument)), el("span", { class: "spacer" }));
    const offer = rateOffers.find((o) => o.payload.instrument === card.instrument);
    if (offer) {
      const input = el("input", { type: "number", step: "1", min: "0", max: "100", value: (card.rate * 100).toFixed(0), style: { width: "58px" } });
      title.append(el("span", { class: "small muted", text: "rate %" }), input);
      title.append(actionButton(offer, ctx.draft, { label: "Set", payload: () => ({ ...offer.payload, rate: Number(input.value) / 100 }) }));
    } else {
      title.append(el("span", { class: "small muted tabular", text: `rate ${formatShare(card.rate)}` }));
    }
    c.append(title);
    const classes = Array.from(new Set([...Object.keys(card.assessed_on), ...Object.keys(card.borne_by)]));
    const max = Math.max(1e-9, ...Object.values(card.assessed_on), ...Object.values(card.borne_by));
    const grid = el("div", { class: "kv", style: { gridTemplateColumns: "auto 1fr auto" } });
    for (const cls of classes) {
      const a = card.assessed_on[cls] || 0, b = card.borne_by[cls] || 0;
      grid.append(el("span", { class: "k", text: L("class", cls) }));
      const bars = el("div", { class: "stackv", style: { gap: "2px" } });
      bars.append(meter(a, { max, cls: "" }), meter(b, { max, cls: "accent" }));
      grid.append(bars);
      grid.append(el("span", { class: "v tabular small", html: `${formatBasket(a)}<br><span class="up">${formatBasket(b)}</span>` }));
    }
    c.append(grid);
    c.append(
      tip(
        el("div", { class: "small muted", style: { marginTop: "6px" }, text: "ink: assessed on · accent: borne by" }),
        `${H("column", "assessed_on")} ${H("column", "borne_by")}`
      )
    );
    c.append(el("div", { class: "small tabular", text: `collected ${formatBasket(card.collected)} · cost ${formatBasket(card.cost)}` }));
    cards.append(c);
  }
  stage.append(cards);

  // budget
  const budgetOffer = offersOf(s, (o) => o.kind === "SET_BUDGET")[0];
  stage.append(sectionTitle(tip(el("span", { text: "Budget" }), H("panel", "budget")), el("span", { class: "small muted", text: "shares of collected revenue · ink productive, hatched unproductive" })));
  const ink = getVar("--ink"), ink2 = getVar("--ink-2");
  stage.append(
    stack(
      p.budget.map((seg) => ({
        share: seg.share,
        color: seg.productive ? ink : ink2,
        hatch: !seg.productive,
        title: `${L("budget", seg.name)} ${formatShare(seg.share)} · draw ${formatBasket(seg.draw)}`,
      })),
      { height: "18px" }
    )
  );
  // Sliders that keep the whole at 100: moving one line takes from or gives to the
  // unlocked others in proportion to what they have; a locked line keeps its share.
  const shares = Object.fromEntries(p.budget.map((seg) => [seg.name, seg.share * 100]));
  const locked = new Set();
  const sliders = {};
  const readouts = {};
  const rebalance = (moved) => {
    const target = shares[moved];
    const others = p.budget.map((seg) => seg.name).filter((n) => n !== moved && !locked.has(n));
    const fixed = p.budget.map((seg) => seg.name).filter((n) => n !== moved && locked.has(n)).reduce((a, n) => a + shares[n], 0);
    const room = Math.max(0, 100 - fixed);
    if (target > room) shares[moved] = room;
    const rest = room - shares[moved];
    const pool = others.reduce((a, n) => a + shares[n], 0);
    for (const n of others) shares[n] = pool > 0 ? (shares[n] / pool) * rest : rest / others.length;
    for (const n of Object.keys(shares)) {
      sliders[n].value = shares[n].toFixed(0);
      readouts[n].textContent = `${shares[n].toFixed(0)}%`;
    }
  };
  const form = el("div", { class: "budget-form", style: { marginTop: "8px" } });
  for (const seg of p.budget) {
    const name = seg.name;
    const row = el("div", { class: "budget-row" });
    row.append(tip(el("span", { class: `small ${seg.productive ? "" : "muted"}`, text: L("budget", name) }), H("budget", name)));
    const slider = el("input", { type: "range", min: "0", max: "100", step: "1", value: shares[name].toFixed(0), disabled: !budgetOffer });
    slider.addEventListener("input", () => {
      shares[name] = Number(slider.value);
      rebalance(name);
    });
    sliders[name] = slider;
    row.append(slider);
    readouts[name] = el("span", { class: "tabular small right", text: `${shares[name].toFixed(0)}%` });
    row.append(readouts[name]);
    row.append(el("span", { class: "small muted tabular right", text: `draw ${formatBasket(seg.draw)}` }));
    const lock = el("button", { class: "quiet small lock", text: "○", title: "Hold this line while the others move" });
    lock.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (locked.has(name)) locked.delete(name);
      else locked.add(name);
      lock.textContent = locked.has(name) ? "●" : "○";
      lock.classList.toggle("active", locked.has(name));
    });
    row.append(lock);
    form.append(row);
  }
  if (budgetOffer) {
    const actions = el("div", { class: "row", style: { marginTop: "6px", gap: "10px" } });
    actions.append(
      actionButton(budgetOffer, ctx.draft, {
        label: "Set budget",
        payload: () => ({ shares: Object.fromEntries(Object.entries(shares).map(([k, v]) => [k, Number(v.toFixed(2))])) }),
      })
    );
    actions.append(tip(el("span", { class: "small muted", text: "the lines always sum to 100 · ● holds a line" }), H("action", "SET_BUDGET")));
    form.append(actions);
  }
  stage.append(form);

  // debt policy and funding
  const debt = offersOf(s, (o) => o.kind === "SET_DEBT_POLICY");
  const funding = offersOf(s, (o) => o.kind === "SET_FUNDING_MODE");
  if (debt.length || funding.length) {
    stage.append(sectionTitle(tip(el("span", { text: "When the debt falls due" }), H("panel", "debt_due")), el("span", { class: "small muted", text: "the three answers, with their cost" })));
    const row = el("div", { class: "row wrap" });
    for (const o of debt) {
      const active = o.payload.policy === p.debt_choice;
      const btn = actionButton(o, ctx.draft, { cls: active ? "active" : o.payload.policy === "DEFAULT" ? "danger" : "" });
      row.append(tip(btn, H("debt_policy", o.payload.policy) || H("action", "SET_DEBT_POLICY")));
    }
    row.append(el("span", { class: "muted small", text: "·" }));
    row.append(tip(el("span", { class: "small muted", text: "extra spending funded by" }), H("action", "SET_FUNDING_MODE")));
    for (const o of funding) {
      const btn = actionButton(o, ctx.draft, { cls: s.snapshot.panels.funding_mode === o.payload.mode ? "active" : "" });
      row.append(tip(btn, H("funding_mode", o.payload.mode) || H("action", "SET_FUNDING_MODE")));
    }
    stage.append(row);
    stage.append(el("div", { class: "small muted", style: { marginTop: "4px" }, text: `current: ${L("debt_policy", p.debt_choice)}` }));
  }
}

// ---------------------------------------------------------------------------
// 3. Capital
// ---------------------------------------------------------------------------

export function renderCapital(stage, ctx) {
  const p = ctx.state.snapshot.panels;
  stage.append(panelHead("Capital", "producers by territory · the split of output", H("panel", "capital")));
  const rows = p.capital;
  const summary = el("div", { class: "summary-row" });
  summary.append(
    stat(L("symbol", "r_bar"), formatRate(p.r_bar), undefined, "basket", H("symbol", "r_bar")),
    stat("Stock in place", sum(rows.map((r) => r.stock)), undefined, "basket", H("column", "stock")),
    stat("Output value", sum(rows.map((r) => r.V)), undefined, "basket", H("column", "output_value"))
  );
  const jobsText = `${formatBasket(sum(rows.map((r) => r.jobs_filled)))} of ${formatBasket(sum(rows.map((r) => r.jobs_total)))}`;
  summary.append(stat("Jobs filled", jobsText, undefined, "basket", H("column", "jobs")));
  stage.append(summary);
  if (!rows.length) {
    stage.append(el("div", { class: "muted", text: "No producers yet." }));
    return;
  }
  const columns = [
    { key: "kind", label: "Producer", numeric: false, get: (r) => L("producer", r.kind) },
    { key: "method", label: "Method", numeric: false, get: (r) => L("method", r.method), tip: H("column", "method") },
    { key: "stock", label: "Stock", format: formatBasket, tip: H("column", "stock") },
    { key: "jobs", label: "Jobs", get: (r) => r.jobs_filled, render: (v, r) => `${formatBasket(r.jobs_filled)} / ${formatBasket(r.jobs_total)}`, tint: (r) => (r.jobs_total > 0 && r.jobs_filled < r.jobs_total * 0.5 ? "warn" : null), tip: H("column", "jobs") },
    { key: "V", label: "Output value", format: formatBasket, tip: H("column", "output_value") },
    { key: "makes", label: "Makes", tip: H("column", "makes"), get: (r) => sum(Object.values(r.makes)), render: (v, r) => goodsList(r.makes) },
    { key: "worked_by", label: "Worked by", numeric: false, tip: H("column", "worked_by"), get: (r) => r.jobs_filled, render: (v, r) => classList(r.worked_by) },
    {
      key: "owned_by",
      label: "Owners",
      numeric: false,
      tip: H("column", "owners"),
      get: (r) => Object.keys(r.owned_by).length,
      render: (v, r) => {
        const owners = Object.keys(r.owned_by).length ? r.owned_by : r.land_by;
        return classList(owners, formatShare);
      },
    },
    {
      key: "split",
      label: "Labour · profit · rent",
      tip: H("column", "split"),
      get: (r) => r.labour_share,
      render: (v, r) => {
        const wrap = el("div", { class: "row", style: { justifyContent: "flex-end" } });
        const ink = getVar("--ink"), accent = getVar("--accent"), ink2 = getVar("--ink-2");
        wrap.append(
          stack(
            [
              { share: r.labour_share, color: ink, title: `labour ${formatShare(r.labour_share)}` },
              { share: r.profit_share, color: accent, title: `profit ${formatShare(r.profit_share)}` },
              { share: r.rent_share, color: ink2, title: `rent ${formatShare(r.rent_share)}` },
            ],
            { width: "96px" }
          ),
          el("span", { class: "small tabular", text: `${formatShare(r.labour_share)} · ${formatShare(r.profit_share)} · ${formatShare(r.rent_share)}` })
        );
        return wrap;
      },
    },
    {
      key: "deviation_from_r_bar",
      label: "Return vs average",
      tip: H("column", "return_vs_average"),
      format: (v) => format(v, "delta_rate"),
      tint: (r) => (r.deviation_from_r_bar > 0.02 ? "up" : r.deviation_from_r_bar < -0.02 ? "down" : null),
    },
  ];
  stage.append(
    table(rows, columns, {
      ...sortable(ctx, "capital"),
      groupBy: (r) => r.location,
      groupLabel: (loc) => {
        const row = el("div", { class: "row" });
        row.append(el("span", { text: nameOf.location(loc) }));
        const flowLine = territoryLine(ctx, loc);
        if (flowLine) row.append(flowLine);
        return row;
      },
      rowKey: (r) => `${r.location}|${r.kind}|${r.method}`,
      openDrawers: drawers(ctx, "capital"),
      drawer: (r) => {
        const d = el("div", { class: "grid-3" });
        const kv = el("div", { class: "kv" });
        const pairs = [
          ["Stock in place", formatBasket(r.stock)],
          ["Output value", formatBasket(r.V)],
          ["Return vs average", format(r.deviation_from_r_bar, "delta_rate")],
        ];
        for (const [k, v] of pairs) kv.append(el("span", { class: "k", text: k }), el("span", { class: "v tabular", text: v }));
        d.append(el("div", {}, el("div", { class: "small muted", text: "Producer" }), kv));
        // production → income: who the value went to
        const who = el("div", { class: "kv" });
        const occupation = r.kind === "HUNTING" || r.kind === "HERDING";
        for (const [label, byClass] of [[occupation ? "Own labour" : "Wages", r.wages_to], ["Profit", r.profit_to], ["Rent", r.rent_to]]) {
          if (!Object.keys(byClass).length) continue;
          who.append(el("span", { class: "k", text: label }), el("span", { class: "v tabular" }, classList(byClass)));
        }
        if (!who.childElementCount) who.append(el("span", { class: "k muted", text: "no output value this year" }), el("span"));
        d.append(el("div", {}, tip(el("div", { class: "small muted", text: "Value paid to" }), H("column", "split")), who));
        // production → consumption: its goods in this territory's market
        const t = (ctx.state.snapshot.panels.territories || []).find((x) => x.location === r.location);
        const mk = el("div", { class: "kv" });
        for (const g of GOOD_ORDER) {
          if (!(r.makes[g] > 0)) continue;
          const made = t ? t.made[g] : 0, wanted = t ? t.wanted[g] : 0, unsold = t ? t.unsold[g] : 0;
          mk.append(
            el("span", { class: "k", style: { color: getVar(GOOD_VAR[g]) }, text: `${GOOD_GLYPH[g]} ${L("good", g)}` }),
            el("span", { class: "v tabular", style: { whiteSpace: "normal", textAlign: "left" }, text: `${formatBasket(r.makes[g])} of ${formatBasket(made)} made here · wanted ${formatBasket(wanted)} · unsold ${formatBasket(unsold)}` })
          );
        }
        if (!mk.childElementCount) mk.append(el("span", { class: "k muted", text: "nothing made this year" }), el("span"));
        d.append(el("div", {}, tip(el("div", { class: "small muted", text: "Makes, against the market here" }), H("flow", "market")), mk));
        return d;
      },
    })
  );
}

// ---------------------------------------------------------------------------
// 4. Politics
// ---------------------------------------------------------------------------

export function renderPolitics(stage, ctx) {
  const politics = ctx.state.snapshot.panels.politics;
  const s = ctx.state;
  const isBand = politics.seat === "BAND";
  stage.append(panelHead("Politics", isBand ? "a band decides by consensus" : "authority, interests, laws, focus"));

  const top = el("div", { class: "grid-2", style: { gridTemplateColumns: "220px 1fr" } });
  const big = el("div", { class: "stat" });
  big.append(tip(el("span", { class: "k", text: isBand ? "Consensus" : L("symbol", "A_S") }), H("symbol", isBand ? "consensus" : "A_S")));
  big.append(el("span", { class: "v", style: { fontSize: "34px", fontFamily: "var(--serif)" }, text: formatBasket(politics.A_S) }));
  big.append(tip(el("span", { class: "small muted", text: L("seat", politics.seat) }), H("seat", politics.seat)));
  top.append(big);
  const bars = el("div", { class: "stackv", style: { gap: "4px" } });
  const scale = Math.max(1e-9, ...politics.interests.map((i) => i.authority * (1 + i.radicalism)));
  for (const bar of politics.interests) {
    const row = el("div", { class: "row" });
    row.append(el("span", { class: "small", style: { width: "120px" }, text: L("interest", bar.interest) }));
    const track = el("div", { class: "meter", style: { flex: "1", height: "10px" } });
    const w = Math.min(100, (bar.authority / scale) * 100);
    track.append(el("div", { class: "fill accent", style: { width: w + "%" } }));
    if (bar.radicalism > 0) {
      const extra = el("div", { class: "fill hatch", style: { left: w + "%", width: Math.min(100 - w, (bar.authority * bar.radicalism / scale) * 100) + "%", background: "transparent", color: getVar("--accent") } });
      track.append(extra);
    }
    row.append(track);
    row.append(el("span", { class: "tabular small", style: { width: "56px", textAlign: "right" }, text: formatBasket(bar.authority) }));
    row.append(tip(el("span", { class: "tabular small muted", style: { width: "64px", textAlign: "right" }, text: `rad ${formatRate(bar.radicalism)}` }), H("symbol", "radicalism")));
    bars.append(row);
  }
  bars.append(tip(el("div", { class: "small muted", text: "authority in accent · radicalism as the hatched extension" }), H("panel", "interests")));
  top.append(bars);
  stage.append(top);

  if (isBand) return;

  // focus
  stage.append(sectionTitle(tip(el("span", { text: "Focus" }), H("panel", "focus")), el("span", { class: "small muted", text: "one at a time · switching forfeits progress" })));
  const focusCard = el("div", { class: "card" });
  if (politics.focus) {
    const f = politics.focus;
    const row = el("div", { class: "row" });
    row.append(el("span", { class: "serif", text: `${L("focus", f.kind)} · ${L("node", f.node)}${f.location ? " · " + nameOf.location(f.location) : ""}` }));
    row.append(meter(f.progress, { cls: "accent", width: "120px", title: `progress ${formatShare(f.progress)}` }));
    row.append(el("span", { class: "small tabular", text: `${formatShare(f.progress)} · upkeep ${formatBasket(f.upkeep)}` }));
    row.append(el("span", { class: "grow" }));
    if (politics.clear_focus) row.append(actionButton(politics.clear_focus, ctx.draft));
    focusCard.append(row);
  } else {
    focusCard.append(el("div", { class: "muted small", text: "No focus set." }));
  }
  if (politics.set_focus) {
    const form = el("div", { class: "row wrap", style: { marginTop: "8px" } });
    const kindSel = el("select");
    for (const opt of politics.focus_options) kindSel.append(el("option", { value: opt.kind, text: L("focus", opt.kind) }));
    const kindTip = () => tip(kindSel, H("focus", kindSel.value));
    const nodeSel = el("select");
    const locSel = el("select");
    locSel.append(el("option", { value: "", text: "every territory" }));
    for (const loc of s.snapshot.map.nodes.filter((n) => n.is_player)) locSel.append(el("option", { value: loc.id, text: loc.name }));
    const refresh = () => {
      const opt = politics.focus_options.find((o) => o.kind === kindSel.value);
      nodeSel.innerHTML = "";
      for (const n of opt ? opt.nodes : []) nodeSel.append(el("option", { value: n, text: L("node", n) }));
      locSel.style.display = opt && opt.takes_location ? "" : "none";
    };
    kindSel.addEventListener("change", () => {
      refresh();
      kindTip();
    });
    refresh();
    kindTip();
    form.append(kindSel, nodeSel, locSel);
    form.append(
      actionButton(politics.set_focus, ctx.draft, {
        label: "Set focus",
        payload: () => ({ kind: kindSel.value, node: nodeSel.value, location: locSel.style.display === "none" || !locSel.value ? null : locSel.value }),
      })
    );
    focusCard.append(form);
  }
  stage.append(focusCard);

  // laws by branch
  stage.append(sectionTitle(tip(el("span", { text: "Laws" }), H("panel", "laws")), el("span", { class: "small muted", text: "enforcement meter · enact or repeal at the cost shown · veto an Interest's pressing demand" })));
  const branches = {};
  for (const law of politics.laws) (branches[law.branch] = branches[law.branch] || []).push(law);
  const open = drawers(ctx, "politics-branches");
  for (const [branch, laws] of Object.entries(branches)) {
    const details = el("details", { class: "branch", open: open.has(branch) });
    details.addEventListener("toggle", () => (details.open ? open.add(branch) : open.delete(branch)));
    const enacted = laws.filter((l) => l.enacted).length;
    const pressing = laws.reduce((n, l) => n + l.vetoes.length, 0);
    const summary = el("summary");
    summary.append(el("span", { text: L("branch", branch) }), el("span", { class: "count", text: `${enacted} of ${laws.length} in force${pressing ? ` · ${pressing} pressing` : ""}` }));
    details.append(summary);
    for (const law of laws) {
      const row = el("div", { class: `law-row ${law.enacted ? "enacted" : ""}` });
      const name = tip(el("span", { class: "name", text: law.label || lawLabel(law.id) }), lawHelp(law.id));
      if (law.veto_cooldown_until != null && law.veto_cooldown_until > s.snapshot.header.year) {
        name.append(el("span", { class: "cool", text: `vetoed until ${formatYear(law.veto_cooldown_until)}` }));
      }
      row.append(name);
      row.append(meter(law.enforcement, { cls: law.enacted ? "up" : "", tipText: `Enforcement ${formatShare(law.enforcement)}. ${H("symbol", "enforcement")}` }));
      const acts = el("div", { class: "actions" });
      if (law.enact) acts.append(actionButton(law.enact, ctx.draft, { label: "Enact" }));
      if (law.repeal) acts.append(actionButton(law.repeal, ctx.draft, { label: "Repeal" }));
      for (const v of law.vetoes) {
        const vetoBtn = actionButton(v, ctx.draft, { label: `Veto · ${L("interest", v.payload.interest).replace(" interest", "")}`, cls: "danger" });
        acts.append(tip(vetoBtn, `${v.label}. ${H("action", "VETO")}`));
      }
      row.append(acts);
      details.append(row);
    }
    stage.append(details);
  }
}

// ---------------------------------------------------------------------------
// 5. Routes and treaties
// ---------------------------------------------------------------------------

function priceStrip(a, b) {
  const grid = el("div", { class: "kv", style: { gridTemplateColumns: `repeat(${GOOD_ORDER.length}, 34px)`, gap: "1px 4px", textAlign: "right" } });
  for (const g of GOOD_ORDER) grid.append(el("span", { class: "small", style: { color: getVar(GOOD_VAR[g]), textAlign: "right" }, text: GOOD_GLYPH[g], title: L("good", g) }));
  for (const g of GOOD_ORDER) grid.append(el("span", { class: "small tabular", text: formatBasket(a[g] ?? 0), title: `${L("good", g)} · ${formatBasket(a[g] ?? 0)} vs ${formatBasket(b[g] ?? 0)}` }));
  for (const g of GOOD_ORDER) grid.append(el("span", { class: "small tabular muted", text: formatBasket(b[g] ?? 0), title: `${L("good", g)} · ${formatBasket(a[g] ?? 0)} vs ${formatBasket(b[g] ?? 0)}` }));
  return grid;
}

// The terms of a treaty or proposal, each with what it binds the other party to.
function termsLine(terms) {
  const line = el("div", { class: "small" });
  if (!terms.length) {
    line.textContent = "no terms";
    return line;
  }
  terms.forEach((k, i) => {
    if (i) line.append(document.createTextNode(" · "));
    line.append(tip(el("span", { text: L("term", k) }), H("term", k)));
  });
  return line;
}

export function renderRoutes(stage, ctx) {
  const routes = ctx.state.snapshot.panels.routes;
  const s = ctx.state;
  stage.append(panelHead("Routes and treaties", "prices at both ends · terms and their keeping", H("panel", "routes")));
  const summary = el("div", { class: "summary-row" });
  summary.append(
    stat("Routes", String(routes.routes.length)),
    stat("Volume", sum(routes.routes.map((r) => r.volume)), undefined, "basket", H("column", "volume")),
    stat("Customs", sum(routes.routes.map((r) => r.customs)), undefined, "basket", H("column", "customs"))
  );
  summary.append(stat("Treaties", String(routes.treaties.length)));
  stage.append(summary);

  if (routes.routes.length) {
    const columns = [
      { key: "a", label: "Route", numeric: false, get: (r) => `${r.a_name || nameOf.location(r.a)} ↔ ${r.b_name || nameOf.location(r.b)}` },
      { key: "prices", label: "Prices there · here", get: (r) => r.volume, render: (v, r) => priceStrip(r.prices_a, r.prices_b) },
      { key: "capacity", label: "Capacity", format: formatBasket, tip: H("column", "capacity") },
      { key: "gap", label: "Widest gap", tip: H("column", "gap"), get: (r) => Math.max(0, ...Object.values(r.gap)), render: (v, r) => {
          const best = Object.entries(r.gap).sort((x, y) => y[1] - x[1])[0];
          return best ? `${L("good", best[0])} ${formatBasket(best[1])}` : "—";
        } },
      { key: "volume", label: "Volume", format: formatBasket, tip: H("column", "volume") },
      { key: "customs", label: "Customs", format: formatBasket, tip: H("column", "customs") },
    ];
    stage.append(table(routes.routes, columns, sortable(ctx, "routes")));
  } else {
    stage.append(el("div", { class: "muted", text: "No route touches your territory." }));
  }

  stage.append(sectionTitle(tip(el("span", { text: "Treaties" }), H("panel", "treaties"))));
  if (!routes.treaties.length) stage.append(el("div", { class: "muted small", text: "None in force." }));
  const cards = el("div", { class: "grid-2" });
  for (const t of routes.treaties) {
    const c = el("div", { class: "card" });
    const title = el("div", { class: "card-title" });
    title.append(el("span", { text: `${t.a_name || nameOf.nation(t.a)} — ${t.b_name || nameOf.nation(t.b)}` }), el("span", { class: "spacer" }));
    if (t.breached) title.append(el("span", { class: "tag warn", text: "breach" }));
    c.append(title);
    c.append(termsLine(t.terms));
    const kv = el("div", { class: "kv", style: { gridTemplateColumns: "auto 1fr auto", marginTop: "6px" } });
    for (const [who, enf] of [[t.a, t.enforcement_a], [t.b, t.enforcement_b]]) {
      kv.append(el("span", { class: "k", text: nameOf.nation(who) }), meter(enf, { cls: enf < 0.7 ? "warn" : "up" }), el("span", { class: "v tabular small", text: formatShare(enf) }));
    }
    c.append(kv);
    cards.append(c);
  }
  stage.append(cards);

  if (routes.proposals.length) {
    stage.append(sectionTitle("Proposals to you"));
    const pc = el("div", { class: "grid-2" });
    for (const p of routes.proposals) {
      const c = el("div", { class: "card" });
      const title = el("div", { class: "card-title" });
      title.append(el("span", { text: p.initiator_name || nameOf.nation(p.initiator) }), el("span", { class: "spacer" }));
      if (p.accept) title.append(actionButton(p.accept, ctx.draft, { label: "Accept" }));
      c.append(title);
      c.append(termsLine(p.terms));
      pc.append(c);
    }
    stage.append(pc);
  }

  const proposeOffers = offersOf(s, (o) => o.kind === "PROPOSE_TREATY");
  if (proposeOffers.length) {
    stage.append(sectionTitle("Propose a treaty", el("span", { class: "small muted", text: "terms bind the other party · they answer at the boundary" })));
    const form = el("div", { class: "card" });
    const row = el("div", { class: "row wrap" });
    const sel = el("select");
    for (const o of proposeOffers) sel.append(el("option", { value: o.payload.target, text: nameOf.nation(o.payload.target) }));
    row.append(sel);
    const checks = {};
    for (const k of routes.term_kinds) {
      const lab = el("label", { class: "row small", style: { gap: "4px" } });
      const cb = el("input", { type: "checkbox", checked: k === "NON_AGGRESSION" });
      checks[k] = cb;
      lab.append(cb, tip(el("span", { text: L("term", k) }), H("term", k)));
      row.append(lab);
    }
    const holder = el("span");
    const renderBtn = () => {
      holder.innerHTML = "";
      const o = proposeOffers.find((x) => x.payload.target === sel.value) || proposeOffers[0];
      holder.append(
        actionButton(o, ctx.draft, {
          label: "Propose",
          payload: () => ({ target: sel.value, terms: Object.entries(checks).filter(([, cb]) => cb.checked).map(([k]) => ({ kind: k })) }),
        })
      );
    };
    sel.addEventListener("change", renderBtn);
    renderBtn();
    row.append(holder);
    form.append(row);
    stage.append(form);
  }

  const hostile = Object.entries(routes.hostility);
  if (hostile.length) {
    stage.append(sectionTitle(tip(el("span", { text: "Hostility" }), H("panel", "hostility")), el("span", { class: "small muted", text: "with each rival · deeper tint, more hostile" })));
    const grid = el("div", { class: "row wrap" });
    for (const [key, v] of hostile) {
      const [a, b] = key.split("|");
      const other = a === s.snapshot.player_nation ? b : a;
      const cell = el("div", { class: "hairline", style: { padding: "6px 10px", background: `color-mix(in srgb, ${getVar("--down")} ${Math.round(Math.min(1, v) * 45)}%, transparent)` } });
      cell.append(el("div", { class: "small", text: nameOf.nation(other) }), el("div", { class: "tabular", text: formatRate(v) }));
      grid.append(cell);
    }
    stage.append(grid);
  }
}

// ---------------------------------------------------------------------------
// 6. Security
// ---------------------------------------------------------------------------

function aroundZero(rows) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.value)));
  const wrap = el("div", { class: "stackv", style: { gap: "3px" } });
  for (const r of rows) {
    const line = el("div", { class: "row" });
    line.append(tip(el("span", { class: "small", style: { width: "170px" }, text: r.label }), r.tip || null));
    const track = el("div", { style: { position: "relative", flex: "1", height: "8px", background: "var(--rule)" } });
    const half = Math.abs(r.value) / max * 50;
    const fill = el("div", { style: { position: "absolute", top: 0, bottom: 0, background: r.value >= 0 ? "var(--up)" : "var(--down)", left: r.value >= 0 ? "50%" : `${50 - half}%`, width: half + "%" } });
    track.append(fill, el("div", { style: { position: "absolute", left: "50%", top: "-2px", bottom: "-2px", width: "1px", background: "var(--ink-2)" } }));
    line.append(track);
    line.append(el("span", { class: `small tabular ${deltaClass(r.value)}`, style: { width: "72px", textAlign: "right" }, text: format(r.value, "delta_basket") }));
    wrap.append(line);
  }
  return wrap;
}

export function renderSecurity(stage, ctx) {
  const sec = ctx.state.snapshot.panels.security;
  const s = ctx.state;
  stage.append(panelHead("Security", "strength, threat, and what each class feels"));
  const summary = el("div", { class: "summary-row" });
  const big = el("div", { class: "stat" });
  big.append(tip(el("span", { class: "k", text: L("symbol", "M") }), H("symbol", "M")));
  big.append(el("span", { class: "v", style: { fontSize: "30px", fontFamily: "var(--serif)" }, text: formatBasket(sec.M) }));
  summary.append(big);
  summary.append(stat("Doctrine", L("doctrine", sec.doctrine), undefined, "basket", H("doctrine", sec.doctrine)));
  const chain = Object.entries(sec.factors).map(([k, v]) => `${L("factor", k)} ${formatRate(v)}`).join("  ×  ");
  summary.append(stat("Factors", chain, undefined, "basket", H("symbol", "M")));
  summary.append(stat(L("symbol", "N_bar"), formatBasket(sec.N_bar), undefined, "basket", H("symbol", "N_bar")));
  stage.append(summary);

  const rows = [
    { label: L("symbol", "PSV"), value: sec.PSV, tip: H("symbol", "PSV") },
    { label: L("symbol", "PTV_ext"), value: -sec.PTV_ext, tip: H("symbol", "PTV_ext") },
  ];
  for (const [cls, v] of Object.entries(sec.PTV_int_by_class)) rows.push({ label: `${L("symbol", "PTV_int")} · ${L("class", cls)}`, value: -v, tip: H("symbol", "PTV_int") });
  for (const [cls, v] of Object.entries(sec.N_r_by_class)) rows.push({ label: `${L("symbol", "N_r")} · ${L("class", cls)}`, value: v, tip: H("symbol", "N_r") });
  rows.push({ label: L("symbol", "N_bar"), value: sec.N_bar, tip: H("symbol", "N_bar") });
  stage.append(sectionTitle(tip(el("span", { text: "Protection and threat" }), H("panel", "protection_threat")), el("span", { class: "small muted", text: "protection to the right, threat to the left" })));
  stage.append(aroundZero(rows));

  stage.append(sectionTitle("Rivals"));
  const warOffers = offersOf(s, (o) => o.kind === "DECLARE_WAR");
  const columns = [
    { key: "name", label: "Nation", numeric: false, render: (v, r) => { const w = el("span"); w.append(el("span", { class: "dot", style: { background: r.color, marginRight: "6px" } }), r.name || nameOf.nation(r.nation)); return w; } },
    { key: "M", label: L("symbol", "M"), format: formatBasket, tip: H("column", "M") },
    { key: "hostility", label: "Hostility", format: formatRate, tint: (r) => (r.hostility > 0.5 ? "down" : null), tip: H("column", "hostility") },
    { key: "distance", label: "Distance", format: (v) => formatBasket(v), tip: H("column", "distance") },
    { key: "status", label: "", numeric: false, render: (v, r) => {
        const w = el("span", { class: "row", style: { justifyContent: "flex-end" } });
        if (r.at_war) w.append(el("span", { class: "tag down", text: "at war" }));
        const o = warOffers.find((x) => x.payload.target === r.nation);
        if (o) w.append(actionButton(o, ctx.draft, { label: "Declare war", cls: "danger" }));
        return w;
      } },
  ];
  stage.append(table(sec.rivals, columns, sortable(ctx, "security")));

  if (sec.wars.length) {
    stage.append(sectionTitle("Wars"));
    const cards = el("div", { class: "grid-2" });
    for (const w of sec.wars) {
      const c = el("div", { class: "card" });
      const title = el("div", { class: "card-title" });
      title.append(el("span", { text: `${w.role === "attacker" ? "Against" : "Defending against"} ${w.other_name || nameOf.nation(w.other)}` }), el("span", { class: "spacer" }), el("span", { class: "small muted tabular", text: `since ${formatYear(w.started)}` }));
      c.append(title);
      const contested = Object.entries(w.contested);
      c.append(el("div", { class: "small", text: contested.length ? "Contested: " + contested.map(([loc, y]) => `${nameOf.location(loc)} (${y}y)`).join(", ") : "No territory contested." }));
      if (w.peace_offer) {
        const po = w.peace_offer;
        c.append(el("div", { class: "small", style: { marginTop: "4px" }, text: `Peace on the table · cession ${po.cession.map(nameOf.location).join(", ") || "none"} · tribute ${formatBasket(po.tribute_amount)} × ${po.tribute_years}y` }));
      }
      const acts = el("div", { class: "row wrap", style: { marginTop: "6px" } });
      const accept = offersOf(s, (o) => o.kind === "ACCEPT_PEACE" && o.payload.target === w.other)[0];
      if (accept) acts.append(actionButton(accept, ctx.draft, { label: "Accept peace" }));
      const offer = offersOf(s, (o) => o.kind === "OFFER_PEACE" && o.payload.target === w.other)[0];
      if (offer) {
        const amount = el("input", { type: "number", min: "0", step: "1", value: "0", style: { width: "64px" }, title: "tribute per year" });
        const years = el("input", { type: "number", min: "0", step: "1", value: "0", style: { width: "48px" }, title: "years" });
        acts.append(el("span", { class: "small muted", text: "tribute" }), amount, el("span", { class: "small muted", text: "× years" }), years);
        acts.append(actionButton(offer, ctx.draft, { label: "Offer peace", payload: () => ({ ...offer.payload, tribute_amount: Number(amount.value), tribute_years: Number(years.value) }) }));
      }
      for (const b of offersOf(s, (o) => o.kind === "BESIEGE" && o.payload.target === w.other)) {
        acts.append(actionButton(b, ctx.draft, { label: `Besiege ${nameOf.location(b.payload.location)}` }));
      }
      c.append(acts);
      cards.append(c);
    }
    stage.append(cards);
  }

  const raids = offersOf(s, (o) => o.kind === "DECLARE_RAID");
  const repress = offersOf(s, (o) => o.kind === "REPRESS")[0];
  if (raids.length || repress) {
    stage.append(sectionTitle("Orders", el("span", { class: "small muted", text: "raids on the frontier · the army turned inward" })));
    const row = el("div", { class: "row wrap" });
    for (const r of raids) row.append(actionButton(r, ctx.draft, { label: `Raid ${nameOf.location(r.payload.location)}` }));
    if (repress) row.append(actionButton(repress, ctx.draft, { cls: "danger" }));
    stage.append(row);
    const notes = [repress, ...raids].map(shortfallNote).filter(Boolean);
    if (notes.length) stage.append(el("div", { class: "row wrap", style: { marginTop: "4px" } }, notes[0]));
  }
}
