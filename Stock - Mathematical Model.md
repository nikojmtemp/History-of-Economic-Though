# Stock — Mathematical Model

The logic to be modelled, and nothing else. Each block: the formula, the terms, and the intention in one line. Section numbers refer to the design document. All quantities are per **nation** unless marked per **record** (class × location) or per **location**. One turn = one year; `'` denotes next year's value; values not yet produced this year are last year's (lag rule).

## Notation

| Symbol | Meaning |
|---|---|
| `r` | a class record; `size_r`, `W_r` (wealth), `H_r` (hoard) |
| `loc` | a location; `nation(loc)` its owner |
| `g` | a good class ∈ {Provisions, Materials, Wares, Luxuries, Arms, Ships, Attendance} |
| `V`, `Q`, `P` | output value, physical output, price (all value in **baskets** — one person-year of subsistence) |
| `w` | the clearing wage for free labour; `w_nat` the basket's price incl. taxes on it |
| `r̄` | the nation's average rate of profit |
| `A_S` | State authority; `J` justice level; `ℓ` labour legibility |
| `N_r`, `N̄` | perceived security per record, and its authority-weighted mean |
| `f(·)` | the sigmoid investment multiplier |
| `O` | the order signal (events only) |
| `U_r` | unrest per record; `U_dis` the nation's disorder-type unrest |
| `M` | effective military strength; `M_i` a rival's |
| `h_ij` | hostility between nations i and j |

---

## 1. Population (§2.3) — per record

```
size_r' = size_r · (1 + β·(A_subs,r − 1)) − m·size_r·max(0, 1 − A_subs,r)² ± mobility flows
```
`A_subs,r` = subsistence satisfaction relative to the basket. Population is an output of pay vs. need; hunger mortality is convex. Dependent records' size is set by the purchase in §6c, not by this rule.

## 2. Mobility (§2.4) — per edge between records

```
flow(r→r') = size_r · rate_edge · (1 − friction_edge) · max(0, NA_r' − NA_r)          horizontal
flow(r→r') = size_r · rate_v · 1[W_r/size_r > threshold]   or   1[W_r/size_r < basket]   vertical up / down
NA_r      = income per head + non-monetary terms (agreeableness, learning cost, constancy, trust, chance)
friction  = law friction (same location)
          = distance / (river or road factor)                               cross-location, same nation
          = that + h_ij + (1 − f(N̄_dest)) + treaty terms                  cross-border
```
Wealth and debt move pro rata with the moving share of size. Intention: equalisation of net advantages across employments; laws are frictions on named edges.

## 3. Authority and Interests (§2.5) — per record, then per Interest

```
W_r         = Σ assets_r + ℓ · size_r · w_nat
authority_r = size_r^κs · W_r^κw + d_dep · dependents_r
authority_I = Σ_r authority_r · (share of W_r held as the Interest's asset class)
ℓ'          = ℓ + j · J · (disorder converted this year) − δ_ℓ · ℓ,   ℓ ∈ [0,1]
radicalism_I' = radicalism_I + Σ_{r∈I} political-demand unrest_r − decay·1[demands met]
```
Intention: political weight follows wealth; labour counts as wealth only as justice makes it legible; Interests are apportionments, so the Moneyed Interest appears when bonds are bought.

## 4. Production (§4.2) — per producer in a location

```
Hunting      Q = y_game(loc) · H^η · dep(loc)                 dep' = dep − δ_dep·use + ρ_dep·(1 − dep)·idle
Herding      ΔHerd = γ · Herd · min(1, herdsmen/(Herd/h));    Q_prov, Q_mat = κ_prov·Herd, κ_mat·Herd
Field        Q = y_arable(loc) · L · labour^η · (1 + rotation) · tools
Workshop     Q = q_c · craftsmen · tools · materials
Manufactory  Q = q_m · labourers · (stock/labourers)^ζ · DoL(market_size) · machinery · materials
Mine         Q = q_x · labourers · resource(loc)
jobs         = stock / stock_per_job     (buildings)   |   L · jobs_per_share   (fields)
```
`H` hunters, `L` land shares. Caps: arable and carrying capacity per location. Intention: yield from the ground for occupations, from land and stock for buildings; division of labour scales with the market.

