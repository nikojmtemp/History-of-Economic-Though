# 02 — Economy Engine (Sweep 1, task 2)

**Read**: 00, 01.
**Owns**: `stock/engine/*`.
**Depends on**: 01. Reads `Params`, `World`; writes records, producers, markets, ledger.

## Goal

Year steps 1 (production), 2 (wage bargaining), 4 (goods trade only — no cross-border routes yet), 5 (consumption), 7 (hoards and reinvestment), 8 (population and mobility), 9 (stock placement), plus the band's opening mechanics. After this task a world of bands can be run for hundreds of years with a null sovereign and will, on its own, tame herds, settle, and (if the scenario allows) reach workshops.

The year has 14 steps in total (assembled by task 05); this task implements the ones listed above. Steps not yet implemented (3 revenue/budget, 6 credit, 10 trees/Focus, 11 unrest, 12 politics, 13 military/events/regression, 14 queued actions) are later tasks' concern — treat their inputs as 0 or absent per the notes below.

## Deliverables — one function per formula

### `engine/production.py` — step 1
- `production_function(producer, location, records, params) -> Q`. One branch per `ProducerKind`:
  ```
  HUNTING      Q = y_game(loc) · H^η · dep(loc)                            H = hunters filled
  HERDING      ΔHerd = γ · Herd · min(1, herdsmen / (Herd / h))
               Q_prov = κ_prov · Herd ;  Q_mat = κ_mat · Herd
  FIELD        Q = y_arable(loc) · L^η · labour^η · (1 + rotation) · tools  L = land shares filled
  WORKSHOP     Q = q_c · craftsmen · tools · materials
  MANUFACTORY  Q = q_m · labourers · (stock / labourers)^ζ · DoL(market_size) · machinery · materials
  MINE         Q = q_x · labourers · resource(loc)
  jobs         = stock_in_place / stock_per_job   (buildings)   |   land_shares · jobs_per_share   (fields)
  ```
  `η` (labour elasticity) defaults 0.7, `ζ` (stock elasticity) 0.3, `γ` (herd breeding rate) 0.08, `h` (persons per herdsman) 40 — all `Params` fields, not literals. `dep(loc)` is `location.capacity.depletion` ∈ [0,1]: the fraction of carrying capacity currently available (1 = fresh ground, 0 = exhausted). `deplete_or_regenerate(location)` updates it after use: `dep' = dep − δ_dep·use + ρ_dep·(1 − dep)·idle`, where `use` is this year's harvest as a share of capacity and `idle` is 1 when nothing was taken. Occupations (HUNTING, HERDING) read the record's *current* location each year — they are not bound to one place. Materials/ore/coal/etc. input consumption for WORKSHOP/MANUFACTORY/MINE is pinned at a 1.0 multiplier (no real input-market clearing yet); Hunting, Herding, and Field run the formula in full.
- `split_rule(producer, V, w_by_class, r_bar_prev, params) -> Split(labour_income, profit, rent)`, applied in this order:
  ```
  V             = price × Q                                   (at last year's price)
  labour_income = filled jobs × w                              free labour: the clearing wage; dependent labour (RETAINERS/SERVANTS): the basket, in kind
  profit        = r_bar_prev × stock_in_place                  the normal return
  rent          = V − labour_income − profit                   residual, to owners_land            [producers with land]
  profit        = V − labour_income − site_rent                 [producers without land: the whole surplus is profit]
  ```
  Wages first, normal profit next, rent last — this ordering is what makes stock earning above `r̄` draw more stock in, while land absorbs the surplus instead.
- `pay_out(split, producer, records)` routes labour income to filled jobs by class, profit to `owners_stock`, rent to `owners_land`. Dependents (RETAINERS, SERVANTS) receive nothing here — they are paid in step 5's consumption, since a dependent record's size *is* its buyer's purchase.
- `average_rate_of_profit(nation) -> r_bar`: `r_bar = Σ profit / Σ stock_in_place` across the nation's producers; a herd's `ΔHerd` (its growth this year) counts as its profit for this sum, in place of its split-rule profit share from selling Provisions/Materials.
- Jobs: `jobs(producer)` per the formula above; filling by class from the location's records, free labour by wage attractiveness, dependents by binding.

### `engine/wages.py` — step 2
- `natural_wage(location_market, tax_on_basket) -> w_nat`: the price of the subsistence basket, including any tax on Provisions/Wares or on wages itself.
- `walk_away_labour(record, world) -> wa_L`, `patience_masters(producer_owners) -> patience_M`, `clearing_wage(...)`:
  ```
  surplus    = V / filled_jobs − w_nat
  π          = wa_L / (wa_L + patience_M)
  w          = w_nat + π · surplus · (1 − enforcement(CombinationAct))
  wa_L       = shares of income: open jobs on the record's edges + Poor Rate transfer + hoard/head
               + credit available + scarcity premium ; decays at ρ_h per year a strike runs
  patience_M = masters' stock_in_place / annual wage bill, plus a silent-combination modifier
  ```
  The wage is a bargain over the surplus above the natural wage; each side's share (`π` vs `1-π`) depends on labour's outside options (`wa_L`) against the masters' capacity to wait (`patience_M`). A tax folded into `w_nat` passes forward onto the employer only as far as `π` allows. Masters' combinations are silent — a ledger-only modifier on `patience_M`, never an event. Labourers' combinations fire an event and, under an enforced Combination Act, are put down at a disorder cost (handled in task 03). Combination Act enforcement is read from `nation.laws` (0 until task 03 exists; treat as unenforced).

