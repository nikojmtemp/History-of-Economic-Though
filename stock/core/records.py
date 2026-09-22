"""Class records: the aggregation unit (DD §2.1-2.2; MM Notation, §1-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from stock.core.goods import Good, Tier


class ClassId(Enum):
    """A social/economic class. One record exists per class x location (DD §2.1)."""

    HUNTERS = auto()
    HERD_OWNERS = auto()
    HERDSMEN = auto()
    LANDLORDS = auto()
    CLERGY = auto()  # v2 (DD §16.1); modelled here, unused by first-build scenarios
    SERFS = auto()
    RETAINERS = auto()
    CRAFTSMEN = auto()
    TENANTS = auto()
    MERCHANTS = auto()
    CAPITALISTS = auto()
    LABOURERS = auto()
    SERVANTS = auto()  # v2 (DD §16.1)
    SOLDIERS = auto()
    COLLECTORS = auto()  # v2 visible (DD §16.1)
    STATE = auto()


class InterestId(Enum):
    """A political Interest (DD §2.5): apportioned from record authority by wealth
    composition."""

    LANDED = auto()
    INDUSTRIAL = auto()
    MERCHANT = auto()
    MONEYED = auto()
    LABOUR = auto()


#: Asset field names on Wealth, used to key apportionment to Interests (DD §2.5).
AssetField = str


@dataclass
class Wealth:
    """A record's wealth vector (DD §2.2), all in baskets."""

    herd: float = 0.0
    land_shares: float = 0.0
    fixed_assets: float = 0.0
    stock_in_place: float = 0.0
    hoard: float = 0.0
    bonds: float = 0.0
    tools: float = 0.0
    loans_out: float = 0.0

    def total(self, land_share_value: float = 1.0) -> float:
        """Sum all wealth components. `land_share_value` is the basket value of one land share
        (placeholder, Doc 08 tuning; default 1.0 for compatibility with mobility calculations)."""
        return (
            self.herd
            + self.land_shares * land_share_value
            + self.fixed_assets
            + self.stock_in_place
            + self.hoard
            + self.bonds
            + self.tools
            + self.loans_out
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "herd": self.herd,
            "land_shares": self.land_shares,
            "fixed_assets": self.fixed_assets,
            "stock_in_place": self.stock_in_place,
            "hoard": self.hoard,
            "bonds": self.bonds,
            "tools": self.tools,
            "loans_out": self.loans_out,
        }


#: A vector of values per consumption Tier (DD §5.1a): [subsistence, comfort, standing].
@dataclass
class TierVec:
    subsistence: float = 0.0
    comfort: float = 0.0
    standing: float = 0.0

    def __getitem__(self, tier: Tier) -> float:
        return float(getattr(self, _TIER_ATTR[tier]))

    def __setitem__(self, tier: Tier, value: float) -> None:
        setattr(self, _TIER_ATTR[tier], value)

    def as_dict(self) -> dict[str, float]:
        return {
            "subsistence": self.subsistence,
            "comfort": self.comfort,
            "standing": self.standing,
        }


_TIER_ATTR = {
    Tier.SUBSISTENCE: "subsistence",
    Tier.COMFORT: "comfort",
    Tier.STANDING: "standing",
}


