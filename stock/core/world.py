"""The world: locations, nations, and the top-level `World` (DD §1.1; MM Notation).

Field lists here are a superset of Doc 01's abbreviated sketch — that sketch marks
itself illustrative ("...") and later docs need places to keep state (Focus, tree
node state, per-record lagged security). Additions are noted in DEVIATIONS.md rather
than forked into parallel state trees on the side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from stock.core.goods import ALL_GOODS, Good
from stock.core.laws import FocusKind, LawId
from stock.core.producers import Producer
from stock.core.records import ClassId, Record
from stock.core.serialize import JSON_EXCLUDE_FIELDS, from_jsonable, to_jsonable
from stock.core.trees import LocationTreeState, NationTreeState

if TYPE_CHECKING:
    from stock.security.war import WarState


@dataclass
class Route:
    """A trade route between two locations of different nations (MM §16)."""

    id: str  # format: f"{a}->{b}" with a < b (location ids)
    a: str  # endpoint location id
    b: str  # endpoint location id
    merchant_stock: dict[str, float] = field(default_factory=dict)  # nation id -> committed stock
    ships: float = 0.0  # capacity multiplier
    charter_holder: tuple[str, ClassId] | None = None  # (nation, class) for CHARTERED_COMPANY
    last_volume_by_good: dict[Good, float] = field(default_factory=dict)
    last_capacity: float = 0.0
    last_gap_by_good: dict[Good, float] = field(default_factory=dict)
    treaty_factor: float = 1.0  # T5 writes this
    broken_years: int = 0  # T5/05 reads this
    customs_collected: float = 0.0  # Doc 05 reads this; we accumulate via the hook
    exclusive_to: str | None = None  # nation id if EXCLUSIVE_ROUTE term applies


class Terrain(Enum):
    """Broad terrain type. Gates nothing directly — `Resources` does that — but flavours
    the map and scenario authoring (DD §1.1 doesn't enumerate terrain types; this is a
    minimal inferred set, see DEVIATIONS.md)."""

    PLAINS = auto()
    HILLS = auto()
    FOREST = auto()
    MOUNTAIN = auto()
    STEPPE = auto()
    WETLAND = auto()
    COASTAL_PLAIN = auto()


class SeatKind(Enum):
    """Who holds the seat over a nation (DD §1.1, §7.3 handovers)."""

    BAND = auto()
    CHIEF = auto()
    STATE = auto()


@dataclass
class Resources:
    """What a location can produce (DD §1.1). Boolean gates plus the yield magnitudes
    the production functions need (MM §4's `y_game(loc)`, `y_arable(loc)`, etc.) — DD
    treats resources as gates but the production functions need a rate, not just a
    flag, so each gate has a paired yield (0 when the gate is false)."""

    game: bool = False
    game_yield: float = 0.0
    grazing: bool = False
    arable: bool = False
    arable_yield: float = 0.0
    timber: bool = False
    timber_yield: float = 0.0
    ore: bool = False
    ore_yield: float = 0.0
    coal: bool = False
    coal_yield: float = 0.0
    fishing: bool = False
    fishing_yield: float = 0.0
    rare: bool = False


@dataclass
class Capacity:
    """Carrying capacity and depletion for game and grazing (DD §1.1; MM §4)."""

    game_cap: float = 0.0
    graze_cap: float = 0.0
    game_depletion: float = 0.0  # in [0, 1]
    graze_depletion: float = 0.0  # in [0, 1]


@dataclass
class Market:
    """One market per location (DD §4.5, §4.7; MM §7, §9). A location with no
    producers and no records has no market — callers create one lazily."""

    price: dict[Good, float] = field(default_factory=lambda: {g: 1.0 for g in ALL_GOODS})
    inventory: dict[Good, float] = field(default_factory=lambda: {g: 0.0 for g in ALL_GOODS})
    last_demand: dict[Good, float] = field(default_factory=lambda: {g: 0.0 for g in ALL_GOODS})
    last_supply: dict[Good, float] = field(default_factory=lambda: {g: 0.0 for g in ALL_GOODS})


@dataclass
class Location:
    id: str
    terrain: Terrain
    resources: Resources = field(default_factory=Resources)
    capacity: Capacity = field(default_factory=Capacity)
    neighbours: dict[str, float] = field(default_factory=dict)  # id -> distance
    river: bool = False
    coast: bool = False
    roads: dict[str, float] = field(default_factory=dict)  # neighbour id -> carriage factor
    nation: str | None = None
    records: list[Record] = field(default_factory=list)
    producers: list[Producer] = field(default_factory=list)
    fields: float = 0.0  # land shares in existence (fixed assets)
    market: Market = field(default_factory=Market)
    tree1: LocationTreeState = field(default_factory=LocationTreeState)
    #: per-nation "contact" accumulator (DD §3: following the herds), the gate on
    #: Domesticated herds (see DEVIATIONS.md — not in Doc 01's abbreviated sketch).
    contact: dict[str, float] = field(default_factory=dict)
    #: optional authored chart position (scenario `x`/`y`, any units) and display
    #: name — presentation only, read by Doc 07's map layout and name register; the
    #: engine never reads them. Absent (None) means "let the UI derive one".
    x: float | None = None
    y: float | None = None
    name: str | None = None

    def record(self, cls: ClassId) -> Record | None:
        for r in self.records:
            if r.cls is cls:
                return r
        return None

    def is_town(self) -> bool:
        """A location becomes a town when enough non-agricultural records live there
        (DD §1.1). Threshold is a placeholder pending Doc 02/05 tuning."""

        non_agri = sum(
            r.size
            for r in self.records
            if r.cls
            not in (ClassId.LANDLORDS, ClassId.TENANTS, ClassId.SERFS, ClassId.HERD_OWNERS, ClassId.HERDSMEN)
        )
        total = sum(r.size for r in self.records) or 1.0
        return non_agri / total > 0.5 and non_agri > 20


@dataclass
class LawState:
    enacted: bool = False
    enforcement: float = 0.0
    enacted_year: int | None = None
    veto_cooldown_until: int | None = None
    years_below_enf_min: int = 0


@dataclass
class FocusState:
    """The sovereign's Focus (DD §6.4). One at a time; switching forfeits progress."""

    kind: FocusKind
    node: str
    location: str | None = None
    progress: float = 0.0
    upkeep: float = 0.0
    expires_year: int | None = None  # Patent's N-year exclusivity


@dataclass
class TreatyRef:
    """A lightweight pointer from a Nation to a Treaty (whose terms/state live in
    `trade.treaties`, Doc 04) — kept minimal here since Doc 01 doesn't own treaties."""

    id: str
    other_nation: str


@dataclass
class Tribute:
    """A tributary flow from one nation to another (Doc 04: step 13 war/peace).

    Payer: the nation owing the tribute.
    Payee: the nation receiving the tribute.
    Amount: baskets per year.
    Years_left: years remaining; decremented each year, dropped at 0.
    """

    payer: str
    payee: str
    amount: float
    years_left: int


@dataclass
class InterestState:
    authority: float = 0.0
    radicalism: float = 0.0


@dataclass
class BudgetShares:
    """Budget allocation as shares of collected revenue (DD §12.2)."""

    defence: float = 0.4
    justice: float = 0.1
    works: float = 0.2
    service: float = 0.1
    court: float = 0.1
    transfers: float = 0.1

    def validate(self) -> None:
        """Raise ValueError if shares don't sum to 1.0 (within tolerance)."""
        total = sum([self.defence, self.justice, self.works, self.service, self.court, self.transfers])
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"BudgetShares sum to {total}, expected 1.0")


