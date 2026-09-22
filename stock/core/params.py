"""Simulation parameters (DD §15, and every named constant in MM).

One frozen, nested dataclass tree, grouped by the section of DD/MM it serves.
`SYMBOL_MAP` documents symbol -> field path for every constant so a test can check
MM's symbol list is fully covered and every field traces back to a symbol (Doc 01
invariant: "Params has no field unused by MM and MM no symbol missing from Params").

Several MM symbols are reused across sections for unrelated quantities (sigma is both
the CES substitution sharpness in §10 and part of the sovereign risk premium in §18;
rho is depletion regen in §4, strike decay in §8, and the credit risk premium in §18;
a/b name both the security-scale constants in §14 and the A_S weight vectors a1-a6/
b1-b4 in §12; p is both the PSV event weight in §14 and a record's savings propensity
in §11). Field names below are disambiguated; the mapping to the source symbol is in
each field's comment and in SYMBOL_MAP.
"""

from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from stock.core.goods import Good


class ParamsError(ValueError):
    """Raised for malformed or unknown parameter data."""


@dataclass(frozen=True)
class AuthorityParams:
    """Authority and Interests (DD §2.5; MM §3)."""

    kappa_s: float = 0.5  # kappa_s: authority exponent on size
    kappa_w: float = 1.0  # kappa_w: authority exponent on wealth
    d_dep: float = 0.5  # d_dep: authority per dependent
    ell_0: float = 0.0  # ell_0: labour legibility start
    j_gain: float = 0.02  # j: legibility gain per unit (J * converted disorder)
    delta_ell: float = 0.01  # delta_ell: legibility decay


@dataclass(frozen=True)
class PopulationParams:
    """Population (DD §2.3; MM §1)."""

    beta: float = 0.02  # beta: population response to subsistence satisfaction, /yr
    mortality_m: float = 0.5  # m: hunger mortality coefficient (MM §1)
    #: hard ceiling on the growth term `beta*(A_subs-1)`, /yr — a well-fed class can
    #: never grow faster than this whatever its surplus (design choice, not MM).
    max_growth: float = 0.10
    #: One person is the smallest unit that works a job: a record below this size is
    #: folded into its vertical-down neighbour (people and wealth) by
    #: `reap_extinct_records`, and mobility never moves less than this or leaves
    #: less than this behind (`core.records.quantise_move`). Was 0.5 and wealth-gated,
    #: which let 1e-8-person records keep working producers for centuries.
    extinct_size_epsilon: float = 1.0
    herd_custody_share: float = 0.5  # share of recipient moved to HERDSMEN (placeholder)


@dataclass(frozen=True)
class MobilityParams:
    """Mobility (DD §2.4; MM §2)."""

    rate_edge_base: float = 0.3  # rate_edge: base horizontal mobility rate
    rate_v_base: float = 0.1  # rate_v: base vertical mobility rate
    #: wealth/head (baskets) above which a law-free vertical promotion can fire (DD
    #: §2.4); MM gives no number for the threshold itself, only the flow rate once it
    #: holds — tuned placeholder, see DEVIATIONS.md.
    vertical_promotion_threshold: float = 5.0
    #: share of a qualifying record's size/wealth/debt that crosses the frontier
    #: edge into unowned ground each year; placeholder (Doc 08 tunes); DEVIATIONS A28.
    rate_frontier: float = 0.1
    #: an unowned neighbour's ground_quality must beat home's by this fraction to
    #: pull the occupation edge; placeholder (Doc 08 tunes); DEVIATIONS A28.
    frontier_margin: float = 0.25
    #: home depletion (game or grazing) above this triggers the occupation edge's
    #: "home is pressed" gate; placeholder (Doc 08 tunes); DEVIATIONS A28.
    frontier_pressure: float = 0.5
    #: fields per cultivating head at home below this triggers the cultivation
    #: edge's "home is pressed" gate; placeholder (Doc 08 tunes); DEVIATIONS A28.
    frontier_land_per_head: float = 0.5


