"""Rival sovereigns (design doc §16.2): the same verbs as the player, chosen by a
utility score weighted by a personality that follows the nation's mode and its
strongest order."""

from __future__ import annotations

from collections import deque

from stock.game import actions, economy, research, rules
from stock.game.state import Nation, Unit, World


def personality(n: Nation) -> str:
    if n.mode == "hunting":
        return "wanderer"
    if n.mode == "pasturage":
        return "khan"
    strongest = max(rules.ORDERS, key=lambda o: n.orders[o].clout)
    return "merchant" if n.mode == "commerce" or strongest == "stock" else "lord"


LANE_WEIGHT = {
    "wanderer": {"subsistence": 1.3, "exchange": 1.0, "force": 0.8, "order": 1.0},
    "khan": {"subsistence": 1.1, "exchange": 0.8, "force": 1.3, "order": 1.0},
    "lord": {"subsistence": 1.3, "exchange": 0.9, "force": 1.0, "order": 1.2},
    "merchant": {"subsistence": 1.2, "exchange": 1.4, "force": 0.8, "order": 1.0},
}
PRIORITY = {
    "taming": 2.0,
    "tillage": 3.0,
    "fishing": 1.2,
    "barter": 1.3,
    "weaving": 1.6,
    "fairs": 2.0,
    "division": 3.0,
    "magistracy": 1.6,
    "land_tenure": 1.4,
    "commutation": 1.8,
    "coinage": 1.5,
    "rotation": 1.4,
    "liberty": 1.3,
}


def _do(world: World, n: Nation, action: actions.Action) -> bool:
    return actions.act(world, n.id, action) is None


def _path_step(world: World, n: Nation, start: str, goal: str) -> str | None:
    prev: dict[str, str | None] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for nxt in world.neighbours(cur):
            if nxt not in prev and actions.can_enter(world, n, nxt):
                prev[nxt] = cur
                q.append(nxt)
    if goal not in prev:
        return None
    step = goal
    while prev[step] is not None and prev[step] != start:
        step = prev[step]  # type: ignore[assignment]
    return step


def _ground_value(world: World, n: Nation, u: Unit, node_id: str) -> float:
    nd = world.nodes[node_id]
    t = nd.t
    crowd = sum(x.hands for x in world.units_at(node_id) if x.id != u.id) + nd.hands
    v = rules.HUNT_YIELD * t.game * nd.game + (t.fish * rules.HUNT_YIELD * (2 if n.knows("fishing") else 1))
    if u.kind == "horde":
        cap = rules.HERD_CAP_PER_GRAZING * t.grazing
        load = sum(x.herds for x in world.units_at(node_id) if x.id != u.id) + nd.herds
        v += 2.0 * t.grazing * max(0.0, 1.0 - (load + u.herds) / cap) if cap > 0 else 0.0
    if "wild_herds" in nd.features and not n.knows("taming"):
        v += 0.3
    return v - 0.08 * crowd


def _settle_target(world: World, n: Nation, u: Unit, radius: int = 3) -> str | None:
    seen = {u.node: 0}
    q = deque([u.node])
    best, best_v = None, 0.0
    while q:
        cur = q.popleft()
        nd = world.nodes[cur]
        if nd.owner is None and nd.t.arable > 0:
            v = (
                nd.t.arable
                + 0.3 * nd.t.grazing
                + (0.3 if nd.river else 0)
                + (0.2 if nd.coast else 0)
                + (0.2 if "rare" in nd.features else 0)
                - 0.15 * seen[cur]
            )
            if any(x.nation != n.id for x in world.units_at(cur)):
                v -= 1.0
            if v > best_v:
                best, best_v = cur, v
        if seen[cur] < radius:
            for nxt in world.neighbours(cur):
                if nxt not in seen and actions.can_enter(world, n, nxt):
                    seen[nxt] = seen[cur] + 1
                    q.append(nxt)
    return best


