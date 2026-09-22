"""World -> `Snapshot` (Doc 07): reads the `World` tree and the ledger, computes
nothing the engine doesn't already compute, and hands the JS pre-shaped display data.

Three presentation-only layers sit on top of the engine's numbers here, each owned by
its own module: the map layout (`api/layout.py`, a crossing-free chart cached per
topology), display names (`ui/names.py`, procedural per world) and plain-English
labels (`ui/labels.py`, one table). Action offers (`api/offers.py`) draft every
action the player could queue, with its cost, so the client never re-derives one.
"""

from __future__ import annotations

import math
from typing import Any

from stock.api.layout import compute_layout
from stock.api.offers import PROPOSABLE_TERMS, OfferBuilder, build_offers
from stock.api.schemas import (
    BudgetSegment,
    CapitalRow,
    Curves,
    EventEntry,
    FocusInfo,
    GameOver,
    Header,
    HeadlineNumber,
    HegemonyBand,
    IncidenceCard,
    IncomeSource,
    InterestBar,
    LawRow,
    LedgerRow,
    MapData,
    MapEdge,
    MapNode,
    NameTable,
    NationShareBars,
    NationSummary,
    NowColumn,
    Panels,
    PeaceOfferInfo,
    PlayerInfo,
    PoliticsPanel,
    ProducerSummary,
    RecordSummary,
    RivalRow,
    RouteRow,
    RoutesPanel,
    SecurityPanel,
    Snapshot,
    TerritoryFlow,
    TreatyCard,
    TreatyProposalCard,
    TreeChain,
    TreeNode,
    TreesPanel,
    WarCard,
)
from stock.core.goods import ALL_GOODS, Good, Tier
from stock.core.laws import LAW_TABLE
from stock.core.producers import OCCUPATIONS
from stock.core.records import InterestId
from stock.core.trees import CREDIT_CHAIN, DEFENCE_CHAIN, PRODUCTION_CHAIN, TreeINode
from stock.core.world import SeatKind, World
from stock.engine.band import ground_quality
from stock.security.military import (
    active_doctrine,
    doctrine_multiplier,
    has_firearms,
    loyalty_factor,
    perceived_security,
)
from stock.sim.ledger import EventRecord
from stock.ui.help import help_tables
from stock.ui.labels import LABELS, law_label
from stock.ui.names import NameRegister, names_for
from stock.ui.strings import render_event

HELP_TABLES = help_tables()  # tooltips: built once, shipped with every snapshot

#: Player = accent; the rest in the spec's fixed nation-colour order.
NATION_COLOURS: tuple[str, ...] = (
    "#3B5B8C",
    "#8C4A3B",
    "#5B7A3B",
    "#7A5B8C",
    "#8C7A3B",
    "#3B7A8C",
)

SPARKLINE_WINDOW = 30
CURVE_WINDOW = 60
#: Node radius ∝ √population, clamped so a ring never swallows its neighbours
#: (`tests/test_layout.py` keeps every line 30px clear of every foreign node).
NODE_RADIUS_MIN = 5.0
NODE_RADIUS_MAX = 24.0


def node_radius(population: float) -> float:
    return max(NODE_RADIUS_MIN, min(NODE_RADIUS_MAX, 5.0 + 0.45 * math.sqrt(max(population, 0.0))))


def _location_hash_maps(world: World) -> dict[int, str]:
    """Reverse `hash(loc.id) % N` (the engine's own lossy placeholder identifier, used
    at two different moduli by different modules) back to a real location id, so the
    event feed can deep-link — best-effort; a collision silently picks one location."""

    reverse: dict[int, str] = {}
    for loc_id in world.locations:
        for modulus in (1000, 1_000_000):
            reverse.setdefault(hash(loc_id) % modulus, loc_id)
    return reverse


def nation_colours(world: World, player_nation: str) -> dict[str, str]:
    colours = {player_nation: NATION_COLOURS[0]}
    rest = [n for n in sorted(world.nations) if n != player_nation]
    palette = list(NATION_COLOURS[1:])
    for i, nid in enumerate(rest):
        colours[nid] = palette[i % len(palette)]
    return colours