@dataclass(frozen=True)
class ProductionParams:
    """Production functions (DD §4.2; MM §4)."""

    eta: float = 0.7  # eta: labour elasticity (Field, Manufactory jobs term)
    zeta: float = 0.3  # zeta: stock elasticity (Manufactory)
    gamma_herd: float = 0.08  # gamma: herd breeding rate
    head_per_herdsman: float = 40.0  # h: head of herd per herdsman
    delta_dep: float = 0.05  # delta_dep: depletion rate under use (hunting ground)
    rho_dep: float = 0.1  # rho_dep: depletion regeneration rate when idle
    kappa_prov: float = 0.3  # kappa_prov: Provisions per unit Herd
    kappa_mat: float = 0.15  # kappa_mat: Materials per unit Herd
    q_workshop: float = 1.0  # q_c: workshop productivity coefficient
    q_manufactory: float = 1.0  # q_m: manufactory productivity coefficient
    q_mine: float = 1.0  # q_x: mine productivity coefficient
    stock_per_job: float = 2.0  # stock_per_job: building jobs = stock / this
    jobs_per_share: float = 1.0  # jobs_per_share: field jobs per land share
    tau_turn: float = 0.08  # tau_turn: share of stock freed for placement each year
    land_share_value: float = 5.0  # placeholder valuation of a land share in baskets (DD tuning, Doc 08)
    r_bar_floor: float = 0.02  # floor on average rate of profit (MM §5 bootstrap fix; placeholder)


@dataclass(frozen=True)
class PriceParams:
    """Prices and the extent of the market (DD §4.5, §4.7; MM §7, §9)."""

    eps: dict[Good, float] = field(
        default_factory=lambda: {
            Good.PROVISIONS: 0.5,
            Good.MATERIALS: 0.8,
            Good.WARES: 1.0,
            Good.LUXURIES: 1.5,
            Good.ARMS: 1.0,
            Good.SHIPS: 1.0,
            Good.ATTENDANCE: 1.5,  # not specified in DD §15; matches Luxuries as the
            # other standing-tier good (see DEVIATIONS.md).
        }
    )  # eps_g: price elasticity per good class
    base_price: dict[Good, float] = field(
        default_factory=lambda: {g: 1.0 for g in Good}
    )  # base_g: base price per good class, in baskets
    inventory_decay: float = 0.1  # decay: unsold inventory carry decay
    c_max: float = 5.0  # c_max: carriage-cost cutoff for extent of market
    dol_scale: float = 50.0  # scale of market_size at which DoL(market_size) ~ 0.5
    ratio_floor: float = 0.05  # bounds on D/S before the exponent (numerical stability, not MM)
    ratio_cap: float = 20.0  # bounds on D/S before the exponent (numerical stability, not MM)


@dataclass(frozen=True)
class BandParams:
    """The opening band loop (DD §3). MM gives no numbers for these — the whole
    section is designer-only/emergent in DD; tuned placeholders, see DEVIATIONS.md."""

    contact_gain_rate: float = 0.08  # contact/yr at a grazing location, per `contact_reference_size` people
    #: Contact scales with the band's size: a band of this many people gains
    #: `contact_gain_rate`/yr; twice as many, twice as fast (more hands following the
    #: herds). 0 disables the scaling (flat rate).
    contact_reference_size: float = 100.0
    #: A band this large on grazing ground tames herds outright, contact or no
    #: contact — population pressure is its own gate (no authority needed). 0 disables.
    #: (above the 200-240 a band starts with, so the opening is not over on turn one — A78;
    #: a band that size reaches the contact threshold in about six years anyway)
    tame_pop_threshold: float = 320.0
    move_depletion_threshold: float = 0.6  # move when worked ground depletes past this
    settle_depletion_threshold: float = 0.6  # an unsteered band settles arable ground once this depleted
    settle_pressed_years: int = 5  # ...or once the hunt has fallen short this many years running
    move_consensus_share: float = 0.2  # a move costs this share of C0 in consensus (DD §3)
    tame_conversion_share: float = 0.3  # share of hunters becoming herd-owners/herdsmen
    settle_conversion_share: float = 0.5  # share of the band settling as tenants
    initial_herd_per_owner: float = 160.0  # total herd seeded at taming (placeholder)


@dataclass(frozen=True)
class WageParams:
    """Wage bargaining (DD §4.6; MM §8)."""

    strike_decay_rho_h: float = 0.3  # rho_h: strike years decay


@dataclass(frozen=True)
class ConsumptionParams:
    """Consumption, standing, hoards (DD §5; MM §10-11)."""

    sigma_substitution: float = 2.0  # sigma: CES substitution sharpness within a tier
    s_att: float = 1.0  # s_att: standing per basket of Attendance
    s_lux: float = 1.0  # s_lux: standing per basket of Luxuries, before vanity
    vanity_min: float = 0.6  # v_min
    vanity_max: float = 1.6  # v_max
    vanity_scale_v0: float = 100.0  # v_0: luxuries-reachable scale in the vanity curve
    dismissal_threshold: float = 0.5  # threshold (share) below which retainers dismiss
    hoard_reentry_omega: float = 0.2  # omega: hoard re-entry rate
    propensity_profit_weight: float = 0.5  # p_prof: propensity response to r_bar
    #: cap on subsistence satisfaction (numerical stability, not MM). With
    #: `population.beta = 0.02` a cap of 6 lets the growth term reach
    #: `population.max_growth` (10%/yr) before that clamp binds.
    a_subs_cap: float = 6.0
    comfort_target_multiplier: float = 0.5  # comfort tier target as multiple of subsistence target