@dataclass
class IncidenceTable:
    """Tax incidence by instrument: assessed on and borne by, by class (DD §12.2)."""

    instrument: Any = None  # LawId | str key
    assessed_on: dict[ClassId, float] = field(default_factory=dict)  # class -> baskets
    borne_by: dict[ClassId, float] = field(default_factory=dict)  # class -> baskets
    collected: float = 0.0  # total collected this year
    cost: float = 0.0  # collection cost in baskets


@dataclass
class NationScalars:
    """Per-nation scalars named directly after their MM symbol (MM Notation, §3, §12,
    §14, §18)."""

    r_bar: float = 0.0
    A_S: float = 0.0
    J: float = 0.0
    ell: float = 0.0
    PSV: float = 0.0
    PTV_ext: float = 0.0  # external threat (Doc 04)
    N_bar: float = 0.0
    O: float = 0.0
    U_dis: float = 0.0
    R_private: float = 0.0
    debt: float = 0.0
    default_history: bool = False
    public_credit_closed_until: int | None = None
    farmed_share: float = 0.0
    court: float = 0.0
    direct_share: float = 0.0  # "direct/revenue" term in the A_S formula (MM §12)
    revenue: float = 0.0
    treasure: float = 0.0
    service: float = 0.0
    M: float = 0.0
    M_state: float = 0.0
    #: this year's pool of freed + reinvested stock awaiting placement (MM §6);
    #: accumulated by engine.capital.hoard_update at step 7, consumed and zeroed by
    #: engine.capital.placement at step 9. Not in Doc 01's abbreviated sketch.
    to_reinvest_pool: float = 0.0
    #: active doctrine (Doc 04): EVERY_MAN, NATION_IN_ARMS, FEUDAL_HOST, MILITIA, STANDING_ARMY
    active_doctrine: str = "EVERY_MAN"
    #: baskets of Arms held (Doc 04)
    arms_stock: float = 0.0
    #: value of army bought this year (Doc 04, step_army_purchase)
    army_bought: float = 0.0
    #: defence draw for army purchase (Doc 05)
    defence_draw: float = 0.0
    #: soldier pay per soldier (Doc 05)
    soldier_pay: float = 0.0
    #: whether nation is currently at war (Doc 04, T3)
    at_war: bool = False
    #: whether army is deployed inside the nation (Doc 04, T3 repression): suppresses disorder
    army_inside: bool = False
    #: justice draw for this year (Doc 05)
    justice_draw: float = 0.0
    #: works draw for this year (Doc 05)
    works_draw: float = 0.0
    #: transfers draw for this year (Doc 05)
    transfers_draw: float = 0.0
    #: whether service is unfunded (Doc 05)
    service_unfunded: bool = False
    #: unfunded laws that should lapse (Doc 05)
    unfunded_laws: frozenset[Any] = field(default_factory=frozenset)  # frozenset[LawId | str]
    #: MM §18 rates this year (Doc 05 credit): r_market, r_legal, r_sovereign
    r_market: float = 0.0
    r_legal: float = 0.0
    r_sovereign: float = 0.0
    #: bonds issued this year, `max(0, spending − revenue)` (MM §18); Doc 05 credit
    bonds_issued: float = 0.0
    #: extra spending committed beyond the budgeted draws this year (a war's cost, a
    #: sovereign's request) that bonds may fund (MM §18 `spending`); Doc 04/05 write it
    spending_extra: float = 0.0
    #: service due next year on the public debt, `D·r_sovereign` (MM §18); Doc 05 credit
    service_due: float = 0.0
    #: this year's actual service draw (`budget.service * collected`), written by
    #: finance/taxation.py's step 3 for finance/credit.py's step 6 to read (Doc 05 credit)
    service_draw: float = 0.0
    #: outstanding private-credit principal (DD §11), interest-only, aggregate per
    #: nation (Doc 05 credit)
    private_debt: float = 0.0
    #: regression state (Doc 05 meta/regression): consecutive spiral-window years,
    #: regressions so far, warning band on/off
    spiral_years: int = 0
    regressions: int = 0
    regression_warning: bool = False
    last_regression_year: int | None = None
    #: band stage (Doc 02 engine/band): years in a row produce per head fell below 1
    pressed_years: int = 0
    #: last year's N_bar / produce_per_head, for spiral_window's "falling" checks
    #: (Doc 05 meta/regression)
    prev_n_bar: float = 0.0
    prev_produce_per_head: float = 0.0


