"""Doc 07 acceptance: `format()` never emits more than 3 significant figures for
baskets, always signs deltas, always uses tabular (thin-space) grouping."""

from __future__ import annotations

from stock.ui.format import (
    DOWN_ARROW,
    MINUS,
    THIN_SPACE,
    UP_ARROW,
    _round_sig,
    format,
    format_basket,
    format_delta,
)


def test_basket_never_exceeds_three_significant_figures() -> None:
    for value in (12437.0, 999999.0, 1.0, 0.0004321, 42.789, 3, 100000.0, 0.9999):
        text = format_basket(value)
        plain = text.replace(THIN_SPACE, "")
        expected = _round_sig(float(value), 3)
        assert float(plain) == expected, f"{value!r} -> {text!r}, expected {expected!r}"


def test_basket_uses_thin_space_grouping() -> None:
    assert format_basket(12437.0) == f"12{THIN_SPACE}400"
    assert format_basket(-12437.0) == f"-12{THIN_SPACE}400"
    assert "," not in format_basket(1234567.0)


def test_basket_never_emits_a_raw_float_string() -> None:
    text = format_basket(1.0 / 3.0)
    assert len(text.split(".")[-1]) <= 3 if "." in text else True
    assert "e" not in text.lower()


def test_deltas_are_always_signed_with_an_arrow_except_zero() -> None:
    up = format_delta(3.2, "share")
    down = format_delta(-140.0, "basket")
    zero = format_delta(0.0, "basket")
    assert up.startswith(UP_ARROW)
    assert "+" in up
    assert down.startswith(DOWN_ARROW)
    assert MINUS in down
    assert UP_ARROW not in zero and DOWN_ARROW not in zero


def test_share_is_a_percentage_to_one_decimal() -> None:
    assert format(0.4321, "share") == "43.2%"


def test_rate_is_two_decimals() -> None:
    assert format(0.05341, "rate") == "0.05"


def test_year_is_a_plain_integer() -> None:
    assert format(1723.0, "year") == "1723"
    assert "." not in format(1723.0, "year")
