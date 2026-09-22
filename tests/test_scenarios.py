"""Doc 08 scenario tests: each pins one of the design's intended emergent or
mechanical behaviours against a scenario (a purpose-built YAML, an existing one, or a
direct `World` construction — whichever gives the behaviour a fair, controllable
test). Four assertions hold for real; five are `xfail(strict=True)` with the actual
measured number in the reason, per `tests/test_invariants.py`'s own convention and
`build/DEVIATIONS-IN-PROGRESS.md`'s fuller writeup of each gap. A strict xfail that
starts passing fails CI, which is the point: it means the underlying gap (usually
another doc's, not 08's to fix) closed and the marker should come off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stock.core.actions import Action, ActionKind, enqueue
from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.records import ClassId, InterestId, Record, Wealth
from stock.core.world import (
    HegemonyState,
    InterestState,
    LawState,
    Location,
    Market,
    Nation,
    PrevSnapshot,
    Resources,
    SeatKind,
    Terrain,
    World,
)
from stock.politics.state import state_authority_update
from stock.security.military import perceived_security
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from stock.sim.year import run_year
from tools.metrics import manufactory_year

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = REPO_ROOT / "tests" / "scenarios"


def _make_world(
    nations: dict[str, Nation], locations: dict[str, Location], params: Params | None = None
) -> World:
    return World(
        year=0,
        nations=nations,
        locations=locations,
        hostility={},
        hegemony=HegemonyState(),
        prev=PrevSnapshot(),
        ledger=Ledger(),
        rng=None,
        params=params or Params.default(),
    )


# ---------------------------------------------------------------------------
# 1. Herds become property
# ---------------------------------------------------------------------------


def test_herds_become_property_within_120_years() -> None:
    """A lone band on grassland (no arable, no rare) tames its herd (band.py's
    automatic `tame_herd`/`band_follow_herds` heuristics fire for a null sovereign
    every year — no law, no action needed) within 120 years, and the largest
    herd-owner record takes the seat (`A_S` set to exactly that record's authority,
    `politics/state.on_tamed_animal`)."""

    for seed in (1, 2, 3, 4, 5):
        world = load_scenario(SCENARIOS / "band_grassland.yaml")
        world.rng = make_rng(seed)
        for _ in range(120):
            run_year(world)
            if world.nations["nation_band"].seat is not SeatKind.BAND:
                break

        nation = world.nations["nation_band"]
        assert nation.seat is SeatKind.CHIEF, f"seed {seed}: still {nation.seat.name} after 120 years"

        owners = [
            r for loc in nation.locations(world) for r in loc.records if r.cls is ClassId.HERD_OWNERS
        ]
        assert owners and owners[0].wealth.herd > 0, f"seed {seed}: no herd-owning record"
        largest = max(owners, key=lambda r: r.authority)
        assert nation.scalars.A_S == pytest.approx(largest.authority), (
            f"seed {seed}: A_S={nation.scalars.A_S} != largest herd-owner authority {largest.authority}"
        )


# ---------------------------------------------------------------------------
# 3. The Standing Army Act has a constituency
# ---------------------------------------------------------------------------


def test_standing_army_act_has_a_constituency() -> None:
    """With `R_private > 0` (retainers under an active Feudal Host), merchants feel
    the internal threat more than landlords do (`SecurityParams.internal_threat_c_r`:
    1.2 for MERCHANTS, 0.0 for LANDLORDS — MM §14's `PTV_int,r`), so their perceived
    security `N_r` is lower. After the Standing Army Act replaces Feudal Host as the
    active doctrine, `R_private` drops to 0 (`politics.state.r_private` reads the
    active doctrine directly), removing that penalty — merchants' `N_r` rises — and
    the Act's own enforcement adds to `A_S` (MM §12's `a3 * law_term`) while the
    `R_private` penalty (`b2 * ln(1+R_private)`) it was paying disappears, so `A_S`
    rises too, once the recurrence reaches its new equilibrium."""

    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="n1", market=Market())
    landlords = Record(
        cls=ClassId.LANDLORDS, location="loc1", size=10.0, authority=50.0, wealth=Wealth(land_shares=5.0)
    )
    merchants = Record(
        cls=ClassId.MERCHANTS, location="loc1", size=10.0, authority=50.0, wealth=Wealth(stock_in_place=100.0)
    )
    retainers = Record(cls=ClassId.RETAINERS, location="loc1", size=20.0)
    loc.records = [landlords, merchants, retainers]

    nation = Nation(id="n1", seat=SeatKind.STATE)
    nation.scalars.active_doctrine = "FEUDAL_HOST"
    nation.scalars.A_S = 10.0
    nation.interests[InterestId.LANDED] = InterestState(authority=50.0)
    nation.interests[InterestId.MERCHANT] = InterestState(authority=50.0)

    params = Params.default()
    world = _make_world({"n1": nation}, {"loc1": loc}, params)

    for _ in range(200):  # run the recurrence to its equilibrium under Feudal Host
        state_authority_update(nation, world, params)
    a_s_before = nation.scalars.A_S

    result = perceived_security(nation, world)
    n_landlord = result.N_r_by_record[("loc1", ClassId.LANDLORDS)]
    n_merchant_before = result.N_r_by_record[("loc1", ClassId.MERCHANTS)]
    assert n_merchant_before < n_landlord, "merchants should feel less secure than landlords here"

    nation.laws[LawId.STANDING_ARMY_ACT] = LawState(enacted=True, enforcement=0.8)
    nation.scalars.active_doctrine = "STANDING_ARMY"
    loc.records.append(Record(cls=ClassId.SOLDIERS, location="loc1", size=5.0))

    for _ in range(20):  # let A_S climb toward its new equilibrium
        state_authority_update(nation, world, params)
    a_s_after = nation.scalars.A_S

    result_after = perceived_security(nation, world)
    n_merchant_after = result_after.N_r_by_record[("loc1", ClassId.MERCHANTS)]

    assert a_s_after > a_s_before, f"A_S did not rise: {a_s_before} -> {a_s_after}"
    assert n_merchant_after > n_merchant_before, (
        f"merchant N_r did not rise: {n_merchant_before} -> {n_merchant_after}"
    )


# ---------------------------------------------------------------------------
# 4. Incidence
# ---------------------------------------------------------------------------


def test_land_tax_borne_by_landlords_equals_assessed() -> None:
    """A land tax's burden lands on landlords: `borne_by[LANDLORDS] ≈ assessed_on`
    one year lagged (DD §12.2's incidence rule for a rent-based instrument — nothing
    shifts it onto the tenant working the field)."""

    from stock.engine.production import step_production
    from stock.engine.wages import step_wages
    from stock.finance.taxation import step_taxation

    params = Params.default()
    resources = Resources(arable=True, arable_yield=1.0)
    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="n1", resources=resources)
    from stock.core.producers import Producer, ProducerKind

    field = Producer(
        kind=ProducerKind.FIELD,
        location="loc1",
        stock_in_place=50.0,
        land_shares=10.0,
        filled={ClassId.TENANTS: 10.0},
        owners_land={ClassId.LANDLORDS: 1.0},
    )
    loc.producers.append(field)
    loc.fields = 1.0
    loc.market = Market()

    landlord = Record(cls=ClassId.LANDLORDS, location="loc1", size=5.0, wealth=Wealth(land_shares=1.0))
    tenant = Record(cls=ClassId.TENANTS, location="loc1", size=40.0, wealth=Wealth(stock_in_place=50.0))
    state_rec = Record(cls=ClassId.STATE, location="loc1", size=1.0)
    loc.records = [landlord, tenant, state_rec]

    nation = Nation(id="n1", seat=SeatKind.STATE, state=state_rec)
    nation.scalars.r_bar = 0.05
    nation.laws[LawId.LAND_TAX] = LawState(enacted=True)
    nation.tax_rates[LawId.LAND_TAX] = 0.1

    world = _make_world({"n1": nation}, {"loc1": loc}, params)

    def mini_year() -> None:
        for n in world.nations.values():
            n.flows = {}
        world.prev = PrevSnapshot.take(world)
        step_production(world)
        step_wages(world)
        step_taxation(world)
        world.year += 1

    mini_year()  # year 0: assessed_on computed, no prior year to derive borne_by from
    assert nation.incidence is not None
    assessed_year0 = dict(nation.incidence[LawId.LAND_TAX].assessed_on)
    assert assessed_year0.get(ClassId.LANDLORDS, 0.0) > 0, "nothing assessed on landlords in year 0"

    mini_year()  # year 1: borne_by derived from year 0's assessed_on
    borne_year1 = nation.incidence[LawId.LAND_TAX].borne_by
    assert set(borne_year1) <= {ClassId.LANDLORDS}, f"land tax burden landed on {set(borne_year1)}"
    assert borne_year1[ClassId.LANDLORDS] == pytest.approx(assessed_year0[ClassId.LANDLORDS], rel=1e-6)


# ---------------------------------------------------------------------------
# 8. Hegemony
# ---------------------------------------------------------------------------


def test_hegemony_late_start_reaches_game_over_with_distinct_winners() -> None:
    """`late_start.yaml`'s deliberately uneven starting sizes (see the scenario's own
    header comment and `build/DEVIATIONS-RESOLVED.md` A54) reach hegemony game-over
    well within a normal play session, with the per-head and labour-output winners
    being two *different* nations — the design's point that scale and prosperity
    aren't the same axis."""

    world = load_scenario(SCENARIOS / "late_start.yaml")
    for _ in range(200):
        if world.hegemony.game_over:
            break
        run_year(world)

    assert world.hegemony.game_over, f"no game over within 200 years (stopped at year {world.year})"
    assert world.year <= 100, f"reached game over later than expected, at year {world.year}"
    assert world.hegemony.winner_per_head is not None
    assert world.hegemony.winner_labour_output is not None
    assert world.hegemony.winner_per_head != world.hegemony.winner_labour_output, (
        f"both metrics won by {world.hegemony.winner_per_head} — expected two distinct nations"
    )


