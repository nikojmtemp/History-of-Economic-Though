# 01 — Core Data Model (Sweep 1, task 1)

**Read**: 00.
**Owns**: `stock/core/*`, `stock/sim/scenario.py`, `stock/sim/ledger.py`, `stock/sim/rng.py`, `params/default.yaml`, `scenarios/three_bands.yaml`.
**Depends on**: nothing.

## Goal

The data every later step reads and writes, loadable from a scenario file, serialisable, and validated. No simulation logic yet except construction, invariants, and the action queue.

## Deliverables

### `core/goods.py`
```python
class Good(Enum): PROVISIONS, MATERIALS, WARES, LUXURIES, ARMS, SHIPS, ATTENDANCE
BASKET: dict[Good, float]        # the unit of account: one person-year of Provisions plus a little Wares
TIER: dict[Good, Tier]           # SUBSISTENCE / COMFORT / STANDING — Provisions+some Wares / Wares / Luxuries+Attendance
```

### `core/params.py`
`@dataclass(frozen=True) class Params`, grouped into nested per-area dataclasses (`PriceParams`, `ConsumptionParams`, `SecurityParams`, `TradeParams`, `CreditParams`, `TreeParams`, …) that later tasks extend with their own fields — each numbered document names the fields it needs and the formula symbol each maps to; put that mapping in a docstring on the field. Seed `Params` in this task with the fields named below and in Doc 02–08's own sections (each documents its constants where it introduces them). `Params.load(path)`; `Params.default()`. Unknown keys in YAML raise.

### `core/world.py`
```python
@dataclass class Location:
    id: str; terrain: Terrain; resources: Resources   # game, grazing, arable, timber, ore, coal, fishing, rare: bool
    capacity: Capacity                                 # game_cap, graze_cap, depletion ∈ [0,1] for each
    neighbours: dict[str, float]                       # id → distance
    river: bool; coast: bool; roads: dict[str, float]  # per-edge carriage factor
    nation: str | None
    records: list[Record]; producers: list[Producer]
    fields: float                                      # land shares in existence (fixed assets)
    market: Market                                     # prices, inventories, last demand/supply per Good
@dataclass class Nation:
    id: str; seat: SeatKind                            # BAND | CHIEF | STATE
    state: Record                                      # the State record (ClassId.STATE), present from seat CHIEF on
    laws: dict[LawId, LawState]                        # enacted, enforcement, cooldowns
    treaties: list[TreatyRef]
    queue: list[Action]                                # applied at step 14
    scalars: NationScalars                             # r_bar, A_S, J, ell, PSV, N_bar, O, U_dis, R_private, debt, …
    interests: dict[InterestId, InterestState]         # authority, radicalism, demand table state
@dataclass class World:
    year: int; nations: dict[str, Nation]; locations: dict[str, Location]
    hostility: dict[tuple[str, str], float]
    hegemony: HegemonyState                            # shares, flags, countdown
    prev: PrevSnapshot                                 # lagged scalars (00: lag rule)
    ledger: Ledger; rng: Generator; params: Params
```

