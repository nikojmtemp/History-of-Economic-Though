"""Producers: occupations and buildings (DD §4.1; MM §4-6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from stock.core.goods import Good
from stock.core.records import ClassId


class ProducerKind(Enum):
    HUNTING = auto()  # occupation
    HERDING = auto()  # occupation
    FIELD = auto()  # building
    WORKSHOP = auto()  # building
    PUTTING_OUT = auto()  # dispersed
    MANUFACTORY = auto()  # building
    MINE = auto()  # building
    PORT = auto()  # building
    STATE = auto()  # building


#: Occupations are re-bound to their record's location each year and hold no fixed
#: assets (DD §4.1); buildings are fixed to the location they were built in.
OCCUPATIONS: frozenset[ProducerKind] = frozenset({ProducerKind.HUNTING, ProducerKind.HERDING})


class MethodId(Enum):
    """A Tree II production method (DD §6.2). One producer runs exactly one method at
    a time; `NONE` for producers with no method distinction yet (Hunting, Herding,
    Port, State)."""

    NONE = auto()
    SOLITARY_LABOUR = auto()
    HERDING_WITH_DEPENDENTS = auto()
    BOUND_LABOUR = auto()
    THREE_FIELD_ROTATION = auto()
    HANDICRAFT = auto()
    PUTTING_OUT = auto()
    MONEY_RENT = auto()
    MANUFACTORY = auto()
    DIVISION_OF_LABOUR = auto()
    MACHINE_PRODUCTION = auto()
    MACHINERY_STEAM = auto()


#: Which class fills a producer's jobs (DD §4.1); the owner/rent-taking class is
#: separate (see `LAND_TAKING` / stock ownership, which is a per-producer share map).
JOB_CLASS: dict[ProducerKind, ClassId] = {
    ProducerKind.HUNTING: ClassId.HUNTERS,
    ProducerKind.HERDING: ClassId.HERDSMEN,
    ProducerKind.FIELD: ClassId.TENANTS,  # or SERFS under Serfdom (engine decides)
    ProducerKind.WORKSHOP: ClassId.CRAFTSMEN,
    ProducerKind.PUTTING_OUT: ClassId.LABOURERS,
    ProducerKind.MANUFACTORY: ClassId.LABOURERS,
    ProducerKind.MINE: ClassId.LABOURERS,
    ProducerKind.PORT: ClassId.MERCHANTS,
    ProducerKind.STATE: ClassId.COLLECTORS,
}

#: Whether a producer kind has land shares taking rent (DD §4.1: Field takes rent;
#: Port site rent is possible via landlords too, but the first build treats Port as
#: landless per DD §4.1's blank rent column).
HAS_LAND_RENT: frozenset[ProducerKind] = frozenset({ProducerKind.FIELD})

#: Producers whose stock is owned by a landlord/State as *site* rent rather than by the
#: operating class (DD §4.1 "Land (rent)" column for Manufactory/Mine = "landlords").
SITE_RENT_TO_LANDLORD: frozenset[ProducerKind] = frozenset(
    {ProducerKind.MANUFACTORY, ProducerKind.MINE}
)


@dataclass
class Producer:
    """A producer at a location (DD §4.1), aggregate per (location, kind, method) — see
    DEVIATIONS.md for the producer-identity simplification."""

    kind: ProducerKind
    location: str
    method: MethodId = MethodId.NONE
    stock_in_place: float = 0.0
    land_shares: float = 0.0
    site_rent: float = 0.0
    owners_stock: dict[ClassId, float] = field(default_factory=dict)  # shares, sum to 1
    owners_land: dict[ClassId, float] = field(default_factory=dict)  # shares, sum to 1
    jobs: float = 0.0
    filled: dict[ClassId, float] = field(default_factory=dict)
    inputs: dict[Good, float] = field(default_factory=dict)  # per unit Q
    outputs: dict[Good, float] = field(default_factory=dict)  # per unit Q
    last_V: float = 0.0
    last_Q: float = 0.0
    #: memory used across steps within a year, or into next year's lagged reads (not
    #: in Doc 01's abbreviated sketch — see DEVIATIONS.md).
    last_split_profit: float = 0.0  # this year's split-rule profit (MM §5)
    last_herd_growth: float = 0.0  # Herding only: this year's ΔHerd (MM §4-5)
    last_wage: float = 1.0  # the wage this producer paid last time wages ran (MM §8)
    last_wage_bill: float = 0.0  # filled_jobs * wage, for patience_M (MM §8)

    def id(self) -> str:
        return f"{self.location}:{self.kind.name}:{self.method.name}"
