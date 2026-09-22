"""Number formatting (Doc 07 spec, `ui/format.ts`, "one function"): baskets to 3
significant figures with thin-space grouping (`12 400`), shares as `%` to one
decimal, rates to two, deltas always signed with an arrow glyph, years as plain
integers. Never a raw float.

This is the tested, canonical Python implementation. The browser needs its own copy
(`stock/ui/static/format.js`) since nothing in this environment can compile or run
TypeScript/JS as part of the Python test suite (no `node`/`tsc` available) — the two
are hand-kept in lockstep; see `build/DEVIATIONS-IN-PROGRESS.md`.
"""

from __future__ import annotations

from math import floor, log10

THIN_SPACE = " "
MINUS = "−"
UP_ARROW = "▲"
DOWN_ARROW = "▼"

Unit = str  # "basket" | "share" | "rate" | "delta_basket" | "delta_share" | "delta_rate" | "year"


def _round_sig(value: float, sig: int) -> float:
    if value == 0:
        return 0.0
    digits = sig - int(floor(log10(abs(value)))) - 1
    return round(value, digits)


def _group_thin(int_text: str) -> str:
    return f"{int(int_text):,}".replace(",", THIN_SPACE)


def format_basket(value: float) -> str:
    """3 significant figures; thousands grouped with a thin space (`12 400`)."""

    value = float(value)
    if value == 0:
        return "0"
    rounded = _round_sig(value, 3)
    sign = "-" if rounded < 0 else ""
    rounded = abs(rounded)
    if rounded >= 1:
        int_digits = len(str(int(rounded)))
        decimals = max(0, 3 - int_digits)
        text = f"{rounded:.{decimals}f}"
        whole, _, frac = text.partition(".")
        whole = _group_thin(whole)
        return f"{sign}{whole}" + (f".{frac}" if frac else "")
    return f"{sign}{rounded:.3g}"


def format_share(value: float) -> str:
    """A share in [0, 1] (or any ratio) as a percentage to one decimal."""

    return f"{float(value) * 100:.1f}%"


def format_rate(value: float) -> str:
    """A rate (e.g. `r_bar`) to two decimals, unscaled."""

    return f"{float(value):.2f}"


def format_year(value: float) -> str:
    return str(int(round(float(value))))


_MAGNITUDE_FORMATTERS = {
    "basket": format_basket,
    "share": format_share,
    "rate": format_rate,
}


def format_delta(value: float, magnitude_unit: str = "basket") -> str:
    """Always signed, with an arrow glyph — except zero, which carries neither
    (the caller renders it in `--ink-2` with no arrow, per the spec's colour rule)."""

    value = float(value)
    formatter = _MAGNITUDE_FORMATTERS[magnitude_unit]
    if value == 0:
        return formatter(0.0)
    arrow = UP_ARROW if value > 0 else DOWN_ARROW
    sign = "+" if value > 0 else MINUS
    magnitude = formatter(abs(value))
    return f"{arrow} {sign}{magnitude}"


def format(value: float, unit: Unit) -> str:  # noqa: A001 - "format", the spec's own name
    """The one entry point every number on screen passes through (Doc 07 spec)."""

    if unit == "basket":
        return format_basket(value)
    if unit == "share":
        return format_share(value)
    if unit == "rate":
        return format_rate(value)
    if unit == "year":
        return format_year(value)
    if unit == "delta_basket":
        return format_delta(value, "basket")
    if unit == "delta_share":
        return format_delta(value, "share")
    if unit == "delta_rate":
        return format_delta(value, "rate")
    raise ValueError(f"unknown format unit {unit!r}")
