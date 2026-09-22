"""Action offers (Doc 07, "Actions — draft, cost, boundary"): every action the player
could queue this year, drafted server-side with the payload the engine's handlers
expect, its cost from `core.actions.validate`, and whether `A_S` covers it.

The JS draws a button per offer where the thing is (a neighbouring ground on the map,
a law row, a rival row) and POSTs the offer's payload unchanged, so the client never
re-derives a cost or a legality rule. Payload shapes follow the handlers exactly:
`politics.legislation.apply_action`, `finance.taxation/credit.apply_action`,
`security.war.apply_action`, `sim.year._apply_band_action/_apply_treaty_action/
_apply_price_control`. Enum-valued fields travel as member names; `api.server`
decodes them back.
"""

from __future__ import annotations

from typing import Any

from stock.api.schemas import ActionOffer, FocusOption
from stock.core.actions import Action, ActionKind, validate
from stock.core.goods import Good
from stock.core.laws import LAW_TABLE, FocusKind, LawBranch
from stock.core.trees import TreeINode
from stock.core.world import Location, Nation, SeatKind, World
from stock.politics.interests import DEMANDS, Repeal
from stock.trade.treaties import TermKind
from stock.ui.labels import describe_action, label, law_label
from stock.ui.names import NameRegister

#: Kinds the spec asks a confirmation for ("declare war, default, veto").
CONFIRM_KINDS: frozenset[ActionKind] = frozenset({ActionKind.DECLARE_WAR, ActionKind.VETO})

#: Focus targets: which node names each Focus kind actually lowers a gate for
#: (`meta/trees.py`'s `_public_works_c_max` / `_patent_threshold` /
#: `_education_threshold` call sites).
FOCUS_TARGETS: dict[FocusKind, tuple[tuple[str, ...], bool]] = {
    FocusKind.PUBLIC_WORKS: (("PUTTING_OUT", "DIVISION_OF_LABOUR", *(n.name for n in TreeINode)), True),
    FocusKind.PATENT: (("THREE_FIELD_ROTATION", "PUTTING_OUT", "MACHINE_PRODUCTION"), False),
    FocusKind.EDUCATION: (("DIVISION_OF_LABOUR",), False),
}

