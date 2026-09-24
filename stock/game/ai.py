"""Rival sovereigns (design doc §16.2): the same verbs as the player, chosen by a
utility score weighted by a personality that follows the nation's mode and its
strongest order."""

from __future__ import annotations

from collections import deque

from stock.game import actions, economy, finance, military, research, rules, trade
from stock.game.state import Nation, Node, Unit, World


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


SCOUTS_FROM_TURN = 10


def _frontier_step(world: World, n: Nation, u: Unit) -> str | None:
    """The first step toward the nearest place with unknown country beside it."""

    known = set(n.explored)
    prev: dict[str, str | None] = {u.node: None}
    q = deque([u.node])
    while q:
        cur = q.popleft()
        if cur != u.node and any(x not in known for x in world.neighbours(cur)):
            step = cur
            while prev[step] != u.node:
                step = prev[step]  # type: ignore[assignment]
            return step
        for nxt in world.neighbours(cur):
            if nxt in prev or actions.hostile_at(world, n, nxt):
                continue
            prev[nxt] = cur
            q.append(nxt)
    return None


def _scouts(world: World, n: Nation) -> None:
    """One party of scouts at a time, while there is country left to see."""

    scouts = [u for u in world.units_of(n.id) if u.kind == "scouts"]
    if not scouts and world.turn >= SCOUTS_FROM_TURN:
        sources: list[Node | Unit] = [
            *world.nodes_of(n.id),
            *(x for x in world.units_of(n.id) if x.kind == "band"),
        ]
        for src in sorted(sources, key=lambda x: -x.hands):
            if military.raise_blocker(world, n, src, "scouts") is None:
                where = {"node": src.id} if isinstance(src, Node) else {"unit": src.id}
                _do(world, n, {"kind": "raise_unit", "unit_kind": "scouts", **where})
                break
        return  # raised scouts set out next turn
    for u in scouts:
        for _ in range(u.max_moves(set(n.known))):
            step = _frontier_step(world, n, u)
            if step is None:
                _do(world, n, {"kind": "disband", "unit": u.id})  # nothing left to find: home
                break
            if not _do(world, n, {"kind": "move", "unit": u.id, "to": step}):
                break


def _units(world: World, n: Nation, style: str) -> None:
    for u in list(world.units_of(n.id)):
        if u.id not in world.units or u.military or u.kind in ("caravan", "merchantman", "scouts"):
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


GROW_RESERVE = 10.0  # Stock the AI keeps back when it grows a settlement


def _grow(world: World, n: Nation) -> None:
    """A settlement with every slot taken grows, when it can and Stock allows."""

    for nd in sorted(world.nodes_of(n.id), key=lambda x: -x.hands):
        if len(nd.works) + actions.queued_on(n, nd.id) < nd.slots() or nd.tier >= len(rules.TIERS) - 1:
            continue
        if n.stock >= rules.TIERS[nd.tier + 1].cost + GROW_RESERVE:
            _do(world, n, {"kind": "grow", "node": nd.id})


def _builds(world: World, n: Nation) -> None:
    _grow(world, n)
    if len(n.build_queue) >= 2:
        return
    r = float(n.last.get("r", rules.R0))
    # the first market town and the first port are planned, not merely priced
    for work in ("market", "port"):
        if any(work in nd.works for nd in world.nodes_of(n.id)) or any(
            q["work"] == work for q in n.build_queue
        ):
            continue
        for nd in sorted(world.nodes_of(n.id), key=lambda x: -x.hands):
            if _do(world, n, {"kind": "build", "node": nd.id, "work": work}):
                return
    pick = actions.best_investment(world, n, r)  # new works and improvements alike
    if pick is not None:
        _, nd, work, improve = pick
        _do(world, n, {"kind": "improve" if improve else "build", "node": nd.id, "work": work})
    else:
        best = _rebuild(world, n, r)
        if best is not None:
            _do(world, n, {"kind": "build", "node": best[1], "work": best[2]})
    # walls on the frontier, then roads when the Treasury is flush
    if n.seat == "civil" and n.knows("masonry") and n.treasury > 30:
        for nd in world.nodes_of(n.id):
            exposed = any(world.nodes[x].owner not in (None, n.id) for x in world.neighbours(nd.id))
            if (
                exposed
                and nd.works.count("fort") < 1
                and _do(world, n, {"kind": "build", "node": nd.id, "work": "fort"})
            ):
                break
    if n.seat == "civil" and n.treasury > 25:
        for nd in world.nodes_of(n.id):
            for x in world.neighbours(nd.id):
                if _do(world, n, {"kind": "road", "a": nd.id, "b": x}):
                    return