def _sparkline(world: World, nation_id: str, key: str, *, from_scalars: bool = False) -> list[float]:
    rows = world.ledger.rows_for(nation_id)[-SPARKLINE_WINDOW:] if world.ledger else []
    source = "scalars" if from_scalars else "curves"
    return [getattr(r, source).get(key, 0.0) for r in rows]


def build_header(
    world: World, nation_id: str, colours: dict[str, str], names: NameRegister
) -> Header:
    nation = world.nations[nation_id]
    s = nation.scalars
    rows = world.ledger.rows_for(nation_id) if world.ledger else []
    prev = rows[-2] if len(rows) >= 2 else None

    def delta(current: float, prev_key: str, *, from_scalars: bool) -> float:
        if prev is None:
            return 0.0
        source = prev.scalars if from_scalars else prev.curves
        return float(current - source.get(prev_key, current))

    authority_label = "Consensus" if nation.seat is SeatKind.BAND else "State authority"
    headline = [
        HeadlineNumber(
            key="produce_per_head",
            label="Produce per head",
            value=nation.curves.get("produce_per_head", 0.0),
            delta=delta(nation.curves.get("produce_per_head", 0.0), "produce_per_head", from_scalars=False),
            sparkline=_sparkline(world, nation_id, "produce_per_head"),
        ),
        HeadlineNumber(
            key="labour_share",
            label="Labour share",
            value=nation.curves.get("labour_share", 0.0),
            delta=delta(nation.curves.get("labour_share", 0.0), "labour_share", from_scalars=False),
            sparkline=_sparkline(world, nation_id, "labour_share"),
        ),
        HeadlineNumber(
            key="n_bar",
            label="Perceived security",
            value=s.N_bar,
            delta=delta(s.N_bar, "N_bar", from_scalars=True),
            sparkline=_sparkline(world, nation_id, "N_bar", from_scalars=True),
        ),
        HeadlineNumber(
            key="a_s",
            label=authority_label,
            value=s.A_S,
            delta=delta(s.A_S, "A_S", from_scalars=True),
            sparkline=_sparkline(world, nation_id, "A_S", from_scalars=True),
        ),
    ]

    band = None
    h = world.hegemony
    if h.countdown is not None and h.countdown_nation is not None:
        band = HegemonyBand(
            active=True,
            nation=h.countdown_nation,
            nation_name=names.nation(h.countdown_nation),
            nation_color=colours.get(h.countdown_nation),
            flags=[nid for nid, n in h.flags.items() if n > 0],
            years_remaining=h.countdown,
        )

    return Header(
        year=world.year, headline=headline, hegemony_band=band
    )