@dataclass(frozen=True)
class SecurityParams:
    """Perceived security (DD §9.1; MM §14)."""

    security_scale_a: float = 1.0  # a: PSV scale on ln(1+M)
    wartime_basket_multiplier: float = 1.5  # placeholder (Doc 08 tunes): army basket x while at_war (Doc 04)
    psv_lag_lambda: float = 0.7  # lambda: PSV stickiness
    psv_event_weight_p: float = 0.3  # p: PSV weight on O
    threat_scale_b: float = 1.0  # b: PTV_ext scale on ln(1+M_i)
    distance_decay_d0: float = 3.0  # d_0: distance decay in g(d) = 1/(1+d/d_0)
    internal_threat_c_r: dict[str, float] = field(
        default_factory=lambda: {
            "MERCHANTS": 1.2,
            "CAPITALISTS": 1.2,
            "CRAFTSMEN": 0.6,
            "LABOURERS": 0.3,
            "LANDLORDS": 0.0,
        }
    )  # c_r: internal-threat weight on ln(1+R_private), by class; default 0 elsewhere
    disorder_weight_u: float = 0.8  # u: internal-threat weight on ln(1+U_dis)
    sigmoid_slope_kappa_f: float = 1.0  # kappa_f: investment sigmoid slope
    sigmoid_centre_n0: float = 0.0  # N_0: investment sigmoid centre
    # Doc 04 (security/military.py) — placeholders, not in SYMBOL_MAP
    levy_share: float = 0.2  # placeholder: share of serfs mobilised as levy
    militia_share: float = 0.3  # placeholder: share of tenants/craftsmen as militia
    arms_per_unit_weight: float = 1.0  # placeholder: arms per unit M
    doctrine_multiplier: dict[str, float] = field(
        default_factory=lambda: {
            "EVERY_MAN": 0.5,
            "NATION_IN_ARMS": 1.2,
            "FEUDAL_HOST": 1.0,
            "MILITIA": 1.0,
            "STANDING_ARMY": 0.8,
        }
    )  # placeholder: doctrine combat multipliers
    firearms_multiplier: float = 2.0  # placeholder: multiplier for STANDING_ARMY with FIREARMS
    arms_share: float = 0.1  # placeholder: Arms share of standing army basket
    wares_share: float = 0.2  # placeholder: Wares share of standing army basket


@dataclass(frozen=True)
class WarParams:
    """War, sieges, conquest (DD §9.3; MM §15)."""

    k_siege: float = 2.0  # k_siege: consecutive losing years before a location falls
    n_conq: float = -1.5  # N_conq: target security threshold for attempted conquest
    m_conq: float = 1.5  # m_conq: attacker strength multiplier required to attempt
    # Raid and war parameters (Doc 04, placeholders not in SYMBOL_MAP)
    raid_share: float = 0.2  # placeholder: share of stealable goods taken per raid
    casualty_rate: float = 0.02  # placeholder: casualty rate per year of war
    fort_bonus: float = 0.5  # placeholder: fortification bonus for towns
    attack_projection_d0: float = 3.0  # placeholder: carriage distance decay for attacker projection
    # Action costs
    cost_raid: float = 0.5  # placeholder: A_S cost for DECLARE_RAID
    cost_war: float = 1.0  # placeholder: A_S cost for DECLARE_WAR
    cost_siege: float = 0.3  # placeholder: A_S cost for BESIEGE
    cost_peace: float = 0.3  # placeholder: A_S cost for OFFER_PEACE/ACCEPT_PEACE
    cost_repress: float = 0.5  # placeholder: A_S cost for REPRESS