### `engine/market.py` — step 4 (goods) and prices
- `market_price(base, demand, supply, eps) -> P`: `P = base · (demand/supply)^eps`, per good class per location market, with unsold output carried into next year's inventory and decaying: `inventory' = (inventory + unsold) · (1 − decay)`. `natural_price(good, producers) -> P_nat`: `w · labour_per_unit + r_bar · stock_per_unit + rent_per_unit`, at the average rates of that good's producers. One `Market` per location; a location with no producers or records for a good has no market for it — such a good keeps last year's price rather than clamping to any cap.
- `market_size(good, location, world) -> float`: BFS over the location graph, summing tier spending on `good` at every location reachable within carriage cost `distance / (river-or-road factor) ≤ c_max`, plus army demand for `good` (from task 04 when present, else 0) and route demand at capacity (from task 04 when present, else 0). `dol(market_size)`: an increasing, saturating function of `market_size` — division of labour scales with the size of the market it can sell into.
- Within-nation goods flow between locations: a simple internal route with capacity from carriage cost alone (cross-border routes are task 04's).

### `engine/consumption.py` — step 5
- `consume(record, market, params) -> Spend`. Tiers fill in order: **subsistence** (Provisions, a little Wares) → **comfort** (Wares) → **standing** (Luxuries and Attendance); the subsistence share falls as income rises. Within a tier, smooth substitution: `share_g ∝ weight_g · price_g^(−σ)` (CES, `σ` = substitution sharpness, default 2.0). The **standing** tier splits between Attendance and Luxuries by the same logit: Attendance yields `s_att` standing per basket spent; Luxuries yield `s_lux · vanity` standing per basket, where `vanity` rises with the volume of Luxuries reachable and saturates between `v_min` and `v_max`. **The dependent record's size equals its buyer's Attendance purchase in baskets** — this is the only place RETAINERS/SERVANTS size is set. When no Luxuries are reachable, gate the Luxuries CES weight to exactly 0 (not `vanity(0,...) = v_min`) so all standing spend is Attendance. Tag every unit spent productive (goods made by productive labour, counted into `market_size`) or unproductive (Attendance, soldiers, clergy, the court).
- `attendance_to_dependents(nation)`: sets RETAINERS (bought by landlords, herd-owners) and SERVANTS (bought by any other rich record) sizes from the Attendance purchases computed above in each location — the only writer of those sizes. Fires a `retainer_dismissal` event (numbers only) when a location's retainer size falls through `dismissal_threshold`; the displaced headcount routes to LABOURERS, since dependents own no wealth to carry with them.
- The State record's consumption is the court draw (input from task 05; 0 until then).

### `engine/capital.py` — steps 7 and 9
- `hoard_update(record, f_N, params)`, the one hoard rule:
  ```
  residual    = income − consumption
  saved       = p_class · residual
  to_reinvest = saved · f_N ;  to_hoard = saved · (1 − f_N)
  H'          = H + to_hoard − ω · f_N · H − deposits − bonds_from_hoard
  ```
  `deposits` and `bonds_from_hoard` are inputs supplied by task 05 (0 until then); `f_N` (the sigmoid investment multiplier on perceived security) is supplied by task 04 — pass `f_N = 1.0` (no insecurity) until then; tests for this task use that value.
- `propensity(record, r_bar, laws, standing_saturated) -> p`: the base propensity to save rises with `r_bar` for stock-holders, a charter raises the holder's and lowers others', and a saturated standing need raises `p` (newly available Luxuries lower it — landlords become worse capital sources exactly when Luxuries free their retainers).
- `placement(nation, world, params)`: free `τ_turn` (default 0.08) of every producer's `stock_in_place`; place that plus every record's `to_reinvest` into the single producer/method with the highest return per unit stock among what the laws allow and the locations can hold — base-return ordering is cultivation > domestic manufacture > foreign trade, reordered by charters, bounties, and tariffs via `LAW_TABLE.effects`. Creates a new producer when a location can hold one and none exists yet.

### `engine/population.py` — step 8a
- `population_update(record, params)`:
  ```
  size' = size · (1 + β · (A_subs − 1)) − m · size · max(0, 1 − A_subs)²  ± mobility flows
  ```
  `A_subs` = subsistence satisfaction relative to the basket; `β` (default 0.02/yr) is the population growth response; hunger mortality (`m` term) is convex in the shortfall. Dependent records (RETAINERS, SERVANTS) are excluded — their size comes only from the Attendance purchase in step 5.

### `engine/mobility.py` — step 8b
- `net_advantage(record, target_class, location)`: income per head plus non-monetary terms (agreeableness, learning cost, constancy, trust, chance of success).
- `flow(...)`, two kinds:
  ```
  horizontal (within a tier, faster): flow = size · rate_edge · (1 − friction_edge) · max(0, NA_target − NA_current)
  vertical (slow, wealth-gated):      flow = size · rate_v · 1[wealth/size > threshold]   (up)
                                       flow = size · rate_v · 1[wealth/size < basket]      (down)
  ```
  Vertical edges that need no law (implement here): herdsman → herd-owner, craftsman → capitalist, labourer → craftsman (all wealth-threshold promotions). Vertical edges gated by a law (serf → tenant via Commutation, serf/tenant → labourer via Enclosure, craftsman → labourer via a closing guild) are task 03's — this module exposes `vertical_flow` as a plain function task 03 calls once law state exists. Horizontal tiers and their edges: dependent labour (herdsman ⇄ serf ⇄ retainer ⇄ levy when mobilised — same records), free labour (labourer ⇄ servant ⇄ soldier ⇄ militia), independent (craftsman ⇄ tenant ⇄ small merchant), owners of stock (capitalist ⇄ merchant ⇄ improving landlord; wealth also shifts directly between stock, bonds, loans, and land). `edge_friction(from_cls, to_cls)` returns 0 in this task (no laws are enacted yet in this module's own scope); task 03 extends it once law state exists to read. Wealth and debt move pro rata with the moving share of `size`. Cross-location edges run the same tier to neighbouring locations with `friction = distance / (river-or-road factor)`; cross-border edges add hostility, `1 − f(N̄_dest)`, and treaty terms as inputs (0 until task 04 supplies them). Derived-size classes (RETAINERS, SERVANTS) never flow through this module.

### Band mechanics — in `engine/band.py`
Every run starts as a band of hunters: HUNTING and HERDING are occupations, attached to a mobile record, no fixed asset, yielding from wherever the record currently stands. Since Doc 06's scripted AI doesn't exist yet, `step_band(nation)` runs simple survival heuristics automatically for any BAND-seat nation (move if depleted, follow herds, tame once contact crosses a threshold, settle when arable), in addition to exposing each mechanic below as a plain function a real sovereign can call instead:
- `band_move`: staying depletes the ground (see `deplete_or_regenerate` above); moving costs a year's yield and *consensus* (the band's stand-in for `A_S`, refilling to `C₀` at the start of each band year — write it to `nation.scalars.state_authority`; task 03's politics module takes over once the nation reaches `seat == CHIEF`). Two bands sharing one location may fight over it.
- `band_follow_herds`: grazing locations carry wild herds; following accumulates a *contact* counter, the gate on the `DOMESTICATED_HERDS` Tree I node.
- `tame_herd`: once contact crosses its threshold, herds become property — this fires directly on the resource/contact gate (not through any law-enactment machinery, since none exists yet for a band). It creates owner and herdsman records; the largest owner's record holds the seat and its authority becomes the nation's `state_authority` (task 03 wires the full handover once `record_authority` exists — until then, use the herd-owner's `size`-and-wealth-based proxy this task can compute). Tamed herds are mobile stock that graze wherever the owning record currently stands.
- `band_barter`: a route at labour-time ratios with a neighbouring band — the first route, built with `market.py`'s machinery — and how `rare` goods first reach a band that lacks them.
- `band_raid`: takes a share of the target's stealable goods, tools, and herds.
- The **share rule** is the band's first law — kill to the killer, or shared by custom — a bookkeeping choice only: it changes nothing in totals, but changes the ledger once herds exist to record ownership of.
- `settle`: a record builds the first FIELD producer on arable land and stops moving — it starts to own something that cannot be carried away, and is therefore worth defending and worth taking. A nation is typically part settled, part herding for a long time; settling does not require herds to have been tamed first.

## Notes
- Every function takes explicit inputs and returns a result; the step wrappers (`step_production(world)` …) do the iteration and ledger writes.
- Occupations are re-bound to their record's location at the start of step 1.
- `f_N` is a parameter of `hoard_update`; until task 04 exists, pass `f_N = 1.0` (no insecurity) — tests for this task use that.

## Acceptance
- `tests/test_economy.py`: split rule conserves value (`labour + profit + rent == V` within 1e-9) on landed and landless producers; `r_bar` equals hand computation on a two-producer fixture; consumption exhausts income and never spends beyond it; standing tier buys only Attendance when no Luxuries are reachable and shifts by ≥ 50% when Luxuries at price ≤ 1 basket/standing appear; hoard rule conserves wealth; population grows with `A_subs > 1` and shrinks convexly below; a labourer record with more open jobs gets a higher `π`; a frozen edge (friction 1) leaves a price gap open after 50 years while an open edge closes it below `gap_tol`.
- Scenario: `three_bands.yaml`, 300 years, null sovereign, seed 1: at least one nation tames herds by year 80 and at least one settles a field by year 200; no NaN; value conservation holds every year (ledger check).
