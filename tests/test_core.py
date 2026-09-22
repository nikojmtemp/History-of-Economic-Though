"""Doc 01 acceptance tests (core data model)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from stock.core.actions import Action, ActionKind, validate
from stock.core.params import SYMBOL_MAP, Params, ParamsError, resolve_symbol
from stock.core.records import ClassId, DerivedSizeError, Record, set_size
from stock.core.world import World, WorldError
from stock.sim.scenario import ScenarioError, load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"
DEFAULT_PARAMS_YAML = REPO_ROOT / "params" / "default.yaml"


# --- scenario loading and validation ---------------------------------------------


def test_scenario_loads_and_validates() -> None:
    world = load_scenario(SCENARIO)
    world.validate()
    assert len(world.locations) == 24
    assert len(world.nations) == 3
    for nation in world.nations.values():
        assert nation.seat.name == "BAND"


def test_scenario_unknown_top_level_key_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("seed: 1\nnonsense: true\nlocations: []\nnations: []\n", encoding="utf-8")
    with pytest.raises(ScenarioError):
        load_scenario(bad)


def test_scenario_duplicate_location_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "seed: 1\n"
        "locations:\n"
        "  - id: a\n    terrain: PLAINS\n"
        "  - id: a\n    terrain: PLAINS\n"
        "nations: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError):
        load_scenario(bad)


# --- World.validate() invariants --------------------------------------------------


def test_validate_rejects_bad_location_owner_shares() -> None:
    world = load_scenario(SCENARIO)
    # No producers exist yet in the opening scenario; fabricate one with bad shares.
    from stock.core.producers import Producer, ProducerKind

    bad = Producer(kind=ProducerKind.FIELD, location="valley_1", owners_land={ClassId.LANDLORDS: 0.5})
    world.locations["valley_1"].producers.append(bad)
    with pytest.raises(WorldError):
        world.validate()


def test_validate_rejects_negative_wealth() -> None:
    world = load_scenario(SCENARIO)
    record = world.locations["valley_1"].records[0]
    record.wealth.hoard = -1.0
    with pytest.raises(WorldError):
        world.validate()


def test_hostility_must_be_symmetric() -> None:
    world = load_scenario(SCENARIO)
    world.hostility[("nation_valley", "nation_forest")] = 0.2
    world.hostility[("nation_forest", "nation_valley")] = 0.5
    with pytest.raises(WorldError):
        world.validate()

    world.hostility[("nation_forest", "nation_valley")] = 0.2
    world.validate()  # now symmetric, should not raise


def test_derived_size_classes_have_no_direct_writer() -> None:
    record = Record(cls=ClassId.RETAINERS, location="x", size=0.0)
    with pytest.raises(DerivedSizeError):
        set_size(record, 5.0)
    set_size(record, 5.0, allow_derived=True)
    assert record.size == 5.0

    labourer = Record(cls=ClassId.LABOURERS, location="x", size=0.0)
    set_size(labourer, 10.0)  # not derived, no exception
    assert labourer.size == 10.0


# --- JSON round-trip ---------------------------------------------------------------


def test_json_round_trip_is_lossless() -> None:
    world = load_scenario(SCENARIO)
    data = world.to_json()
    restored = World.from_json(data)
    assert restored.to_json() == data
    assert restored.year == world.year
    assert set(restored.nations) == set(world.nations)
    assert len(restored.locations) == len(world.locations)
    orig_record = world.locations["valley_1"].records[0]
    restored_record = restored.locations["valley_1"].records[0]
    assert restored_record.cls == orig_record.cls
    assert restored_record.size == orig_record.size


# --- Params ---------------------------------------------------------------------


def test_params_default_equals_default_yaml() -> None:
    assert Params.default() == Params.load(DEFAULT_PARAMS_YAML)


def test_params_unknown_key_raises() -> None:
    with pytest.raises(ParamsError):
        Params.from_dict({"not_a_real_field": 1.0})
    with pytest.raises(ParamsError):
        Params.from_dict({"authority": {"not_a_real_field": 1.0}})


def test_params_override_applies() -> None:
    p = Params.from_dict({"authority": {"kappa_s": 0.9}})
    assert p.authority.kappa_s == 0.9
    assert p.authority.kappa_w == Params.default().authority.kappa_w  # untouched


#: The full MM/DD §15 symbol list, kept independent of stock.core.params.SYMBOL_MAP so
#: this test catches drift rather than just checking self-consistency.
MM_SYMBOLS = {
    "kappa_s", "kappa_w", "d_dep", "ell_0", "j", "delta_ell", "beta", "m", "rate_edge",
    "rate_v", "eta", "zeta", "gamma", "h", "delta_dep", "rho_dep", "kappa_prov",
    "kappa_mat", "q_c", "q_m", "q_x", "stock_per_job", "jobs_per_share", "tau_turn",
    "eps_g", "base_g", "decay", "c_max", "rho_h", "sigma_substitution", "s_att",
    "s_lux", "v_min", "v_max", "v_0", "omega", "p_prof", "a_security", "lambda",
    "p_psv", "b_threat", "d0", "c_r", "u_disorder_weight", "kappa_f", "n0", "k_siege",
    "n_conq", "m_conq", "k_cap", "s_lender", "rho_risk_premium", "sigma_sovereign",
    "tau_d", "theta", "theta_prime", "w_r", "k_veto", "delta_a_s", "a1", "a2", "a3",
    "a4", "a5", "a6", "b1", "b2", "b3", "b4", "c0", "j_cust_mobile", "j_cust_settled",
    "enf_min", "k_lapse", "alpha_up", "alpha_down", "alpha_collapse", "w_tier",
    "a_split", "u1", "u2", "u3", "n_crit", "u_crit", "k_spiral", "kappa_loss",
    "kappa_def", "k_food", "wa_free", "h_share", "h_years",
}


def test_symbol_map_matches_mm_symbol_list() -> None:
    assert set(SYMBOL_MAP) == MM_SYMBOLS


def test_every_symbol_resolves() -> None:
    p = Params.default()
    for symbol in SYMBOL_MAP:
        resolve_symbol(p, symbol)  # raises AttributeError/KeyError if broken


# --- actions ------------------------------------------------------------------


def test_validate_rejects_enact_from_band() -> None:
    world = load_scenario(SCENARIO)
    action = Action(kind=ActionKind.ENACT, nation="nation_valley", payload={})
    result = validate(world, action)
    assert not result.ok
    assert "BAND" in (result.reason or "")


def test_validate_accepts_band_move_from_band() -> None:
    world = load_scenario(SCENARIO)
    action = Action(kind=ActionKind.BAND_MOVE, nation="nation_valley", payload={"to": "highland_1"})
    result = validate(world, action)
    assert result.ok


def test_validate_rejects_band_move_from_non_band() -> None:
    world = load_scenario(SCENARIO)
    from stock.core.world import SeatKind

    world.nations["nation_valley"].seat = SeatKind.STATE
    action = Action(kind=ActionKind.BAND_MOVE, nation="nation_valley", payload={})
    result = validate(world, action)
    assert not result.ok


def test_validate_unaffordable_sovereign_action_rejected() -> None:
    world = load_scenario(SCENARIO)
    from stock.core.actions import register_cost_fn
    from stock.core.world import SeatKind

    world.nations["nation_valley"].seat = SeatKind.STATE
    world.nations["nation_valley"].scalars.A_S = 1.0
    register_cost_fn(ActionKind.SET_BUDGET, lambda w, a: 100.0)
    action = Action(kind=ActionKind.SET_BUDGET, nation="nation_valley", payload={})
    result = validate(world, action)
    assert not result.ok
    assert result.numbers["cost"] == 100.0


# --- CLI ---------------------------------------------------------------------


def test_cli_run_years_zero_prints_summary_and_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "stock.sim", "run", str(SCENARIO), "--years", "0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "nation_valley" in result.stdout
    assert "Year 0" in result.stdout