@dataclass(frozen=True)
class TradeParams:
    """Trade, routes, hostility (DD §10; MM §16-17)."""

    k_cap: float = 1.0  # k_cap: route capacity per unit merchant stock
    merchant_commit_share: float = 0.5  # share of (hoard + stock_in_place) committed per route
    navigation_friction: float = 0.3  # placeholder: friction from NAVIGATION_ACT
    tariff_rate: float = 0.2  # placeholder: tariff wedge as share of import price
    barter_capacity: float = 5.0  # placeholder: barter route capacity multiplier
    barter_hostility_max: float = 0.5  # placeholder: max hostility for band barter
    carriage_price_per_unit: float = 0.01  # baskets of carriage per unit of good per unit carriage distance
    # Doc 04 (trade/hostility.py) — placeholders, not in SYMBOL_MAP
    h_war: float = 0.2  # placeholder: hostility increment per war
    h_route_competition: float = 0.05  # placeholder: hostility per route competition
    h_capture: float = 0.15  # placeholder: hostility per route capture
    h_breach: float = 0.25  # placeholder: hostility per treaty breach
    h_trade_volume_rate: float = 0.001  # placeholder: hostility decrement per basket of trade volume
    h_treaty_kept: float = 0.02  # placeholder: hostility decrement per kept treaty
    h_tribute: float = 0.03  # placeholder: hostility decrement per tribute flow
    # Doc 04 (trade/treaties.py) — placeholders
    cost_treaty: float = 0.5  # placeholder: A_S cost for PROPOSE_TREATY action
    treaty_route_bonus: float = 0.25  # placeholder: treaty_factor bonus for access terms
    treaty_ptv_reduction: float = 0.3  # placeholder: PTV_ext reduction for treaty partners
    k_penalty: int = 5  # placeholder: years of breach penalty
    phi_breach: float = 0.3  # placeholder: route treaty_factor multiplier under penalty
    dearth_price_multiple: float = 1.5  # placeholder: price threshold for grain guarantee breach
    renegotiate_h_delta: float = 0.3  # placeholder: hostility delta to trigger renegotiation
    renegotiate_m_ratio: float = 2.0  # placeholder: M ratio change to trigger renegotiation
    null_accept_margin: float = 0.0  # placeholder: margin for null sovereign to accept treaties


@dataclass(frozen=True)
class CreditParams:
    """Credit and debt (DD §11; MM §18)."""

    lender_share_s: float = 0.5  # s: lender's share of r_bar in r_market
    risk_premium_base: float = 0.05  # rho(): base component of the credit risk premium
    risk_premium_security_weight: float = 0.1  # rho(): weight on max(0, -N_bar)
    risk_premium_justice_weight: float = 0.1  # rho(): weight on (1 - J)
    sovereign_premium_base: float = 0.02  # sigma(): base sovereign premium
    sovereign_premium_debt_weight: float = 0.1  # sigma(): weight on D/revenue
    sovereign_premium_default_weight: float = 0.2  # sigma(): weight on default_history
    tau_d: float = 0.4  # tau_d: service/revenue ratio that forces a debt choice
    # Doc 04 (trade/treaties.py) — placeholders for treaty effects on sigma
    sigma_breach_penalty: float = 0.05  # placeholder: σ increment while under breach penalty
    sigma_treaty_bonus: float = 0.02  # placeholder: σ decrement per kept treaty (capped at -0.1)
    # Doc 05 (finance/credit.py)
    debt_ratio_cap: float = 5.0  # placeholder: ceiling on D/revenue fed into sigma()
    usury_cap_default: float = 0.1  # rate assumed for USURY_CAP when no rate is set
    #: MM §18's f_s (private lenders' willingness) has no specified functional form —
    #: smallest monotone choice: linear in the rate gap, clamped to [0,1] (DEVIATIONS A25-style)
    f_s_base: float = 0.3
    f_s_slope: float = 2.0
    demand_k: float = 2.0  # placeholder: slope of project credit demand on the return gap
    demand_cap_share: float = 0.3  # placeholder: ceiling on a project's demand as a share of its stock
    default_closure_years: int = 10  # k: years Public Credit stays closed after a default
    cost_debt_change: float = 0.1  # A_S cost for SET_DEBT_POLICY and SET_FUNDING_MODE actions


