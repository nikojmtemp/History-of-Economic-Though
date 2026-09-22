"""Justice and legibility (DD §7.6; MM §12, §3)."""

from __future__ import annotations

from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.producers import ProducerKind
from stock.core.records import InterestId
from stock.core.world import InterestState, Nation, World


def _any_field(nation: Nation, world: World) -> bool:
    return any(p.kind is ProducerKind.FIELD for loc in nation.locations(world) for p in loc.producers)


def justice_floor(nation: Nation, world: World) -> float:
    """`J_cust`: 0.3 (band/herds), 0.4 (fields) — decided by whether any FIELD
    producer exists (DD §3's "settled" configuration)."""

    p = world.params.politics
    return float(p.justice_floor_settled if _any_field(nation, world) else p.justice_floor_mobile)


def justice_need(nation: Nation, world: World) -> float:
    """`justice_need ∝ population*(1+town share)` (MM §12). The proportionality
    constant isn't named in MM/DD — tuned placeholder, see DEVIATIONS.md."""

    locations = nation.locations(world)
    population = sum(r.size for loc in locations for r in loc.records)
    if population <= 0:
        return 0.0
    town_pop = sum(r.size for loc in locations if loc.is_town() for r in loc.records)
    town_share = town_pop / population
    return float(population * (1.0 + town_share) * world.params.politics.justice_need_per_head)


def justice_level(nation: Nation, draw: float, world: World) -> float:
    """`J = J_cust + (1-J_cust)*min(1, justice_draw/justice_need)` if Administration
    of Justice is enacted, else `J_cust` (MM §12)."""

    floor = justice_floor(nation, world)
    law = nation.laws.get(LawId.ADMINISTRATION_OF_JUSTICE)
    if law is None or not law.enacted:
        return floor
    need = justice_need(nation, world)
    ratio = min(1.0, draw / need) if need > 0 else 0.0
    return floor + (1.0 - floor) * ratio


def legibility_update(nation: Nation, j: float, disorder_converted: float, params: Params) -> float:
    """`ell' = ell + j_gain*J*(disorder converted) - delta_ell*ell` (MM §3), clamped
    to [0,1] (MM §3's declared domain)."""

    ell = nation.scalars.ell
    updated = ell + params.authority.j_gain * j * disorder_converted - params.authority.delta_ell * ell
    return min(1.0, max(0.0, updated))


def convert_disorder(nation: Nation, j: float) -> float:
    """Moves a share `J` of `U_dis` into LABOUR radicalism (DD §7.4's "Justice
    converts a share of disorder to lawful demand — into Labour's radicalism and its
    legibility `ell`"). Returns the converted amount."""

    converted = nation.scalars.U_dis * j
    if converted <= 0:
        return 0.0
    state = nation.interests.setdefault(InterestId.LABOUR, InterestState())
    state.radicalism += converted
    nation.scalars.U_dis -= converted
    return converted