@dataclass
class Nation:
    id: str
    seat: SeatKind = SeatKind.BAND
    state: Record | None = None  # the State record (DD §2.2); present from CHIEF on
    laws: dict[Any, LawState] = field(default_factory=dict)  # LawId | str (trade laws)
    treaties: list[TreatyRef] = field(default_factory=list)
    tributes: list[Tribute] = field(default_factory=list)  # tributaries (Doc 04: war/peace)
    queue: list[Any] = field(default_factory=list)  # list[Action], applied at step 14
    scalars: NationScalars = field(default_factory=NationScalars)
    interests: dict[Any, InterestState] = field(default_factory=dict)  # InterestId -> state
    tree2: NationTreeState = field(default_factory=NationTreeState)
    focus: FocusState | None = None
    ended: bool = False
    ai: str | None = None  # sovereign kind: None/"null" | "scripted" | "player"; Docs 02/04/06/07 read it
    #: optional authored display name (scenario `name`); presentation only, see Location.name
    name: str | None = None
    #: this year's value flows in baskets, reset at the start of the year by the year
    #: runner, written by engine steps, flushed to the ledger row — the source for Doc 08's
    #: value-conservation invariants
    flows: dict[str, float] = field(default_factory=dict)
    #: tax rates by instrument (LawId or str), read at step 14 via apply_action (Doc 05)
    tax_rates: dict[LawId | str, float] = field(default_factory=dict)
    #: incidence table from last year (lagged): assessed-on this year filled at step 3,
    #: borne_by computed and stored for next year (Doc 05)
    incidence: dict[Any, IncidenceTable] | None = None  # dict[LawId | str, IncidenceTable]
    #: budget shares (defence, justice, works, service, court, transfers) summing to 1.0 (Doc 05)
    budget: BudgetShares = field(default_factory=BudgetShares)
    #: the sovereign's standing answer to `debt_choice` (Doc 05 credit): "TAX" | "ROLLOVER" | "DEFAULT";
    #: a null sovereign leaves it at ROLLOVER (Doc 05)
    debt_policy: str = "ROLLOVER"
    #: how extra spending is funded when Public Credit is open: "BONDS" | "TAX" (Doc 05 credit)
    funding_mode: str = "BONDS"
    #: this year's three curves (MM §22), written by meta/scoreboards, copied to the ledger row
    curves: dict[str, float] = field(default_factory=dict)
    #: exogenous-event and regression flags (Doc 05 meta): e.g. "watt", "plague:<year>"
    flags: set[str] = field(default_factory=set)
    #: the final ledger snapshot (DD §13) written once by meta/regression.end_nation
    final_ledger: dict[str, float] | None = None

    def locations(self, world: World) -> list[Location]:
        return [loc for loc in world.locations.values() if loc.nation == self.id]

    def all_records(self, world: World) -> list[Record]:
        return [r for loc in self.locations(world) for r in loc.records]

    def population(self, world: World) -> float:
        """Everyone at every location the nation holds (the State record included)."""

        return sum(r.size for r in self.all_records(world))

    def add_flow(self, key: str, amount: float) -> None:
        """Accumulate a value flow in this year's flows dict."""
        self.flows[key] = self.flows.get(key, 0.0) + amount


