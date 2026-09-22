"""Tests for Doc 06: scripted sovereigns."""

from __future__ import annotations

from stock.ai.scripts import LANDED_SCRIPT, SCRIPTS, Mode, respond_to_breach, select_mode
from stock.ai.sovereign import NullSovereign, ScriptedSovereign
from stock.ai.view import NationView, OtherNation
from stock.core.actions import ActionKind, validate
from stock.core.laws import LawId
from stock.core.records import InterestId
from stock.core.world import InterestState, Location, Nation, NationScalars, SeatKind, World
from stock.sim.rng import make_rng


def _make_world(nations: dict[str, Nation], locations: dict[str, Location] | None = None) -> World:
    from stock.core.params import Params

    return World(
        year=10,
        nations=nations,
        locations=locations or {},
        rng=make_rng(1),
        params=Params.default(),
    )


def _view(
    *,
    nation_id: str = "n",
    scalars: dict[str, float] | None = None,
    interests: dict[str, float] | None = None,
    dominant: str | None = None,
    law_states: dict[str, dict[str, float]] | None = None,
    others: dict[str, OtherNation] | None = None,
    breaches: tuple[str, ...] = (),
) -> NationView:
    return NationView(
        nation_id=nation_id,
        year=10,
        seat="STATE",
        scalars=scalars or {},
        curves={},
        flows={},
        class_sizes={},
        law_states=law_states or {},
        interests=interests or {},
        dominant_interest=dominant,
        own_treaties=(),
        others=others or {},
        breaches_against_us=breaches,
    )


def _other(id_: str, m: float = 1.0, hostility: float = 0.0, at_war: bool = False) -> OtherNation:
    return OtherNation(
        id=id_,
        seat="STATE",
        ended=False,
        curves={},
        capital_share=0.0,
        consumption_share=0.0,
        production_share=0.0,
        m=m,
        hostility=hostility,
        at_war=at_war,
        treaties_with_us=(),
    )


class TestModeSelection:
    def test_landed_dominant_interest_selects_landed_mode(self) -> None:
        assert select_mode(_view(dominant="LANDED")) is Mode.LANDED

    def test_industrial_or_merchant_selects_commercial_mode(self) -> None:
        assert select_mode(_view(dominant="INDUSTRIAL")) is Mode.COMMERCIAL
        assert select_mode(_view(dominant="MERCHANT")) is Mode.COMMERCIAL

    def test_no_interest_selects_herding_mode(self) -> None:
        assert select_mode(_view(dominant=None)) is Mode.HERDING


class TestActionsValidate:
    def test_every_action_a_script_returns_passes_validate(self) -> None:
        """Every rule's action_factory, run against a well-resourced fixture, must
        produce an Action that `actions.validate` accepts."""

        rng = make_rng(1)
        seat_by_mode = {
            Mode.HERDING: SeatKind.BAND,
            Mode.LANDED: SeatKind.STATE,
            Mode.COMMERCIAL: SeatKind.STATE,
        }

        for mode, script in SCRIPTS.items():
            nation = Nation(
                id="n",
                seat=seat_by_mode[mode],
                scalars=NationScalars(A_S=1000.0, PSV=0.0, PTV_ext=5.0, R_private=0.0),
            )
            nation.interests[InterestId.LANDED] = InterestState(authority=100.0)
            world = _make_world({"n": nation})
            for name, _condition, factory in script:
                action = factory(_view(nation_id="n", scalars={"A_S": 1000.0}), rng)
                if action is None:
                    continue
                result = validate(world, action)
                assert result.ok, (
                    f"{mode.name}.{name} produced an action that failed validate: {result.reason}"
                )


class TestNoPrivateFieldNeeded:
    def test_scripts_run_on_a_minimal_view_with_no_extra_fields(self) -> None:
        """A NationView with nothing beyond its declared (all-public) fields still
        runs every rule without needing anything more — proof there's no private
        back-channel a rule secretly depends on."""

        sovereign = ScriptedSovereign()
        rng = make_rng(1)
        dominant_by_mode = {"LANDED": "LANDED", "COMMERCIAL": "INDUSTRIAL", "HERDING": None}
        for mode in Mode:
            view = _view(dominant=dominant_by_mode[mode.name])
            sovereign.scripts = {mode: SCRIPTS[mode]}
            actions = sovereign.decide(view, rng)
            assert isinstance(actions, list)


