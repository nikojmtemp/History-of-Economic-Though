"""The event feed's string table (Doc 07 spec): `kind` -> a template of field names and
numbers. This is the only prose the game produces, and it is not prose at all — every
template is mechanical effect and numbers, generated once here, server-side.

The kind/field pairs below were taken empirically from the engine (`stock/meta`,
`stock/politics`, `stock/security`, `stock/trade`, `stock/finance`, `stock/engine`) by
running both scenarios for several seeds and recording every `EventRecord.kind` and
its `numbers` keys — not by reading each call site, since a stale reading would drift
from what the engine actually emits. `tests/test_strings.py` re-derives that set the
same way and checks it against `TEMPLATES` on every run, so this file cannot go stale
silently.

Two engine gaps, logged rather than patched (07 owns `stock/ui/*` only, not the
modules that emit these):
  - `law_self_enacted`/`law_lapsed` carry no law identifier in `numbers` (only
    `authority_I`/`A_S`/`opposition`, or `enforcement`) — the templates below cannot
    name the law, only compare the numbers, unlike the spec's own illustrative
    example. See `build/DEVIATIONS-IN-PROGRESS.md`.
  - The player's own `ENACT`/`REPEAL`/etc. (`politics.legislation.enact`/`repeal`)
    never emit an event at all, so a player's own queued action resolving would
    otherwise vanish from the feed. `resolved_*` kinds below are synthesised at the
    API layer (`stock/api/server.py`), not read from the ledger, to cover this.

A `location` field, where present, is a lossy `hash(id) % N` placeholder the engine
uses internally (Doc 04/05's own choice) — not human-legible, so no template prints
it; the API layer resolves it back to a real location id for the deep link instead.
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING

from stock.ui.format import format_basket

if TYPE_CHECKING:
    from stock.sim.ledger import EventRecord

#: Exact tokens the spec forbids anywhere in a template (07 §"Event feed").
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = ('"', "“", "Smith", "WoN", "HL ", "§")
FORBIDDEN_WORDS: tuple[str, ...] = ("should", "recommend", "because")

#: kind -> template. `{field}` placeholders must be a subset of that kind's
#: `EventRecord.numbers` keys (checked by `tests/test_strings.py` against a live run).
TEMPLATES: dict[str, str] = {
    # meta/events.py — exogenous events
    "plague": "Plague · shrink {shrink}",
    "harvest_failure": "Harvest failure · stock −{lost}",
    "watt": "Steam · unlocked",
    "trade_fair": "Trade fair · merchants +{merchants_added}",
    "ore_find": "Ore deposit found",
    "coal_find": "Coal seam found",
    "wild_herds": "Wild herds arrive",
    # meta/trees.py
    # (rendered by node name instead — see render_event; this is the numbers-only fallback)
    "node_lit": "Advance unlocked · tree {tree} branch {branch} node {node}",
    # meta/regression.py
    "regression": "Regression · strength left {M_surviving} · regressions so far {regressions}",
    "nation_ended": "Nation ended",
    # politics/unrest.py — U-threshold events (soldiers get mutiny/desertion instead)
    "strike": "Strike · unrest {U} among {size} · ratio {ratio}",
    "revolt": "Revolt · unrest {U} among {size} · ratio {ratio}",
    "riot": "Riot · unrest {U} among {size} · ratio {ratio}",
    "mutiny": "Mutiny · unrest {U} among {size} · ratio {ratio}",
    "desertion": "Desertion · unrest {U} among {size} · ratio {ratio}",
    # politics/state.py
    "settled_handover": "Settled · state authority {A_S} · people {size}",
    "protection_of_property": (
        "Protection of property · interest authority {authority_I} vs threshold {threshold}"
    ),
    # politics/legislation.py
    "law_self_enacted": (
        "Law self-enacted by an interest · its authority {authority_I} "
        "vs state {A_S} + opposition {opposition}"
    ),
    "law_lapsed": "Law lapsed · enforcement {enforcement}",
    # `law` is the LawId value; `render_event` names it (see `_custom_law_name`)
    "law_by_custom": "Settled by custom · people {population} of {threshold}",
    # finance/credit.py
    "private_credit_default": "Private lenders default · written off {written_off}",
    "default": "Sovereign default · written off {debt_written_off}",
    # finance/taxation.py
    "tax_uncollectable": "Tax uncollectable · owed {owed} · shortfall {shortfall}",
    "draw_unfunded_defence": "Defence unfunded · draw {draw} of {need}",
    "draw_unfunded_justice": "Justice unfunded · draw {draw} of {need}",
    "draw_unfunded_works": "Works unfunded · draw {draw} of {need}",
    "draw_unfunded_service": "Service unfunded · draw {draw} of {need}",
    "draw_unfunded_court": "Court unfunded · draw {draw} of {need}",
    "draw_unfunded_transfers": "Transfers unfunded · draw {draw} of {need}",
    # engine/population.py, engine/consumption.py, engine/mobility.py
    "record_extinct": "Class died out · people {size} · wealth {wealth_total}",
    "retainer_dismissal": "Retainers dismissed −{dismissed} · {old_size}→{new_size}",
    "location_claimed": "Territory claimed · people {size}",
    # security/war.py
    "war_declared": "War declared",
    "aggression": "Aggression · cost {cost}",
    "raid": "Raid · goods {taken_goods} · hoard {taken_hoard} · herd {taken_herd} · odds {p_win}",
    "raided": "Raided · goods −{lost_goods} · hoard −{lost_hoard} · herd −{lost_herd}",
    "defence": "Defence held · odds {p_win}",
    "location_lost": "Territory lost · population {population} · producers {producers} · stock {stock}",
    "location_taken": "Territory taken · population {population} · producers {producers} · stock {stock}",
    "victory": "Victory",
    "defeat": "Defeat",
    # trade/treaties.py
    "breach": "Treaty breached · enforcement {enforcement} · years {years_breached}",
    "treaty_broken_against_us": "Treaty broken against us · enforcement {enforcement}",
    # synthesised at the API layer: a player/AI action resolving at the year boundary
    "resolved_enact": "Enacted · cost {cost}",
    "resolved_repeal": "Repealed · cost {cost}",
    "resolved_veto": "Vetoed · cost {cost}",
    "resolved_set_focus": "Focus set · cost {cost}",
    "resolved_clear_focus": "Focus cleared · cost {cost}",
    "resolved_set_tax_rate": "Tax rate set · cost {cost}",
    "resolved_set_budget": "Budget set · cost {cost}",
    "resolved_set_debt_policy": "Debt policy set · cost {cost}",
    "resolved_set_funding_mode": "Funding mode set · cost {cost}",
    "resolved_declare_raid": "Raid declared · cost {cost}",
    "resolved_declare_war": "War declared · cost {cost}",
    "resolved_besiege": "Siege · cost {cost}",
    "resolved_offer_peace": "Peace offered · cost {cost}",
    "resolved_accept_peace": "Peace accepted · cost {cost}",
    "resolved_propose_treaty": "Treaty proposed · cost {cost}",
    "resolved_accept_treaty": "Treaty accepted · cost {cost}",
    "resolved_repress": "Repression · cost {cost}",
    "resolved_price_control": "Price control set · cost {cost}",
    "resolved_band_move": "Moved · cost {cost}",
    "resolved_band_follow_herds": "Followed herds · cost {cost}",
    "resolved_band_settle": "Settled · cost {cost}",
    "resolved_band_raid": "Raided · cost {cost}",
    "resolved_band_barter": "Bartered · cost {cost}",
}

#: A queued action step 14 skipped (illegal by the time it applied, or declined by its
#: handler — `sim/year.apply_actions` marks it): the feed says so instead of "done".
TEMPLATES.update(
    {k.replace("resolved_", "rejected_"): "Not applied" for k in list(TEMPLATES) if k.startswith("resolved_")}
)


def template_fields(template: str) -> set[str]:
    """The `{field}` names a template references."""

    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def check_forbidden(text: str) -> None:
    for token in FORBIDDEN_SUBSTRINGS:
        if token in text:
            raise ValueError(f"forbidden token {token!r} in template text: {text!r}")
    lowered = text.lower()
    for word in FORBIDDEN_WORDS:
        if word in lowered:
            raise ValueError(f"forbidden word {word!r} in template text: {text!r}")


def _node_lit_name(numbers: dict[str, float]) -> str | None:
    """`node_lit` encodes (tree, branch, node) as enum values (`meta/trees.py`'s
    module docstring); decode them back to the node's plain-English label."""

    from stock.core.producers import MethodId
    from stock.core.trees import CreditNode, DefenceNode, TreeINode
    from stock.ui.labels import label

    tree, branch, node = (int(numbers.get(k, 0)) for k in ("tree", "branch", "node"))
    enum = TreeINode if tree == 1 else {0: MethodId, 1: DefenceNode, 2: CreditNode}.get(branch)
    if enum is None:
        return None
    member = next((m for m in enum if m.value == node), None)
    return label("node", member.name) if member is not None else None


def _custom_law_name(numbers: dict[str, float]) -> str | None:
    """`law_by_custom` carries the `LawId` value as a number (`numbers` holds only
    floats); name it through the law label table."""

    from stock.core.laws import LawId
    from stock.ui.labels import law_label

    value = numbers.get("law")
    if value is None:
        return None
    member = next((m for m in LawId if m.value == value), None)
    return law_label(member) if member is not None else None


def render_event(event: EventRecord) -> str:
    """Render one ledger event through its template. Falls back to a bare
    `kind · field value ...` line (still numbers-only) for an unregistered kind rather
    than raising, so an engine addition never crashes the feed before 07 catches up."""

    if event.kind == "node_lit":
        name = _node_lit_name(event.numbers)
        if name is not None:
            return f"Advance unlocked · {name}"
    if event.kind == "law_by_custom":
        name = _custom_law_name(event.numbers)
        if name is not None:
            numbers = {k: v for k, v in event.numbers.items() if k != "law"}
            formatted = {k: format_basket(v) for k, v in numbers.items()}
            return f"{name} · " + TEMPLATES["law_by_custom"].format(**formatted)
    template = TEMPLATES.get(event.kind)
    if template is None:
        parts = " · ".join(f"{k} {format_basket(v)}" for k, v in sorted(event.numbers.items()))
        return f"{event.kind}" + (f" · {parts}" if parts else "")
    formatted = {k: format_basket(v) for k, v in event.numbers.items()}
    return template.format(**formatted)
