"""Pydantic models for the UI (Doc 07): every number on screen exists in one of these.

The JS formats and draws; it never computes. So a `Snapshot` carries raw numbers
(baskets, shares, rates — never a pre-formatted string) plus the small amount of
purely-visual data (map layout, colours) that isn't a game number at all. The one
exception is `EventEntry.text`: the event feed is "the only prose" (Doc 07 spec), and
that text is generated once, server-side, from `stock/ui/strings.py`'s numbers-only
templates — the client never assembles game text itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HeadlineNumber(BaseModel):
    key: str
    label: str
    value: float
    delta: float
    sparkline: list[float] = []


class HegemonyBand(BaseModel):
    active: bool = False
    nation: str | None = None
    nation_name: str | None = None
    nation_color: str | None = None
    flags: list[str] = []
    years_remaining: int | None = None


class Header(BaseModel):
    year: int
    headline: list[HeadlineNumber] = []
    hegemony_band: HegemonyBand | None = None


class RecordSummary(BaseModel):
    cls: str
    size: float


class ProducerSummary(BaseModel):
    kind: str
    method: str


class MapNode(BaseModel):
    id: str
    name: str = ""
    x: float
    y: float
    nation: str | None = None
    nation_name: str | None = None
    nation_color: str | None = None
    population: float
    radius: float
    terrain: str
    river: bool
    coast: bool
    contested: bool
    resources: list[str] = []
    is_capital: bool = False
    is_band: bool = False
    #: the player's own territory / adjacent to it (what band-mode "move or stay" compares)
    is_player: bool = False
    adjacent_to_player: bool = False
    #: DD §3's `game+grazing × (1−depletion)` number for a band's move/stay comparison
    ground_quality: float = 0.0
    depletion: float = 0.0
    fields: float = 0.0
    records: list[RecordSummary] = []
    producers: list[ProducerSummary] = []
    prices: dict[str, float] = {}


class MapEdge(BaseModel):
    a: str
    b: str
    river: bool = False
    road: bool = False


class NationShareBars(BaseModel):
    nation: str
    name: str = ""
    color: str
    capital: float
    consumption: float
    production: float


class MapData(BaseModel):
    band_mode: bool
    nodes: list[MapNode] = []
    edges: list[MapEdge] = []
    nation_shares: list[NationShareBars] = []


class Curves(BaseModel):
    """The three MM §22 curves, one line per nation, over the last `window` years."""

    years: list[int] = []
    series: dict[str, dict[str, list[float]]] = {}  # curve name -> nation id -> values
    n_bar_band: list[float] = []  # curve-1-aligned N_bar wash, one value per year
    regression_markers: list[int] = []  # years, this nation only


class QueuedAction(BaseModel):
    id: str
    kind: str
    label: str
    cost: float
    applies_year: int


class EventEntry(BaseModel):
    year: int
    nation: str
    nation_name: str = ""
    nation_color: str
    kind: str
    numbers: dict[str, float] = {}
    text: str
    panel: str | None = None
    location: str | None = None


class NowColumn(BaseModel):
    countdown: int | None = None
    warning_fill: float = 0.0  # spiral-window fill, in [0, 1]
    regression_warning: bool = False
    queued: list[QueuedAction] = []
    events: list[EventEntry] = []


class IncomeSource(BaseModel):
    """What one producer paid a record this year: wages for its jobs, profit on the
    stock it owns there, rent on the land (Doc 07; the production → income half of
    the loop the Ledger shows)."""

    producer: str
    wages: float = 0.0
    profit: float = 0.0
    rent: float = 0.0


class LedgerRow(BaseModel):
    location: str
    location_name: str = ""
    cls: str
    size: float
    wealth_by_asset: dict[str, float] = {}
    hoard: float
    A: dict[str, float] = {}
    E: dict[str, float] = {}
    shortfall: float  # sum(max(0, E-A)) over tiers, this row's "U" contribution
    walk_away: float
    authority: float
    standing_split: dict[str, float] = {}  # {"attendance": x, "luxuries": y}, shares
    # production → income → consumption for this record
    income: float = 0.0  # this year's income after taxation, baskets
    paid: float = 0.0  # what producers paid this record before taxation (the sum of `sources`)
    taxed: float = 0.0  # paid less income, when positive: what taxation took first
    sources: list[IncomeSource] = []  # by producer: wages, profit, rent
    works_at: dict[str, float] = {}  # producer kind -> jobs this class fills there
    spend_by_good: dict[str, float] = {}  # baskets spent on each good this year
    saved: float = 0.0  # income not spent (to hoard or reinvest)


class IncidenceCard(BaseModel):
    instrument: str
    label: str = ""
    rate: float
    assessed_on: dict[str, float] = {}
    borne_by: dict[str, float] = {}
    collected: float
    cost: float


class BudgetSegment(BaseModel):
    name: str
    share: float
    productive: bool
    draw: float


class CapitalRow(BaseModel):
    location: str
    location_name: str = ""
    kind: str
    method: str
    stock: float
    jobs_filled: float
    jobs_total: float
    V: float
    labour_share: float
    profit_share: float
    rent_share: float
    deviation_from_r_bar: float
    # who works it, who owns it, what it makes, and who its value goes to
    makes: dict[str, float] = {}  # good -> quantity this year
    worked_by: dict[str, float] = {}  # class -> jobs filled
    owned_by: dict[str, float] = {}  # class -> share of the stock
    land_by: dict[str, float] = {}  # class -> share of the land
    wages_to: dict[str, float] = {}  # class -> baskets
    profit_to: dict[str, float] = {}
    rent_to: dict[str, float] = {}


class TerritoryFlow(BaseModel):
    """One territory's market this year: what its producers made, what its records
    wanted, what stayed unsold, at this year's prices (Doc 07; the consumption half
    of the loop the Ledger and Capital panels show)."""

    location: str
    name: str = ""
    price: dict[str, float] = {}
    made: dict[str, float] = {}  # supply by good, quantity
    wanted: dict[str, float] = {}  # demand by good, quantity
    unsold: dict[str, float] = {}  # inventory carried, quantity
    made_value: float = 0.0
    wanted_value: float = 0.0
    unsold_value: float = 0.0
    income_total: float = 0.0  # records' gross income
    spent_total: float = 0.0  # records' spending
    shortfall_total: float = 0.0  # records' unmet need


class InterestBar(BaseModel):
    interest: str
    authority: float
    radicalism: float


class ActionOffer(BaseModel):
    """One action the player could queue right now, drafted server-side (Doc 07
    "Actions — draft, cost, boundary"): its payload, its cost from `actions.validate`,
    and whether it is affordable — so the button shows the cost before the click and
    an unaffordable one is disabled with its shortfall. `confirm` marks the
    irreversible kinds (war, default, veto)."""

    kind: str
    label: str
    payload: dict[str, Any] = {}
    cost: float = 0.0
    affordable: bool = True
    shortfall: float = 0.0
    reason: str | None = None
    confirm: bool = False
    panel: str = "politics"
    location: str | None = None
    group: str | None = None


class LawRow(BaseModel):
    id: str
    label: str = ""
    branch: str
    enacted: bool
    enforcement: float
    veto_cooldown_until: int | None = None
    enact_cost: float | None = None
    repeal_cost: float | None = None
    enact: ActionOffer | None = None
    repeal: ActionOffer | None = None
    vetoes: list[ActionOffer] = []


class FocusInfo(BaseModel):
    kind: str
    node: str
    location: str | None
    progress: float
    upkeep: float


class FocusOption(BaseModel):
    kind: str
    nodes: list[str] = []
    takes_location: bool = False


class PoliticsPanel(BaseModel):
    A_S: float
    seat: str = "BAND"
    interests: list[InterestBar] = []
    laws: list[LawRow] = []
    focus: FocusInfo | None = None
    focus_options: list[FocusOption] = []
    set_focus: ActionOffer | None = None
    clear_focus: ActionOffer | None = None


class RouteRow(BaseModel):
    id: str
    a: str
    b: str
    a_name: str = ""
    b_name: str = ""
    prices_a: dict[str, float] = {}
    prices_b: dict[str, float] = {}
    capacity: float
    gap: dict[str, float] = {}
    volume: float
    customs: float


class TreatyCard(BaseModel):
    id: str
    a: str
    b: str
    a_name: str = ""
    b_name: str = ""
    terms: list[str] = []
    enforcement_a: float
    enforcement_b: float
    breached: bool


class TreatyProposalCard(BaseModel):
    initiator: str
    initiator_name: str = ""
    terms: list[str] = []
    accept: ActionOffer | None = None


class RoutesPanel(BaseModel):
    routes: list[RouteRow] = []
    treaties: list[TreatyCard] = []
    hostility: dict[str, float] = {}  # "a|b" -> hostility
    proposals: list[TreatyProposalCard] = []  # addressed to the player
    term_kinds: list[str] = []  # TermKind names a proposal may carry


class RivalRow(BaseModel):
    nation: str
    name: str = ""
    color: str
    M: float
    hostility: float
    distance: float
    at_war: bool = False


class PeaceOfferInfo(BaseModel):
    cession: list[str] = []
    tribute_amount: float = 0.0
    tribute_years: int = 0


class WarCard(BaseModel):
    other: str
    other_name: str = ""
    role: str  # "attacker" | "defender"
    started: int
    contested: dict[str, int] = {}
    peace_offer: PeaceOfferInfo | None = None


class SecurityPanel(BaseModel):
    M: float
    doctrine: str
    factors: dict[str, float] = {}  # units, equipment, doctrine, supply, loyalty
    PSV: float
    PTV_ext: float
    PTV_int_by_class: dict[str, float] = {}
    N_r_by_class: dict[str, float] = {}
    N_bar: float
    rivals: list[RivalRow] = []
    wars: list[WarCard] = []


class TreeNode(BaseModel):
    id: str
    lit: bool = False
    lit_year: int | None = None
    idle: bool = False
    focus: bool = False  # the sovereign's Focus targets this node


class TreeChain(BaseModel):
    """One ordered branch of a tree: Tree I for one location, or a Tree II branch."""

    id: str
    label: str = ""
    location: str | None = None
    nodes: list[TreeNode] = []


class TreesPanel(BaseModel):
    tree1: list[TreeChain] = []  # one chain per territory of the player's (WHAT)
    tree2: list[TreeChain] = []  # production, defence, credit (HOW)


class Panels(BaseModel):
    ledger: list[LedgerRow] = []
    incidence: list[IncidenceCard] = []
    budget: list[BudgetSegment] = []
    debt_choice: str
    funding_mode: str = "BONDS"
    r_market: float
    r_legal: float
    r_sovereign: float
    capital: list[CapitalRow] = []
    territories: list[TerritoryFlow] = []
    r_bar: float
    politics: PoliticsPanel
    routes: RoutesPanel
    security: SecurityPanel
    trees: TreesPanel = TreesPanel()


class NationSummary(BaseModel):
    id: str
    name: str = ""
    color: str
    seat: str
    ai: str | None
    ended: bool


class GameOver(BaseModel):
    winner_per_head: str | None = None
    winner_labour_output: str | None = None


class NameTable(BaseModel):
    nations: dict[str, str] = {}
    locations: dict[str, str] = {}


class PlayerInfo(BaseModel):
    id: str
    name: str = ""
    seat: str = "BAND"
    home: str | None = None  # a band's one location; a state's capital


class Snapshot(BaseModel):
    header: Header
    map: MapData
    curves: Curves
    now: NowColumn
    panels: Panels
    nations: list[NationSummary] = []
    player_nation: str
    player: PlayerInfo | None = None
    game_over: GameOver | None = None
    #: id -> display name (`stock/ui/names.py`), and group -> key -> plain-English
    #: label (`stock/ui/labels.py`): the JS never prints a raw id or symbol.
    names: NameTable = NameTable()
    labels: dict[str, dict[str, str]] = {}
    help: dict[str, dict[str, str]] = {}  # tooltips (stock/ui/help.py), keyed like `labels`
    #: every action the player could queue this year, drafted with its cost
    actions: list[ActionOffer] = []


class ActionRequest(BaseModel):
    nation: str
    kind: str
    payload: dict[str, Any] = {}


class ActionResult(BaseModel):
    ok: bool
    cost: float = 0.0
    reason: str | None = None
    numbers: dict[str, float] = {}
    queued_id: str | None = None


class NewWorldRequest(BaseModel):
    """`POST /new`: start over on another world. `scenario` is a `random[:seed[:locations
    [:nations]]]` spec or a scenario file path; None draws a fresh seed."""

    scenario: str | None = None
    player_nation: str | None = None


class ScenarioInfo(BaseModel):
    name: str
    path: str