class TestLandedNeverStandingArmyWithPrivateRecourse:
    def test_standing_army_rule_condition_false_when_r_private_positive(self) -> None:
        rule = next(r for r in LANDED_SCRIPT if r[0] == "standing_army_only_if_no_private_recourse")
        _name, condition, _factory = rule
        assert condition(_view(scalars={"R_private": 5.0})) is False
        assert condition(_view(scalars={"R_private": 0.0}, law_states={})) is True

    def test_scripted_sovereign_never_enacts_standing_army_while_r_private_positive(self) -> None:
        sovereign = ScriptedSovereign(scripts={Mode.LANDED: LANDED_SCRIPT}, max_actions=len(LANDED_SCRIPT))
        rng = make_rng(1)
        scalars = {"A_S": 1000.0, "R_private": 5.0, "PSV": 10.0, "PTV_ext": 0.0}
        view = _view(dominant="LANDED", scalars=scalars)
        actions = sovereign.decide(view, rng)
        assert not any(
            a.kind is ActionKind.ENACT and a.payload.get("law") is LawId.STANDING_ARMY_ACT for a in actions
        )


class TestCommercialNeverVetoesCharter:
    def test_commercial_script_has_no_veto_rule_at_all(self) -> None:
        """The commercial script never vetoes a Merchant charter self-enactment
        (Doc 06's own instruction: "let it self-enact; do not veto") — trivially
        true here since no rule in the script ever produces a VETO action."""

        for _name, _condition, factory in SCRIPTS[Mode.COMMERCIAL]:
            action = factory(_view(scalars={"A_S": 1000.0}), make_rng(1))
            if action is not None:
                assert action.kind is not ActionKind.VETO


class TestBreachResponse:
    def test_superior_strength_against_a_breacher_produces_a_war_declaration(self) -> None:
        view = _view(
            scalars={"M": 10.0},
            others={"rival": _other("rival", m=5.0)},
            breaches=("rival",),
        )
        action = respond_to_breach(view)
        assert action is not None
        assert action.kind is ActionKind.DECLARE_WAR
        assert action.payload["target"] == "rival"

    def test_no_breach_no_response(self) -> None:
        view = _view(scalars={"M": 10.0}, others={"rival": _other("rival", m=5.0)}, breaches=())
        assert respond_to_breach(view) is None

    def test_inferior_strength_does_not_respond(self) -> None:
        view = _view(scalars={"M": 1.0}, others={"rival": _other("rival", m=10.0)}, breaches=("rival",))
        assert respond_to_breach(view) is None


class TestNullSovereign:
    def test_enqueues_nothing(self) -> None:
        view = _view()
        assert NullSovereign().decide(view, make_rng(1)) == []


# --- wars, raids, peace and pacts (A76) --------------------------------------------


def _rival(id_: str, m: float, **kw: object) -> OtherNation:
    from dataclasses import replace

    return replace(_other(id_, m=m), **kw)  # type: ignore[arg-type]


def _frontier(owner: str) -> dict[str, object]:
    from stock.ai.view import LocationSummary

    loc = LocationSummary(
        id="x",
        nation=owner,
        game_yield=1.0,
        grazing=False,
        depletion=0.0,
        arable=True,
        is_town=False,
        fields=1.0,
    )
    return {"neighbour_locations": {"x": loc}}


def _landed_view(**kw: object) -> NationView:
    from dataclasses import replace

    base = _view(scalars={"M": 100.0}, interests={"LANDED": 10.0}, dominant="LANDED")
    return replace(base, curves={"produce_per_head": 1.2}, **kw)  # type: ignore[arg-type]


