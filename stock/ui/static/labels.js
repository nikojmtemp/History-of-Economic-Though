// Plain-English lookups over the tables the snapshot carries (stock/ui/labels.py and
// stock/ui/names.py). The JS never prints a raw id or a model symbol: every enum
// member goes through L(), every id through nameOf(). Two small pieces are hand-kept
// in lockstep with labels.py (like format.js with format.py): humanize() and the
// trade-law prefixes in lawLabel(); everything else arrives from the server.

let tables = {};
let names = { nations: {}, locations: {} };
let help = {};

export function setTables(snapshot) {
  tables = snapshot.labels || {};
  names = snapshot.names || { nations: {}, locations: {} };
  help = snapshot.help || {};
}

// Tooltip text (stock/ui/help.py): what a law does, what a number means, what an
// action will do. Empty when nothing is written for the key, so callers can attach
// it unconditionally and nothing shows.
export function H(group, key) {
  const table = help[group] || {};
  return table[String(key ?? "")] || "";
}

export function lawHelp(id) {
  const k = String(id ?? "");
  const laws = help.law || {};
  if (k in laws) return laws[k];
  for (const [prefix, text] of Object.entries(help.law_prefix || {})) if (k.startsWith(prefix)) return text;
  return "";
}

export function humanize(key) {
  const text = String(key ?? "").replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1).toLowerCase() : "";
}

export function L(group, key) {
  const table = tables[group] || {};
  const k = String(key ?? "");
  if (k in table) return table[k];
  return humanize(k);
}

// Laws include dynamically named trade laws (TARIFF_WARES ...) no enum lists.
export function lawLabel(id) {
  const k = String(id ?? "");
  const laws = tables.law || {};
  if (k in laws) return laws[k];
  const prefixes = [["TARIFF_", "Tariff on"], ["BOUNTY_", "Bounty on"], ["PROHIBITION_", "Prohibition of"]];
  for (const [prefix, word] of prefixes) {
    if (k.startsWith(prefix)) return `${word} ${L("good", k.slice(prefix.length)).toLowerCase()}`;
  }
  return humanize(k);
}

export const nameOf = {
  location: (id) => (id == null ? "" : names.locations[id] ?? id),
  nation: (id) => (id == null ? "" : names.nations[id] ?? id),
};

// Good-class emblems (Doc 07: a fixed glyph per class, tint used only in the routes
// and capital panels). Two-letter monograms render identically everywhere; emoji
// would bring colour of their own, which the palette rule forbids.
export const GOOD_GLYPH = {
  PROVISIONS: "Pr",
  MATERIALS: "Ma",
  WARES: "Wa",
  LUXURIES: "Lu",
  ARMS: "Ar",
  SHIPS: "Sh",
  ATTENDANCE: "At",
};
export const GOOD_ORDER = ["PROVISIONS", "MATERIALS", "WARES", "LUXURIES", "ARMS", "SHIPS", "ATTENDANCE"];
export const GOOD_VAR = {
  PROVISIONS: "--good-provisions",
  MATERIALS: "--good-materials",
  WARES: "--good-wares",
  LUXURIES: "--good-luxuries",
  ARMS: "--good-arms",
  SHIPS: "--good-ships",
  ATTENDANCE: "--good-attendance",
};