# ---------------------------------------------------------------------------
# 2. Retainer dismissal — measured, not reached without a law on the existing
# null-sovereign scenario; see the docstring for the actual numbers.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Measured on tests/scenarios/three_bands.yaml (null sovereigns), seeds 1-3, 300 years: "
        "RETAINERS only ever appears for nation_steppe (peak ~74), and never drops >= 50% "
        "within 40 years of its peak in any seed. The LUXURIES Tree I gate "
        "(`has_rare and craftsmen_present` or `route_reaches_luxuries`, core/trees.py) never "
        "fires without a sovereign opening a rare workshop or a route — which a null "
        "sovereign never does — so the 'opening a rare workshop or a route' trigger this test "
        "needs never occurs organically. Forcing the trigger directly (rather than via a null "
        "sovereign) would test a different claim ('dismissal follows from Luxuries becoming "
        "available', which is very likely true) than the one written ('...without any law', "
        "i.e. emergent under a null sovereign). Re-measured after A68-A70 (the band and "
        "regression guards): nation_steppe still peaks at 69-74 and never halves. See "
        "build/DEVIATIONS-IN-PROGRESS.md."
    ),
)
def test_retainer_dismissal_is_emergent() -> None:
    hit = False
    for seed in (1, 2, 3):
        world = load_scenario(SCENARIOS / "three_bands.yaml")
        world.rng = make_rng(seed)
        peak = 0.0
        peak_year = None
        for year in range(300):
            run_year(world)
            nation = world.nations["nation_valley"]
            size = sum(
                r.size for loc in nation.locations(world) for r in loc.records if r.cls is ClassId.RETAINERS
            )
            if size > peak:
                peak, peak_year = size, year
            elif peak >= 10 and peak_year is not None and year - peak_year <= 40 and size <= 0.5 * peak:
                # (a peak of a fraction of a person that then vanishes is not a dismissal)
                hit = True
                break
    assert hit, "no >= 50% retainer dismissal within 40 years of a peak, on any seed"


