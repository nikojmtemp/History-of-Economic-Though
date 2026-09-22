"""World state (design doc §5–§7). Plain dataclasses; the whole world deep-copies,
which is how forecasts (§19.5) run a turn without touching the real game."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from stock.game import rules


@dataclass
class Node:
    id: str
    name: str
    x: float
    y: float
    terrain: str
    river: bool = False
    coast: bool = False
    features: list[str] = field(default_factory=list)
    game: float = 1.0  # game level 0..1 (depletion)
    hands: float = 0.0  # settled population
    owner: str | None = None
    works: list[str] = field(default_factory=list)
    herds: float = 0.0  # herds kept on pastures here
    unrest: float = 0.0
    siege: dict[str, Any] | None = None  # {"by": nation, "turns": left}
    revolt_turns: int = 0
    conquered: int = 0  # turns of conquest unrest left

    @property
    def t(self) -> rules.Terrain:
        return rules.TERRAIN[self.terrain]

    def slots(self) -> int:
        return min(rules.WORK_SLOTS_MAX, rules.WORK_SLOTS_BASE + int(self.hands / rules.WORK_SLOTS_PER_HANDS))

    def site_ok(self, site: str | None) -> bool:
        t = self.t
        if site is None:
            return True
        if site == "arable":
            return t.arable > 0.0
        if site == "grazing":
            return t.grazing > 0.0
        if site == "coast":
            return self.coast
        if site == "rare":
            return "rare" in self.features
        if site == "mine":
            return "ore" in self.features or "coal" in self.features
        return False


@dataclass
class Edge:
    a: str
    b: str
    kind: str  # path | rough | river | road | sea

    def other(self, node_id: str) -> str:
        return self.b if node_id == self.a else self.a

    def cost(self) -> int:
        return 2 if self.kind == "rough" else 1


@dataclass
class Unit:
    id: str
    nation: str
    kind: str  # band | horde
    node: str
    hands: float
    herds: float = 0.0
    moves_left: int = 1
    followed: bool = False  # followed wild herds this turn
    cohesion: float = 100.0
    age: int = 0  # turns in the field: the host's season, a regiment's drill
    rebel_of: str | None = None  # rebels: the nation they rose against
    hold: int = 0  # rebels: turns they have held their node
    road_used: bool = False  # regiments: the free road step taken this turn
    home: str | None = None  # traders: the market town or port they set out from

    @property
    def military(self) -> bool:
        return rules.UNITS[self.kind].military

    def max_moves(self, known: set[str]) -> int:
        if self.kind in ("horde", "riders"):
            return 3 if "horsemanship" in known else rules.HORDE_MOVES
        return rules.UNITS[self.kind].moves


@dataclass
class Route:
    id: str
    kind: str  # barter | caravan | sea
    a: str  # the nation that opened it (its merchants take the profit)
    b: str
    capacity: float
    a_node: str | None = None  # endpoints (barter routes have none)
    b_node: str | None = None
    hops: int = 1
    active: bool = True
    flows: dict[str, float] = field(default_factory=dict)  # good -> quantity, + from a to b, - from b to a
    profit: float = 0.0


@dataclass
class OrderState:
    size: float = 0.0
    income: float = 0.0
    share: float = 0.0
    contentment: float = 50.0
    expectation: float = 0.9
    satisfaction: float = 0.9
    clout: float = 0.0
    food_sat: float = 1.0
    comfort_sat: float = 1.0
    standing_sat: float = 1.0


@dataclass
class Decision:
    id: str
    kind: str
    title: str
    text: str
    choices: list[dict[str, Any]]
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Nation:
    id: str
    name: str
    colour: str
    player: bool = False
    alive: bool = True
    seat: str = "council"  # council | chiefdom | civil | interregnum
    sway: float = rules.START_SWAY
    stock: float = 0.0
    hoard: float = 0.0
    treasury: float = 0.0
    store: dict[str, float] = field(
        default_factory=lambda: {"food": rules.START_FOOD, "wares": 0.0, "luxuries": 0.0}
    )
    prices: dict[str, float] = field(default_factory=lambda: dict(rules.BASE_PRICE))
    demand: dict[str, float] = field(default_factory=dict)  # last turn's quantities
    known: list[str] = field(default_factory=lambda: list(rules.START_DISCOVERIES))
    researching: str | None = None
    research_progress: float = 0.0
    institutions: dict[str, str] = field(default_factory=lambda: dict(rules.START_INSTITUTIONS))
    pending_institutions: dict[str, str] = field(default_factory=dict)
    pillar_cooldown: dict[str, int] = field(default_factory=dict)
    orders: dict[str, OrderState] = field(default_factory=lambda: {o: OrderState() for o in rules.ORDERS})
    retainers: float = 0.0
    luxury_turns: int = 0
    mode: str = "hunting"
    mode_challenger: str | None = None
    mode_streak: int = 0
    tax_rate: str = "moderate"
    budget: dict[str, int] = field(default_factory=lambda: {line: 0 for line in rules.BUDGET_LINES})
    build_queue: list[dict[str, Any]] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    relations: dict[str, float] = field(default_factory=dict)
    explored: list[str] = field(default_factory=list)
    counters: dict[str, float] = field(default_factory=dict)  # observation counters
    moments: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    feast_ready: int = 0
    war_weariness: float = 0.0
    casus_belli: dict[str, int] = field(default_factory=dict)  # nation -> turns left
    tributes: list[dict[str, Any]] = field(default_factory=list)  # {"to", "turns", "share"} we pay
    exile_turns: int = 0
    truce: dict[str, int] = field(default_factory=dict)  # nation -> last turn of the truce
    embargo: dict[str, int] = field(default_factory=dict)  # nation -> last turn of our embargo on them
    trade: dict[str, Any] = field(default_factory=dict)  # this turn's imports, exports, profit, tolls
    # figures of the last resolved turn, for display, forecasts and victory
    last: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, float]] = field(default_factory=list)

    def knows(self, key: str | None) -> bool:
        return key is None or key in self.known

    def option(self, pillar: str) -> str:
        return self.institutions[pillar]


@dataclass
class Event:
    turn: int
    nation: str | None
    kind: str
    text: str
    node: str | None = None
    quote: str = ""


@dataclass
class World:
    seed: int
    spec: str
    nodes: dict[str, Node]
    edges: list[Edge]
    nations: dict[str, Nation]
    units: dict[str, Unit] = field(default_factory=dict)
    routes: dict[str, Route] = field(default_factory=dict)
    turn: int = 1
    log: list[Event] = field(default_factory=list)
    next_id: int = 1
    rng: random.Random = field(default_factory=random.Random)
    hegemony: dict[str, Any] = field(
        default_factory=lambda: {"leader": None, "countdown": None, "failing": 0}
    )
    winner: dict[str, Any] | None = None
    wars: list[dict[str, Any]] = field(default_factory=list)  # {"a", "b", "since", "score": {a, b}}
    treaties: list[dict[str, Any]] = field(default_factory=list)  # {"kind", "a", "b", "since"}
    _adj: dict[str, list[Edge]] | None = field(default=None, repr=False)

    # --- graph helpers --------------------------------------------------------------

    def adjacency(self) -> dict[str, list[Edge]]:
        if self._adj is None:
            adj: dict[str, list[Edge]] = {n: [] for n in self.nodes}
            for e in self.edges:
                adj[e.a].append(e)
                adj[e.b].append(e)
            self._adj = adj
        return self._adj

    def edges_of(self, node_id: str, *, sea: bool = False) -> list[Edge]:
        return [e for e in self.adjacency()[node_id] if sea or e.kind != "sea"]

    def edge_between(self, a: str, b: str) -> Edge | None:
        for e in self.adjacency()[a]:
            if e.other(a) == b:
                return e
        return None

    def neighbours(self, node_id: str, *, sea: bool = False) -> list[str]:
        return [e.other(node_id) for e in self.edges_of(node_id, sea=sea)]

    def new_id(self, prefix: str) -> str:
        self.next_id += 1
        return f"{prefix}{self.next_id}"

    def units_of(self, nation_id: str) -> list[Unit]:
        """The nation's own units; rebels answer to nobody."""

        return [u for u in self.units.values() if u.nation == nation_id and u.rebel_of is None]

    def units_at(self, node_id: str) -> list[Unit]:
        return [u for u in self.units.values() if u.node == node_id]

    def nodes_of(self, nation_id: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.owner == nation_id]

    def hands_of(self, nation_id: str) -> float:
        return sum(n.hands for n in self.nodes_of(nation_id)) + sum(u.hands for u in self.units_of(nation_id))

    def herds_of(self, nation_id: str) -> float:
        return sum(n.herds for n in self.nodes_of(nation_id)) + sum(u.herds for u in self.units_of(nation_id))

    def emit(
        self, nation: str | None, kind: str, text: str, node: str | None = None, quote: str = ""
    ) -> None:
        self.log.append(Event(self.turn, nation, kind, text, node, quote))

    def war_between(self, a: str, b: str) -> dict[str, Any] | None:
        for w in self.wars:
            if {w["a"], w["b"]} == {a, b}:
                return w
        return None

    def hostile(self, u: Unit, nation_id: str) -> bool:
        """Is unit `u` an enemy of `nation_id`? Rebels are enemies of the nation they rose against."""

        if u.rebel_of is not None:
            return u.rebel_of == nation_id
        return u.nation != nation_id and self.war_between(u.nation, nation_id) is not None

    def treaty(self, kind: str, a: str, b: str) -> dict[str, Any] | None:
        for t in self.treaties:
            if t["kind"] == kind and {t["a"], t["b"]} == {a, b}:
                return t
        return None

    def hostile_owner(self, nation_id: str, node: Node) -> bool:
        """Is `node` held by a people at war with `nation_id`?"""

        return (
            node.owner is not None
            and node.owner != nation_id
            and self.war_between(node.owner, nation_id) is not None
        )

    def player(self) -> Nation | None:
        for n in self.nations.values():
            if n.player:
                return n
        return None