## 5. The split rule and the rate of profit (§4.3–4.4)

```
V             = P_g · Q                                  (last year's price)
labour_income = filled jobs · w                          (dependents: the basket in kind)
profit        = r̄_{t−1} · stock in place                 producers with land
rent          = V − labour_income − profit                producers with land (residual to land shares)
profit        = V − labour_income − site_rent             producers without land
r̄            = Σ profit / Σ stock in place               (herd increase counts as profit on herd stock)
```
Intention: wages first, normal profit next, rent last — the adding-up price with an order, which makes excess profit attract stock and lets land absorb surplus.

## 6. Placement of stock (§4.4)

```
freed        = τ_turn · stock in place (every producer)
placeable    = freed + Σ_r to_reinvest_r
placement    → producer/method with max (return per unit stock) among those laws allow and locations can hold
base returns: cultivation > domestic manufacture > foreign trade   (reordered by charters, bounties, tariffs)
```
Intention: gravitation on the supply side; stock leaves sub-normal sectors gradually.

## 7. Prices (§4.5) — per good class, per location market

```
P_g        = base_g · (D_g / S_g)^ε_g                    inventory' = (inventory + unsold) · (1 − decay)
P_nat,g    = w · labour_per_unit + r̄ · stock_per_unit + rent_per_unit      at the average rates of g's producers
```
Unit of account: the basket; in a band, `P` is labour time. Intention: market price gravitates to natural price through §2 and §6.

## 8. Wages (§4.6) — per free-labour record

```
w_nat     = P(basket) incl. taxes on Provisions/Wares and on wages
surplus   = V / filled jobs − w_nat
π         = wa_L / (wa_L + patience_M)
w         = w_nat + π · surplus · (1 − enf_CombinationAct)
wa_L      = Σ shares of income: open jobs on edges + Poor Rate transfer + H_r/size_r + credit available + scarcity premium
            − ρ_h · (strike years)
patience_M = stock in place / annual wage bill + silent combination modifier
```
Intention: the wage is a bargain over surplus whose shares depend on outside options and capacity to wait; a tax in the basket passes forward only as far as `π` allows.

## 9. Extent of the market (§4.7) — per good class, per location

```
market_size(g, loc) = Σ_{loc' : carriage(loc, loc') ≤ c_max} spending_on_tier(g, loc') + army demand_g + route demand_g at capacity
DoL                 = f_DoL(market_size)     (increasing, saturating)
```
Intention: one number through which consumption, the army, migration, and trade all feed the division of labour.

## 10. Consumption (§5.1) — per record

```
tiers filled in order: subsistence (Provisions, some Wares) → comfort (Wares) → standing (Luxuries, Attendance)
share_g within a tier  ∝ weight_g · P_g^(−σ)
standing per basket:   Attendance  s_att;   Luxuries  s_lux · vanity,   vanity = v_min + (v_max − v_min)·(1 − e^{−Luxuries reachable / v₀})
Attendance bought (baskets) = size of the dependent record it maintains
tag each unit spent: productive (goods by productive labour) | unproductive (attendance, soldiers, clergy, court)
```
Intention: dependents and luxuries compete in one unit; retainers exist only where nothing else buys standing; the dismissal is a substitution.

## 11. Hoards and reinvestment (§5.2–5.3) — per record

```
residual     = income − consumption
saved        = p_r · residual
to_reinvest  = saved · f(N_r);    to_hoard = saved · (1 − f(N_r))
H_r'         = H_r + to_hoard − ω · f(N_r) · H_r − deposits_r − bonds_from_hoard_r
bonds bought = from H in proportion (1 − f(N_r)), from to_reinvest in proportion f(N_r)
p_r          = p_base,r · (1 + p_prof · r̄) · charter modifier · standing-saturation modifier
```
Intention: insecurity parks wealth once, here; hoards re-enter as security returns.