def build_map(world: World, player_nation: str, colours: dict[str, str], names: NameRegister) -> MapData:
    layout = compute_layout(world)
    player = world.nations[player_nation]
    band_mode = player.seat is SeatKind.BAND
    own = {loc.id for loc in player.locations(world)}
    adjacent = {nid for lid in own for nid in world.locations[lid].neighbours if nid not in own}

    nodes: list[MapNode] = []
    for loc_id, loc in sorted(world.locations.items()):
        population = sum(r.size for r in loc.records)
        x, y = layout.get(loc_id, (0.0, 0.0))
        resources = [
            name
            for name, present in (
                ("game", loc.resources.game),
                ("grazing", loc.resources.grazing),
                ("arable", loc.resources.arable),
                ("timber", loc.resources.timber),
                ("ore", loc.resources.ore),
                ("coal", loc.resources.coal),
                ("fishing", loc.resources.fishing),
                ("rare", loc.resources.rare),
            )
            if present
        ]
        contested = any(
            other != loc.nation
            for other in world.nations
            if other != loc.nation and world.hostility.get((loc.nation or "", other), 0.0) > 0
        ) if loc.nation else False
        nodes.append(
            MapNode(
                id=loc_id,
                name=names.location(loc_id),
                x=x,
                y=y,
                nation=loc.nation,
                nation_name=names.nation(loc.nation) if loc.nation else None,
                nation_color=colours.get(loc.nation) if loc.nation else None,
                population=population,
                radius=node_radius(population),
                terrain=loc.terrain.name,
                river=loc.river,
                coast=loc.coast,
                contested=contested,
                resources=resources,
                is_capital=(player.state is not None and player.state.location == loc_id),
                is_band=(band_mode and loc.nation == player_nation),
                is_player=loc_id in own,
                adjacent_to_player=loc_id in adjacent,
                ground_quality=ground_quality(loc),
                depletion=max(loc.capacity.game_depletion, loc.capacity.graze_depletion),
                fields=loc.fields,
                records=[RecordSummary(cls=r.cls.name, size=r.size) for r in loc.records],
                producers=[ProducerSummary(kind=p.kind.name, method=p.method.name) for p in loc.producers],
                prices={g.name: loc.market.price.get(g, 0.0) for g in ALL_GOODS},
            )
        )

    seen_edges: set[tuple[str, str]] = set()
    edges: list[MapEdge] = []
    for loc_id, loc in world.locations.items():
        for neighbour_id, _dist in loc.neighbours.items():
            a_id, b_id = sorted((loc_id, neighbour_id))
            key = (a_id, b_id)
            if key in seen_edges or neighbour_id not in world.locations:
                continue
            seen_edges.add(key)
            edges.append(
                MapEdge(
                    a=key[0],
                    b=key[1],
                    river=loc.river and world.locations[neighbour_id].river,
                    road=neighbour_id in loc.roads,
                )
            )

    shares = [
        NationShareBars(
            nation=nid,
            name=names.nation(nid),
            color=colours.get(nid, "#999999"),
            capital=world.hegemony.capital_share.get(nid, 0.0),
            consumption=world.hegemony.consumption_share.get(nid, 0.0),
            production=world.hegemony.production_share.get(nid, 0.0),
        )
        for nid in sorted(world.nations)
        if not world.nations[nid].ended
    ]

    return MapData(band_mode=band_mode, nodes=nodes, edges=edges, nation_shares=shares)


def build_curves(world: World, player_nation: str) -> Curves:
    living = [nid for nid, n in world.nations.items() if not n.ended]
    all_rows = {nid: world.ledger.rows_for(nid)[-CURVE_WINDOW:] for nid in living} if world.ledger else {}
    years = sorted({r.year for rows in all_rows.values() for r in rows})
    series: dict[str, dict[str, list[float]]] = {}
    for curve_name in ("produce_per_head", "labour_share", "freedom_index"):
        by_nation: dict[str, list[float]] = {}
        for nid, rows in all_rows.items():
            by_year = {r.year: r.curves.get(curve_name, 0.0) for r in rows}
            by_nation[nid] = [by_year.get(y, 0.0) for y in years]
        series[curve_name] = by_nation

    n_bar_band = []
    for y in years:
        row = next((r for r in all_rows.get(player_nation, []) if r.year == y), None)
        n_bar_band.append(row.scalars.get("N_bar", 0.0) if row else 0.0)

    markers = [
        e.year
        for e in (world.ledger.events if world.ledger else [])
        if e.kind == "regression" and e.nation == player_nation and e.year in years
    ]

    return Curves(years=years, series=series, n_bar_band=n_bar_band, regression_markers=markers)


def _tier_dict(vec: Any) -> dict[str, float]:
    return {"subsistence": vec.subsistence, "comfort": vec.comfort, "standing": vec.standing}


def _producer_payouts(p: Any) -> tuple[dict[Any, float], dict[Any, float], dict[Any, float]]:
    """Where one producer's output value went this year, by class: wages to the
    classes filling its jobs (pro rata), profit to the owners of its stock, rent to
    the holders of its land (the split `build_capital_panel` shows as shares)."""

    filled_total = sum(p.filled.values())
    # An occupation (hunting, herding) pays no wage: its whole output is the working
    # class's own labour (DD §4.1), so the row shows it under wages.
    paid = p.last_V if p.kind in OCCUPATIONS else p.last_wage_bill
    wages = {cls: paid * jobs / filled_total for cls, jobs in p.filled.items()} if filled_total > 0 else {}
    profit = {cls: p.last_split_profit * share for cls, share in p.owners_stock.items() if share > 0}
    rent_total = max(0.0, p.last_V - p.last_wage_bill - p.last_split_profit)
    rent = {cls: rent_total * share for cls, share in p.owners_land.items() if share > 0}
    return wages, profit, rent


