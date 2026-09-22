"""`NationView`: a read-only, privacy-respecting projection for one nation's
sovereign (Doc 06) — its own full ledger row plus the world's *public* numbers only
for everyone else: curves, world shares, `M`, hostility, treaties, and the price at
the far end of any route touching this nation's territory. Exactly the UI's
information set; a sovereign never reads another nation's raw scalars/flows/laws.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock.core.world import Nation, World
from stock.sim.ledger import build_row


@dataclass(frozen=True)
class OtherNation:
    id: str
    seat: str
    ended: bool
    curves: dict[str, float]
    capital_share: float
    consumption_share: float
    production_share: float
    m: float
    hostility: float
    at_war: bool
    treaties_with_us: tuple[str, ...]
    #: years since a war between us began (0 when not at war)
    war_years: int = 0
    #: we attacked them (an attacker offers peace; a defender accepts it)
    we_attacked: bool = False
    #: they have a peace offer on the table for us to accept
    peace_offered_to_us: bool = False
    #: a treaty they proposed to us waits for our answer (term kinds)
    proposal_to_us: tuple[str, ...] = ()
    #: a treaty we proposed to them waits for their answer
    our_proposal_pending: bool = False


@dataclass(frozen=True)
class LocationSummary:
    """Map data a UI (and so a sovereign) can see for any location: its own
    territory in full, a neighbour only as much as who holds it and its raw
    resources — never another nation's records/producers."""

    id: str
    nation: str | None
    game_yield: float
    grazing: bool
    depletion: float
    arable: bool
    is_town: bool
    fields: float


@dataclass(frozen=True)
class NationView:
    nation_id: str
    year: int
    seat: str
    scalars: dict[str, float]
    curves: dict[str, float]
    flows: dict[str, float]
    class_sizes: dict[str, float]
    law_states: dict[str, dict[str, float]]
    interests: dict[str, float]
    dominant_interest: str | None
    own_treaties: tuple[str, ...]
    others: dict[str, OtherNation] = field(default_factory=dict)
    #: route id -> {good name: price at the far endpoint} for routes touching us
    route_prices: dict[str, dict[str, float]] = field(default_factory=dict)
    #: our own locations, by id
    own_locations: dict[str, LocationSummary] = field(default_factory=dict)
    #: locations adjacent to any of ours, not already ours, by id
    neighbour_locations: dict[str, LocationSummary] = field(default_factory=dict)
    #: nation ids that breached a treaty against us this year (best-effort: a
    #: "breach" event fired for us this year, attributed to any of our treaty
    #: partners whose breach count is nonzero — see build_view's docstring note)
    breaches_against_us: tuple[str, ...] = ()
    #: the doctrine our strength is counted under (security/military.Doctrine name);
    #: under EVERY_MAN and NATION_IN_ARMS the army *is* the food producers, so a
    #: year at war is a year without output (Doc 04)
    doctrine: str = "EVERY_MAN"


def dominant_interest(nation: Nation) -> str | None:
    """The Interest with the largest apportioned authority this year (Doc 03's
    politics/authority.py writes `nation.interests[...].authority`); `None` for a
    band or a nation with no Interests apportioned yet."""

    if not nation.interests:
        return None
    best_id, best_state = max(nation.interests.items(), key=lambda kv: kv[1].authority)
    if best_state.authority <= 0:
        return None
    name: str = best_id.name
    return name


def _at_war(world: World, a: str, b: str) -> bool:
    return (a, b) in world.wars or (b, a) in world.wars


def _treaties_with(nation: Nation, world: World, other_id: str) -> tuple[str, ...]:
    ids = []
    for ref in nation.treaties:
        treaty = world.treaties.get(ref.id)
        if treaty is not None and other_id in (treaty.a, treaty.b):
            ids.append(ref.id)
    return tuple(ids)


def _term_kind_name(term: object) -> str:
    """A proposal's term as its kind's name (a `Term`, a `TermKind`, or a bare string)."""

    kind = getattr(term, "kind", term)
    return str(getattr(kind, "name", kind))