## 12. Order, State authority, justice (§7.1, 7.3, 7.6)

```
O   = Σ event weights (victory +2, defence +1, raid −1, defeat −2, location lost −2, riot −1, revolt −2, mutiny −3,
                       default −1, law lapsed −1, treaty broken against us −1)

A_S' = (1 − δ)·A_S + a₁·(M_state/M)·ln(1+M) + a₂·J + a₃·Σ_laws weight·enf + a₄·(direct/revenue) + a₅·max(0,O) + a₆·ln(1+court)
       − b₁·max(0,−O) − b₂·ln(1+R_private) − b₃·ln(1+U_dis) − b₄·farmed_share − spent

handover: band A_S = consensus (refills to C₀);  at Tamed Animal A_S := authority of the largest herd-owner record;
          at Protection of Property the State record is created with A_S unchanged

J   = J_cust + (1 − J_cust) · min(1, justice_draw / justice_need)   if Administration of Justice enacted;  else J_cust
justice_need ∝ population · (1 + town share)
```
Intention: `O` carries events; `R_private` and `U_dis` are read once each here and once in §14; the State earns authority by doing.

## 13. Laws (§7.4–7.5)

```
self-enact_I    if  authority_I · (1 + radicalism_I)  >  θ' · (A_S + Σ_{opposing} authority)
passes          if  support + spend  ≥  θ · opposition · (1 + Σ_{opposing} radicalism · w_r)
veto            cost = gap · premium;  demand on cooldown k_veto years
enf_law         = J · A_S / (A_S + opposition_of_that_law)     ∈ (0,1)    multiplies the law's effects
```
Intention: the sovereign spends authority to override Interests, Interests override a weak sovereign, and every law is only as real as the State's authority over those it binds.

## 14. Security (§9.1) — per nation, then per record

```
M        = Σ_units (size · equipment) · doctrine · supply · loyalty
PSV'     = λ·PSV + (1 − λ)·a·ln(1+M) + p·O
PTV_ext  = Σ_i b · ln(1+M_i) · h_i · g(d_i),        g(d) = 1/(1 + d/d₀)
PTV_int,r = c_r · ln(1+R_private) + u · ln(1+U_dis)
N_r      = PSV − PTV_ext − PTV_int,r
N̄        = Σ_r authority_r · N_r / Σ_r authority_r
f(N_r)   = 1 / (1 + e^{−κf (N_r − N₀)})
```
Intention: security is perceived (lagged, log in strength) and enters investment per record; internal threat weighs differently by class.

## 15. War (§9.3) — per contested location

```
outcome_t ∝ M_att · matchup · supply  vs  M_def · matchup · supply · fort(loc)
location falls after k_siege consecutive losing years → nation(loc) := winner; laws := winner's at low enforcement
conquest attempted only if N̄_target < N_conq and M_att(loc) > m_conq · M_def(loc)
matchup (doctrine): nation in arms > host ≈ militia > standing army before Firearms;  standing army + Firearms > all after
```

## 16. Trade (§10.1–10.3) — per route between two location markets

```
capacity  = k_cap · merchant stock committed · (1 + bills) · Ships_on_route · method / carriage_cost · (1 − law_friction) · treaty_factor
flow_g    = min(capacity, arbitrage volume) from the lower-P market to the higher
merchant income = Σ_g flow_g · (P_high − P_low − carriage)
stock flow (cross-border owners-of-stock edge) per §2 with return differential as NA
h_ij'     = h_ij + Δwar + Δroute competition + Δcapture + Δbreach − Δtrade volume − Δtreaty kept − Δtribute
```
Intention: the standing price gap is merchant profit; it closes as stock enters; hostility falls with trade.

## 17. Treaties (§10.4)

```
term enforcement on side k  = enf_law computed in nation k against the Interest the term binds
breach                      → h_ij += Δbreach;  casus belli for the beneficiary;  breacher: σ_foreign += Δσ, treaty_factor ×= (1 − φ) for k years
benefit                     → h_ij −= weight;  carriage friction −;  market_size extended;  PTV_ext −;  lenders' σ −
```