# ---------------------------------------------------------------------------
# 5. Funding hides the cost of war — not attempted; see reason.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Not constructed: an apples-to-apples comparison needs two wars that are identical "
        "except for `debt_policy`/`funding_mode`, which in turn needs a controlled security "
        "setup (matched M/doctrine/PSV on both sides) that `security.war.declare_war`/"
        "`step_war` don't expose as a simple fixture the way `trade.treaties.impose` does for "
        "treaties — every attempt either needs a full multi-hundred-year organic run (where "
        "war timing/outcome isn't controllable enough to isolate funding as the one variable) "
        "or enough hand-built WarState/security scaffolding to risk testing the scaffolding "
        "instead of the funding claim. Logged rather than shipped as a shallow assertion; see "
        "build/DEVIATIONS-IN-PROGRESS.md."
    ),
)
def test_funding_hides_the_cost_of_war() -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 6. Regression to equilibrium — measured: the spiral fires, but "after
# resolution" does not describe what's actually observed.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Measured on tests/scenarios/three_bands_ai.yaml, seed 1: nation_valley regresses in 25 of "
        "the 26 years from year 6 to year 31 (one single-year gap; every other year triggers "
        "again) — there is no post-resolution equilibrium window where U_dis stays below "
        "U_crit and Tree II nodes stay lit; the spiral re-triggers almost immediately every "
        "time. A forced-blockade fixture would only add one more trigger to a mechanism that "
        "is already firing on essentially every step, and wouldn't let the assertion this test "
        "needs ('after resolution, stable') be written honestly. This is a measured instance "
        "of A26's law-churn finding, not a new root cause — see "
        "build/DEVIATIONS-IN-PROGRESS.md."
    ),
)
def test_regression_to_equilibrium() -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 7. Treaty breach, weak vs strong State — measured: the mechanic this test
# would need to drive organically doesn't exist.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "politics/interests.DEMANDS (the self-enactment table) has no tariff law under any "
        "Interest — MERCHANT's demands are FREE_TRADE/NAVIGATION_ACT/CHARTERED_COMPANY/"
        "PUBLIC_CREDIT/repeal-CUSTOMS only (core/laws.tariff_law results never appear there). "
        "So there is no organic path by which a nation's own State strength (A_S) governs "
        "whether it ends up breaching an imposed TARIFF_CEILING — the only way to make one "
        "breach and the other not is to set `LawState.enacted`/`enforcement` directly on each, "
        "which tests `trade.treaties.check_breach` (already covered by "
        "tests/test_treaties.py) rather than 'a weak-State nation breaches, a strong one "
        "doesn't'. See build/DEVIATIONS-IN-PROGRESS.md."
    ),
)
def test_treaty_breach_weak_vs_strong_state() -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 9. Laissez-faire viability — measured: blocked by the same chain-gating
# issue as A46, on the only scenario this test can run on.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Measured on tests/scenarios/three_bands.yaml, seeds 1-3, 500 years each: a hand-driven "
        "'laissez-faire' policy (every year: ENACT Protection of Property if not enacted, "
        "REPEAL any of SERFDOM/GUILD_CHARTER/NAVIGATION_ACT/APPRENTICESHIP/COMBINATION_ACT/"
        "CHARTERED_COMPANY/SETTLEMENT_LAW that is enacted, queued directly via core.actions."
        "enqueue — no change to stock/ai/*, which 07/08 don't own) reaches a manufactory in "
        "0 of 3 seeds within 500 years. This is A46's already-logged root cause: nation_valley "
        "never herds, so core/trees.PRODUCTION_CHAIN's sequential gating (each node needs its "
        "predecessor lit) keeps it stuck at node 1 of 11 regardless of sovereign policy. "
        "Note also that this same policy, left running past game-over, reaches hegemony game "
        "over by year ~29 on this scenario (one nation gets a decisive head start over two "
        "other null-sovereign nations almost immediately) — worth knowing if this scenario is "
        "reused for a different test. See build/DEVIATIONS-IN-PROGRESS.md (A46) and "
        "build/DEVIATIONS-RESOLVED.md."
    ),
)
def test_laissez_faire_viability() -> None:
    RESTRAINTS = [
        LawId.SERFDOM,
        LawId.GUILD_CHARTER,
        LawId.NAVIGATION_ACT,
        LawId.APPRENTICESHIP,
        LawId.COMBINATION_ACT,
        LawId.CHARTERED_COMPANY,
        LawId.SETTLEMENT_LAW,
    ]
    hits = 0
    seeds = (1, 2, 3)
    for seed in seeds:
        world = load_scenario(SCENARIOS / "three_bands.yaml")
        world.rng = make_rng(seed)
        nation_id = "nation_valley"
        for _ in range(500):
            nation = world.nations.get(nation_id)
            if nation is None or nation.ended:
                break
            if nation.seat is not SeatKind.BAND:
                prop = nation.laws.get(LawId.PROTECTION_OF_PROPERTY)
                if prop is None or not prop.enacted:
                    payload = {"law": LawId.PROTECTION_OF_PROPERTY, "spend": 1e9}
                    enqueue(world, Action(kind=ActionKind.ENACT, nation=nation_id, payload=payload))
                for law in RESTRAINTS:
                    state = nation.laws.get(law)
                    if state is not None and state.enacted:
                        payload = {"law": law, "spend": 1e9}
                        enqueue(world, Action(kind=ActionKind.REPEAL, nation=nation_id, payload=payload))
            run_year(world)
        if manufactory_year(world.ledger, nation_id) is not None:
            hits += 1
    assert hits / len(seeds) >= 0.6, f"manufactory reached in only {hits}/{len(seeds)} seeds within 500 years"
