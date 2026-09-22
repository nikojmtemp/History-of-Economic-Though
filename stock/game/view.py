"""What the player sees (design doc §19): one JSON-ready snapshot per request.

Only the viewing nation's own books are shown in full; rivals appear as far as
contact and fog allow. Every number the UI shows comes from here, with its
breakdown where the design asks for one (§19.4)."""

from __future__ import annotations

from typing import Any

from stock.game import actions, economy, military, politics, research, rules, trade, victory
from stock.game.state import Nation, Unit, World


def _r(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


def _unit(world: World, n: Nation, u: Unit) -> dict[str, Any]:
    t = rules.UNITS[u.kind]
    out: dict[str, Any] = {
        "id": u.id,
        "nation": u.nation,
        "kind": u.kind,
        "name": t.name,
        "node": u.node,
        "hands": _r(u.hands, 1),
        "herds": _r(u.herds, 0),
        "military": t.military,
        "strength": _r(military.unit_strength(world, u), 1),
        "cohesion": _r(u.cohesion, 0),
        "rebel": u.rebel_of is not None,
        "hostile": world.hostile(u, n.id),
    }
    if u.nation != n.id or u.rebel_of is not None:
        return out
    moves = []
    for e in world.edges_of(u.node):
        to = e.other(u.node)
        why = actions.check(world, n, {"kind": "move", "unit": u.id, "to": to})
        m: dict[str, Any] = {"to": to, "ok": why is None, "why": why, "cost": e.cost()}
        if why is None and actions.hostile_at(world, n, to):
            m["attack"] = _r(military.odds(world, u, world.nodes[to]))
        moves.append(m)
    raids = []
    if u.kind in ("warband", "riders", "horde"):
        for to in world.neighbours(u.node):
            if military.raid_blocker(world, n, u, to) is None:
                nd = world.nodes[to]
                victim = (
                    nd.owner
                    if nd.owner not in (None, n.id)
                    else next(
                        (x.nation for x in world.units_at(to) if x.nation != n.id and x.rebel_of is None),
                        None,
                    )
                )
                raids.append(
                    {"to": to, "victim": victim, "odds": _r(military.odds(world, u, nd, victim=victim))}
                )
    raise_opts = []
    if not t.military:
        for kind in ("warband", "riders"):
            raise_opts.append(
                {
                    "kind": kind,
                    "name": rules.UNITS[kind].name,
                    "why": military.raise_blocker(world, n, u, kind),
                }
            )
    out.update(
        raids=raids,
        raise_options=raise_opts,
        supplied=military.supplied(world, u),
        upgrade=military.upgrade_blocker(world, n, u) if u.kind == "regiment" else None,
        description=t.description,
    )
    verbs = {}
    for kind in ("split", "follow", "tame", "settle"):
        verbs[kind] = actions.check(world, n, {"kind": kind, "unit": u.id})
    merge_with = [x.id for x in world.units_at(u.node) if x.nation == n.id and x.id != u.id]
    out.update(
        moves_left=u.moves_left,
        max_moves=u.max_moves(set(n.known)),
        moves=moves,
        verbs=verbs,
        merge_with=merge_with,
        followed=u.followed,
        split_cost=actions.split_cost(n),
    )
    return out


def _node(world: World, n: Nation, node_id: str, vis: set[str]) -> dict[str, Any]:
    nd = world.nodes[node_id]
    t = nd.t
    out: dict[str, Any] = {
        "id": nd.id,
        "name": nd.name,
        "x": nd.x,
        "y": nd.y,
        "terrain": nd.terrain,
        "terrain_name": t.name,
        "river": nd.river,
        "coast": nd.coast,
        "features": nd.features,
        "visible": node_id in vis,
        "yields": {
            "game": t.game,
            "grazing": t.grazing,
            "arable": t.arable,
            "fish": t.fish,
            "defence": t.defence,
        },
    }
    if node_id in vis:
        out.update(
            owner=nd.owner,
            hands=_r(nd.hands, 1),
            works=nd.works,
            herds=_r(nd.herds, 0),
            game=_r(nd.game),
            unrest=_r(nd.unrest, 0),
            slots=nd.slots(),
            siege=nd.siege,
            conquered=nd.conquered,
            forts=nd.works.count("fort"),
            enemy=world.hostile_owner(n.id, nd),
        )
    if nd.owner == n.id:
        buildable = []
        for w in rules.WORKS.values():
            why = actions.build_blocker(world, n, nd.id, w.key)
            if why == "no such work":
                continue
            entry: dict[str, Any] = {
                "key": w.key,
                "name": w.name,
                "cost": actions.work_cost(n, w.key),
                "public": w.public,
                "why": why,
            }
            if why is None and not w.public:
                entry["return"] = _r(actions.expected_return(world, n, nd, w.key), 3)
            buildable.append(entry)
        out["buildable"] = buildable
        out["found_band"] = actions.check(world, n, {"kind": "found_band", "node": nd.id})
        out["raise_options"] = [
            {
                "kind": k,
                "name": ut.name,
                "why": military.raise_blocker(world, n, nd, k),
                "hands": ut.hands,
                "wares": ut.wares,
                "treasury": ut.treasury,
                "herds": ut.herds,
                "upkeep": ut.upkeep,
                "strength": ut.strength,
                "description": ut.description,
            }
            for k, ut in rules.UNITS.items()
            if ut.raisable
        ]
        jobs = sum(rules.WORKS[w].jobs for w in nd.works)
        out["jobs"] = jobs
    return out


def _discoveries(world: World, n: Nation) -> list[dict[str, Any]]:
    m = research.metrics(world, n)
    out = []
    for d in rules.DISCOVERIES.values():
        state = "known" if d.key in n.known else "available" if research.available(n, d.key) else "locked"
        entry: dict[str, Any] = {
            "key": d.key,
            "name": d.name,
            "era": d.era,
            "lane": d.lane,
            "state": state,
            "requires": [list(g) for g in d.requires],
            "unlocks": d.unlocks,
            "quote": d.quote,
            "observation": d.observation_text,
            "observed": research.observation_met(n, d.key, m),
            "progress": _r(min(1.0, m.get(d.observation[0], 0.0) / d.observation[1]), 2)
            if d.observation
            else 1.0,
        }
        if state != "known":
            entry["cost"] = research.cost(world, n, d.key, m)
            entry["diffusion"] = _r(research.diffusion(world, n, d.key))
            entry["known_by"] = [
                o.name for o in world.nations.values() if o.id in n.contacts and d.key in o.known
            ]
        out.append(entry)
    return out


def _institutions(n: Nation) -> list[dict[str, Any]]:
    out = []
    for p in rules.PILLARS.values():
        opts = []
        for o in p.options:
            why = politics.institution_blocker(n, p.key, o.key)
            opts.append(
                {
                    "key": o.key,
                    "name": o.name,
                    "effect": o.effect,
                    "supports": list(o.supports),
                    "opposes": list(o.opposes),
                    "needs": rules.DISCOVERIES[o.needs].name if o.needs else None,
                    "why": why,
                    "cost": politics.institution_cost(n, p.key, o.key) if why is None else None,
                    "active": n.option(p.key) == o.key,
                    "pending": n.pending_institutions.get(p.key) == o.key,
                }
            )
        out.append(
            {"key": p.key, "name": p.name, "options": opts, "cooldown": n.pillar_cooldown.get(p.key, 0)}
        )
    return out


def _breakdowns(world: World, n: Nation) -> dict[str, Any]:
    L = n.last
    if "made" not in L:
        return {
            "sway": {k: _r(v) for k, v in L.get("sway_parts", {}).items()},
            "ingenuity": {k: _r(v) for k, v in L.get("ingenuity", {}).items()},
        }
    made, used = L["made"], L["consumed"]
    return {
        "food": {
            "made": _r(made["food"]),
            "eaten": _r(used["food"]),
            "store": _r(n.store["food"]),
            "by_source": {k: _r(v) for k, v in L["sources"].items() if v},
        },
        "sway": {k: _r(v) for k, v in L.get("sway_parts", {}).items()},
        "ingenuity": {k: _r(v) for k, v in L.get("ingenuity", {}).items()},
        "stock": {
            "saved": _r(L["savings"]),
            "security": _r(L["security"]),
            "to_stock": _r(L["to_stock"]),
            "hoarded": _r(L["savings"] - L["to_stock"]),
            "rate_of_profit": _r(L["r"], 3),
        },
        "treasury": {
            "collected": _r(L["tax"]["collected"]),
            "spent": {k: _r(v) for k, v in L.get("spent", {}).items()},
        },
    }


def snapshot(world: World, nation_id: str | None = None) -> dict[str, Any]:
    n = world.nations[nation_id] if nation_id else world.player()
    assert n is not None
    vis = trade.visible(world, n)
    explored = set(n.explored) | vis
    shares = victory.world_shares(world)
    L = n.last
    full = "made" in L  # a turn has resolved
    nations = []
    for o in world.nations.values():
        met = o.id == n.id or o.id in n.contacts
        entry: dict[str, Any] = {
            "id": o.id,
            "name": o.name if met else "Unknown people",
            "colour": o.colour,
            "met": met,
            "alive": o.alive,
        }
        if met:
            entry.update(
                mode=o.mode,
                seat=o.seat,
                share=_r(shares.get(o.id, 0.0), 3),
                hands=_r(world.hands_of(o.id), 1),
                relations=_r(n.relations.get(o.id, 0.0), 0),
                per_head=_r(victory.produce_per_head(world, o), 3),
                barter=None if o.id == n.id else actions.check(world, n, {"kind": "barter", "nation": o.id}),
                trading=trade.route_between(world, n.id, o.id) is not None,
                history=o.history[-150:],
                at_war=military.at_war(world, n.id, o.id),
                war_score=_r(military.war_score(world, n, o.id), 0),
                strength=_r(military.military_strength(world, o.id), 1),
                cause=o.id in n.casus_belli,
                truce=n.truce.get(o.id, 0) if n.truce.get(o.id, 0) >= world.turn else 0,
                declare=None
                if o.id == n.id
                else actions.check(world, n, {"kind": "declare_war", "nation": o.id}),
                peace={
                    terms: actions.check(world, n, {"kind": "offer_peace", "nation": o.id, "terms": terms})
                    for terms in ("white", "tribute", "submit")
                }
                if o.id != n.id
                else {},
            )
        nations.append(entry)
    edges = [{"a": e.a, "b": e.b, "kind": e.kind} for e in world.edges if e.a in explored and e.b in explored]
    orders = {
        o: {
            "name": rules.ORDER_NAMES[o],
            "size": _r(st.size, 1),
            "income": _r(st.income),
            "share": _r(st.share, 3),
            "contentment": _r(st.contentment, 0),
            "clout": _r(st.clout, 3),
            "satisfaction": {
                "food": _r(st.food_sat),
                "comfort": _r(st.comfort_sat),
                "standing": _r(st.standing_sat),
            },
        }
        for o, st in n.orders.items()
    }
    log = [
        {"turn": e.turn, "kind": e.kind, "text": e.text, "node": e.node, "quote": e.quote}
        for e in world.log
        if e.nation in (None, n.id)
    ][-80:]
    return {
        "turn": world.turn,
        "year": rules.year_of(world.turn),
        "last_turn": rules.LAST_TURN,
        "spec": world.spec,
        "winner": world.winner,
        "hegemony": world.hegemony,
        "me": {
            "id": n.id,
            "name": n.name,
            "colour": n.colour,
            "seat": n.seat,
            "mode": n.mode,
            "mode_challenger": n.mode_challenger,
            "mode_streak": n.mode_streak,
            "sway": _r(n.sway, 1),
            "sway_income": _r(sum(L.get("sway_parts", {}).values()), 1),
            "stock": _r(n.stock, 1),
            "stock_income": _r(L.get("to_stock", 0.0), 1),
            "treasury": _r(n.treasury, 1),
            "treasury_income": _r(
                L.get("tax", {}).get("collected", 0.0) - sum(L.get("spent", {}).values()), 1
            )
            if full
            else 0.0,
            "food": _r(n.store["food"], 1),
            "food_income": _r(L["made"]["food"] - L["consumed"]["food"], 1) if full else 0.0,
            "ingenuity": _r(sum(L.get("ingenuity", {}).values()), 1),
            "researching": n.researching,
            "research_progress": _r(n.research_progress, 1),
            "research_cost": research.cost(world, n, n.researching) if n.researching else None,
            "extent": _r(L.get("extent", 0.0), 1),
            "dol": _r(L.get("dol", 1.0)),
            "security": _r(L.get("security", economy.security_of(world, n))),
            "hands": _r(world.hands_of(n.id), 1),
            "herds": _r(world.herds_of(n.id), 0),
            "retainers": _r(n.retainers, 1),
            "prices": {k: _r(v) for k, v in n.prices.items()},
            "orders": orders,
            "tax_rate": n.tax_rate,
            "budget": n.budget,
            "produce": _r(L.get("produce", 0.0)),
            "per_head": _r(victory.produce_per_head(world, n), 3),
            "sources": {k: _r(v) for k, v in L.get("sources", {}).items()},
            "split": {k: _r(v) for k, v in L.get("split", {}).items()},
            "uses": {
                "consumed": {k: _r(v) for k, v in L.get("consumed", {}).items()},
                "saved": _r(L.get("savings", 0.0)),
                "to_stock": _r(L.get("to_stock", 0.0)),
                "taxes": _r(L.get("tax", {}).get("collected", 0.0)),
            }
            if full
            else {},
            "tax": L.get("tax", {}),
            "wage": _r(L.get("wage", 1.0)),
            "bargaining": _r(L.get("bargaining", 0.0)),
            "breakdowns": _breakdowns(world, n),
            "build_queue": n.build_queue,
            "decisions": [d.__dict__ for d in n.decisions],
            "feast": actions.check(world, n, {"kind": "feast"}),
            "found_government": actions.check(world, n, {"kind": "found_government"}),
            "restore": actions.check(world, n, {"kind": "restore"}),
            "history": n.history[-150:],
            "moments": n.moments,
            "route_slots": trade.route_slots(world, n),
            "routes": trade.route_count(world, n.id),
            "war": military.summary(world, n),
            "defence": n.option("defence"),
            "war_cost": rules.WAR_COST,
        },
        "nations": nations,
        "nodes": [_node(world, n, nid, vis) for nid in sorted(explored)],
        "edges": edges,
        "units": [_unit(world, n, u) for u in world.units.values() if u.node in vis or u.nation == n.id],
        "discoveries": _discoveries(world, n),
        "institutions": _institutions(n),
        "works": [
            {
                "key": w.key,
                "name": w.name,
                "cost": w.cost,
                "jobs": w.jobs,
                "description": w.description,
                "needs": rules.DISCOVERIES[w.needs].name if w.needs else None,
                "public": w.public,
            }
            for w in rules.WORKS.values()
        ],
        "unit_types": {
            k: {
                "kind": k,
                "name": t.name,
                "hands": t.hands,
                "strength": t.strength,
                "wares": t.wares,
                "treasury": t.treasury,
                "herds": t.herds,
                "upkeep": t.upkeep,
                "description": t.description,
            }
            for k, t in rules.UNITS.items()
        },
        "log": log,
        "modes": [rules.MODE_NAMES[m] for m in rules.MODES],
    }