### `core/records.py`
```python
class ClassId(Enum): HUNTERS, HERD_OWNERS, HERDSMEN, LANDLORDS, CLERGY, SERFS, RETAINERS, CRAFTSMEN, TENANTS,
                     MERCHANTS, CAPITALISTS, LABOURERS, SERVANTS, SOLDIERS, COLLECTORS, STATE
@dataclass class Wealth: herd, land_shares, fixed_assets, stock_in_place, hoard, bonds, tools, loans_out   # baskets
@dataclass class Record:
    cls: ClassId; location: str; size: float; wealth: Wealth; debt: float
    A: TierVec; E: TierVec            # satisfaction and expected, per tier
    walk_away: float; authority: float
    mobilised: bool                    # levy / militia / nation-in-arms state
    flags: set[str]                    # e.g. "rent_pledged"
CLASS_TABLE: dict[ClassId, ClassSpec]  # productive, base walk-away, base propensity, tier profile, interest asset map
```
`ClassSpec` field values, one row per `ClassId` (walk-away is the share of this year's income the record keeps if it leaves its employer):

| Class | Productive? | Base walk-away | Owns (for interest apportionment) |
|---|---|---|---|
| HUNTERS | yes | 1.0 | tools, the kill (no interest asset class — apportions via labour legibility) |
| HERD_OWNERS | owner | 1.0 | herd → Landed |
| HERDSMEN | yes | 0.2 | — (labour power) → Labour |
| LANDLORDS | no | 1.0 | land shares → Landed |
| CLERGY | no | 1.0 | Church land → Landed |
| SERFS | yes | `0 × enforcement(Serfdom)` | — (bound; labour power) → Labour |
| RETAINERS | no | 0.1 | — (labour power) → Labour |
| CRAFTSMEN | yes | 0.7 | tools, materials → Industrial |
| TENANTS | yes | 0.5 | lease, small stock → Landed (small) |
| MERCHANTS | yes | 1.0 | trading stock, Ships, routes held → Merchant |
| CAPITALISTS | owner | 1.0 | stock in producers → Industrial |
| LABOURERS | yes | computed each year by wage bargaining (task 02, `engine/wages.py`) | — (labour power) → Labour |
| SERVANTS | no | 0.4 | — (labour power) → Labour |
| SOLDIERS | no | `0` enlisted; desertion is a mobility flow, not a walk-away value | — (labour power) → Labour |
| COLLECTORS | no | 0.6 (visible in v2 only) | — (labour power) → Labour |
| STATE | — | — | treasure, crown demesne, bonds issued — one per nation, not apportioned to an Interest |

Bonds and loans out (however held) apportion to Moneyed regardless of class — the Moneyed Interest
*emerges* whenever a record's wealth includes them; there is no fixed roster of classes for it.

**Tier access by class** (used by task 02's consumption function to gate which tiers a class can
reach — treat as a hard cutoff only at the two extremes below; every other class reaches all three
tiers and lets the tier logit's own price/weight terms produce thin standing spend where appropriate):
`SUBSISTENCE_ONLY_CLASSES = {HUNTERS, HERDSMEN, SERFS, RETAINERS, SERVANTS, SOLDIERS}` never reach
comfort or standing. Every other class (LABOURERS, CRAFTSMEN, TENANTS, HERD_OWNERS, LANDLORDS,
MERCHANTS, CAPITALISTS) can reach comfort and standing once income allows it.

Rule: **a record's `size` for RETAINERS and SERVANTS is derived** — it equals the Attendance purchase that maintains it, set only in task 02's consumption step; provide `derived_size_classes` and assert no step writes their size directly.

### `core/producers.py`
```python
class ProducerKind(Enum): HUNTING, HERDING, FIELD, WORKSHOP, PUTTING_OUT, MANUFACTORY, MINE, PORT, STATE
@dataclass class Producer:
    kind; location: str; method: MethodId
    stock_in_place: float; land_shares: float; site_rent: float
    owners_stock: dict[ClassId, float]; owners_land: dict[ClassId, float]   # shares by class
    jobs: float; filled: dict[ClassId, float]
    inputs: dict[Good, float]; outputs: dict[Good, float]                    # per unit Q, from METHOD_TABLE
    last_V: float; last_Q: float
```
Occupations (HUNTING, HERDING) have `location = record.location` re-bound each year and no fixed assets — they are attached to a mobile record, not to a place. Buildings (FIELD, WORKSHOP, PUTTING_OUT, MANUFACTORY, MINE, PORT, STATE) sit fixed in one location.

### `core/laws.py`
`LawId` enum with one member per row below. `LAW_TABLE: dict[LawId, LawSpec]` with `branch, support: set[InterestId], opposition: set[InterestId], binds: InterestId, weight, effects: EffectSpec` (effects are declarative tags read by the engines, e.g. `friction(edge="free_labour_cross_location", x=0.6)`, `enforcement_in_wage=True`, `unlocks=("MANUFACTORY",)`). `InterestId` is `LANDED | INDUSTRIAL | MERCHANT | MONEYED | LABOUR` (defined fully in task 03; usable here as a bare enum).

| Branch | LawId | Effect | Support | Opposition |
|---|---|---|---|---|
| Property | `SHARE_RULE` | the band's share rule (kill to the killer / shared by custom) | — | — |
| Property | `TAMED_ANIMAL_TO_TAMER` | herds become mobile stock; owner and herdsman records appear | herd-holders | — |
| Property | `PROTECTION_OF_PROPERTY` | creates the State record; raid losses fall; a tax on all | LANDED | LABOUR |
| Property | `HERDS_HERITABLE` | owner record's `size` held down as herds grow (concentration) | LANDED | — |
| Property | `LAND_OWNABLE` | fields become land shares; landlord records appear | LANDED | LABOUR |
| Property | `PRIMOGENITURE` | owner `size` held down; default pledges rent, keeps title | LANDED | MERCHANT, INDUSTRIAL |
| Property | `ALIENABLE` (repeals/replaces `PRIMOGENITURE`) | owner `size` free to rise; tenants; default transfers land outright | MERCHANT, INDUSTRIAL | LANDED |
| Property | `STOCK_SEPARABLE` | unlocks the manufactory; the profit-stream split rule applies to it | INDUSTRIAL, MERCHANT | LANDED |
| Labour | `SERFDOM` | walk-away `0 × enforcement`; no migration off the land | LANDED | LABOUR |
| Labour | `COMMUTATION` | serf → tenant vertical edge opens; rent paid in coin | LABOUR, MERCHANT | LANDED |
| Labour | `ENCLOSURE` | commons → land shares; serfs/tenants → labourers (forced vertical edge); migration; Materials (wool) output | LANDED | LABOUR |
| Labour | `SETTLEMENT_LAW` | friction on free-labour cross-location edges | LANDED | INDUSTRIAL, LABOUR |
| Labour | `APPRENTICESHIP` | friction on producer hiring edges; a State wage ceiling | INDUSTRIAL (masters) | LABOUR |
| Labour | `GUILD_CHARTER` | craftsmen count capped; blocks manufactories in the town | INDUSTRIAL (craftsmen) | INDUSTRIAL (capitalists), MERCHANT |
| Labour | `COMBINATION_ACT` | enforcement term enters the wage formula (masters' side) | INDUSTRIAL | LABOUR |
| Commerce | `FREE_TRADE` (default) | routes open to all | MERCHANT | INDUSTRIAL (protected) |
| Commerce | `TARIFF` (per good class) | import price up / route closed; that class dearer for all | the protected producer's Interest | MERCHANT, LABOUR |
| Commerce | `PROHIBITION` (per good class) | route closed outright for that class | the protected producer's Interest | MERCHANT, LABOUR |
| Commerce | `BOUNTY` (per good class) | export price pushed above natural price; stock pulled toward it | the producer's Interest | whoever pays for the bounty |
| Commerce | `NAVIGATION_ACT` | domestic Ships only; carriage cost up; navy base; maritime hostility | MERCHANT (shipping) | MERCHANT (carriers), INDUSTRIAL |
| Commerce | `CHARTERED_COMPANY` | one merchant record holds a route exclusively; the price gap stays; State takes a cut | MERCHANT (holder) | INDUSTRIAL, LABOUR |
| Revenue | `LAND_TAX`, `TITHE`, `CAPITATION`, `WAGE_TAX`, `PROFIT_TAX`, `EXCISE_PROVISIONS_WARES`, `EXCISE_LUXURIES`, `CUSTOMS`, `TOLLS`, `POOR_RATE`, `TAX_FARMING`, `SALE_OF_CROWN_LANDS` (base and incidence for each in task 05's tax-instrument table), `SINGLE_TAX_ON_RENT` | — | whoever escapes the instrument | the payer; LANDED |
| Credit | `USURY_LAW` (payload: prohibition / cap value / none) | governs `r_legal` (task 05) | varies | varies; LANDED |
| Credit | `PUBLIC_CREDIT` | unlocks State bond issuance | MERCHANT, INDUSTRIAL; MONEYED once bonds exist | LANDED |
| Credit | `SINKING_FUND` (v2, stub only) | — | — | — |
| Defence | `STANDING_ARMY_ACT` | creates the SOLDIERS record; a defence draw funds it | MERCHANT, INDUSTRIAL | LANDED |
| Defence | `MILITIA_ACT` | seasonal levy from tenants/craftsmen | LANDED | INDUSTRIAL |
| Justice | `ADMINISTRATION_OF_JUSTICE` | the justice draw raises `J` above its customary floor | MERCHANT, INDUSTRIAL | LANDED |
| Relief | `POOR_RATE` | transfers funded on rent | LABOUR, INDUSTRIAL | LANDED |
| Relief | `PRICE_CONTROL_ON_GRAIN` | price cap on Provisions; supply falls | LABOUR, INDUSTRIAL | LANDED |

Focus kinds (task 03's `politics/focus.py` consumes these; declare the enum here): `PUBLIC_WORKS` (cuts carriage cost on chosen edges), `PATENT` (one capitalist record holds a method exclusively for N years), `EDUCATION` (reduces the skill penalty of division of labour).

### `core/trees.py`
Three enums of nodes, plus `NodeState` per nation (and per location for Tree I nodes). `gate_met(node, nation, location) -> bool` is *declared* here (pure predicate over world state) and evaluated by the engine in task 05.

**Tree I — WHAT** (per location; what a location's market can carry):

| Node | Puts in the market | Gate (in the location) |
|---|---|---|
| `GAME_AND_GATHERING` | Provisions, Materials | game resource present |
| `DOMESTICATED_HERDS` | Provisions, Materials; herds as mobile stock | grazing resource + contact (band mechanic, task 02) |
| `GRAIN` | Provisions at scale | arable resource + a settled record |
| `WARES` | Wares | Materials available + craftsmen present in a town |
| `LUXURIES` | Luxuries | any of: `rare` resource + craftsmen; a route to a market that already has Luxuries; a manufactory |
| `SHIPS` | route capacity | coast + Materials + Wares |
| `ARMS` | Arms | ore + coal + a manufactory or ironworks |

**Tree II — HOW** (per nation; three independent branches, each a straight chain — a node's gate is "the previous node lit" plus the extra condition named):

- *Production*: `SOLITARY_LABOUR` (hunting; always lit) → `HERDING_WITH_DEPENDENTS` (herds ownable, i.e. `TAMED_ANIMAL_TO_TAMER` enacted) → `BOUND_LABOUR` (`LAND_OWNABLE` + `SERFDOM` enacted) → `THREE_FIELD_ROTATION` (+50% land yield once lit) → `HANDICRAFT` (a town exists) → `PUTTING_OUT` (merchant stock committed + Materials available; dispersed wage jobs) → `MONEY_RENT` (`COMMUTATION` enacted) → `MANUFACTORY` (`STOCK_SEPARABLE` enacted + free labourers available) → `DIVISION_OF_LABOUR` (`market_size` past a threshold; skill penalty starts falling) → `MACHINE_PRODUCTION` (Wares at scale + ore + accumulated capital) → `MACHINERY_STEAM` (machine production + coal + the Watt event).
- *Defence*: `EVERY_MAN_A_WARRIOR` (always lit) → `NATION_IN_ARMS` (herds exist) → `FEUDAL_HOST` (fields + retainers exist) → `MILITIA` (`MILITIA_ACT` enacted) → `STANDING_ARMY` (`STANDING_ARMY_ACT` enacted + a defence draw + free labour available) → `FIREARMS` (Arms class at scale) → `NAVY` (a Port + Ships).
- *Credit*: `BILLS_OF_EXCHANGE` (a Port + merchant stock) → `BANK` (v2, stub only).

A WHAT node can be lit but unusable (no producer built yet); a HOW node lit but idle (no one has taken the method up); nodes stay lit once lit, including through a regression (task 05's `meta/regression.py` keeps them lit but the producers using them may idle).

### `core/actions.py`
```python
class ActionKind(Enum): ENACT, REPEAL, VETO, SET_FOCUS, CLEAR_FOCUS, SET_TAX_RATE, SET_BUDGET, DECLARE_RAID, DECLARE_WAR,
                        BESIEGE, OFFER_PEACE, ACCEPT_PEACE, PROPOSE_TREATY, ACCEPT_TREATY, REPRESS, PRICE_CONTROL,
                        BAND_MOVE, BAND_FOLLOW_HERDS, BAND_SETTLE, BAND_RAID, BAND_BARTER
@dataclass class Action: kind; nation: str; payload: dict; cost: float | None   # cost filled by validate()
def validate(world, action) -> ValidationResult      # legality + cost; the actual cost formulas are filled in by tasks 03/04, which own the currency they spend
def enqueue(world, action) -> None
```
Every action costs **State authority** `A_S` — the sovereign's only currency; there is no action-count limit, only the `A_S` stock. This task defines the hook (`validate` returns a `ValidationResult` with a `cost`, and rejects the action if the nation can't afford it); tasks 03–04 fill in each `ActionKind`'s actual cost formula: laws cost 0 if the enacting Interest already clears its self-enactment bar, otherwise the authority gap to close it; a veto costs the gap at a premium plus a cooldown; a Focus costs its upkeep; tax and budget changes cost a small fixed amount; war, siege, peace, and treaty actions cost a fixed spend each; repression costs a spend and puts the army "inside" for the year; band decisions spend consensus (the band-stage equivalent of `A_S`). A sovereign with no authority can still act for free wherever an Interest already supports the action.

### `sim/scenario.py`, `scenarios/three_bands.yaml`
Scenario = map (locations, resources, graph) + nations (each a band of hunters on a starting location) + params override + seed. `three_bands.yaml`: ~24 locations, 3 bands, one river valley, one coast, one `rare` location, ore and coal somewhere reachable. `load_scenario(path) -> World`.

### `sim/ledger.py`
Append-only per-nation-per-year rows: every scalar in `NationScalars`, the three curves, world shares, class sizes and wealth totals, law states, events. `Ledger.to_parquet/csv/json`. Event records are `{year, nation, kind, numbers: dict}` — no prose.

### `sim/rng.py`
`make_rng(seed)`; helper `draw(rng, p)`.

## Invariants (enforce in `World.validate()`, run in tests)
- Every record's location exists and belongs to its nation (or the record is mobile and its nation holds no location).
- `sum(owners_stock.values()) == 1` and `sum(owners_land.values()) == 1` where non-zero.
- Derived-size classes have no direct writer.
- `hostility[(i,j)] == hostility[(j,i)]`.
- All wealth fields ≥ 0; `debt ≥ 0`.

Whether every `Params` field is actually read somewhere, and whether any formula constant named in a later document never made it into `Params`, is a completeness check for the end-of-project review pass (Doc 00), not a task-01 unit test — `Params` only has task 01's own fields at this point.

## Acceptance
- `pytest tests/test_core.py`: scenario loads; `World.validate()` passes; JSON round-trip is lossless; `Params.default()` equals `params/default.yaml`; unknown YAML key raises; `validate(action)` rejects an ENACT from a nation with `seat == BAND`.
- `python -m stock.sim run scenarios/three_bands.yaml --years 0` prints the world summary (nations, locations, records) and exits 0.