def build_territory_flows(world: World, player_nation: str, names: NameRegister) -> list[TerritoryFlow]:
    nation = world.nations[player_nation]
    flows: list[TerritoryFlow] = []
    for loc in nation.locations(world):
        m = loc.market
        price = {g.name: m.price.get(g, 1.0) for g in ALL_GOODS}
        made = {g.name: m.last_supply.get(g, 0.0) for g in ALL_GOODS}
        wanted = {g.name: m.last_demand.get(g, 0.0) for g in ALL_GOODS}
        unsold = {g.name: m.inventory.get(g, 0.0) for g in ALL_GOODS}
        flows.append(
            TerritoryFlow(
                location=loc.id,
                name=names.location(loc.id),
                price=price,
                made=made,
                wanted=wanted,
                unsold=unsold,
                made_value=sum(made[g] * price[g] for g in made),
                wanted_value=sum(wanted[g] * price[g] for g in wanted),
                unsold_value=sum(unsold[g] * price[g] for g in unsold),
                income_total=sum(r.last_gross_income for r in loc.records),
                spent_total=sum(sum(r.last_spend_by_good.values()) for r in loc.records),
                shortfall_total=sum(max(0.0, r.E[t] - r.A[t]) for r in loc.records for t in Tier),
            )
        )
    return flows


def build_ledger_panel(world: World, player_nation: str, names: NameRegister) -> list[LedgerRow]:
    nation = world.nations[player_nation]
    rows: list[LedgerRow] = []
    for loc in nation.locations(world):
        payouts = [(p, *_producer_payouts(p)) for p in loc.producers]
        for r in loc.records:
            shortfall = sum(max(0.0, r.E[t] - r.A[t]) for t in Tier)
            sources: list[IncomeSource] = []
            works_at: dict[str, float] = {}
            for p, wages, profit, rent in payouts:
                w, pr, rt = wages.get(r.cls, 0.0), profit.get(r.cls, 0.0), rent.get(r.cls, 0.0)
                if w > 0 or pr > 0 or rt > 0:
                    sources.append(IncomeSource(producer=p.kind.name, wages=w, profit=pr, rent=rt))
                jobs = p.filled.get(r.cls, 0.0)
                if jobs > 0:
                    works_at[p.kind.name] = works_at.get(p.kind.name, 0.0) + jobs
            spend = {g.name: v for g, v in r.last_spend_by_good.items() if v > 0}
            attendance = r.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
            luxuries = r.last_spend_by_good.get(Good.LUXURIES, 0.0)
            total_standing = attendance + luxuries
            split = (
                {"attendance": attendance / total_standing, "luxuries": luxuries / total_standing}
                if total_standing > 0
                else {"attendance": 0.0, "luxuries": 0.0}
            )
            rows.append(
                LedgerRow(
                    location=loc.id,
                    location_name=names.location(loc.id),
                    cls=r.cls.name,
                    size=r.size,
                    wealth_by_asset=r.wealth.as_dict(),
                    hoard=r.wealth.hoard,
                    A=_tier_dict(r.A),
                    E=_tier_dict(r.E),
                    shortfall=shortfall,
                    walk_away=r.walk_away,
                    authority=r.authority,
                    standing_split=split,
                    income=r.last_gross_income,
                    paid=sum(s.wages + s.profit + s.rent for s in sources),
                    taxed=max(0.0, sum(s.wages + s.profit + s.rent for s in sources) - r.last_gross_income),
                    sources=sources,
                    works_at=works_at,
                    spend_by_good=spend,
                    saved=max(0.0, r.last_gross_income - sum(spend.values())),
                )
            )
    return rows