def _rebuild(world: World, n: Nation, r: float) -> tuple[float, str, str] | None:
    """Every slot is taken: pull down the poorest work where a manufactory would pay far better."""

    if (
        n.option("labour") not in rules.FREE_LABOUR
        or not n.knows("division")
        or n.stock < actions.work_cost(n, "manufactory")
    ):
        return None
    best: tuple[float, str, str] | None = None
    for nd in world.nodes_of(n.id):
        if actions.build_blocker(world, n, nd.id, "manufactory") is None or not nd.works:
            continue
        ret = actions.expected_return(world, n, nd, "manufactory")
        if ret >= 2 * r and (best is None or ret > best[0]):
            best = (ret, nd.id, "manufactory")
    if best is None:
        return None
    nd = world.nodes[best[1]]
    rows = {w: v for w, _jobs, _per, v in economy._work_jobs(world, n, nd, float(n.last.get("dol", 1.0)))}
    poorest = min(
        (w for w in actions.replaceable(n, nd) if w != "manufactory"),
        key=lambda w: rows.get(w, 0.0),
        default=None,
    )
    if poorest is None or not _do(world, n, {"kind": "demolish", "node": nd.id, "work": poorest}):
        return None
    if actions.build_blocker(world, n, nd.id, "manufactory") is not None:
        return None
    return best


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
            "free": 2.5 if style == "merchant" or n.knows("division") else 0.8,
            "poor_laws": 0.6,
        },
        "commerce": {
            "tolls": 0.8,
            "mercantile": 1.2 if style == "lord" else 1.0,
            "free_trade": 2.0 if style == "merchant" else 0.5,
        },
        "defence": {
            "nation_in_arms": 1.5 if style == "khan" else 0.3,
            "feudal_host": 1.3 if style == "lord" else 0.6,
            "militia": 1.2,
            "standing": 2.2 if n.knows("firearms") or style == "merchant" else 1.0,
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
    if n.seat == "civil" and world.turn % 5 == 0:
        _choose_revenue(world, n)
    if n.seat == "civil":
        hands = world.hands_of(n.id)
        income = float(n.last.get("tax", {}).get("collected", 0.0))
        justice_cost = rules.JUSTICE_COST_PER_10_HANDS * hands / 10.0
        want = 2 if income > 2 * justice_cost else 1 if income > 0.4 * justice_cost else 0
        if n.budget.get("justice") != want:
            _do(world, n, {"kind": "budget", "line": "justice", "level": want})
        if n.knows("instruction") and economy.has_stupefaction(world, n) and n.treasury > 40:
            _do(world, n, {"kind": "budget", "line": "instruction", "level": 1})
        if n.treasury > 80 and n.budget.get("court", 0) == 0:
            _do(world, n, {"kind": "budget", "line": "court", "level": 1})


# --- war (§15, §16.2) --------------------------------------------------------------------------

UNIT_FOR = {
    "warriors": "warband",
    "nation_in_arms": "riders",
    "feudal_host": "host",
    "militia": "militia",
    "standing": "regiment",
}


def _enemies(world: World, n: Nation) -> list[str]:
    return [w["b"] if w["a"] == n.id else w["a"] for w in world.wars if n.id in (w["a"], w["b"])]


def _army_hands(world: World, n: Nation) -> float:
    return sum(u.hands for u in world.units_of(n.id) if u.military)


def _raise(world: World, n: Nation) -> None:
    """Keep an army sized to the danger; disband the surplus in quiet times (hands are workers)."""

    hands = world.hands_of(n.id)
    enemies = _enemies(world, n)
    threatened = bool(enemies) or any(n.relations.get(o, 0.0) < -20 for o in n.contacts)
    share = (0.10 if enemies else 0.06) if threatened else (0.04 if n.mode == "pasturage" else 0.02)
    target = share * hands
    army = [u for u in world.units_of(n.id) if u.military]
    have = sum(u.hands for u in army)
    if not enemies and have > 2.0 * target + 1.0:
        weakest = min(army, key=lambda u: military.unit_strength(world, u))
        _do(world, n, {"kind": "disband", "unit": weakest.id})
        return
    if not n.contacts or world.turn < 10 or (hands < 25 and not threatened):
        return
    preferred = UNIT_FOR.get(n.option("defence"), "warband")
    kinds = ["musketeers", preferred, "warband"] if preferred == "regiment" else [preferred, "warband"]
    sources: list[actions.Action] = [
        {"node": nd.id} for nd in sorted(world.nodes_of(n.id), key=lambda x: -x.hands)
    ]
    sources += [{"unit": u.id} for u in world.units_of(n.id) if not u.military]
    for kind in kinds:
        if have + rules.UNITS[kind].hands > target + 1.0:
            continue
        for src in sources:
            if _do(world, n, {"kind": "raise_unit", "unit_kind": kind, **src}):
                return


def _army_path(world: World, n: Nation, start: str, goal: str) -> str | None:
    prev: dict[str, str | None] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for nxt in world.neighbours(cur):
            if nxt not in prev and (actions.can_enter(world, n, nxt) or actions.hostile_at(world, n, nxt)):
                prev[nxt] = cur
                q.append(nxt)
    if goal not in prev:
        return None
    step = goal
    while prev[step] is not None and prev[step] != start:
        step = prev[step]  # type: ignore[assignment]
    return step


def _targets(world: World, n: Nation) -> list[str]:
    """Nodes worth marching on: enemy settlements, enemy armies, rebels in our land."""

    out = [nd.id for nd in world.nodes.values() if world.hostile_owner(n.id, nd)]
    out += [u.node for u in world.units.values() if world.hostile(u, n.id)]
    return list(dict.fromkeys(out))


def _armies(world: World, n: Nation) -> None:
    targets = _targets(world, n)
    home = [nd.id for nd in world.nodes_of(n.id)]
    for u in [x for x in world.units_of(n.id) if x.military and x.kind != "fleet"]:
        for _ in range(3):
            if u.id not in world.units or u.moves_left <= 0:
                break
            here = u.node
            adjacent = [t for t in targets if t in world.neighbours(here)]
            if adjacent:
                best = max(adjacent, key=lambda t: military.odds(world, u, world.nodes[t]))
                if military.odds(world, u, world.nodes[best]) >= 0.55 and u.cohesion >= 50:
                    _do(world, n, {"kind": "move", "unit": u.id, "to": best})
                    targets = _targets(world, n)
                    continue
                break  # too strong: hold the line
            goal = None
            if targets and u.cohesion >= 60:
                goal = min(targets, key=lambda t: _distance(world, here, t))
            elif home and world.nodes[here].owner != n.id:
                goal = min(home, key=lambda t: _distance(world, here, t))
            if goal is None or goal == here:
                break
            step = _army_path(world, n, here, goal)
            if step is None or not _do(world, n, {"kind": "move", "unit": u.id, "to": step}):
                break


def _open_land(world: World, n: Nation) -> bool:
    """Is there unclaimed arable ground within three steps of our settlements?"""

    frontier = {nd.id for nd in world.nodes_of(n.id)}
    seen = set(frontier)
    for _ in range(3):
        frontier = {y for x in frontier for y in world.neighbours(x)} - seen
        seen |= frontier
        if any(world.nodes[x].owner is None and world.nodes[x].t.arable >= 0.7 for x in frontier):
            return True
    return False


def _distance(world: World, a: str, b: str) -> int:
    seen = {a: 0}
    q = deque([a])
    while q:
        cur = q.popleft()
        if cur == b:
            return seen[cur]
        for nxt in world.neighbours(cur):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                q.append(nxt)
    return 99


def _raids(world: World, n: Nation, style: str) -> None:
    if style not in ("khan", "wanderer") or world.rng.random() > 0.15:
        return
    for u in world.units_of(n.id):
        if u.kind not in ("warband", "riders", "horde") or u.moves_left <= 0:
            continue
        for x in world.neighbours(u.node):
            victims = {v.nation for v in world.units_at(x) if v.nation != n.id and v.rebel_of is None}
            owner = world.nodes[x].owner
            if owner not in (None, n.id):
                victims.add(owner)
            for v in victims:
                if military.at_war(world, n.id, v) or n.relations.get(v, 0.0) > 0:
                    continue
                if military.odds(world, u, world.nodes[x], victim=v) >= 0.6:
                    if _do(world, n, {"kind": "raid", "unit": u.id, "to": x}):
                        return


def _diplomacy(world: World, n: Nation, style: str) -> None:
    mine = military.military_strength(world, n.id)
    for other_id in _enemies(world, n):
        other = world.nations[other_id]
        w = world.war_between(n.id, other_id)
        assert w is not None
        length = world.turn - int(w["since"])
        score = military.war_score(world, n, other_id)
        if length < rules.PEACE_MIN_TURNS:
            continue
        if score >= 4 and length >= 6:
            _do(world, n, {"kind": "offer_peace", "nation": other_id, "terms": "tribute"})
        elif score <= -2 or n.war_weariness > 15 or length >= 8:
            _do(world, n, {"kind": "offer_peace", "nation": other_id, "terms": "white"})
        del other
    if _enemies(world, n) or world.turn < 25 or world.turn % 4 != 0 or style in ("wanderer",):
        return
    for other_id in n.contacts:
        other = world.nations[other_id]
        if not other.alive or not world.nodes_of(other_id):
            continue
        near = any(
            _distance(world, a.id, b.id) <= 2 for a in world.nodes_of(n.id) for b in world.nodes_of(other_id)
        )
        if not near:
            continue
        theirs = (
            military.military_strength(world, other_id) + rules.SETTLED_LEVY * world.hands_of(other_id) * 0.3
        )
        eager = {"khan": 1.3, "lord": 1.5, "merchant": 2.5}.get(style, 3.0)
        if float(n.last.get("share", 0.0)) >= rules.AMBITION_SHARE:
            eager *= 0.7  # a people within reach of hegemony takes more risks
        cause = other_id in n.casus_belli
        hungry = not _open_land(world, n)  # lords want land only when none is free
        motive = cause or (style == "khan") or hungry
        reserve = n.sway >= (0.0 if cause else rules.WAR_COST) + 20.0  # keep Sway for reforms
        if (
            motive
            and reserve
            and mine > eager * theirs
            and n.relations.get(other_id, 0.0) < (30.0 if style in ("khan", "lord") else 10.0)
            and (world.rng.random() < 0.5)
        ):
            if _do(world, n, {"kind": "declare_war", "nation": other_id}):
                return


def _choose_revenue(world: World, n: Nation) -> None:
    from stock.game import politics

    current = economy.revenue_estimate(world, n, n.option("revenue"))
    best, best_v = None, current * 1.3 + 0.5
    for o in rules.PILLARS["revenue"].options:
        if politics.institution_blocker(n, "revenue", o.key) is not None:
            continue
        v = economy.revenue_estimate(world, n, o.key)
        if o.key == "tax_farming":
            v *= 0.7  # the unrest and insecurity it brings
        if v > best_v and politics.institution_cost(n, "revenue", o.key) <= n.sway - 5:
            best, best_v = o.key, v
    if best is not None:
        _do(world, n, {"kind": "institution", "pillar": "revenue", "option": best})
    at_war = bool(_enemies(world, n))
    calm = max((nd.unrest for nd in world.nodes_of(n.id)), default=0.0) < 30
    rate = "heavy" if at_war and calm else "moderate" if calm or at_war else "light"
    if rate != n.tax_rate:
        _do(world, n, {"kind": "tax", "rate": rate})


# --- trade, fleets and treaties (§11, §16) --------------------------------------------------------


def _unit_step(world: World, n: Nation, u: Unit, goal: str) -> str | None:
    """First step on the shortest path `u` itself may travel (ships by sea, traders by land)."""

    prev: dict[str, str | None] = {u.node: None}
    q = deque([u.node])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for e in world.adjacency()[cur]:
            nxt = e.other(cur)
            if nxt in prev:
                continue
            probe = Unit(u.id, u.nation, u.kind, cur, u.hands)
            if actions.move_cost(world, probe, nxt) is None or actions.hostile_at(world, n, nxt):
                continue
            prev[nxt] = cur
            q.append(nxt)
    if goal not in prev:
        return None
    step = goal
    while prev[step] is not None and prev[step] != u.node:
        step = prev[step]  # type: ignore[assignment]
    return step


def _trade_targets(world: World, n: Nation, kind: str) -> list[str]:
    out = []
    for nd in world.nodes.values():
        if nd.owner in (None, n.id) or nd.owner not in n.contacts:
            continue
        if military.at_war(world, n.id, nd.owner) or trade.embargoed(world, n.id, nd.owner):
            continue
        if n.relations.get(nd.owner, 0.0) < -20:
            continue
        if kind == "merchantman" and "port" not in nd.works:
            continue
        if (
            kind == "merchantman"
            and world.nations[nd.owner].option("commerce") == "mercantile"
            and not world.treaty("trade_pact", n.id, nd.owner)
        ):
            continue
        if any(r.a == n.id and r.b_node == nd.id for r in world.routes.values()):
            continue
        out.append(nd.id)
    return out


def _trade(world: World, n: Nation) -> None:
    for u in [x for x in world.units_of(n.id) if x.kind in ("caravan", "merchantman")]:
        if _do(world, n, {"kind": "open_route", "unit": u.id}):
            continue
        targets = _trade_targets(world, n, u.kind)
        if not targets:
            if u.age > 20:
                del world.units[u.id]  # no one to trade with: the venture is written off
            continue
        goal = min(targets, key=lambda t: _distance(world, u.node, t))
        for _ in range(3):
            if u.id not in world.units or u.moves_left <= 0 or u.node == goal:
                break
            step = _unit_step(world, n, u, goal)
            if step is None or not _do(world, n, {"kind": "move", "unit": u.id, "to": step}):
                break
        if u.id in world.units:
            _do(world, n, {"kind": "open_route", "unit": u.id})
    for nd in world.nodes_of(n.id):
        for which in ("merchantman", "caravan"):
            if n.stock < rules.TRADER_COST[which] + 15:
                continue
            if not _trade_targets(world, n, which):
                continue
            if _do(world, n, {"kind": "send_trader", "node": nd.id, "trader": which}):
                return


def _fleets(world: World, n: Nation, style: str) -> None:
    enemies = _enemies(world, n)
    fleets = [u for u in world.units_of(n.id) if u.kind == "fleet"]
    enemy_ports = [nd.id for nd in world.nodes.values() if nd.owner in enemies and "port" in nd.works]
    if enemy_ports and not fleets and style == "merchant" and n.treasury > 40:
        for nd in world.nodes_of(n.id):
            if _do(world, n, {"kind": "raise_unit", "node": nd.id, "unit_kind": "fleet"}):
                break
    for u in fleets:
        if u.id not in world.units:
            continue
        goals = [
            x.node for x in world.units.values() if x.kind == "fleet" and world.hostile(x, n.id)
        ] + enemy_ports
        if not goals:
            continue
        goal = min(goals, key=lambda t: _distance(world, u.node, t))
        for _ in range(3):
            if u.id not in world.units or u.moves_left <= 0 or u.node == goal:
                break
            step = _unit_step(world, n, u, goal) if not actions.hostile_at(world, n, goal) else None
            if step is None and goal in world.neighbours(u.node, sea=True):
                step = goal
            if step is None or not _do(world, n, {"kind": "move", "unit": u.id, "to": step}):
                break


def _treaties(world: World, n: Nation, style: str) -> None:
    if world.turn % 5 != 2:
        return
    mine = military.military_strength(world, n.id) + 1.0
    for o in n.contacts:
        other = world.nations[o]
        if not other.alive or military.at_war(world, n.id, o):
            continue
        rel = n.relations.get(o, 0.0)
        theirs = military.military_strength(world, o)
        if theirs > 1.5 * mine and rel >= -10 and not world.treaty("non_aggression", n.id, o):
            if _do(world, n, {"kind": "propose_treaty", "nation": o, "treaty": "non_aggression"}):
                continue
        if trade.route_between(world, n.id, o) and rel >= 10 and not world.treaty("trade_pact", n.id, o):
            if _do(world, n, {"kind": "propose_treaty", "nation": o, "treaty": "trade_pact"}):
                continue
        shared = set(_enemies(world, n)) & set(trade._enemies(world, o))
        if shared and rel >= 0 and not world.treaty("alliance", n.id, o):
            if _do(world, n, {"kind": "propose_treaty", "nation": o, "treaty": "alliance"}):
                continue
        if style == "merchant" and rel < 20 and theirs > mine:
            _do(world, n, {"kind": "gift", "nation": o})


# --- credit, ambition and the balance of power (§14.4, §17) ---------------------------------------


def _credit(world: World, n: Nation) -> None:
    if n.seat != "civil" or not n.knows("public_credit"):
        return
    owed = finance.debt(n)
    at_war = bool(_enemies(world, n))
    short = n.treasury < 5.0 and (at_war or n.counters.get("deficit", 0.0) > 0)
    if short and owed < 2 * finance.loan_limit(n):
        amount = round(finance.loan_limit(n) * 0.5, 1)
        if n.stock >= 2 * amount:
            _do(world, n, {"kind": "borrow", "source": finance.DOMESTIC, "amount": amount})
            return
        lenders = sorted(
            (world.nations[o] for o in n.contacts if world.nations[o].alive and not world.nations[o].player),
            key=lambda o: -o.stock,
        )
        for lender in lenders[:2]:
            if _do(world, n, {"kind": "borrow", "source": lender.id, "amount": amount}):
                return
    elif owed > 0 and n.treasury > 40.0:
        foreign = [d["lender"] for d in n.debts if d["lender"] != finance.DOMESTIC]
        leader = world.hegemony.get("leader")
        first = leader if leader in foreign else (foreign[0] if foreign else None)
        _do(world, n, {"kind": "repay", "amount": n.treasury - 30.0, **({"lender": first} if first else {})})


def _ambition(world: World, n: Nation) -> None:
    """Within reach of hegemony: gather the weak under our protection (the force lever)."""

    if float(n.last.get("share", 0.0)) < rules.AMBITION_SHARE or world.turn % 5 != 3:
        return
    for o in sorted(n.contacts, key=lambda x: military.military_strength(world, x)):
        if _do(world, n, {"kind": "propose_treaty", "nation": o, "treaty": "protection"}):
            return


def _balance(world: World, n: Nation) -> None:
    """Against an ascendant people: slip its orbit and, if we can, fight it (§17.4)."""

    leader_id = world.hegemony.get("leader")
    if not leader_id or leader_id == n.id or not world.nations[leader_id].alive:
        return
    if world.treaty("protection", leader_id, n.id):
        _do(world, n, {"kind": "cancel_treaty", "nation": leader_id, "treaty": "protection"})
    if finance.debt(n, leader_id) > 0 and n.treasury > 10:
        _do(world, n, {"kind": "repay", "lender": leader_id, "amount": n.treasury - 5.0})
    if military.at_war(world, n.id, leader_id) or leader_id not in n.contacts:
        return
    ours = military.military_strength(world, n.id) + sum(
        military.military_strength(world, x) for x in trade.allies_of(world, n.id)
    )
    at_war_with_leader = [
        o
        for o in world.nations.values()
        if o.alive and o.id != n.id and military.at_war(world, o.id, leader_id)
    ]
    ours += 0.5 * sum(military.military_strength(world, o.id) for o in at_war_with_leader)
    theirs = military.military_strength(world, leader_id)
    if ours >= 0.8 * theirs or (at_war_with_leader and ours >= 0.4 * theirs):
        _do(world, n, {"kind": "declare_war", "nation": leader_id})


def take_turn(world: World, n: Nation) -> None:
    style = personality(n)
    for d in list(n.decisions):
        if d.kind == "event":
            _do(world, n, {"kind": "decide", "id": d.id, "choice": d.data["ai"]})
            continue
        if d.kind == "capture":
            _do(
                world, n, {"kind": "decide", "id": d.id, "choice": "plunder" if style == "khan" else "occupy"}
            )
            continue
        if d.kind == "peace":
            _do(world, n, {"kind": "decide", "id": d.id, "choice": "accept"})
            continue
        if d.kind == "treaty":
            other = world.nations[d.data["from"]]
            ok = trade.would_accept(world, other, n, d.data["treaty"])
            _do(world, n, {"kind": "decide", "id": d.id, "choice": "accept" if ok else "refuse"})
            continue
        order = d.data.get("order", "labour")
        choice = "grant" if n.orders[order].clout > 0.4 or n.sway < 15 else "refuse"
        _do(world, n, {"kind": "decide", "id": d.id, "choice": choice})
    _research(world, n, style)
    _balance(world, n)
    _diplomacy(world, n, style)
    _credit(world, n)
    _ambition(world, n)
    _raise(world, n)
    _armies(world, n)
    _raids(world, n, style)
    _fleets(world, n, style)
    _treaties(world, n, style)
    _units(world, n, style)
    _scouts(world, n)
    _trade(world, n)
    _builds(world, n)
    _expand(world, n)
    for partner in n.contacts:
        if actions.check(world, n, {"kind": "barter", "nation": partner}) is None:
            _do(world, n, {"kind": "barter", "nation": partner})
    _state(world, n, style)
    if world.turn % 3 == 0:
        _institutions(world, n, style)
    if n.orders["labour"].contentment < 40 and n.feast_ready == 0:
        _do(world, n, {"kind": "feast"})