#: Treaty term kinds a player may propose (the others — tribute, cession — are
#: peace terms imposed at war's end, `security.war`).
PROPOSABLE_TERMS: tuple[TermKind, ...] = (
    TermKind.NON_AGGRESSION,
    TermKind.TARIFF_CEILING,
    TermKind.ROUTE_ACCESS,
    TermKind.PORT_ACCESS,
    TermKind.MOST_FAVOURED,
    TermKind.GRAIN_GUARANTEE,
    TermKind.EXCLUSIVE_ROUTE,
)


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if hasattr(v, "name") and not isinstance(v, str):
            out[k] = v.name
        elif isinstance(v, list):
            out[k] = [x.name if hasattr(x, "name") and not isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


class OfferBuilder:
    def __init__(self, world: World, nation_id: str, names: NameRegister) -> None:
        self.world = world
        self.nation_id = nation_id
        self.nation: Nation = world.nations[nation_id]
        self.names = names
        self.offers: list[ActionOffer] = []

    def offer(
        self,
        kind: ActionKind,
        payload: dict[str, Any],
        *,
        panel: str,
        label_text: str | None = None,
        location: str | None = None,
        group: str | None = None,
        confirm: bool | None = None,
    ) -> ActionOffer:
        action = Action(kind=kind, nation=self.nation_id, payload=dict(payload))
        result = validate(self.world, action)
        available = self.nation.scalars.A_S
        short = not result.ok and result.reason == "insufficient A_S"
        shortfall = max(0.0, result.cost - available) if short else 0.0
        json_payload = _jsonable(payload)
        offer = ActionOffer(
            kind=kind.name,
            label=label_text or describe_action(kind.name, json_payload, self.names),
            payload=json_payload,
            cost=result.cost,
            affordable=result.ok,
            shortfall=shortfall,
            reason=result.reason,
            confirm=(kind in CONFIRM_KINDS) if confirm is None else confirm,
            panel=panel,
            location=location,
            group=group,
        )
        self.offers.append(offer)
        return offer

    # -- band ----------------------------------------------------------------

    def band(self) -> None:
        homes = self.nation.locations(self.world)
        if not homes:
            return
        home = homes[0]
        for nid in sorted(home.neighbours):
            other = self.world.locations.get(nid)
            if other is None:
                continue
            if other.nation is None:
                self.offer(ActionKind.BAND_MOVE, {"to": nid}, panel="map", location=nid, group="band")
            elif other.nation != self.nation_id:
                self.offer(ActionKind.BAND_RAID, {"location": nid}, panel="map", location=nid, group="band")
                self.offer(ActionKind.BAND_BARTER, {"with": nid}, panel="map", location=nid, group="band")
        if home.resources.grazing:
            self.offer(ActionKind.BAND_FOLLOW_HERDS, {}, panel="map", location=home.id, group="band")
        if home.resources.arable and home.fields <= 0:
            self.offer(ActionKind.BAND_SETTLE, {}, panel="map", location=home.id, group="band")

    # -- politics ------------------------------------------------------------

    def laws(self) -> dict[str, dict[str, Any]]:
        """Per law: `enact`/`repeal` offer and the `vetoes` available against the
        Interests pressing for or against it. Returned keyed by law name for the
        politics panel to attach to its rows."""

        out: dict[str, dict[str, Any]] = {}
        year = self.world.year
        k_veto = self.world.params.politics.k_veto if self.world.params else 0
        for law_id in LAW_TABLE:
            state = self.nation.laws.get(law_id)
            enacted = bool(state and state.enacted)
            row: dict[str, Any] = {"enact": None, "repeal": None, "vetoes": []}
            # `legislation.enact/repeal` pass the bar and deduct A_S by the payload's
            # `spend`; the quote shown is the cost function's value now, and the amount
            # actually spent is the bar's cost when the action applies.
            kind = ActionKind.REPEAL if enacted else ActionKind.ENACT
            payload = {"law": law_id, "spend": "bar"}  # "bar": the cost at the boundary (sim/year.py)
            row["repeal" if enacted else "enact"] = self.offer(kind, payload, panel="politics", group="law")
            until = state.veto_cooldown_until if state is not None else None
            cooling = until is not None and year < until
            if not cooling:
                for interest_id, demands in DEMANDS.items():
                    if interest_id not in self.nation.interests:
                        continue
                    for demand in demands:
                        wants_repeal = isinstance(demand, Repeal)
                        target = demand.law if isinstance(demand, Repeal) else demand
                        if target != law_id:
                            continue
                        # A demand only presses when its outcome isn't already the case.
                        if wants_repeal != enacted:
                            continue
                        verb = "repeal of" if wants_repeal else "enactment of"
                        text = (
                            f"Veto {label('interest', interest_id)}'s {verb} {law_label(law_id)} "
                            f"· blocks it {k_veto}y"
                        )
                        row["vetoes"].append(
                            self.offer(
                                ActionKind.VETO,
                                {"interest": interest_id, "law": law_id},
                                panel="politics",
                                label_text=text,
                                group="veto",
                            )
                        )
            out[law_id.name] = row
        return out

    def focus(self) -> tuple[list[FocusOption], ActionOffer | None, ActionOffer | None]:
        options = [
            FocusOption(kind=kind.name, nodes=list(nodes), takes_location=takes_loc)
            for kind, (nodes, takes_loc) in FOCUS_TARGETS.items()
        ]
        first = FOCUS_TARGETS[FocusKind.PUBLIC_WORKS][0][0]
        set_focus = self.offer(
            ActionKind.SET_FOCUS,
            {"kind": FocusKind.PUBLIC_WORKS, "node": first, "location": None},
            panel="politics",
            label_text="Set focus",
            group="focus",
        )
        clear = None
        if self.nation.focus is not None:
            clear = self.offer(
                ActionKind.CLEAR_FOCUS, {}, panel="politics", label_text="Clear focus", group="focus"
            )
        return options, set_focus, clear

    # -- finance -------------------------------------------------------------

    def finance(self) -> None:
        params = self.world.params
        default_rate = params.tax.default_rate if params else 0.1
        for law_id, spec in LAW_TABLE.items():
            if spec.branch is not LawBranch.REVENUE:
                continue
            state = self.nation.laws.get(law_id)
            if not (state and state.enacted):
                continue
            rate = float(self.nation.tax_rates.get(law_id, default_rate))
            self.offer(
                ActionKind.SET_TAX_RATE,
                {"instrument": law_id.name, "rate": rate},
                panel="incidence",
                label_text=f"Set rate · {law_label(law_id)}",
                group=f"tax:{law_id.name}",
            )
        b = self.nation.budget
        shares = {
            "defence": b.defence,
            "justice": b.justice,
            "works": b.works,
            "service": b.service,
            "court": b.court,
            "transfers": b.transfers,
        }
        self.offer(
            ActionKind.SET_BUDGET,
            {"shares": shares},
            panel="incidence",
            label_text="Set budget",
            group="budget",
        )
        for policy in ("TAX", "ROLLOVER", "DEFAULT"):
            self.offer(
                ActionKind.SET_DEBT_POLICY,
                {"policy": policy},
                panel="incidence",
                label_text=label("debt_policy", policy),
                group="debt",
                confirm=(policy == "DEFAULT"),
            )
        for mode in ("BONDS", "TAX"):
            self.offer(
                ActionKind.SET_FUNDING_MODE,
                {"mode": mode},
                panel="incidence",
                label_text=label("funding_mode", mode),
                group="funding",
            )

    # -- security ------------------------------------------------------------

    def _frontier(self) -> dict[str, Location]:
        """Foreign locations adjacent to the player's territory."""

        own = {loc.id for loc in self.nation.locations(self.world)}
        out: dict[str, Location] = {}
        for lid in own:
            for nid in self.world.locations[lid].neighbours:
                other = self.world.locations.get(nid)
                if other is not None and other.nation not in (None, self.nation_id):
                    out[nid] = other
        return dict(sorted(out.items()))

    def security(self) -> None:
        world = self.world
        me = self.nation_id
        living = [nid for nid, n in sorted(world.nations.items()) if nid != me and not n.ended]
        at_war_with = {b for (a, b) in world.wars if a == me} | {a for (a, b) in world.wars if b == me}
        for nid in living:
            if nid in at_war_with:
                continue
            self.offer(
                ActionKind.DECLARE_WAR,
                {"target": nid, "casus_belli": False},
                panel="security",
                group=f"rival:{nid}",
            )
        frontier = self._frontier()
        for lid, loc in frontier.items():
            self.offer(
                ActionKind.DECLARE_RAID, {"location": lid}, panel="security", location=lid, group="raid"
            )
            if loc.nation in at_war_with and (me, loc.nation) in world.wars:
                self.offer(
                    ActionKind.BESIEGE,
                    {"location": lid, "target": loc.nation},
                    panel="security",
                    location=lid,
                    group=f"war:{loc.nation}",
                )
        for (attacker, defender), war in sorted(world.wars.items()):
            if attacker == me:
                self.offer(
                    ActionKind.OFFER_PEACE,
                    {
                        "target": defender,
                        "cession": [],
                        "tribute_amount": 0.0,
                        "tribute_years": 0,
                        "treaty_terms": [],
                    },
                    panel="security",
                    group=f"war:{defender}",
                )
            elif defender == me and war.peace_offer is not None:
                self.offer(
                    ActionKind.ACCEPT_PEACE,
                    {"target": attacker},
                    panel="security",
                    group=f"war:{attacker}",
                )
        self.offer(ActionKind.REPRESS, {}, panel="security", group="order")

    # -- trade ---------------------------------------------------------------

    def trade(self) -> None:
        world = self.world
        me = self.nation_id
        for nid, n in sorted(world.nations.items()):
            if nid == me or n.ended:
                continue
            self.offer(
                ActionKind.PROPOSE_TREATY,
                {"target": nid, "terms": [{"kind": TermKind.NON_AGGRESSION.name}]},
                panel="routes",
                group=f"treaty:{nid}",
            )
        for proposal in world.treaty_proposals:
            if proposal.get("target") != me:
                continue
            initiator = str(proposal.get("initiator", ""))
            self.offer(
                ActionKind.ACCEPT_TREATY,
                {"initiator": initiator},
                panel="routes",
                group=f"proposal:{initiator}",
            )
        for loc in self.nation.locations(world):
            price = float(loc.market.price.get(Good.PROVISIONS, 1.0))
            self.offer(
                ActionKind.PRICE_CONTROL,
                {"location": loc.id, "price": price},
                panel="ledger",
                location=loc.id,
                group="price",
            )


def build_offers(world: World, nation_id: str, names: NameRegister) -> OfferBuilder:
    """Every offer for `nation_id` this year, seat-appropriate. Returns the builder so
    the politics panel can also read the per-law rows it produced."""

    builder = OfferBuilder(world, nation_id, names)
    nation = builder.nation
    if nation.ended:
        return builder
    if nation.seat is SeatKind.BAND:
        builder.band()
        return builder
    builder.finance()
    builder.security()
    builder.trade()
    return builder