@dataclass(frozen=True)
class PoliticsParams:
    """Laws, State authority, justice (DD §7; MM §12-13)."""

    theta: float = 1.0  # theta: passing bar
    theta_prime: float = 1.5  # theta': self-enactment bar
    #: Customary law (DD §6.3's first property nodes): these enact themselves at no
    #: authority cost once the nation's population reaches the threshold — nobody
    #: legislates "the kill belongs to the killer", it's just what everyone does.
    #: See `politics.legislation.enact_by_custom`. A threshold < 0 disables that law's
    #: customary path.
    custom_kill_to_killer_pop: float = 0.0  # from the first year
    custom_shared_by_custom_pop: float = 60.0
    custom_herds_heritable_pop: float = 120.0  # once herds exist (seat past BAND)
    #: Population at which the Protection of Property handover fires regardless of
    #: Landed authority (`state.protection_of_property_condition`'s other trigger).
    custom_protection_of_property_pop: float = 400.0
    radicalism_weight_w_r: float = 0.5  # w_r: radicalism weight in bars
    k_veto: int = 5  # k_veto: veto cooldown, years
    a_s_decay: float = 0.05  # delta: A_S decay
    a1: float = 0.2  # a1: A_S weight on (M_state/M) ln(1+M)
    a2: float = 0.2  # a2: A_S weight on J
    a3: float = 0.15  # a3: A_S weight on sum(law weight * enforcement)
    a4: float = 0.15  # a4: A_S weight on direct/revenue
    a5: float = 0.1  # a5: A_S weight on max(0, O)
    a6: float = 0.1  # a6: A_S weight on ln(1+court)
    b1: float = 0.2  # b1: A_S penalty weight on max(0, -O)
    b2: float = 0.15  # b2: A_S penalty weight on ln(1+R_private)
    b3: float = 0.15  # b3: A_S penalty weight on ln(1+U_dis)
    b4: float = 0.1  # b4: A_S penalty weight on farmed_share
    consensus_c0: float = 1.0  # C_0: band consensus refill level
    justice_floor_mobile: float = 0.3  # J_cust: band/herds
    justice_floor_settled: float = 0.4  # J_cust: fields
    enforcement_floor_enf_min: float = 0.1  # enf_min: below this, a law risks lapsing
    k_lapse: int = 5  # k_lapse: years under enf_min before a law lapses
    #: radicalism decay when an Interest's demand is met (MM §3's "decay*1[demands
    #: met]"); MM names the term but not the constant — tuned placeholder, see
    #: DEVIATIONS.md (Doc 03).
    radicalism_decay: float = 0.1
    #: veto cost premium (DD §7.2 "the gap at a premium"; MM §13's `premium`, unnamed
    #: numerically) — tuned placeholder, see DEVIATIONS.md (Doc 03).
    veto_premium: float = 1.5
    #: floor under `enf_law` (MM §13's "∈(0,1)" is violated at the literal formula's
    #: A_S=0 edge; DD §7.5 says enforcement "is never zero") — see DEVIATIONS.md.
    enforcement_epsilon: float = 1e-3
    #: Focus upkeep cost in A_S per year (DD §7.2 "Focus: upkeep"), MM doesn't name a
    #: constant — tuned placeholder, see DEVIATIONS.md (Doc 03).
    focus_upkeep: float = 0.1
    #: proportionality constant in `justice_need ∝ population*(1+town share)` (MM
    #: §12) — MM gives no number, tuned placeholder, see DEVIATIONS.md (Doc 03).
    justice_need_per_head: float = 0.05
    #: Focus gate-reduction rate per unit `works_draw` (DD §6.4); no MM constant —
    #: tuned placeholder, see DEVIATIONS.md (Doc 03).
    focus_gate_rate: float = 0.05
    focus_gate_rate_education: float = 0.03


@dataclass(frozen=True)
class UnrestParams:
    """Expected needs and unrest (DD §8; MM §20)."""

    alpha_up: float = 0.3  # alpha_up
    alpha_down: float = 0.1  # alpha_down
    alpha_collapse: float = 0.8  # alpha_collapse: replaces alpha_down during regression
    w_tier_subsistence: float = 8.0  # w_tier: subsistence
    w_tier_comfort: float = 2.0  # w_tier: comfort
    w_tier_standing: float = 0.5  # w_tier: standing
    a_split: float = 1.0  # a_split: authority/size threshold, disorder vs. demand
    u1: float = 0.2  # u1: strike threshold on U_r/size_r
    u2: float = 0.5  # u2: riot / desertion threshold
    u3: float = 1.0  # u3: revolt / mutiny threshold
    #: placeholder (Doc 08): a record smaller than this share of the nation's people
    #: fires no strike/riot/revolt event (its unrest still counts in U_dis)
    event_min_share: float = 0.02


@dataclass(frozen=True)
class RegressionParams:
    """Regression (DD §13; MM §21)."""

    n_crit: float = -2.0  # N_crit
    u_crit: float = 5.0  # U_crit
    k_spiral: int = 4  # k_spiral
    kappa_loss: float = 0.3  # kappa_loss: capital-loss share of stock trigger
    kappa_def: float = 0.5  # kappa_def: default share trigger
    k_food: int = 3  # k_food: years a Provisions route may stay broken
    reinvest_zero_epsilon: float = 0.5  # placeholder: "to_reinvest ~= 0" tolerance for spiral_window
    #: placeholder (Doc 08): years after a regression during which neither trigger fires again
    cooldown_years: int = 10
    #: placeholder: stock fraction lost when a method falls out of the carrying configuration
    collapse_stock_loss: float = 0.3