class TestWarsRaidsAndPeace:
    def test_a_landed_host_conquers_across_a_frontier_only(self) -> None:
        from stock.ai.scripts import LANDED_SCRIPT

        rule = next(c for name, c, _ in LANDED_SCRIPT if name == "declare_war_on_land_hunger")
        weak = {"weak": _rival("weak", m=20.0)}
        assert not rule(_landed_view(doctrine="FEUDAL_HOST", others=weak))  # no shared frontier
        assert rule(_landed_view(doctrine="FEUDAL_HOST", others=weak, **_frontier("weak")))
        # a nation whose army is its food producers does not go to war for land...
        assert not rule(_landed_view(doctrine="NATION_IN_ARMS", others=weak, **_frontier("weak")))
        # ...nor does one already at war, or one that cannot feed itself
        at_war = {"weak": _rival("weak", m=20.0, at_war=True)}
        assert not rule(_landed_view(doctrine="FEUDAL_HOST", others=at_war, **_frontier("weak")))

    def test_a_herding_nation_raids_a_weaker_neighbour_instead(self) -> None:
        from stock.ai.scripts import LANDED_SCRIPT

        name, rule, factory = next(r for r in LANDED_SCRIPT if r[0] == "raid_weak_neighbour")
        weak = {"weak": _rival("weak", m=20.0)}
        view = _landed_view(doctrine="NATION_IN_ARMS", others=weak, year=10, **_frontier("weak"))
        assert rule(view)
        action = factory(view, make_rng(1))
        assert action is not None and action.kind is ActionKind.DECLARE_RAID
        assert action.payload["location"] == "x"
        assert not rule(_landed_view(doctrine="FEUDAL_HOST", others=weak, year=10, **_frontier("weak")))

    def test_an_attacker_offers_peace_and_a_defender_accepts(self) -> None:
        from stock.ai.scripts import PEACE_AFTER_YEARS, make_peace

        years = PEACE_AFTER_YEARS
        long_war = {"o": _rival("o", m=50.0, at_war=True, we_attacked=True, war_years=years)}
        action = make_peace(_landed_view(doctrine="FEUDAL_HOST", others=long_war))
        assert action is not None and action.kind is ActionKind.OFFER_PEACE
        assert action.payload["target"] == "o"
        young_war = {"o": _rival("o", m=50.0, at_war=True, we_attacked=True, war_years=1)}
        assert make_peace(_landed_view(doctrine="FEUDAL_HOST", others=young_war)) is None
        # a nation in arms cannot afford a second year without output
        assert make_peace(_landed_view(doctrine="NATION_IN_ARMS", others=young_war)) is not None
        # losing: offer peace at once
        losing = {"o": _rival("o", m=300.0, at_war=True, we_attacked=True, war_years=1)}
        assert make_peace(_landed_view(doctrine="FEUDAL_HOST", others=losing)) is not None
        # the defender accepts an offer unless it is clearly winning
        offered = {"o": _rival("o", m=100.0, at_war=True, peace_offered_to_us=True)}
        accept = make_peace(_landed_view(others=offered))
        assert accept is not None and accept.kind is ActionKind.ACCEPT_PEACE
        winning = {"o": _rival("o", m=10.0, at_war=True, peace_offered_to_us=True)}
        assert make_peace(_landed_view(others=winning)) is None

    def test_non_aggression_is_sought_when_outmatched_and_accepted_when_harmless(self) -> None:
        from stock.ai.scripts import LANDED_SCRIPT, answer_proposals

        name, rule, factory = next(r for r in LANDED_SCRIPT if r[0] == "seek_non_aggression_when_outmatched")
        strong = {"s": _rival("s", m=400.0)}
        view = _landed_view(others=strong, **_frontier("s"))
        assert rule(view)
        action = factory(view, make_rng(1))
        assert action is not None and action.kind is ActionKind.PROPOSE_TREATY
        assert action.payload["target"] == "s"
        assert {t.bound for t in action.payload["terms"]} == {"s", "n"}
        pending = {"s": _rival("s", m=400.0, our_proposal_pending=True)}
        assert not rule(_landed_view(others=pending, **_frontier("s")))
        bound = {"s": _rival("s", m=400.0, treaties_with_us=("t1",))}
        assert not rule(_landed_view(others=bound, **_frontier("s")))

        proposal = {"p": _rival("p", m=100.0, proposal_to_us=("NON_AGGRESSION",))}
        accept = answer_proposals(_landed_view(others=proposal))
        assert accept is not None and accept.kind is ActionKind.ACCEPT_TREATY
        assert accept.payload["initiator"] == "p"
        already = {"p": _rival("p", m=100.0, proposal_to_us=("NON_AGGRESSION",), treaties_with_us=("t1",))}
        assert answer_proposals(_landed_view(others=already)) is None

    def test_a_rule_that_cannot_pass_its_bar_does_not_use_up_the_year(self) -> None:
        # decide() proposes everything that holds; the year loop keeps the first
        # `max_actions_per_year` that validate (an unaffordable enact used to burn a slot).
        from stock.ai.scripts import LANDED_SCRIPT

        sovereign = ScriptedSovereign(scripts={Mode.LANDED: LANDED_SCRIPT}, max_actions=None)
        weak = {"weak": _rival("weak", m=20.0)}
        scalars = {"M": 100.0, "R_private": 0.0}
        view = _landed_view(doctrine="FEUDAL_HOST", others=weak, scalars=scalars, **_frontier("weak"))
        kinds = [a.kind for a in sovereign.decide(view, make_rng(1))]
        assert ActionKind.DECLARE_WAR in kinds and len(kinds) > 2