def _units(world: World, n: Nation, style: str) -> None:
    for u in list(world.units_of(n.id)):
        if u.id not in world.units:
            continue
        nd = world.nodes[u.node]
        # tame when standing on wild herds (khans and wanderers readily; others if pressed)
        if u.kind == "band" and n.knows("taming") and "wild_herds" in nd.features:
            if style in ("wanderer", "khan") or world.rng.random() < 0.3:
                _do(world, n, {"kind": "tame", "unit": u.id})
                continue
        # settle good arable ground
        if n.knows("tillage") and nd.owner is None and nd.t.arable > 0 and u.hands >= 3:
            good = nd.t.arable >= 0.7 or _settle_target(world, n, u, radius=2) in (None, u.node)
            eager = 0.9 if u.kind == "band" else (0.35 if style != "khan" else 0.15)
            if u.kind == "horde" and u.herds >= 0.8 * rules.HERD_CAP_PER_GRAZING * nd.t.grazing:
                eager += 0.4
            eager = eager if good else 0.1
            if world.rng.random() < eager:
                if _do(world, n, {"kind": "settle", "unit": u.id}):
                    continue
        # join an own settlement that has jobs to spare
        if nd.owner == n.id and u.kind == "band" and world.rng.random() < 0.5:
            _do(world, n, {"kind": "settle", "unit": u.id})
            continue
        # follow the herds while taming is being learned
        if not n.knows("taming") and "wild_herds" in nd.features and u.kind == "band":
            _do(world, n, {"kind": "follow", "unit": u.id})
            continue
        # split a large band to spread out
        if u.hands >= 7.5 and n.sway >= actions.split_cost(n) + 4:
            _do(world, n, {"kind": "split", "unit": u.id})
        # move: toward settling ground once tillage is known, else to better hunting
        target = _settle_target(world, n, u) if n.knows("tillage") else None
        step = _path_step(world, n, u.node, target) if target and target != u.node else None
        if step is None:
            here = _ground_value(world, n, u, u.node)
            options = [
                (x, _ground_value(world, n, u, x))
                for x in world.neighbours(u.node)
                if actions.can_enter(world, n, x)
            ]
            if not n.knows("taming"):
                herds = [x for x, _ in options if "wild_herds" in world.nodes[x].features]
                if herds and "wild_herds" not in nd.features and world.rng.random() < 0.6:
                    step = herds[0]
            if step is None and options:
                best, v = max(options, key=lambda t: t[1])
                if v > here * 1.15 + 0.05:
                    step = best
        if step is not None:
            _do(world, n, {"kind": "move", "unit": u.id, "to": step})


def _research(world: World, n: Nation, style: str) -> None:
    if n.researching is not None:
        return
    m = research.metrics(world, n)
    options = [k for k in rules.DISCOVERIES if research.available(n, k)]
    if not options:
        return

    def score(k: str) -> float:
        d = rules.DISCOVERIES[k]
        return LANE_WEIGHT[style][d.lane] * PRIORITY.get(k, 1.0) / research.cost(world, n, k, m)

    _do(world, n, {"kind": "research", "key": max(options, key=score)})


def _builds(world: World, n: Nation) -> None:
    if len(n.build_queue) >= 2:
        return
    r = float(n.last.get("r", rules.R0))
    best: tuple[float, str, str] | None = None
    for nd in world.nodes_of(n.id):
        for work in rules.WORKS:
            if rules.WORKS[work].public:
                continue
            if actions.build_blocker(world, n, nd.id, work) is not None:
                continue
            ret = actions.expected_return(world, n, nd, work)
            if ret >= r and (best is None or ret > best[0]):
                best = (ret, nd.id, work)
    if best is not None:
        _do(world, n, {"kind": "build", "node": best[1], "work": best[2]})
    # public works when the Treasury is flush
    if n.seat == "civil" and n.treasury > 60:
        for nd in world.nodes_of(n.id):
            for x in world.neighbours(nd.id):
                if _do(world, n, {"kind": "road", "a": nd.id, "b": x}):
                    return


def _expand(world: World, n: Nation) -> None:
    """Send out a band from a crowded settlement toward open arable ground."""

    if n.sway < actions.split_cost(n) + 8 or len(world.units_of(n.id)) >= 2:
        return
    for nd in sorted(world.nodes_of(n.id), key=lambda x: -x.hands):
        jobs = sum(rules.WORKS[w].jobs for w in nd.works)
        if nd.hands > jobs + 3 and nd.hands >= 6:
            if _do(world, n, {"kind": "found_band", "node": nd.id}):
                return