@dataclass(frozen=True)
class EventParams:
    """Exogenous events (DD §13; Doc 05 `meta/events.py`) — six probability rolls per
    year, never generated from the simulation's own state. All placeholders pending
    Doc 08 tuning."""

    plague_prob: float = 0.01  # per location per year
    plague_shrink: float = 0.2  # fraction of size lost
    harvest_failure_prob: float = 0.02  # per arable location per year
    harvest_failure_loss: float = 0.3  # fraction of FIELD stock_in_place lost
    watt_prob: float = 0.005  # per nation per year, once MACHINE_PRODUCTION is lit
    trade_fair_prob: float = 0.01  # per non-town location per year
    trade_fair_merchants_added: float = 5.0  # MERCHANTS size added
    ore_find_prob: float = 0.005  # per location without ore per year
    ore_find_yield: float = 0.1
    coal_find_prob: float = 0.005  # per location without coal per year
    coal_find_yield: float = 0.1
    wild_herds_prob: float = 0.01  # per location per year
    wild_herds_game_yield: float = 0.1  # added to game_yield


@dataclass(frozen=True)
class AiParams:
    """Scripted sovereigns (Doc 06). Presets (cautious/normal/bold) are a Params
    override per nation in the scenario file, not code."""

    max_actions_per_year: int = 2
    aggression: float = 1.0  # scales war/raid thresholds
    patience: float = 1.0  # scales gap tolerances for self-enactment
    reserve: float = 0.2  # share of A_S never spent


@dataclass(frozen=True)
class ScoreboardParams:
    """Curves and hegemony (DD §14.1, §1.4; MM §22-23)."""

    wa_free: float = 0.3  # wa_free: freedom-index walk-away threshold
    h_share: float = 0.75  # H_share: hegemony share threshold
    h_years: int = 25  # H_years: hegemony countdown length
    #: placeholder (Doc 08): flags count only once this many living nations hold a
    #: seat beyond BAND (a band has no capital to share)
    h_min_settled: int = 2




@dataclass(frozen=True)
class TaxParams:
    """Taxation (DD §12; MM §19). Placeholders pending Doc 08 tuning."""

    default_rate: float = 0.1  # default rate when instrument enacted without explicit rate
    evasion_rate_slope: float = 0.1  # placeholder: slope of g_e on rate (MM §19)
    evasion_mobility_weight: float = 0.05  # placeholder: weight on base_mobility in g_e
    evasion_certainty_weight: float = 0.05  # placeholder: weight on certainty in g_e
    evasion_mobility_default: float = 0.5  # placeholder: base mobility fallback for an unlisted base
    collection_cost_per_instrument: float = 0.02  # placeholder: cost per active instrument
    collectors_per_instrument: float = 2.0  # placeholder: COLLECTORS record size per instrument
    chief_herd_share: float = 0.1  # placeholder: share of HERD_OWNERS' income (herd produce) to the seat
    feudal_dues_share: float = 0.1  # placeholder: share of serf in-kind income under SERFDOM
    farm_advance_share: float = 0.5  # placeholder: share of expected collection tax farmer advances
    farm_premium: float = 0.2  # placeholder: premium tax farmer collects as (1 + farm_premium)
    toll_base_share: float = 0.01  # placeholder: share of trade volume as tolls base under PUBLIC_WORKS
    profit_shift_share: float = 0.3  # placeholder: share of profit tax shifted to consumers
    customs_merchant_share: float = 0.5  # placeholder: share of customs borne by merchant
    cost_tax_change: float = 0.1  # A_S cost for SET_TAX_RATE and SET_BUDGET actions
    evasion_cap: float = 0.9  # placeholder (Doc 08 tuning): ceiling on g_e before enforcement (MM §19)
    collection_cost_cap: float = 0.5  # placeholder (Doc 08 tuning): ceiling on collection_cost share (MM §19)
    tithe_flat_share: float = 0.1  # placeholder: pre-State tithe flat draw, share of gross FIELD produce
    unfunded_tolerance: float = 0.05  # placeholder: share of need a draw may miss before a law is unfunded
    max_rate: float = 0.9  # placeholder: ceiling on any SET_TAX_RATE rate (DD §7.2 action legality)
    default_soldier_pay: float = 1.2  # baskets per soldier per year (DD §5.3)
    default_budget: dict[str, float] = field(
        default_factory=lambda: {
            "defence": 0.4,
            "justice": 0.1,
            "works": 0.2,
            "service": 0.1,
            "court": 0.1,
            "transfers": 0.1,
        }
    )  # default budget shares (sum = 1.0)