@dataclass
class HegemonyState:
    """World shares and the countdown (DD §1.4; MM §23)."""

    capital_share: dict[str, float] = field(default_factory=dict)
    consumption_share: dict[str, float] = field(default_factory=dict)
    production_share: dict[str, float] = field(default_factory=dict)
    flags: dict[str, int] = field(default_factory=dict)
    countdown: int | None = None
    countdown_nation: str | None = None
    game_over: bool = False
    winner_per_head: str | None = None
    winner_labour_output: str | None = None


@dataclass
class PrevSnapshot:
    """The lag-rule snapshot (Doc 00): fields a step reads that a *later* step this
    year will write, frozen at the start of the year. Extended by later docs as new
    lag cases are found (see DEVIATIONS.md) rather than redesigned.

    - `r_bar`: MM §5, `r_bar_{t-1}` used by the split rule at step 1.
    - `price`: DD §4.3, "V = price x Q at last year's price", used at step 1.
    - `record_f_n`: `f(N_r)` used by `hoard_update` at step 7; `N_r` is only produced
      at step 13 (security), which runs later in the year.
    - `M`: MM §14, `M_{t-1}` of each rival used by `perceived_security` at step 13;
      written by `strength` this year.
    """

    r_bar: dict[str, float] = field(default_factory=dict)
    price: dict[tuple[str, Good], float] = field(default_factory=dict)
    record_f_n: dict[tuple[str, ClassId], float] = field(default_factory=dict)
    M: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def take(world: World) -> PrevSnapshot:
        r_bar = {nid: n.scalars.r_bar for nid, n in world.nations.items()}
        price: dict[tuple[str, Good], float] = {}
        for loc in world.locations.values():
            for g, p in loc.market.price.items():
                price[(loc.id, g)] = p
        # populated by security (Doc 04); {} until then. The nation id in
        # `_f_n_by_record`'s key is redundant (a location has one owning nation) and
        # dropped here since PrevSnapshot only needs to key by (location, class).
        record_f_n = {(loc_id, cls): f_n for (_nid, loc_id, cls), f_n in world._f_n_by_record.items()}
        # M from each living nation (Doc 04); written by strength each year
        M = {nid: n.scalars.M for nid, n in world.nations.items() if not n.ended}
        return PrevSnapshot(r_bar=r_bar, price=price, record_f_n=record_f_n, M=M)


