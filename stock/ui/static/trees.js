// The two technology trees, drawn whole (DD §6): Tree I — WHAT a territory can make,
// one chain per territory; Tree II — HOW a nation produces, defends and lends, three
// chains. Nodes sit in chain order on a hairline, lit nodes filled in ink with the
// year they lit, idle nodes (lit but unused) hatched, unlit nodes hollow, the Focus's
// target ringed in accent.

import { formatYear } from "./format.js";
import { H, L } from "./labels.js";
import { el, panelHead, sectionTitle } from "./ui.js";

const SVG = "http://www.w3.org/2000/svg";
const STEP = 118, R = 11, TOP = 26, LABEL_H = 44;

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

function wrapLabel(text, max = 16) {
  const words = text.split(" ");
  const lines = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > max && cur) {
      lines.push(cur);
      cur = w;
    } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 3);
}

export function chainSvg(chain, { hatchId }) {
  const n = chain.nodes.length;
  const width = STEP * (n - 1) + 2 * STEP * 0.5 + 40;
  const height = TOP + R + LABEL_H + 8;
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "tree-chain" });
  const x = (i) => 20 + STEP * 0.5 + i * STEP;
  // the chain line, drawn ink up to the last lit node and rule beyond
  let lastLit = -1;
  chain.nodes.forEach((node, i) => node.lit && (lastLit = i));
  if (n > 1) {
    svg.append(svgEl("line", { x1: x(0), y1: TOP, x2: x(n - 1), y2: TOP, stroke: "var(--rule)", "stroke-width": 1 }));
    if (lastLit > 0) svg.append(svgEl("line", { x1: x(0), y1: TOP, x2: x(lastLit), y2: TOP, stroke: "var(--ink)", "stroke-width": 1.5 }));
  }
  chain.nodes.forEach((node, i) => {
    const cx = x(i);
    const g = svgEl("g", { class: `tree-node ${node.lit ? "lit" : ""} ${node.idle ? "idle" : ""}` });
    if (node.focus) g.append(svgEl("circle", { cx, cy: TOP, r: R + 5, fill: "none", stroke: "var(--accent)", "stroke-width": 1.5, "stroke-dasharray": "3 3" }));
    g.append(
      svgEl("circle", {
        cx,
        cy: TOP,
        r: R,
        fill: node.lit ? (node.idle ? `url(#${hatchId})` : "var(--ink)") : "var(--paper)",
        stroke: node.lit ? "var(--ink)" : "var(--ink-2)",
        "stroke-width": node.lit ? 1.5 : 1,
      })
    );
    g.append(svgEl("text", { x: cx, y: TOP + 4, "text-anchor": "middle", "font-size": 10, fill: node.lit && !node.idle ? "var(--paper)" : "var(--ink-2)", "font-family": "var(--sans)" }, String(i + 1)));
    const lines = wrapLabel(L("node", node.id));
    lines.forEach((line, k) => {
      g.append(
        svgEl("text", { x: cx, y: TOP + R + 14 + k * 12, "text-anchor": "middle", "font-size": 11, "font-family": "var(--serif)", fill: node.lit ? "var(--ink)" : "var(--ink-2)" }, line)
      );
    });
    if (node.lit && node.lit_year !== null) {
      g.append(
        svgEl("text", { x: cx, y: TOP + R + 14 + lines.length * 12, "text-anchor": "middle", "font-size": 10, "font-family": "var(--sans)", fill: "var(--ink-2)" }, (node.idle ? "idle · " : "") + formatYear(node.lit_year))
      );
    }
    const title = svgEl("title", {}, `${L("node", node.id)} · ${node.lit ? (node.idle ? "lit, idle" : "lit") : "not yet"}${node.lit_year !== null ? " · " + formatYear(node.lit_year) : ""}`);
    g.append(title);
    svg.append(g);
  });
  return svg;
}

function hatchDefs(id) {
  const svg = svgEl("svg", { width: 0, height: 0, style: "position:absolute" });
  const defs = svgEl("defs");
  const pat = svgEl("pattern", { id, width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  pat.append(svgEl("rect", { width: 5, height: 5, fill: "var(--paper)" }));
  pat.append(svgEl("rect", { width: 2, height: 5, fill: "var(--ink)" }));
  defs.append(pat);
  svg.append(defs);
  return svg;
}

function legend() {
  const row = el("div", { class: "row wrap small muted", style: { gap: "16px", marginTop: "4px" } });
  row.append(el("span", { html: '<span class="tree-key lit"></span> lit' }));
  row.append(el("span", { html: '<span class="tree-key idle"></span> lit, idle' }));
  row.append(el("span", { html: '<span class="tree-key"></span> not yet' }));
  row.append(el("span", { html: '<span class="tree-key focus"></span> focus target' }));
  return row;
}

export function renderTree1(stage, ctx) {
  const trees = ctx.state.snapshot.panels.trees;
  stage.append(panelHead("Tree I · What", "what each territory can make · nodes in order, lit once and for good", H("panel", "trees")));
  stage.append(legend());
  stage.append(hatchDefs("hatch-t1"));
  if (!trees.tree1.length) stage.append(el("div", { class: "muted", text: "No territory held." }));
  for (const chain of trees.tree1) {
    const lit = chain.nodes.filter((n) => n.lit).length;
    stage.append(sectionTitle(chain.label, el("span", { class: "small muted tabular", text: `${lit} of ${chain.nodes.length} lit` })));
    const wrap = el("div", { class: "tree-wrap" });
    wrap.append(chainSvg(chain, { hatchId: "hatch-t1" }));
    stage.append(wrap);
  }
}

export function renderTree2(stage, ctx) {
  const trees = ctx.state.snapshot.panels.trees;
  stage.append(panelHead("Tree II · How", "production, defence and credit · a nation's methods in the order they can be reached", H("panel", "trees")));
  stage.append(legend());
  stage.append(hatchDefs("hatch-t2"));
  for (const chain of trees.tree2) {
    const lit = chain.nodes.filter((n) => n.lit).length;
    stage.append(sectionTitle(chain.label, el("span", { class: "small muted tabular", text: `${lit} of ${chain.nodes.length} lit` })));
    const wrap = el("div", { class: "tree-wrap" });
    wrap.append(chainSvg(chain, { hatchId: "hatch-t2" }));
    stage.append(wrap);
  }
}