@dataclass
class Record:
    """One class record at one location (DD §2.1-2.2). Mutated in place by year steps."""

    cls: ClassId
    location: str
    size: float = 0.0
    wealth: Wealth = field(default_factory=Wealth)
    debt: float = 0.0
    A: TierVec = field(default_factory=TierVec)  # satisfaction by tier
    E: TierVec = field(default_factory=TierVec)  # expected by tier
    walk_away: float = 1.0
    authority: float = 0.0
    mobilised: bool = False
    flags: set[str] = field(default_factory=set)
    #: this year's flow income (wages, profit, rent, transfers) not yet consumed or
    #: saved — reset to 0 at the start of each year, spent at step 5, the residual
    #: saved at step 7 (DD §5; not in Doc 01's abbreviated sketch, see DEVIATIONS.md).
    income: float = 0.0
    #: consecutive years this record has been on strike (DD §4.6, §8.2); 0 = not
    #: striking. Written by politics/unrest.py (Doc 03), read by engine/wages.py.
    strike_years: int = 0
    #: this year's income before consumption/saving touch it (DD §2.4's "income per
    #: head" for net-advantage comparisons in mobility, read at step 8 after step 5
    #: has already zeroed `income`). Set by engine/consumption.py at step 5, just
    #: before it repurposes `income` to carry the saved residual to step 7.
    last_gross_income: float = 0.0
    #: last year's spending by good (DD §4.7, §5.1); written by engine/consumption.py
    #: at step 5, read (lagged, naturally, since step 4 runs before step 5 each year)
    #: by engine/market.py's market_size at step 4. Not in Doc 01's sketch.
    last_spend_by_good: dict[Good, float] = field(default_factory=dict)
    #: this year's disorder-driven emigration intensity (DD §8.2 "emigration flow
    #: request handed to mobility"; MM §20 "emigration ∝ U_r"), a per-record share in
    #: [0,1]. Written by politics/unrest.py (Doc 03); read by Doc 04's cross-border
    #: mobility edge, which doesn't exist yet — see DEVIATIONS.md.
    emigration_pressure: float = 0.0
    #: this record's savings to be placed into producers by class, reset to 0 by
    #: placement after use (DD §5.3 per-record placement). Written by engine/capital's
    #: hoard_update at step 7, placed by placement at step 9.
    to_reinvest: float = 0.0
    #: this year's wage-bargain pass-through share `pi = wa_L/(wa_L+patience_M)` (MM
    #: §8), written by engine/wages.py's step_wages (step 2) at the clearing_wage call
    #: site for bargaining classes; 0.0 for dependent/non-bargaining classes. Read one
    #: year lagged by finance/taxation.py's incidence rule (Doc 05) — at step 3 of the
    #: *next* year this is still last year's value from the caller's point of view.
    last_pi: float = 0.0

    def key(self) -> tuple[str, ClassId]:
        return (self.location, self.cls)


@dataclass(frozen=True)
class ClassSpec:
    """Static data about a class (DD §2.2, §2.5, §5.1, §5.3): not overridden by Params —
    these are structural facts about what a class *is*, not tunable rates."""

    productive: bool
    base_walk_away: float
    base_propensity: float  # p_base (DD §5.3); a Wealth field name for owner classes
    #: which Wealth field this class's savings target (DD §5.3); None = no reinvestment
    #: target of its own (e.g. hunters have p=0).
    interest_assets: dict[InterestId, str]
    """which Wealth field(s) count toward which Interest's apportionment (DD §2.5);
    LABOUR is special-cased (labour-power, ell-weighted, not a Wealth field)."""