def build_incidence_panel(
    world: World, player_nation: str
) -> tuple[list[IncidenceCard], list[BudgetSegment], str, float, float, float]:
    nation = world.nations[player_nation]
    cards: list[IncidenceCard] = []
    for instrument, table in (nation.incidence or {}).items():
        name = instrument.name if hasattr(instrument, "name") else str(instrument)
        cards.append(
            IncidenceCard(
                instrument=name,
                label=law_label(instrument),
                rate=nation.tax_rates.get(instrument, 0.0),
                assessed_on={c.name: v for c, v in table.assessed_on.items()},
                borne_by={c.name: v for c, v in table.borne_by.items()},
                collected=table.collected,
                cost=table.cost,
            )
        )
    b = nation.budget
    draws = {
        "defence": nation.scalars.defence_draw,
        "justice": nation.scalars.justice_draw,
        "works": nation.scalars.works_draw,
        "service": nation.scalars.service_draw,
        "court": nation.scalars.court,
        "transfers": nation.scalars.transfers_draw,
    }
    productive = {"defence", "justice", "works"}
    budget = [
        BudgetSegment(name=name, share=share, productive=name in productive, draw=draws.get(name, 0.0))
        for name, share in (
            ("defence", b.defence),
            ("justice", b.justice),
            ("works", b.works),
            ("service", b.service),
            ("court", b.court),
            ("transfers", b.transfers),
        )
    ]
    s = nation.scalars
    return cards, budget, nation.debt_policy, s.r_market, s.r_legal, s.r_sovereign


def build_capital_panel(world: World, player_nation: str, names: NameRegister) -> list[CapitalRow]:
    nation = world.nations[player_nation]
    rows: list[CapitalRow] = []
    for loc in nation.locations(world):
        for p in loc.producers:
            v = max(p.last_V, 1e-9)
            labour = p.last_wage_bill
            profit = p.last_split_profit
            rent = max(0.0, p.last_V - labour - profit)
            return_rate = (profit / p.stock_in_place) if p.stock_in_place > 0 else 0.0
            wages_to, profit_to, rent_to = _producer_payouts(p)
            rows.append(
                CapitalRow(
                    location=loc.id,
                    location_name=names.location(loc.id),
                    kind=p.kind.name,
                    method=p.method.name,
                    stock=p.stock_in_place,
                    jobs_filled=sum(p.filled.values()),
                    jobs_total=p.jobs,
                    V=p.last_V,
                    labour_share=labour / v,
                    profit_share=profit / v,
                    rent_share=rent / v,
                    deviation_from_r_bar=return_rate - nation.scalars.r_bar,
                    makes={g.name: q * p.last_Q for g, q in p.outputs.items() if q * p.last_Q > 0},
                    worked_by={cls.name: jobs for cls, jobs in p.filled.items() if jobs > 0},
                    owned_by={cls.name: share for cls, share in p.owners_stock.items() if share > 0},
                    land_by={cls.name: share for cls, share in p.owners_land.items() if share > 0},
                    wages_to={cls.name: x for cls, x in wages_to.items() if x > 0},
                    profit_to={cls.name: x for cls, x in profit_to.items() if x > 0},
                    rent_to={cls.name: x for cls, x in rent_to.items() if x > 0},
                )
            )
    return rows


def build_politics_panel(world: World, player_nation: str, offers: OfferBuilder) -> PoliticsPanel:
    nation = world.nations[player_nation]
    interests = [
        InterestBar(
            interest=i.name,
            authority=nation.interests[i].authority if i in nation.interests else 0.0,
            radicalism=nation.interests[i].radicalism if i in nation.interests else 0.0,
        )
        for i in InterestId
    ]
    sovereign = nation.seat is not SeatKind.BAND
    law_offers = offers.laws() if sovereign else {}
    laws: list[LawRow] = []
    for law_id, spec in LAW_TABLE.items():
        state = nation.laws.get(law_id)
        enacted = state.enacted if state else False
        row = law_offers.get(law_id.name, {"enact": None, "repeal": None, "vetoes": []})
        enact = row["enact"]
        repeal = row["repeal"]
        laws.append(
            LawRow(
                id=law_id.name,
                label=law_label(law_id),
                branch=spec.branch.name,
                enacted=enacted,
                enforcement=state.enforcement if state else 0.0,
                veto_cooldown_until=state.veto_cooldown_until if state else None,
                enact_cost=enact.cost if enact is not None else None,
                repeal_cost=repeal.cost if repeal is not None else None,
                enact=enact,
                repeal=repeal,
                vetoes=list(row["vetoes"]),
            )
        )
    focus = None
    if nation.focus is not None:
        focus = FocusInfo(
            kind=nation.focus.kind.name,
            node=nation.focus.node,
            location=nation.focus.location,
            progress=nation.focus.progress,
            upkeep=nation.focus.upkeep,
        )
    options, set_focus, clear_focus = offers.focus() if sovereign else ([], None, None)
    return PoliticsPanel(
        A_S=nation.scalars.A_S,
        seat=nation.seat.name,
        interests=interests,
        laws=laws,
        focus=focus,
        focus_options=options,
        set_focus=set_focus,
        clear_focus=clear_focus,
    )