## 18. Credit (§11)

```
r_market    = s · r̄ + ρ(N̄, J)                      r_legal = min(r_market, usury_cap)
r_sovereign = r_market + σ(D/revenue, default_history, J, treaty standing)
supply_lender = lendable surplus · f_s(r_legal − own return)
demand        = Σ projects with return > r_legal + subsistence demand (inelastic)
bonds_t       = max(0, spending − revenue);     D' = D · (1 + r_sovereign) − service
default: D := 0; bondholders' bonds := 0; default_history := 1; Public Credit closed k years; O −= 1
```
Intention: interest follows profit; lending follows security and justice; funding defers the cost of war onto later classes.

## 19. Taxation (§12.2) — per instrument

```
assessed   = base · rate
evasion    = g_e(rate, certainty, mobility of base) · (1 − enf_instrument)
collected  = assessed · (1 − evasion) · (1 − collection_cost)
incidence  = burden by class recorded after next year's wage, price, and placement adjustment
budget     = shares over {defence, justice, works, service, court, transfers} of collected revenue
```
Intention: nominal payer ≠ effective payer; shifting runs through §5, §6, §8.

## 20. Expected needs and unrest (§8.1–8.2) — per record, per tier

```
E'        = E + α_up · max(0, A − E) − α_down · max(0, E − A)          (α_collapse replaces α_down during a regression)
shortfall = max(0, E − A) / E
U_r       = size_r · Σ_tier w_tier · φ_tier(shortfall_tier),    w = 8:2:0.5,  φ_subs = x², others x
expression: authority_r/size_r < a_split → disorder (events at U_r/size_r > u₁ strike, u₂ riot/desertion, u₃ revolt; emigration ∝ U_r)
            else → political demand → radicalism_I
U_dis     = Σ_{disorder records} U_r
loyalty   (Soldier record) = 1 − shortfall_subs;  mutiny at u₃
```
Intention: expectations adapt asymmetrically; the poor riot and the rich lobby over the same shortfall.

## 21. Regression (§13)

```
spiral if for k_spiral consecutive years: N̄ < N_crit ∧ ΔN̄ < 0 ∧ U_dis > U_crit ∧ Σ to_reinvest ≈ 0 ∧ Δ(produce/head) < 0
discrete: mutiny | capital loss > κ_loss · stock | uncontained revolt | Provisions route broken > k_food years | default > κ_def · stock
resolve: config := highest node-set whose gates the surviving assets meet; sizes flow down vertical edges with wealth;
         unenforceable laws lapse; Tree I/II nodes stay lit; E := A at α_collapse; PSV := a·ln(1+M_surviving)
nation ends when it holds no location and no herd
```

## 22. Scoreboards (§14.1) — per nation

```
produce_per_head = Σ productive V / population
labour_share     = labour income of productive records / (that + profit + rent)
freedom_index    = Σ_{r : walk-away_r > wa_free} size_r / population
```

## 23. Hegemony and the end (§1.4) — world

```
capital_share_n      = (stock in place + herds + hoards + treasure)_n / world
consumption_share_n  = consumption value_n / world
production_share_n   = Σ productive V_n / world
flags_n              = #{k : share_k,n ≥ H_share}
countdown            = H_years when flags_n ≥ 2 first holds;  −1 per year while flags_n ≥ 2;  := H_years when flags_n < 2
end when countdown = 0
winner_A = argmax_living produce_per_head;   winner_B = argmax_living Σ productive V   (labour output)
```
Intention: the game ends by dominance of the world's capital, consumption, or production, and names a per-head winner and a total-output winner, which may differ.

## 24. The clock (§1.3)

```
speed ∈ {paused, slow, fast, faster, very fast} = {0, 0.1, 0.2, 0.5, 2} years per real second
queued actions apply at the next year boundary; costs deducted then; scripted sovereigns act at the same boundary
auto-pause on configured events
```