@dataclass(frozen=True)
class TreeParams:
    """The three trees' numeric gate thresholds (DD §6; Doc 05 `meta/trees.py`).
    MM names no constants for these — tuned placeholders pending Doc 08, sized for
    `scenarios/three_bands.yaml`'s ~200-240 person bands, see DEVIATIONS.md."""

    #: contact/yr needed before Domesticated Herds can light (DD §3's "following the
    #: herds"); mirrors the `1.0` literal band.py's `tame_herd` compares `contact`
    #: against — see Blockers (band.py:81 not in this task's file allowlist).
    contact_threshold: float = 1.0
    #: placeholder (Doc 08 tunes): Sigma FIELD land shares for Three-field rotation.
    rotation_land_threshold: float = 50.0
    #: placeholder (Doc 08 tunes): MERCHANTS stock (baskets) for Putting-out.
    putting_out_stock_threshold: float = 20.0
    #: placeholder (Doc 08 tunes): market_size(Wares) for Division of labour (MM §9).
    dol_market_size_threshold: float = 30.0
    #: placeholder (Doc 08 tunes): Sigma Wares output (last_Q) for Machine production.
    machine_wares_threshold: float = 20.0
    #: placeholder (Doc 08 tunes): Sigma producer stock (baskets) for Machine production.
    machine_capital_threshold: float = 100.0
    #: placeholder (Doc 08 tunes): arms_stock (baskets) for the Firearms defence node.
    firearms_arms_threshold: float = 10.0


@dataclass(frozen=True)
class Params:
    """Every DD §15 parameter and every named MM constant, grouped by section."""

    authority: AuthorityParams = field(default_factory=AuthorityParams)
    population: PopulationParams = field(default_factory=PopulationParams)
    mobility: MobilityParams = field(default_factory=MobilityParams)
    band: BandParams = field(default_factory=BandParams)
    production: ProductionParams = field(default_factory=ProductionParams)
    prices: PriceParams = field(default_factory=PriceParams)
    wages: WageParams = field(default_factory=WageParams)
    consumption: ConsumptionParams = field(default_factory=ConsumptionParams)
    security: SecurityParams = field(default_factory=SecurityParams)
    war: WarParams = field(default_factory=WarParams)
    trade: TradeParams = field(default_factory=TradeParams)
    credit: CreditParams = field(default_factory=CreditParams)
    tax: TaxParams = field(default_factory=TaxParams)
    tree: TreeParams = field(default_factory=TreeParams)
    politics: PoliticsParams = field(default_factory=PoliticsParams)
    unrest: UnrestParams = field(default_factory=UnrestParams)
    event: EventParams = field(default_factory=EventParams)
    regression: RegressionParams = field(default_factory=RegressionParams)
    ai: AiParams = field(default_factory=AiParams)
    scoreboard: ScoreboardParams = field(default_factory=ScoreboardParams)

    @staticmethod
    def default() -> "Params":
        return Params()

    @staticmethod
    def load(path: str | Path) -> "Params":
        """Load Params from YAML, overriding defaults. Unknown keys raise ParamsError."""

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return Params.from_dict(data)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Params":
        """Build Params from a plain dict of overrides (e.g. a scenario's inline
        `params_override`). Unknown keys raise ParamsError."""

        return _build(Params, data, trail="Params")


def _build[T](cls: type[T], data: dict[str, Any], trail: str) -> T:
    if not isinstance(data, dict):
        raise ParamsError(f"{trail}: expected a mapping, got {type(data).__name__}")
    known = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    unknown = set(data) - set(known)
    if unknown:
        raise ParamsError(f"{trail}: unknown key(s) {sorted(unknown)}")
    kwargs: dict[str, Any] = {}
    for name, f in known.items():
        if name not in data:
            continue
        value = data[name]
        if is_dataclass(f.type) and isinstance(f.type, type):
            kwargs[name] = _build(f.type, value, trail=f"{trail}.{name}")
        elif name == "eps" or name == "base_price":
            kwargs[name] = {_good_from_key(k): v for k, v in value.items()}
        else:
            kwargs[name] = value
    if not kwargs:
        return cls()
    return replace(cls(), **kwargs)  # type: ignore[type-var]


def _good_from_key(key: str) -> Good:
    try:
        return Good[key.upper()]
    except KeyError as exc:
        raise ParamsError(f"unknown good class {key!r}") from exc