class WorldError(ValueError):
    """Raised by `World.validate()` for a structural invariant violation."""


@dataclass
class World:
    year: int
    nations: dict[str, Nation]
    locations: dict[str, Location]
    hostility: dict[tuple[str, str], float] = field(default_factory=dict)
    hegemony: HegemonyState = field(default_factory=HegemonyState)
    #: world-level exogenous-event flags (Doc 05 meta/events), e.g. "watt"
    flags: set[str] = field(default_factory=set)
    prev: PrevSnapshot = field(default_factory=PrevSnapshot)
    ledger: Any = None  # sim.ledger.Ledger; Any avoids an import cycle at module load
    rng: Any = None  # numpy.random.Generator
    params: Any = None  # core.params.Params

    #: f(N_r) as of the last time security (Doc 04) ran, keyed like `Record.key()`,
    #: prefixed by nation id: (nation_id, location_id, cls). {} until Doc 04 exists,
    #: matching Doc 02's "pass f=1.0" fallback for its own tests.
    _f_n_by_record: dict[tuple[str, str, ClassId], float] = field(default_factory=dict)
    #: trade volume between nation pairs last year (Doc 04, T4 writes it)
    trade_volume: dict[tuple[str, str], float] = field(default_factory=dict)
    #: number of kept treaties between nation pairs (Doc 04, T5 writes it)
    kept_treaties_count: dict[tuple[str, str], float] = field(default_factory=dict)
    #: set of nation pairs with active tribute flows (Doc 04, T3/peace writes it)
    tribute_pairs: set[tuple[str, str]] = field(default_factory=set)
    #: wars indexed by (attacker_id, defender_id) tuple; tuple keys serialize via __dict__ tag
    wars: dict[tuple[str, str], "WarState"] = field(default_factory=dict)  # noqa: UP037
    #: cross-border routes indexed by route id (e.g., "loc_a->loc_b")
    routes: dict[str, Route] = field(default_factory=dict)
    #: treaties indexed by treaty id; forward ref to trade.treaties.Treaty
    treaties: dict[str, Any] = field(default_factory=dict)
    #: pending treaty proposals for acceptance (list of dicts with initiator/target/terms)
    treaty_proposals: list[dict[str, Any]] = field(default_factory=list)
    #: set of (attacker, defender) pairs where attacker has casus belli against defender
    casus_belli: set[tuple[str, str]] = field(default_factory=set)
    #: dict to track years a treaty was breached per side (for check_breach)
    breached_years: dict[str, int] = field(default_factory=dict)

    def location_of(self, record: Record) -> Location:
        return self.locations[record.location]

    def validate(self) -> None:
        """Structural invariants (Doc 01). Raises WorldError on the first violation."""

        for nation_id, nation in self.nations.items():
            if nation.id != nation_id:
                raise WorldError(f"nation key {nation_id!r} != nation.id {nation.id!r}")

        for loc_id, loc in self.locations.items():
            if loc.id != loc_id:
                raise WorldError(f"location key {loc_id!r} != location.id {loc.id!r}")
            if loc.nation is not None and loc.nation not in self.nations:
                raise WorldError(f"location {loc_id!r} claims unknown nation {loc.nation!r}")
            for record in loc.records:
                if record.location != loc_id:
                    raise WorldError(
                        f"record {record.cls.name} lives in {record.location!r} "
                        f"but is stored under location {loc_id!r}"
                    )
                if record.size < 0:
                    raise WorldError(f"record {record.cls.name} at {loc_id!r} has negative size")
                if record.debt < 0:
                    raise WorldError(f"record {record.cls.name} at {loc_id!r} has negative debt")
                for field_name, value in record.wealth.as_dict().items():
                    if value < 0:
                        raise WorldError(
                            f"record {record.cls.name} at {loc_id!r} has negative "
                            f"wealth.{field_name}"
                        )
            for producer in loc.producers:
                _check_shares(producer.owners_stock, f"producer {producer.id()} owners_stock")
                _check_shares(producer.owners_land, f"producer {producer.id()} owners_land")

        for (i, j), h in self.hostility.items():
            reverse = self.hostility.get((j, i))
            if reverse is not None and reverse != h:
                raise WorldError(f"hostility[{i},{j}]={h} != hostility[{j},{i}]={reverse}")

    def to_json(self) -> str:
        """JSON round-trip covers everything under Doc 00's "tree of dataclasses"
        (nations, locations, records, producers, scalars, params, ...). `ledger` and
        `rng` are excluded (output and transient state, not simulation state) — see
        `JSON_EXCLUDE_FIELDS`."""

        import json

        return json.dumps(to_jsonable(self))

    @staticmethod
    def from_json(data: str) -> World:
        import json

        world = from_jsonable(json.loads(data))
        assert isinstance(world, World)
        return world

    def summary(self) -> str:
        lines = [f"Year {self.year}"]
        for nid, nation in sorted(self.nations.items()):
            locs = nation.locations(self)
            n_records = sum(len(loc.records) for loc in locs)
            lines.append(
                f"  {nid}: seat={nation.seat.name} locations={len(locs)} records={n_records} "
                f"A_S={nation.scalars.A_S:.2f}"
            )
        lines.append(f"  locations: {len(self.locations)}")
        return "\n".join(lines)


def _check_shares(shares: dict[Any, float], label: str) -> None:
    if not shares:
        return
    total = sum(shares.values())
    if abs(total - 1.0) > 1e-6:
        raise WorldError(f"{label} shares sum to {total}, expected 1.0")


JSON_EXCLUDE_FIELDS[World] = frozenset({"ledger", "rng"})
