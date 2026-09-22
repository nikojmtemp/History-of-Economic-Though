# 04 — Security, War, Trade, and Treaties (Sweep 1, task 4)

**Read**: 00–03.
**Owns**: `stock/security/*`, `stock/trade/*`.
**Depends on**: 01–03. Supplies `f(N_r)` to 02, `M_state/M` and `R_private` to 03, route demand to `market_size`, cross-border frictions to mobility.

## Goal

Perceived security per record and per nation; the army as a consumer recruited by pay; raids, wars resolved per location, sieges, conquest, cession, tribute; cross-border routes for goods and stock; hostility; treaties with terms, enforcement, breach, and casus belli. After this task nations fight, trade, and bind each other, and insecurity reaches investment.

## Deliverables

### `security/military.py`
- Doctrine from `nation.laws` and available records: `active_doctrine(nation) -> Doctrine` (EVERY_MAN, NATION_IN_ARMS, FEUDAL_HOST, MILITIA, STANDING_ARMY; FIREARMS and NAVY as flags).
- `strength(nation) -> M`: `M = Σ_units (size × equipment) × doctrine_multiplier × supply × loyalty`, per active doctrine: units are mobilised records (nation-in-arms: herdsmen + owners; feudal host: retainers + serf levy; militia: tenants/craftsmen; standing army: SOLDIERS), `equipment` is Arms held per unit, `supply`/`loyalty` from recruitment below. `M_state` = the share commanded directly by the State (STANDING_ARMY, NAVY doctrines; 0 for the feudal host, which is the lords', not the State's).
- **Recruitment** (with 02's mobility): the defence draw sets `pay`; the free-labour → SOLDIERS edge's net advantage uses it; `army_basket(nation)` per doctrine (Provisions always; Wares/Arms/Ships once the relevant Tree II defence node is lit) purchased in step 5 through 02's consumption at market prices, multiplied by a wartime basket multiplier (`SecurityParams.wartime_basket_multiplier`) while at war; `supply = min(1, bought/needed)`; underpaid → `supply < 1`; hungry → `loyalty < 1` → risk of mutiny. Mobilisation of an occupation zeroes its output for the year (02 reads `record.mobilised`).
- `perceived_security(nation, world) -> (PSV, PTV_ext, PTV_int_by_class, N_r, N_bar, f_N_by_record)`:
  ```
  PSV'      = λ·PSV + (1−λ)·a·ln(1+M) + p·O                                (one per nation; λ makes perception sticky)
  PTV_ext   = Σ_i b·ln(1+M_i)·h_i·g(d_i)  ,  g(d) = 1/(1 + d/d₀)            (i ranges over other nations)
  PTV_int,r = c_r·ln(1+R_private) + u·ln(1+U_dis)                          (c_r varies by the record's class)
  N_r       = PSV − PTV_ext − PTV_int,r
  N_bar     = Σ_r authority_r · N_r / Σ_r authority_r
  f(N_r)    = 1 / (1 + e^{−κf·(N_r − N₀)})
  ```
  `c_r` by class (`Params`, default): merchants/capitalists 1.2, craftsmen 0.6, labourers 0.3, landlords 0 — set so a merchant reads the lords' host as a threat first (`c_r·ln(1+R_private)` exceeds his share of `a·ln(1+M_host)`), while a landlord reads it as pure defence. `R_private` from 03 (the size of RETAINERS when FEUDAL_HOST is active); `h_i` from `trade/hostility`, `d_i` = distance between the two nations' nearest locations on the location graph. The logs make the first regiment worth much and the twentieth little, and arms races self-limiting. Writes `f(N_r)` where 02's `hoard_update` reads it as `f_N`.
- `matchup(doctrine_a, doctrine_b, firearms)`: before Firearms, nation-in-arms beats feudal host and militia roughly evenly, both beat standing army; after Firearms, standing army beats everything.

### `security/war.py` — step 13a
- `WarState` per pair: contested locations, siege counters, tribute/cession offers.
- `raid(attacker, location)`: strength roll vs. defender's local strength; takes a share of stealable goods, hoards, herds; events for both sides; `O` events (raid −1 / defence +1).
- `war_year(war, world)`, per contested location:
  ```
  outcome_t ∝ M_att · matchup · supply   vs   M_def · matchup · supply · fortification(loc)
  ```
  `k_siege` (default 2) consecutive losing years for the defender → `transfer_location(location, winner)`: records, producers, fields, fixed assets move to the winner's nation; the winner's laws apply with `enforcement` recomputed with the new records' opposition counted in full; markets rebind; `O` events (location lost −2). Losses to record sizes on both sides; war basket applied.
- `conquest_allowed(attacker, target, location)`: true only when `N_bar` of the target nation is below `N_conq` (deeply negative) and the attacker's local strength exceeds the defender's by a margin `m_conq`; the AI (06) and the player both go through it.
- Peace: `offer_peace(terms)` / `accept_peace` → cession, tribute (a revenue transfer registered with 05 for `k` years), or a treaty (below). A nation with no locations and no herds → `meta.regression.end_nation` (05).
- Repression action: the army is `inside` this year (`M` unavailable to `PTV` defence; disorder events suppressed in 03).

### `trade/routes.py` — step 4 (cross-border and stock)
- `Route` between two location markets. `capacity(route, world)`:
  ```
  capacity = k_cap · merchant stock committed · (1 + bills) · Ships_on_route · method / carriage_cost · (1 − law_friction) · treaty_factor
  ```
  `clear_goods(route)`: `flow_g = min(capacity, arbitrage volume)`, moved from the lower-price market to the higher; `merchant income = Σ_g flow_g · (P_high − P_low − carriage)`, routed to MERCHANTS in the earning nation's home location; customs hook for 05 at the border location. As merchant stock enters the route, the price gap narrows toward `r_bar` — that narrowing is exactly what causes the Merchant Interest to demand a charter in task 03.
- `route_demand(good, location)` supplied to 02's `market_size`.
- **Stock routes**: `clear_stock(route)` runs the owners-of-stock cross-border edge with the return differential as net advantage (02's mobility with a `wealth-only` mode: stock moves, size does not) — capital flight and foreign lending; returns accrue abroad and can flow back.
- Bands' border barter (02) is a `Route` with `capacity` from carriage only and prices at labour-time ratios.
- Charter: a `LawId.CHARTERED_COMPANY` on a route restricts `merchant stock committed` to the holder record; interlopers' flows are zero at that enforcement.

### `trade/hostility.py`
- `hostility_update(world)`: `h_ij' = h_ij + Δwar + Δroute_competition + Δcapture + Δbreach − Δtrade_volume − Δtreaty_kept − Δtribute`, symmetric (`h_ij == h_ji` always); route competition = two nations' merchants active on the same route, capture = one nation's merchants taking over a route the other held, breach = a broken treaty term (task 03/04's `check_breach`).
- Rival wars among AI nations use the same `conquest_allowed` and `war_year`; the player's merchants earn a carrying premium on routes between two belligerents.

### `trade/treaties.py`
- `Treaty` between two nations with any combination of these terms: `TARIFF_CEILING(goods, rate)`, `ROUTE_ACCESS`, `PORT_ACCESS`, `EXCLUSIVE_ROUTE`, `MOST_FAVOURED`, `TRIBUTE(years, amount)`, `CESSION(location)`, `GRAIN_GUARANTEE` (no Provisions prohibition against the other side in a dearth), `NON_AGGRESSION` (v2 flag, stub only). Negotiated (both pay `A_S`) or imposed at peace (loser pays nothing, consent not required).
- `treaty_factor(route)`, hostility weight, `PTV_ext` reduction, lenders' `σ` reduction — applied through the existing hooks.
- `enforcement_of_term(treaty, side)` = 03's `enforcement` computed in that nation against the Interest the term binds; `check_breach(treaty)` each year: a bound Interest re-enacting a tariff above the ceiling (03's self-enact), a closed Port, a Provisions prohibition in a dearth → `breach` event: `h_ij += Δbreach`; `casus_belli(beneficiary, breacher)` (war declaration without the aggression `O` cost; Interests' support flag for the AI); breacher's foreign `σ += Δσ` and `treaty_factor ×= (1 − φ)` for `k` years. Treaties lapse when a signatory ends; `renegotiable(treaty)` when `h_ij` and relative `M` have moved past thresholds (AI reads it).

## Notes
- All strength, threat, and hostility numbers go to the ledger each year for every nation (the security panel).
- Cross-border mobility frictions (`h_ij`, `1 − f(N̄_dest)`, treaty terms) are supplied to 02 via a `border_friction(loc_a, loc_b)` function owned here.

## Acceptance
- `tests/test_security_trade.py`: `f(N)` decreases as a rival's `M_i` rises and increases with a treaty that lowers `h_ij`; a merchant record's `N` is lower than a landlord's in the same nation when `R_private > 0` and the doctrine is FEUDAL_HOST; the defence draw raised at fixed pay increases Arms bought, not SOLDIERS size, while higher pay increases size; a location falls exactly after `k_siege` losing years and its records, producers, and market belong to the winner with the winner's laws at enforcement computed against full opposition; a route's gap narrows toward `r̄` as merchant stock enters and stops narrowing under a Chartered Company; a tariff ceiling term breached by the bound side's Industrial Interest self-enacting a tariff produces a breach event, raises `h_ij`, and grants casus belli; hostility is symmetric after every update.
- Scenario: `three_bands.yaml`, 400 years, null sovereigns (03) plus a fixed script that declares a raid every 20 years: at least one raid, one route with positive volume, one treaty imposed at a peace, and `f(N)` in `(0,1)` for every record every year; no nation's `M` is NaN.