#: symbol -> dotted field path, for every constant named in DD §15 / MM. Used by
#: tests/test_core.py to check MM's symbol list is fully covered.
SYMBOL_MAP: dict[str, str] = {
    "kappa_s": "authority.kappa_s",
    "kappa_w": "authority.kappa_w",
    "d_dep": "authority.d_dep",
    "ell_0": "authority.ell_0",
    "j": "authority.j_gain",
    "delta_ell": "authority.delta_ell",
    "beta": "population.beta",
    "m": "population.mortality_m",
    "rate_edge": "mobility.rate_edge_base",
    "rate_v": "mobility.rate_v_base",
    "eta": "production.eta",
    "zeta": "production.zeta",
    "gamma": "production.gamma_herd",
    "h": "production.head_per_herdsman",
    "delta_dep": "production.delta_dep",
    "rho_dep": "production.rho_dep",
    "kappa_prov": "production.kappa_prov",
    "kappa_mat": "production.kappa_mat",
    "q_c": "production.q_workshop",
    "q_m": "production.q_manufactory",
    "q_x": "production.q_mine",
    "stock_per_job": "production.stock_per_job",
    "jobs_per_share": "production.jobs_per_share",
    "tau_turn": "production.tau_turn",
    "eps_g": "prices.eps",
    "base_g": "prices.base_price",
    "decay": "prices.inventory_decay",
    "c_max": "prices.c_max",
    "rho_h": "wages.strike_decay_rho_h",
    "sigma_substitution": "consumption.sigma_substitution",
    "s_att": "consumption.s_att",
    "s_lux": "consumption.s_lux",
    "v_min": "consumption.vanity_min",
    "v_max": "consumption.vanity_max",
    "v_0": "consumption.vanity_scale_v0",
    "omega": "consumption.hoard_reentry_omega",
    "p_prof": "consumption.propensity_profit_weight",
    "a_security": "security.security_scale_a",
    "lambda": "security.psv_lag_lambda",
    "p_psv": "security.psv_event_weight_p",
    "b_threat": "security.threat_scale_b",
    "d0": "security.distance_decay_d0",
    "c_r": "security.internal_threat_c_r",
    "u_disorder_weight": "security.disorder_weight_u",
    "kappa_f": "security.sigmoid_slope_kappa_f",
    "n0": "security.sigmoid_centre_n0",
    "k_siege": "war.k_siege",
    "n_conq": "war.n_conq",
    "m_conq": "war.m_conq",
    "k_cap": "trade.k_cap",
    "s_lender": "credit.lender_share_s",
    "rho_risk_premium": "credit.risk_premium_base",
    "sigma_sovereign": "credit.sovereign_premium_base",
    "tau_d": "credit.tau_d",
    "theta": "politics.theta",
    "theta_prime": "politics.theta_prime",
    "w_r": "politics.radicalism_weight_w_r",
    "k_veto": "politics.k_veto",
    "delta_a_s": "politics.a_s_decay",
    "a1": "politics.a1",
    "a2": "politics.a2",
    "a3": "politics.a3",
    "a4": "politics.a4",
    "a5": "politics.a5",
    "a6": "politics.a6",
    "b1": "politics.b1",
    "b2": "politics.b2",
    "b3": "politics.b3",
    "b4": "politics.b4",
    "c0": "politics.consensus_c0",
    "j_cust_mobile": "politics.justice_floor_mobile",
    "j_cust_settled": "politics.justice_floor_settled",
    "enf_min": "politics.enforcement_floor_enf_min",
    "k_lapse": "politics.k_lapse",
    "alpha_up": "unrest.alpha_up",
    "alpha_down": "unrest.alpha_down",
    "alpha_collapse": "unrest.alpha_collapse",
    "w_tier": "unrest.w_tier_subsistence",
    "a_split": "unrest.a_split",
    "u1": "unrest.u1",
    "u2": "unrest.u2",
    "u3": "unrest.u3",
    "n_crit": "regression.n_crit",
    "u_crit": "regression.u_crit",
    "k_spiral": "regression.k_spiral",
    "kappa_loss": "regression.kappa_loss",
    "kappa_def": "regression.kappa_def",
    "k_food": "regression.k_food",
    "wa_free": "scoreboard.wa_free",
    "h_share": "scoreboard.h_share",
    "h_years": "scoreboard.h_years",
}


def resolve_symbol(params: Params, symbol: str) -> Any:
    """Look up a Params value by its MM/DD symbol name, via SYMBOL_MAP."""

    path = SYMBOL_MAP[symbol]
    obj: Any = params
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj
