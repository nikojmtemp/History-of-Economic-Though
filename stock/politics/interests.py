"""Interests: demand tables and radicalism (DD §2.5, §7.4; MM §3).

`InterestId` itself lives in `core.records` (it's needed there for `ClassSpec.
interest_assets` and `LAW_TABLE`'s support/opposition sets) — this module re-exports
it for callers that only need politics-layer symbols, per Doc 03's own listing.
"""

from __future__ import annotations

from dataclasses import dataclass

from stock.core.goods import Good
from stock.core.laws import LawId, prohibition_law, tariff_law
from stock.core.params import Params
from stock.core.records import InterestId  # re-exported

__all__ = ["InterestId", "Repeal", "DEMANDS", "radicalism_update"]


@dataclass(frozen=True)
class Repeal:
    """A demand to repeal (rather than enact) a law. Wraps a `LawId` or a dynamically
    named trade-law key (`tariff_law`/`bounty_law`/`prohibition_law` — `LawId` can't
    carry a payload, core/laws.py)."""

    law: LawId | str


#: Demand tables (DD §7.4), ordered by priority, per Interest. Only demands namable
#: as a single `LawId`/`Repeal` are included; DD §7.4 also names demands with no
#: single-law equivalent at this granularity ("Poor Rate on others", "tariffs on
#: rival Wares", "a charter on a closing route", "no default") — these are omitted
#: rather than mapped to an approximate law, see DEVIATIONS.md. `PROTECTION_OF_
#: PROPERTY` is deliberately *not* here: DD §7.3 and `politics/state.py` treat it as
#: a handover (structurally parallel to Tamed Animal), gated the same way
#: self-enactment is but fired directly by `state.on_protection_of_property`, not
#: cycled through this table.
DEMANDS: dict[InterestId, list[LawId | Repeal | str]] = {
    InterestId.LANDED: [
        tariff_law(Good.PROVISIONS),  # "corn tariff"
        Repeal(LawId.LAND_TAX),  # "no land tax"
        LawId.SERFDOM,  # "Serfdom or Settlement" — Serfdom first
        LawId.SETTLEMENT_LAW,
        LawId.MILITIA_ACT,
        LawId.LAND_OWNABLE,  # property in land recognised at all (DD §2.4/§7.3) —
        # omitted from the original table (A45); appended rather than reordered to
        # the front so it doesn't outrank the other, already-tested priorities.
    ],
    InterestId.INDUSTRIAL: [
        LawId.COMBINATION_ACT,
        LawId.APPRENTICESHIP,
        Repeal(LawId.GUILD_CHARTER),  # the capitalists' side (LAW_TABLE opposition
        # already includes INDUSTRIAL for this law — the craftsmen side isn't
        # representable without splitting the Interest, see DEVIATIONS.md).
        Repeal(LawId.PROFIT_TAX),  # "no profit tax"
        LawId.STANDING_ARMY_ACT,
        LawId.ADMINISTRATION_OF_JUSTICE,
        LawId.STOCK_SEPARABLE,  # unlocks MANUFACTORY (LAW_TABLE's own effect) —
        # omitted from the original table (A45); appended, not reordered, for the
        # same reason as LANDED's LAND_OWNABLE above.
    ],
    InterestId.MERCHANT: [
        LawId.FREE_TRADE,
        LawId.NAVIGATION_ACT,
        LawId.CHARTERED_COMPANY,
        LawId.PUBLIC_CREDIT,
        Repeal(LawId.CUSTOMS),  # "no customs"
    ],
    InterestId.MONEYED: [
        LawId.SINKING_FUND,
        LawId.LAND_TAX,  # "service by land tax" (DD §7.4) — omitted pending finance
        # (Doc 05); LAND_TAX already exists as a LawId, so it does map cleanly (A45).
    ],
    InterestId.LABOUR: [
        Repeal(LawId.COMBINATION_ACT),
        Repeal(prohibition_law(Good.PROVISIONS)),  # "free grain trade"
        LawId.POOR_RATE,
        LawId.COMMUTATION,
    ],
}


def radicalism_update(radicalism: float, demand_unrest: float, met: bool, params: Params) -> float:
    """`radicalism_I' = radicalism_I + Σ_{r in I} political-demand unrest_r −
    decay*1[demands met]` (MM §3). Called once (from `unrest.step_unrest`) with the
    year's accumulated demand-unrest and `met=False`, and again (from
    `legislation.self_enact`) with `demand_unrest=0.0, met=True` for any Interest
    whose demand succeeded that year — the codebase's usual pattern of splitting one
    MM formula across the steps that chronologically produce each term (see
    DEVIATIONS.md, Doc 02's hoard/consumption split)."""

    decay = params.politics.radicalism_decay if met else 0.0
    return max(0.0, radicalism + demand_unrest - decay)