def _institutions(world: World, n: Nation, style: str) -> None:
    from stock.game import politics

    prefs = {
        "property": {
            "herds": 2.0 if world.herds_of(n.id) > 0 else 0.0,
            "entailed": 2.5 if style == "lord" else 1.2,
            "alienable": 2.5 if style == "merchant" else 0.8,
        },
        "labour": {
            "serfdom": 1.5 if style == "lord" else 0.3,
            "guilds": 1.0,
            "free": 2.5 if style == "merchant" or (n.knows("division") and style != "khan") else 0.8,
            "poor_laws": 0.6,
        },
        "revenue": {
            "feudal_dues": 1.5,
            "excise": 1.0 if style == "lord" else 0.8,
            "land_tax": 2.0 if style == "merchant" else 0.5,
            "tax_farming": 0.7,
            "customs": 0.6,
        },
        "commerce": {
            "tolls": 0.8,
            "mercantile": 1.2 if style == "lord" else 1.0,
            "free_trade": 2.0 if style == "merchant" else 0.5,
        },
        "defence": {
            "nation_in_arms": 1.5 if style == "khan" else 0.4,
            "feudal_host": 1.2,
            "militia": 0.9,
            "standing": 1.4 if style == "merchant" else 0.8,
        },
    }
    best: tuple[float, str, str] | None = None
    for pillar, opts in prefs.items():
        current = prefs[pillar].get(
            n.option(pillar), 0.3 if n.option(pillar) in rules.START_INSTITUTIONS.values() else 0.0
        )
        for opt, weight in opts.items():
            if weight <= current + 0.3 or politics.institution_blocker(n, pillar, opt) is not None:
                continue
            c = politics.institution_cost(n, pillar, opt)
            if c > n.sway - 5:
                continue
            value = weight - current - c / 40.0
            if best is None or value > best[0]:
                best = (value, pillar, opt)
    if best is not None and best[0] > 0.2:
        _do(world, n, {"kind": "institution", "pillar": best[1], "option": best[2]})


def _state(world: World, n: Nation, style: str) -> None:
    if n.seat == "chiefdom" and n.knows("magistracy"):
        _do(world, n, {"kind": "found_government"})
    if n.seat == "interregnum":
        _do(world, n, {"kind": "restore"})
    if n.seat == "civil":
        hands = world.hands_of(n.id)
        income = float(n.last.get("tax", {}).get("collected", 0.0))
        justice_cost = rules.JUSTICE_COST_PER_10_HANDS * hands / 10.0
        want = 2 if income > 3 * justice_cost else 1 if income > justice_cost else 0
        if n.budget.get("justice") != want:
            _do(world, n, {"kind": "budget", "line": "justice", "level": want})
        if n.knows("instruction") and economy.has_stupefaction(world, n) and n.treasury > 40:
            _do(world, n, {"kind": "budget", "line": "instruction", "level": 1})
        if n.treasury > 80 and n.budget.get("court", 0) == 0:
            _do(world, n, {"kind": "budget", "line": "court", "level": 1})


def take_turn(world: World, n: Nation) -> None:
    style = personality(n)
    for d in list(n.decisions):
        order = d.data.get("order", "labour")
        choice = "grant" if n.orders[order].clout > 0.4 or n.sway < 15 else "refuse"
        _do(world, n, {"kind": "decide", "id": d.id, "choice": choice})
    _research(world, n, style)
    _units(world, n, style)
    _builds(world, n)
    _expand(world, n)
    for other in n.contacts:
        if actions.check(world, n, {"kind": "barter", "nation": other}) is None:
            _do(world, n, {"kind": "barter", "nation": other})
    _state(world, n, style)
    if world.turn % 3 == 0:
        _institutions(world, n, style)
    if n.orders["labour"].contentment < 40 and n.feast_ready == 0:
        _do(world, n, {"kind": "feast"})
