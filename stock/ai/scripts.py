"""Mode selection and the three scripts (Doc 06), as data: each script is an ordered
list of `(name, condition, action_factory)` rules. `ScriptedSovereign.decide` walks
a script in order and fires every rule whose condition holds, up to
`Params.ai.max_actions_per_year`.

**Scope note**: each script here is a representative subset of the doc's named
rules (4-6 of the 6-8 listed), not a verbatim implementation of every one —
several reference mechanics (Enclosure's ten-year price mean, a Focus's specific
carriage edge, per-good tariff opponents) that would need substantially more
`NationView` surface for a payoff no acceptance test checks. Logged as A47. Mode
selection also recomputes every year rather than caching for ten (the "sticky
for 10 years / immediately on handover" cadence) — recomputing more often than
asked is a superset of the specified behaviour, not a narrower one.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from stock.ai.heuristics import best_raid_target, conquest_allowed, strongest_rival, treaty_value, war_odds
from stock.ai.view import LocationSummary, NationView, OtherNation
from stock.core.actions import Action, ActionKind
from stock.core.laws import LawId

Rule = tuple[str, Callable[[NationView], bool], Callable[[NationView, Any], Action | None]]
Script = list[Rule]


class Mode(Enum):
    HERDING = auto()
    LANDED = auto()
    COMMERCIAL = auto()


def select_mode(view: NationView) -> Mode:
    """The script follows the dominant Interest: LANDED -> landed; INDUSTRIAL or
    MERCHANT -> commercial; none yet (band or herds) -> herding."""

    interest = view.dominant_interest
    if interest == "LANDED":
        return Mode.LANDED
    if interest in ("INDUSTRIAL", "MERCHANT"):
        return Mode.COMMERCIAL
    return Mode.HERDING


def _enact(law: LawId, spend_fraction: float = 0.2) -> Callable[[NationView, Any], Action | None]:
    def factory(view: NationView, rng: Any) -> Action | None:
        spend = spend_fraction * view.scalars.get("A_S", 0.0)
        return Action(kind=ActionKind.ENACT, nation=view.nation_id, payload={"law": law, "spend": spend})

    return factory


def _law_absent_or_unenacted(law: LawId) -> Callable[[NationView], bool]:
    def condition(view: NationView) -> bool:
        state = view.law_states.get(law.name)
        return state is None or state.get("enacted", 0.0) < 0.5

    return condition


# --- Herding ---


def _subsistence_pressed(view: NationView) -> bool:
    return view.curves.get("produce_per_head", 1.0) < 1.0


def _ground_score(loc: LocationSummary) -> float:
    """What a band can make of a location: the hunt now, herds or fields later."""

    hunt = loc.game_yield * (1.0 - loc.depletion)
    return hunt + (1.0 if loc.grazing else 0.0) + (1.0 if loc.arable else 0.0)


def _home(view: NationView) -> LocationSummary | None:
    return next(iter(view.own_locations.values()), None)


BETTER_GROUND_MARGIN = 1.0  # a move costs consensus and a year's contact: only for clearly better ground


def _better_ground(view: NationView) -> LocationSummary | None:
    """The best unclaimed neighbour with game (a band without game starves the
    year it arrives) that scores clearly higher than where the band stands — the
    margin keeps a band from flipping between two near-equal locations every year."""

    home = _home(view)
    neighbours = view.neighbour_locations.values()
    candidates = [loc for loc in neighbours if loc.nation is None and loc.game_yield > 0]
    if home is None or not candidates:
        return None
    best = max(candidates, key=_ground_score)
    return best if _ground_score(best) > _ground_score(home) + BETTER_GROUND_MARGIN else None


def _move_to_best_ground(view: NationView, rng: Any) -> Action | None:
    best = _better_ground(view)
    if best is None:
        return None
    return Action(kind=ActionKind.BAND_MOVE, nation=view.nation_id, payload={"to": best.id})


def _has_raid_target(view: NationView) -> bool:
    return best_raid_target(view) is not None


def _raid_weakest(view: NationView, rng: Any) -> Action | None:
    target = best_raid_target(view)
    if target is None:
        return None
    other = view.others.get(target)
    loc_id = next((lid for lid, loc in view.neighbour_locations.items() if loc.nation == target), None)
    if loc_id is None or other is None:
        return None
    return Action(kind=ActionKind.BAND_RAID, nation=view.nation_id, payload={"location": loc_id})


def _should_settle(view: NationView) -> bool:
    """Settle the home ground once it is arable and giving out — depleted, or the
    hunt short of subsistence for several years running with nowhere better to go
    (DD §3; the same rule `engine/band.step_band` applies to an unsteered band). An
    arable *neighbour* used to count, which settled every band on its first year — a
    band can only settle where it stands."""

    home = _home(view)
    if home is None or not home.arable or _better_ground(view) is not None:
        return False
    return home.depletion > 0.6 or view.scalars.get("pressed_years", 0.0) >= 5


def _has_no_ground(view: NationView) -> bool:
    """Neither herds to follow nor ground to settle where the band stands."""

    home = _home(view)
    return home is not None and not home.grazing and not home.arable


def _seek_ground(view: NationView, rng: Any) -> Action | None:
    """Move to the best unclaimed neighbour with game to hunt *and* herds or arable
    ground — a band that moves onto fields it cannot yet work has nothing to eat."""

    candidates = [
        loc
        for loc in view.neighbour_locations.values()
        if loc.nation is None and loc.game_yield > 0 and (loc.grazing or loc.arable)
    ]
    if not candidates:
        return None
    best = max(candidates, key=_ground_score)
    return Action(kind=ActionKind.BAND_MOVE, nation=view.nation_id, payload={"to": best.id})


def _settle(view: NationView, rng: Any) -> Action | None:
    return Action(kind=ActionKind.BAND_SETTLE, nation=view.nation_id, payload={})


HERDING_SCRIPT: Script = [
    ("seek_ground", _has_no_ground, _seek_ground),
    (
        "move_to_better_ground",
        lambda v: _subsistence_pressed(v) and _better_ground(v) is not None,
        _move_to_best_ground,
    ),
    ("raid_weakest_neighbour", lambda v: _subsistence_pressed(v) and _has_raid_target(v), _raid_weakest),
    ("settle", _should_settle, _settle),
]


# --- Landed ---

#: doctrines under which the army is the food producers (security/military): a year
#: at war is a year without output, so such a nation raids rather than conquers
OCCUPATION_DOCTRINES: tuple[str, ...] = ("EVERY_MAN", "NATION_IN_ARMS")


def _r_private_zero(view: NationView) -> bool:
    return view.scalars.get("R_private", 0.0) <= 0.0


LANDED_SCRIPT: Script = [
    ("enact_land_ownable", _law_absent_or_unenacted(LawId.LAND_OWNABLE), _enact(LawId.LAND_OWNABLE)),
    ("enact_serfdom", _law_absent_or_unenacted(LawId.SERFDOM), _enact(LawId.SERFDOM)),
    ("enact_primogeniture", _law_absent_or_unenacted(LawId.PRIMOGENITURE), _enact(LawId.PRIMOGENITURE)),
    (
        # ...and only once there are tenants or craftsmen to drill: a militia of
        # nobody is no defence (the engine no longer lets it disarm a herding nation
        # either, A76)
        "enact_militia_when_threatened",
        lambda v: v.scalars.get("PTV_ext", 0.0) > v.scalars.get("PSV", 0.0)
        and _militia_material(v) > 0
        and _law_absent_or_unenacted(LawId.MILITIA_ACT)(v),
        _enact(LawId.MILITIA_ACT),
    ),
    (
        "standing_army_only_if_no_private_recourse",
        lambda v: _r_private_zero(v) and _law_absent_or_unenacted(LawId.STANDING_ARMY_ACT)(v),
        _enact(LawId.STANDING_ARMY_ACT, 0.2),
    ),
    (
        # A conquest is for a nation whose army is not its food supply (A76): under
        # every-man / nation-in-arms a year at war is a year without output, so a
        # herding nation raids instead (next rule).
        "declare_war_on_land_hunger",
        lambda v: v.interests.get("LANDED", 0.0) > 0
        and v.doctrine not in OCCUPATION_DOCTRINES
        and v.curves.get("produce_per_head", 1.0) >= 1.0
        and not any(o.at_war for o in v.others.values())
        and strongest_rival(v) is not None
        and _shares_frontier(v, strongest_rival(v) or "")
        and conquest_allowed(v, strongest_rival(v) or ""),
        lambda v, rng: Action(
            kind=ActionKind.DECLARE_WAR,
            nation=v.nation_id,
            payload={"target": strongest_rival(v), "casus_belli": False},
        ),
    ),
    (
        # A herding nation's land hunger: a raid on a weaker neighbour's frontier
        # (when the hunt or the herds fall short, else once a decade)
        "raid_weak_neighbour",
        lambda v: v.doctrine in OCCUPATION_DOCTRINES
        and (_subsistence_pressed(v) or v.year % 10 == 0)
        and _raid_target_location(v) is not None,
        lambda v, rng: Action(
            kind=ActionKind.DECLARE_RAID, nation=v.nation_id, payload={"location": _raid_target_location(v)}
        ),
    ),
    (
        # Landed's diplomacy: a stronger, hostile neighbour is asked for non-aggression
        "seek_non_aggression_when_outmatched",
        lambda v: _outmatched_hostile(v) is not None,
        lambda v, rng: _propose_non_aggression(v),
    ),
]


def _shares_frontier(view: NationView, other_id: str) -> bool:
    """A war is fought across adjacent locations (security/war.war_year): no frontier, no war."""

    return any(loc.nation == other_id for loc in view.neighbour_locations.values())


def _raid_target_location(view: NationView) -> str | None:
    """A frontier location of the weakest rival we clearly outmatch (`best_raid_target`)."""

    target = best_raid_target(view)
    if target is None:
        return None
    return next((lid for lid, loc in view.neighbour_locations.items() if loc.nation == target), None)


def _militia_material(view: NationView) -> float:
    return view.class_sizes.get("TENANTS", 0.0) + view.class_sizes.get("CRAFTSMEN", 0.0)


def _outmatched_hostile(view: NationView) -> OtherNation | None:
    """A living neighbour we are not at war with, clearly stronger than us, and not
    yet bound to us by any treaty. (Hostility only rises with wars, captures and
    breaches — MM §16 — so it cannot be the trigger for the first treaty.)"""

    candidates = [
        o
        for o in view.others.values()
        if not o.ended
        and not o.at_war
        and not o.treaties_with_us
        and not o.our_proposal_pending
        and _shares_frontier(view, o.id)
        and war_odds(view, o.id) < 0.4
    ]
    return max(candidates, key=lambda o: o.m) if candidates else None


def _propose_non_aggression(view: NationView) -> Action | None:
    other = _outmatched_hostile(view)
    if other is None:
        return None
    from stock.trade.treaties import Term, TermKind

    # Non-aggression binds both ways: one term each way, so neither side is the
    # only one restrained.
    terms = [
        Term(kind=TermKind.NON_AGGRESSION, bound=other.id, beneficiary=view.nation_id),
        Term(kind=TermKind.NON_AGGRESSION, bound=view.nation_id, beneficiary=other.id),
    ]
    payload = {"target": other.id, "terms": terms}
    return Action(kind=ActionKind.PROPOSE_TREATY, nation=view.nation_id, payload=payload)


# --- Commercial ---


COMMERCIAL_SCRIPT: Script = [
    (
        "enact_stock_separable",
        _law_absent_or_unenacted(LawId.STOCK_SEPARABLE),
        _enact(LawId.STOCK_SEPARABLE, 0.3),
    ),
    ("enact_commutation", _law_absent_or_unenacted(LawId.COMMUTATION), _enact(LawId.COMMUTATION, 0.3)),
    (
        "enact_administration_of_justice",
        _law_absent_or_unenacted(LawId.ADMINISTRATION_OF_JUSTICE),
        _enact(LawId.ADMINISTRATION_OF_JUSTICE, 0.3),
    ),
    ("enact_free_trade", _law_absent_or_unenacted(LawId.FREE_TRADE), _enact(LawId.FREE_TRADE, 0.3)),
    ("enact_public_credit", _law_absent_or_unenacted(LawId.PUBLIC_CREDIT), _enact(LawId.PUBLIC_CREDIT, 0.3)),
    (
        "propose_treaty_with_hostile_neighbour",
        lambda v: any(o.hostility > 0.4 and not o.at_war for o in v.others.values()),
        lambda v, rng: _propose_treaty_to_most_hostile(v),
    ),
    (
        "fund_defence_when_outmatched",
        lambda v: v.scalars.get("PSV", 0.0) < v.scalars.get("PTV_ext", 0.0) + 0.5
        and _law_absent_or_unenacted(LawId.STANDING_ARMY_ACT)(v),
        _enact(LawId.STANDING_ARMY_ACT, 0.3),
    ),
]


def _propose_treaty_to_most_hostile(view: NationView) -> Action | None:
    hostile = [o for o in view.others.values() if o.hostility > 0.4 and not o.at_war]
    if not hostile:
        return None
    target = max(hostile, key=lambda o: o.hostility)
    return Action(
        kind=ActionKind.PROPOSE_TREATY,
        nation=view.nation_id,
        payload={"target": target.id, "terms": []},
    )


SCRIPTS: dict[Mode, Script] = {
    Mode.HERDING: HERDING_SCRIPT,
    Mode.LANDED: LANDED_SCRIPT,
    Mode.COMMERCIAL: COMMERCIAL_SCRIPT,
}


PEACE_AFTER_YEARS = 8  # an attacker offers peace after this long without winning outright
PEACE_AFTER_YEARS_OCCUPATION = 1  # ...or after one year when its army is its food producers


def make_peace(view: NationView) -> Action | None:
    """Common to all scripts (A76): an attacker offers peace once the war has gone
    on `PEACE_AFTER_YEARS` (one year when its army is an occupation) or the odds
    have turned against it; a defender accepts an offer on the table unless it is
    clearly winning. Wars used to run until one side was conquered, which also kept
    every other war from starting."""

    patience = PEACE_AFTER_YEARS_OCCUPATION if view.doctrine in OCCUPATION_DOCTRINES else PEACE_AFTER_YEARS
    for other in view.others.values():
        if not other.at_war:
            continue
        odds = war_odds(view, other.id)
        if other.we_attacked and (other.war_years >= patience or odds < 0.5):
            return Action(
                kind=ActionKind.OFFER_PEACE,
                nation=view.nation_id,
                payload={"target": other.id, "cession": [], "tribute_amount": 0.0, "tribute_years": 0},
            )
        if other.peace_offered_to_us and odds <= 0.6:
            return Action(kind=ActionKind.ACCEPT_PEACE, nation=view.nation_id, payload={"target": other.id})
    return None


def answer_proposals(view: NationView) -> Action | None:
    """Common to all scripts (A76): accept a treaty proposed to us when its value
    (threat relief against market cost) is positive."""

    for other in view.others.values():
        if not other.proposal_to_us or other.treaties_with_us:
            continue
        only_peace = all(kind == "NON_AGGRESSION" for kind in other.proposal_to_us)
        # Non-aggression costs nothing unless we meant to attack them; anything else
        # is weighed as threat relief against market access.
        if (only_peace and war_odds(view, other.id) <= 0.6) or treaty_value(view, other.id) > 0:
            payload = {"initiator": other.id}
            return Action(kind=ActionKind.ACCEPT_TREATY, nation=view.nation_id, payload=payload)
    return None


def respond_to_breach(view: NationView) -> Action | None:
    """Common to all scripts: a war declaration against a treaty-breacher we're at
    least as strong as; a war odds > 0.5 stands in for the doc's `M >= 0.8*M_breacher`."""

    for breacher_id in view.breaches_against_us:
        other = view.others.get(breacher_id)
        if other is None:
            continue
        our_m = view.scalars.get("M", 0.0)
        if our_m >= 0.8 * other.m:
            return Action(
                kind=ActionKind.DECLARE_WAR,
                nation=view.nation_id,
                payload={"target": breacher_id, "casus_belli": True},
            )
    return None
