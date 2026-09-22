// Curves (Doc 07): three stacked ink plots on a shared time axis, every nation as a
// thin line in its ink, the player heavier; the perceived-security band behind
// curve 1 as a warn wash; regression markers as short vertical ticks; a scrub cursor
// that reports every value at that year in the footer.

import { format, formatYear } from "./format.js";
import { L } from "./labels.js";
import { el, getVar } from "./ui.js";

const W = 940, H = 560;
const CURVES = [
  { key: "produce_per_head", unit: "basket" },
  { key: "labour_share", unit: "share" },
  { key: "freedom_index", unit: "share" },
];

export function renderCurves(stage, state, actions) {
  const s = state.snapshot;
  const hidden = state.hiddenNations;
  const canvas = el("canvas", { class: "chart" });
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = "100%";
  canvas.style.maxWidth = W + "px";
  stage.append(canvas);
  const ctx = canvas.getContext("2d");
  const years = s.curves.years;
  const plotH = H / 3;
  const padL = 46, padR = 12;
  const xOf = (idx) => padL + (idx / Math.max(1, years.length - 1)) * (W - padL - padR);

  const scales = CURVES.map(({ key }) => {
    const series = s.curves.series[key] || {};
    let all = Object.entries(series).filter(([n]) => !hidden.has(n)).map(([, v]) => v).flat();
    if (key === "produce_per_head") all = all.concat(s.curves.n_bar_band);
    const min = Math.min(0, ...all);
    const max = Math.max(key === "produce_per_head" ? 1 : 1, ...all);
    return { min, max: max === min ? min + 1 : max };
  });

  function draw(cursorIdx = null) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    CURVES.forEach(({ key, unit }, i) => {
      const top = i * plotH;
      const { min, max } = scales[i];
      const yOf = (v) => top + plotH - 16 - ((v - min) / (max - min)) * (plotH - 34);
      ctx.strokeStyle = getVar("--rule");
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padL, top + 12);
      ctx.lineTo(padL, top + plotH - 16);
      ctx.lineTo(W - padR, top + plotH - 16);
      ctx.stroke();
      // gridlines + axis labels
      ctx.fillStyle = getVar("--ink-2");
      ctx.font = "10px " + getVar("--sans");
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (const f of [0, 0.5, 1]) {
        const v = min + (max - min) * f;
        const y = yOf(v);
        ctx.fillText(format(v, unit), padL - 6, y);
        if (f > 0) {
          ctx.strokeStyle = getVar("--rule");
          ctx.globalAlpha = 0.5;
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(W - padR, y);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }
      ctx.textAlign = "left";
      ctx.font = "13px " + getVar("--serif");
      ctx.fillStyle = getVar("--ink");
      ctx.fillText(L("symbol", key), padL + 6, top + 12);

      if (key === "produce_per_head" && s.curves.n_bar_band.length) {
        ctx.fillStyle = getVar("--warn") + "26";
        ctx.beginPath();
        s.curves.n_bar_band.forEach((v, idx) => {
          const x = xOf(idx), y = yOf(Math.max(min, Math.min(max, v)));
          if (idx === 0) ctx.moveTo(x, top + plotH - 16);
          ctx.lineTo(x, y);
        });
        ctx.lineTo(xOf(s.curves.n_bar_band.length - 1), top + plotH - 16);
        ctx.closePath();
        ctx.fill();
      }
      const series = s.curves.series[key] || {};
      for (const [nation, values] of Object.entries(series)) {
        if (hidden.has(nation)) continue;
        const info = s.nations.find((n) => n.id === nation);
        const isPlayer = nation === s.player_nation;
        ctx.strokeStyle = (info && info.color) || "#999";
        ctx.lineWidth = isPlayer ? 2.2 : 1;
        ctx.beginPath();
        values.forEach((v, idx) => {
          const x = xOf(idx), y = yOf(v);
          if (idx === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      if (key === "produce_per_head") {
        for (const markerYear of s.curves.regression_markers) {
          const idx = years.indexOf(markerYear);
          if (idx < 0) continue;
          const x = xOf(idx);
          ctx.strokeStyle = getVar("--down");
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(x, top + plotH - 16);
          ctx.lineTo(x, top + plotH - 30);
          ctx.stroke();
        }
      }
      // x-axis year ticks
      ctx.fillStyle = getVar("--ink-2");
      ctx.font = "10px " + getVar("--sans");
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const step = Math.max(1, Math.ceil(years.length / 8));
      years.forEach((y, idx) => {
        if (idx % step === 0 || idx === years.length - 1) ctx.fillText(formatYear(y), xOf(idx), top + plotH - 13);
      });
    });
    if (cursorIdx !== null && years.length) {
      const x = xOf(cursorIdx);
      ctx.strokeStyle = getVar("--accent");
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, 6);
      ctx.lineTo(x, H - 6);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
  draw();

  canvas.addEventListener("mousemove", (ev) => {
    if (!years.length) return;
    const rect = canvas.getBoundingClientRect();
    const x = ((ev.clientX - rect.left) / rect.width) * W;
    const idx = Math.max(0, Math.min(years.length - 1, Math.round(((x - padL) / (W - padL - padR)) * (years.length - 1))));
    draw(idx);
    const parts = [];
    for (const { key, unit } of CURVES) {
      const series = s.curves.series[key] || {};
      const vals = Object.entries(series)
        .filter(([n]) => !hidden.has(n))
        .map(([n, v]) => `${s.names.nations[n] || n} ${format(v[idx] ?? 0, unit)}`)
        .join(", ");
      parts.push(`${L("symbol", key)}: ${vals}`);
    }
    actions.footer(`${formatYear(years[idx])} · ${parts.join(" · ")}`);
  });
  canvas.addEventListener("mouseleave", () => {
    draw();
    actions.footer(null);
  });

  const legend = el("div", { id: "curves-legend" });
  for (const n of s.nations) {
    const b = el("button", { class: `quiet ${hidden.has(n.id) ? "off" : ""}` });
    b.append(el("span", { class: "swatch", style: { background: n.color } }), el("span", { text: n.name || n.id }));
    if (n.ended) b.append(el("span", { class: "tag", text: "ended" }));
    b.addEventListener("click", () => {
      if (hidden.has(n.id)) hidden.delete(n.id);
      else hidden.add(n.id);
      actions.rerender();
    });
    legend.append(b);
  }
  legend.append(el("span", { class: "muted small", text: "▏regression" }));
  stage.append(legend);
}