def build_routes_panel(
    world: World, player_nation: str, colours: dict[str, str], names: NameRegister, offers: OfferBuilder
) -> RoutesPanel:
    player_locs = {loc.id for loc in world.nations[player_nation].locations(world)}
    routes: list[RouteRow] = []
    for route in world.routes.values():
        if route.a not in player_locs and route.b not in player_locs:
            continue
        loc_a = world.locations.get(route.a)
        loc_b = world.locations.get(route.b)
        routes.append(
            RouteRow(
                id=route.id,
                a=route.a,
                b=route.b,
                a_name=names.location(route.a),
                b_name=names.location(route.b),
                prices_a={g.name: loc_a.market.price.get(g, 0.0) for g in ALL_GOODS} if loc_a else {},
                prices_b={g.name: loc_b.market.price.get(g, 0.0) for g in ALL_GOODS} if loc_b else {},
                capacity=route.last_capacity,
                gap={g.name: v for g, v in route.last_gap_by_good.items()},
                volume=sum(route.last_volume_by_good.values()),
                customs=route.customs_collected,
            )
        )
    treaties: list[TreatyCard] = []
    for t in world.treaties.values():
        if t.a != player_nation and t.b != player_nation:
            continue
        breached = any(v > 0 for v in t.breached_years.values())
        treaties.append(
            TreatyCard(
                id=t.id,
                a=t.a,
                b=t.b,
                a_name=names.nation(t.a),
                b_name=names.nation(t.b),
                terms=[term.kind.name for term in t.terms],
                enforcement_a=1.0 - min(1.0, t.breached_years.get(t.a, 0) * 0.1),
                enforcement_b=1.0 - min(1.0, t.breached_years.get(t.b, 0) * 0.1),
                breached=breached,
            )
        )
    hostility = {
        f"{a}|{b}": v
        for (a, b), v in world.hostility.items()
        if a == player_nation or b == player_nation
    }
    accept_by_initiator = {
        o.payload.get("initiator"): o for o in offers.offers if o.kind == "ACCEPT_TREATY"
    }
    proposals = [
        TreatyProposalCard(
            initiator=str(p.get("initiator", "")),
            initiator_name=names.nation(p.get("initiator")),
            terms=[term.kind.name for term in p.get("terms", []) if hasattr(term, "kind")],
            accept=accept_by_initiator.get(p.get("initiator")),
        )
        for p in world.treaty_proposals
        if p.get("target") == player_nation
    ]
    return RoutesPanel(
        routes=routes,
        treaties=treaties,
        hostility=hostility,
        proposals=proposals,
        term_kinds=[t.name for t in PROPOSABLE_TERMS],
    )


