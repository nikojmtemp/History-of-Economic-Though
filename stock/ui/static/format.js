// Number formatting (Doc 07 spec). A hand-kept port of stock/ui/format.py — see that
// module's docstring for why there are two copies (no node/tsc in the build env).

export const THIN_SPACE = " ";
export const MINUS = "−";
export const UP_ARROW = "▲";
export const DOWN_ARROW = "▼";

function roundSig(value, sig) {
  if (value === 0) return 0;
  const digits = sig - Math.floor(Math.log10(Math.abs(value))) - 1;
  const factor = Math.pow(10, digits);
  return Math.round(value * factor) / factor;
}

function groupThin(intText) {
  return Number(intText).toLocaleString("en-US").replace(/,/g, THIN_SPACE);
}

export function formatBasket(value) {
  value = Number(value);
  if (value === 0) return "0";
  let rounded = roundSig(value, 3);
  const sign = rounded < 0 ? "-" : "";
  rounded = Math.abs(rounded);
  if (rounded >= 1) {
    const intDigits = String(Math.trunc(rounded)).length;
    const decimals = Math.max(0, 3 - intDigits);
    const text = rounded.toFixed(decimals);
    const [whole, frac] = text.split(".");
    return sign + groupThin(whole) + (frac ? "." + frac : "");
  }
  return sign + rounded.toPrecision(3).replace(/0+$/, "").replace(/\.$/, "");
}

export function formatShare(value) {
  return (Number(value) * 100).toFixed(1) + "%";
}

export function formatRate(value) {
  return Number(value).toFixed(2);
}

export function formatYear(value) {
  return String(Math.round(Number(value)));
}

const MAGNITUDE = { basket: formatBasket, share: formatShare, rate: formatRate };

export function formatDelta(value, unit = "basket") {
  value = Number(value);
  const fmt = MAGNITUDE[unit];
  if (value === 0) return fmt(0);
  const arrow = value > 0 ? UP_ARROW : DOWN_ARROW;
  const sign = value > 0 ? "+" : MINUS;
  return `${arrow} ${sign}${fmt(Math.abs(value))}`;
}

export function format(value, unit) {
  switch (unit) {
    case "basket": return formatBasket(value);
    case "share": return formatShare(value);
    case "rate": return formatRate(value);
    case "year": return formatYear(value);
    case "delta_basket": return formatDelta(value, "basket");
    case "delta_share": return formatDelta(value, "share");
    case "delta_rate": return formatDelta(value, "rate");
    default: throw new Error(`unknown format unit ${unit}`);
  }
}