def _other_nation_view(world: World, nation: Nation, other: Nation) -> OtherNation:
    from stock.trade.hostility import hostility

    h = world.hegemony
    war = world.wars.get((nation.id, other.id)) or world.wars.get((other.id, nation.id))
    we_attacked = (nation.id, other.id) in world.wars
    proposal = None
    ours_pending = False
    for p in world.treaty_proposals:
        if p.get("initiator") == other.id and p.get("target") == nation.id:
            proposal = p
        elif p.get("initiator") == nation.id and p.get("target") == other.id:
            ours_pending = True
    return OtherNation(
        id=other.id,
        seat=other.seat.name,
        ended=other.ended,
        curves=dict(other.curves),
        capital_share=h.capital_share.get(other.id, 0.0),
        consumption_share=h.consumption_share.get(other.id, 0.0),
        production_share=h.production_share.get(other.id, 0.0),
        m=other.scalars.M,
        hostility=hostility(world, nation.id, other.id),
        at_war=war is not None,
        treaties_with_us=_treaties_with(nation, world, other.id),
        war_years=(world.year - war.started) if war is not None else 0,
        we_attacked=we_attacked,
        peace_offered_to_us=war is not None and not we_attacked and war.peace_offer is not None,
        proposal_to_us=tuple(_term_kind_name(t) for t in (proposal or {}).get("terms", [])),
        our_proposal_pending=ours_pending,
    )


def _route_prices(world: World, nation: Nation) -> dict[str, dict[str, float]]:
    our_locations = {loc.id for loc in nation.locations(world)}
    prices: dict[str, dict[str, float]] = {}
    for route in world.routes.values():
        if route.a in our_locations:
            far_id = route.b
        elif route.b in our_locations:
            far_id = route.a
        else:
            continue
        far = world.locations.get(far_id)
        if far is None:
            continue
        prices[route.id] = {good.name: price for good, price in far.market.price.items()}
    return prices


def _location_summary(world: World, loc_id: str) -> LocationSummary | None:
    loc = world.locations.get(loc_id)
    if loc is None:
        return None
    return LocationSummary(
        id=loc.id,
        nation=loc.nation,
        game_yield=loc.resources.game_yield,
        grazing=loc.resources.grazing,
        depletion=max(loc.capacity.game_depletion, loc.capacity.graze_depletion),
        arable=loc.resources.arable,
        is_town=loc.is_town(),
        fields=loc.fields,
    )


def _locations(world: World, nation: Nation) -> tuple[dict[str, LocationSummary], dict[str, LocationSummary]]:
    own_ids = {loc.id for loc in nation.locations(world)}
    own: dict[str, LocationSummary] = {}
    neighbours: dict[str, LocationSummary] = {}
    for loc_id in own_ids:
        summary = _location_summary(world, loc_id)
        if summary is not None:
            own[loc_id] = summary
        loc = world.locations.get(loc_id)
        if loc is None:
            continue
        for neighbour_id in loc.neighbours:
            if neighbour_id in own_ids or neighbour_id in neighbours:
                continue
            neighbour_summary = _location_summary(world, neighbour_id)
            if neighbour_summary is not None:
                neighbours[neighbour_id] = neighbour_summary
    return own, neighbours


def _breaches_against_us(world: World, nation: Nation) -> tuple[str, ...]:
    """Best-effort: `trade.treaties.check_breach` emits a `breach` event whose
    `nation` field is the wronged party (a string-only `numbers` dict can't also
    carry the breacher's id) — attributed here to any treaty partner whose breach
    count is nonzero, which is exact for a nation with a single treaty and an
    approximation for one with several."""

    if world.ledger is None:
        return ()
    if not any(e.kind == "breach" for e in world.ledger.events_in_year(world.year) if e.nation == nation.id):
        return ()
    breachers = []
    for ref in nation.treaties:
        treaty = world.treaties.get(ref.id)
        if treaty is None:
            continue
        other_side = treaty.b if treaty.a == nation.id else treaty.a
        if treaty.breached_years.get(other_side, 0) > 0:
            breachers.append(other_side)
    return tuple(breachers)


def build_view(nation: Nation, world: World) -> NationView:
    row = build_row(nation, world)
    others = {
        n.id: _other_nation_view(world, nation, n)
        for n in world.nations.values()
        if n.id != nation.id
    }
    interests = {i.name: s.authority for i, s in nation.interests.items()}
    own_locations, neighbour_locations = _locations(world, nation)
    return NationView(
        nation_id=nation.id,
        year=world.year,
        seat=nation.seat.name,
        scalars=row.scalars,
        curves=row.curves,
        flows=row.flows,
        class_sizes=row.class_sizes,
        law_states=row.law_states,
        interests=interests,
        dominant_interest=dominant_interest(nation),
        own_treaties=tuple(ref.id for ref in nation.treaties),
        doctrine=nation.scalars.active_doctrine,
        others=others,
        route_prices=_route_prices(world, nation),
        own_locations=own_locations,
        neighbour_locations=neighbour_locations,
        breaches_against_us=_breaches_against_us(world, nation),
    )