def build_security_panel(
    world: World,
    player_nation: str,
    colours: dict[str, str],
    layout: dict[str, tuple[float, float]],
    names: NameRegister,
) -> SecurityPanel:
    nation = world.nations[player_nation]
    s = nation.scalars
    doctrine = active_doctrine(nation, world)
    factors = {
        "doctrine": doctrine_multiplier(doctrine, has_firearms(nation, world), world.params),
        "loyalty": loyalty_factor(nation, world, doctrine),
    }
    try:
        result = perceived_security(nation, world)
        ptv_int = {cls: v for cls, v in result.PTV_int_by_class.items()}
        n_r = {cls.name: v for (_loc, cls), v in result.N_r_by_record.items()}
    except Exception:
        ptv_int = {}
        n_r = {}

    player_capital = next(iter(layout.values()), (0.0, 0.0))
    player_locs = {loc.id for loc in nation.locations(world)}
    if player_locs & set(layout):
        xs = [layout[loc][0] for loc in player_locs if loc in layout]
        ys = [layout[loc][1] for loc in player_locs if loc in layout]
        player_capital = (sum(xs) / len(xs), sum(ys) / len(ys))

    at_war_with = {b for (a, b) in world.wars if a == player_nation} | {
        a for (a, b) in world.wars if b == player_nation
    }
    rivals: list[RivalRow] = []
    for nid, other in sorted(world.nations.items()):
        if nid == player_nation or other.ended:
            continue
        other_locs = {loc.id for loc in other.locations(world)}
        dist = 0.0
        if other_locs & set(layout):
            xs = [layout[loc][0] for loc in other_locs if loc in layout]
            ys = [layout[loc][1] for loc in other_locs if loc in layout]
            other_capital = (sum(xs) / len(xs), sum(ys) / len(ys))
            dist = math.hypot(player_capital[0] - other_capital[0], player_capital[1] - other_capital[1])
        hostility = world.hostility.get(
            (player_nation, nid), world.hostility.get((nid, player_nation), 0.0)
        )
        rivals.append(
            RivalRow(
                nation=nid,
                name=names.nation(nid),
                color=colours.get(nid, "#999999"),
                M=other.scalars.M,
                hostility=hostility,
                distance=dist,
                at_war=nid in at_war_with,
            )
        )

    wars: list[WarCard] = []
    for (attacker, defender), war in sorted(world.wars.items()):
        if player_nation not in (attacker, defender):
            continue
        other_id = defender if attacker == player_nation else attacker
        offer = None
        if war.peace_offer is not None:
            offer = PeaceOfferInfo(
                cession=list(war.peace_offer.cession),
                tribute_amount=war.peace_offer.tribute_amount,
                tribute_years=war.peace_offer.tribute_years,
            )
        wars.append(
            WarCard(
                other=other_id,
                other_name=names.nation(other_id),
                role="attacker" if attacker == player_nation else "defender",
                started=war.started,
                contested=dict(war.contested),
                peace_offer=offer,
            )
        )

    return SecurityPanel(
        M=s.M,
        doctrine=doctrine.value,
        factors=factors,
        PSV=s.PSV,
        PTV_ext=s.PTV_ext,
        PTV_int_by_class=ptv_int,
        N_r_by_class=n_r,
        N_bar=s.N_bar,
        rivals=rivals,
        wars=wars,
    )


def build_trees_panel(world: World, player_nation: str, names: NameRegister) -> TreesPanel:
    """Tree I per territory and the three Tree II branches, nodes in chain order
    (`core/trees.py`), with lit/idle/lit-year and the Focus's target marked."""

    nation = world.nations[player_nation]
    focus_node = nation.focus.node if nation.focus is not None else None
    focus_loc = nation.focus.location if nation.focus is not None else None

    def chain(
        cid: str, label: str, states: dict[Any, Any], order: tuple[Any, ...], loc: str | None
    ) -> TreeChain:
        nodes = []
        for member in order:
            st = states.get(member)
            targeted = focus_node == member.name and (focus_loc is None or focus_loc == loc)
            nodes.append(
                TreeNode(
                    id=member.name,
                    lit=bool(st and st.lit),
                    lit_year=st.lit_year if st else None,
                    idle=bool(st and st.idle),
                    focus=targeted,
                )
            )
        return TreeChain(id=cid, label=label, location=loc, nodes=nodes)

    tree1 = [
        chain(loc.id, names.location(loc.id), loc.tree1.nodes, tuple(TreeINode), loc.id)
        for loc in nation.locations(world)
    ]
    t2 = nation.tree2
    tree2 = [
        chain("production", "Production", t2.production, PRODUCTION_CHAIN, None),
        chain("defence", "Defence", t2.defence, DEFENCE_CHAIN, None),
        chain("credit", "Credit", t2.credit, CREDIT_CHAIN, None),
    ]
    return TreesPanel(tree1=tree1, tree2=tree2)