#: Static per-class facts (DD §2.2 table, §2.5 table, §5.3 table). `interest_assets`
#: values are Wealth field names except LABOUR, which is computed from `ell * size *
#: w_nat` (MM §3) rather than a Wealth field, and is added by politics/authority.py.
CLASS_TABLE: dict[ClassId, ClassSpec] = {
    ClassId.HUNTERS: ClassSpec(
        productive=True,
        base_walk_away=1.0,
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.HERD_OWNERS: ClassSpec(
        productive=True,
        base_walk_away=1.0,
        base_propensity=0.6,
        interest_assets={InterestId.LANDED: "herd"},
    ),
    ClassId.HERDSMEN: ClassSpec(
        productive=True,
        base_walk_away=0.2,
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.LANDLORDS: ClassSpec(
        productive=False,
        base_walk_away=1.0,
        base_propensity=0.15,
        interest_assets={InterestId.LANDED: "land_shares"},
    ),
    ClassId.CLERGY: ClassSpec(
        productive=False,
        base_walk_away=1.0,
        base_propensity=0.1,
        interest_assets={InterestId.LANDED: "land_shares"},
    ),
    ClassId.SERFS: ClassSpec(
        productive=True,
        base_walk_away=0.0,  # x enforcement(Serfdom), applied by politics
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.RETAINERS: ClassSpec(
        productive=False,
        base_walk_away=0.1,
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.CRAFTSMEN: ClassSpec(
        productive=True,
        base_walk_away=0.7,
        base_propensity=0.4,
        interest_assets={InterestId.INDUSTRIAL: "tools"},
    ),
    ClassId.TENANTS: ClassSpec(
        productive=True,
        base_walk_away=0.5,
        base_propensity=0.4,
        interest_assets={InterestId.LANDED: "stock_in_place"},
    ),
    ClassId.MERCHANTS: ClassSpec(
        productive=True,
        base_walk_away=1.0,
        base_propensity=0.7,
        interest_assets={InterestId.MERCHANT: "stock_in_place"},
    ),
    ClassId.CAPITALISTS: ClassSpec(
        productive=False,  # owner; production credited to the labourers they employ
        base_walk_away=1.0,
        base_propensity=0.9,
        interest_assets={InterestId.INDUSTRIAL: "stock_in_place"},
    ),
    ClassId.LABOURERS: ClassSpec(
        productive=True,
        base_walk_away=0.0,  # computed (DD §4.6 wa_L)
        base_propensity=0.0,  # > 0 when w > w_natural (DD §5.3), applied by engine
        interest_assets={},
    ),
    ClassId.SERVANTS: ClassSpec(
        productive=False,
        base_walk_away=0.4,
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.SOLDIERS: ClassSpec(
        productive=False,
        base_walk_away=0.0,  # enlisted; desertion is a flow, not walk-away
        base_propensity=0.0,
        interest_assets={},
    ),
    ClassId.COLLECTORS: ClassSpec(
        productive=False,
        base_walk_away=0.6,
        base_propensity=0.1,
        interest_assets={},
    ),
    ClassId.STATE: ClassSpec(
        productive=False,
        base_walk_away=0.0,
        base_propensity=1.0,  # revenue unspent -> treasure (DD §5.3)
        interest_assets={},
    ),
}

#: Classes whose `size` is derived from another mechanism and must never be written
#: directly by a step (DD §2.2 note; enforced by `set_size` below).
DERIVED_SIZE_CLASSES: frozenset[ClassId] = frozenset({ClassId.RETAINERS, ClassId.SERVANTS})


class DerivedSizeError(RuntimeError):
    """Raised when a step tries to write a derived-size class's `size` directly."""


def quantise_move(src_size: float, moved: float, minimum: float) -> float:
    """One person is the smallest unit that changes class or location. Returns the
    size a move of `moved` people out of a record of `src_size` may actually take:
    nothing if it is below `minimum` (no dust-sized destination record), or the whole
    record if what it would leave behind is below `minimum` (no dust-sized source
    record). A source already below `minimum` moves entire. `minimum <= 0` disables
    the rule (the raw `moved`, clamped to the source)."""

    if moved <= 0 or src_size <= 0:
        return 0.0
    moved = min(moved, src_size)
    if minimum <= 0:
        return moved
    if src_size <= minimum:
        return src_size
    if moved < minimum:
        return 0.0
    if src_size - moved < minimum:
        return src_size
    return moved


def set_size(record: Record, value: float, *, allow_derived: bool = False) -> None:
    """The only sanctioned way to write `record.size`. Raises for RETAINERS/SERVANTS
    unless `allow_derived=True` — reserved for `engine.consumption.attendance_to_
    dependents` (Doc 02), the sole writer of those classes' size (DD §5.1c)."""

    if record.cls in DERIVED_SIZE_CLASSES and not allow_derived:
        raise DerivedSizeError(
            f"{record.cls.name}.size is derived from the Attendance purchase "
            "(DD §5.1c) and may only be set via attendance_to_dependents()"
        )
    record.size = value


#: Classes that hold labour power counted toward the LABOUR Interest (DD §2.5); their
#: labour-power wealth (ell * size * w_nat, MM §3) is computed by politics/authority.py.
LABOUR_INTEREST_CLASSES: frozenset[ClassId] = frozenset(
    {
        ClassId.LABOURERS,
        ClassId.SERFS,
        ClassId.HERDSMEN,
        ClassId.SOLDIERS,
        ClassId.SERVANTS,
    }
)