def build_now_column(
    world: World,
    player_nation: str,
    colours: dict[str, str],
    queued: list[Any],
    synthetic_events: list[EventRecord],
    names: NameRegister,
) -> NowColumn:
    nation = world.nations[player_nation]
    s = nation.scalars
    k_spiral = world.params.regression.k_spiral if world.params else 4
    reverse_locations = _location_hash_maps(world)

    all_events = list(world.ledger.events[-500:]) if world.ledger else []
    all_events += synthetic_events
    all_events.sort(key=lambda e: e.year)
    entries: list[EventEntry] = []
    sorted_locations = sorted(world.locations)
    for e in all_events[-60:]:
        loc = None
        raw_loc = e.numbers.get("location")
        if raw_loc is not None:
            if e.kind == "node_lit":  # index into sorted ids (meta/trees.py), not a hash
                idx = int(raw_loc)
                loc = sorted_locations[idx] if 0 <= idx < len(sorted_locations) else None
            else:
                loc = reverse_locations.get(int(raw_loc))
        text = render_event(e)
        detail = getattr(e, "detail", None)
        if detail:
            text = f"{detail} · {text}"
        entries.append(
            EventEntry(
                year=e.year,
                nation=e.nation,
                nation_name=names.nation(e.nation),
                nation_color=colours.get(e.nation, "#999999"),
                kind=e.kind,
                numbers=e.numbers,
                text=text,
                location=loc,
            )
        )

    return NowColumn(
        countdown=world.hegemony.countdown if world.hegemony.countdown_nation == player_nation else None,
        warning_fill=min(1.0, s.spiral_years / k_spiral) if k_spiral else 0.0,
        regression_warning=s.regression_warning,
        queued=queued,
        events=entries,
    )


def build_snapshot(
    world: World,
    player_nation: str,
    *,
    queued: list[Any] | None = None,
    synthetic_events: list[EventRecord] | None = None,
) -> Snapshot:
    colours = nation_colours(world, player_nation)
    names = names_for(world)
    layout = compute_layout(world)
    offers = build_offers(world, player_nation, names)
    incidence, budget, debt_choice, r_market, r_legal, r_sovereign = build_incidence_panel(
        world, player_nation
    )

    # Law and Focus offers are drafted inside build_politics_panel (it needs them per
    # row), so Panels(...) must be built before `actions=offers.offers` below is read.
    panels = Panels(
        ledger=build_ledger_panel(world, player_nation, names),
        incidence=incidence,
        budget=budget,
        debt_choice=debt_choice,
        funding_mode=world.nations[player_nation].funding_mode,
        r_market=r_market,
        r_legal=r_legal,
        r_sovereign=r_sovereign,
        capital=build_capital_panel(world, player_nation, names),
        territories=build_territory_flows(world, player_nation, names),
        r_bar=world.nations[player_nation].scalars.r_bar,
        politics=build_politics_panel(world, player_nation, offers),
        routes=build_routes_panel(world, player_nation, colours, names, offers),
        security=build_security_panel(world, player_nation, colours, layout, names),
        trees=build_trees_panel(world, player_nation, names),
    )

    game_over = None
    if world.hegemony.game_over:
        game_over = GameOver(
            winner_per_head=world.hegemony.winner_per_head,
            winner_labour_output=world.hegemony.winner_labour_output,
        )

    player = world.nations[player_nation]
    homes = player.locations(world)
    home = None
    if player.state is not None:
        home = player.state.location
    elif homes:
        home = homes[0].id

    return Snapshot(
        header=build_header(world, player_nation, colours, names),
        map=build_map(world, player_nation, colours, names),
        curves=build_curves(world, player_nation),
        now=build_now_column(
            world,
            player_nation,
            colours,
            queued or [],
            synthetic_events or [],
            names,
        ),
        panels=panels,
        nations=[
            NationSummary(
                id=nid,
                name=names.nation(nid),
                color=colours.get(nid, "#999999"),
                seat=n.seat.name,
                ai=n.ai,
                ended=n.ended,
            )
            for nid, n in sorted(world.nations.items())
        ],
        player_nation=player_nation,
        player=PlayerInfo(
            id=player_nation, name=names.nation(player_nation), seat=player.seat.name, home=home
        ),
        game_over=game_over,
        names=NameTable(nations=dict(names.nations), locations=dict(names.locations)),
        labels=LABELS,
        help=HELP_TABLES,
        actions=offers.offers,
    )
