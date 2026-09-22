# 03 — Politics and Unrest (Sweep 1, task 3)

**Read**: 00, 01, 02.
**Owns**: `stock/politics/*`.
**Depends on**: 01, 02. Reads records, laws, scalars; writes authority, Interests, `A_S`, `J`, `ℓ`, law states, unrest, events.

## Goal

Year steps 11 and 12, and the legislative half of step 14: expected needs and unrest; the order signal; class authority and apportioned Interests; State authority with its handovers; justice and legibility; the political pipeline, passing, veto, enforcement; the Focus. After this task laws are enacted by Interests on their own and by a sovereign spending authority, and unrest produces riots and lobbying.

## Deliverables

### `politics/unrest.py` — step 11
- `expected_needs_update(record, alpha_up, alpha_down)`:
  ```
  E' = E + α_up · max(0, A − E) − α_down · max(0, E − A)      (α_collapse replaces α_down during a regression, flag passed in by 05)
  shortfall = max(0, E − A) / E
  ```
  `α_up > α_down > 0`, `α_collapse ≫ α_down` — expectations adapt up fast, down slowly; comforts long satisfied migrate toward the subsistence weight and back slowly, so stalled growth generates unrest with no decline, and a decline that stops eventually goes quiet.
- `unrest(record, params) -> U`:
  ```
  U = size · Σ_tier w_tier · φ_tier(shortfall_tier)      w = 8:2:0.5 (subsistence:comfort:standing)
  φ_subsistence = shortfall²  ;  φ_comfort = φ_standing = shortfall
  ```
  `expression(record) -> DISORDER | DEMAND` by `authority/size < a_split`: below the split, unrest expresses as disorder; above it, as a political demand read by `politics/interests.py`.
- Disorder events on thresholds `u₁..u₃` (defaults 0.2, 0.5, 1.0) against `U/size`: `strike` at `u₁`, `riot` (and `desertion` for SOLDIERS) at `u₂`, `revolt` at `u₃`; each an event record with numbers. Emigration flow request handed to `mobility` (a per-record intensity proportional to `U`, applied by 02's cross-border edge next year). `U_dis` = Σ `U` over disorder-expressing records → `nation.scalars`. Skip records with `size < extinct_size_epsilon` entirely — a near-zero record has nobody to strike.
- `loyalty(soldier_record) = 1 − shortfall_subsistence`; `mutiny` event at `u₃`.

### `politics/authority.py` — step 12a
- `record_authority(record, ell, w_nat, params)`:
  ```
  W_r          = Σ assets_r + ell · size_r · w_nat
  authority_r  = size_r^κs · W_r^κw + d_dep · dependents_r
  ```
  `κs` (default 0.5), `κw` (1.0), `d_dep` (0.5) are `Params` fields. `ell` (labour legibility, ∈ [0,1]) is the only route by which labour power counts toward `W_r` as wealth. `dependents_r` is estimated from derived-size classes this record maintains: for a buyer of Attendance, `dependent_record.size × (this buyer's Attendance spend / total Attendance spend by that dependent class's buyers)` — the only information the model keeps linking a dependent headcount back to a particular buyer.
- `apportion(record) -> dict[InterestId, float]`: split `authority_r` across Interests by the share of `W_r` held as each Interest's asset class, using the wealth-composition map in Doc 01's `CLASS_TABLE` section (land/herds/Church land/agricultural fixed assets → LANDED; stock in producers/tools → INDUSTRIAL; trading stock/Ships/routes held → MERCHANT; bonds/loans out → MONEYED, wherever held; labour power weighted by `ell` → LABOUR). `interest_authority(nation) = Σ_r apportion(r)`, recomputed fresh every year — nothing about authority itself is a stored accumulator; only `radicalism` and `ell` persist.

### `politics/interests.py`
- `InterestId` = LANDED, INDUSTRIAL, MERCHANT, MONEYED, LABOUR.
- `DEMANDS[InterestId] -> list[LawId | Repeal(LawId)]`, ordered by priority (each Interest tries the first affordable/clearable item first):
  ```
  LANDED:     TARIFF(Provisions)                          # the corn tariff
              SERFDOM  (or SETTLEMENT_LAW where SERFDOM no longer applies)
              MILITIA_ACT
  INDUSTRIAL: COMBINATION_ACT
              APPRENTICESHIP
              GUILD_CHARTER  (craftsman-dominated nation)  or  Repeal(GUILD_CHARTER)  (capitalist-dominated)
              STANDING_ARMY_ACT
              ADMINISTRATION_OF_JUSTICE
  MERCHANT:   FREE_TRADE
              NAVIGATION_ACT
              PUBLIC_CREDIT
  MONEYED:    (empty in sweep 1 — its demands need finance-specific law instruments task 05 adds; leave the list empty rather than mapping to an unrelated law)
  LABOUR:     Repeal(COMBINATION_ACT)
              Repeal(TARIFF(Provisions))  or  Repeal(PROHIBITION(Provisions))  # free grain trade
              POOR_RATE
              COMMUTATION
  ```
  `GUILD_CHARTER`'s enact/repeal pair are both filed under INDUSTRIAL (craftsmen want it, capitalists want it gone) because `InterestId` has no craftsmen-vs-capitalists split. A few plainer demands (e.g. "Poor Rate funded by others", "a charter on a closing route") have no `LawId` at this granularity and are simply left off rather than mapped to a nearby-but-wrong law; see `DEVIATIONS-RESOLVED.md` if you need the full reasoning.
  `radicalism_update(interest, demand_unrest, met)`: `radicalism_I' = radicalism_I + Σ_{r∈I} political-demand unrest_r − decay·1[demands met]` — political-demand unrest (from `politics/unrest.py`, the `DEMAND` branch) accumulates into the Interest's stored `radicalism`, and decays only when its demands have been met.

### `politics/state.py` — step 12b
- `order_signal(nation.events_this_year, params) -> O`: sum of this year's event weights only (nothing is a running total): victory +2, defence +1, raid −1, defeat −2, location lost −2, riot −1, revolt −2, mutiny −3, default −1, law lapsed −1 each, treaty broken against us −1.
- `state_authority_update(nation, world, params)`:
  ```
  A_S' = (1−δ)·A_S + a₁·(M_state/M)·ln(1+M) + a₂·J + a₃·Σ_laws weight·enforcement + a₄·(direct/revenue) + a₅·max(0,O) + a₆·ln(1+court)
         − b₁·max(0,−O) − b₂·ln(1+R_private) − b₃·ln(1+U_dis) − b₄·farmed_share − spent
  ```
  `δ` (decay, default 0.05), `a₁–a₆`, `b₁–b₄` are tuned `Params` fields. `R_private` = the size of RETAINERS in the nation when FEUDAL_HOST is the nation's active doctrine (read "active", not merely "ever lit" — track which defence doctrine is currently in force; task 04 owns doctrine selection, 0 until then). `M_state / M` comes from task 04 (0 until then). `spent` is deducted immediately at the point of expenditure by `actions.validate`, not re-subtracted here (that would double-count it).
- `on_protection_of_property`'s firing condition compares Landed's authority against a nominal weak-government baseline, **not** the nation's own `A_S`: `landed_authority > θ' · consensus_c0` (reusing the band-consensus constant `C₀` as "what a minimal government commands"). Do not reuse the ordinary self-enactment bar (`authority_I·(1+radicalism_I) > θ'·(A_S + opposing authority)`) here — `on_tamed_animal` initialises `A_S` from a herd-owner's authority in the first place, so at the moment a nation becomes eligible for this check `A_S` already starts at or above the Landed authority the ordinary bar would need to beat, and never catches up as `A_S` decays slower than population's authority can shrink. The baseline-against-`C₀` version fires within a few years of taming, matching the intended chain: taming creates stakes worth defending, which is what motivates government.
- **Handovers**: `on_tamed_animal(nation)` sets `A_S := authority(largest herd-owner record)` (computed fresh via `record_authority`, since the record can be created this same year, before step 12a has run on it), `seat := CHIEF`. `on_protection_of_property(nation)` creates the STATE record (Doc 01's `ClassId.STATE`) with `A_S` unchanged — small beside the Landed Interest, which still holds the host, the courts, the dues — and sets `seat := STATE`; place the State record at the nation's most populous location (there is no separate "capital" concept yet). A band that settles a field without ever taming herds also needs a seat handover to CHIEF (it now has land shares, a Landed Interest, and `seat == BAND` would otherwise block all legislation forever): `on_settled` sets `A_S` to the authority of the largest land-holding record and `seat := CHIEF`. Band consensus refill (`C₀`) stays in task 02.

### `politics/justice.py`
- `justice_level(nation, draw, params) -> J`:
  ```
  J = J_cust + (1 − J_cust)·min(1, justice_draw/justice_need)   if ADMINISTRATION_OF_JUSTICE enacted, else J_cust
  ```
  `J_cust` (the customary floor) = 0.3 if the nation has no FIELD producer (band or herds stage), else 0.4. `justice_need` scales with population, higher where the town share of population is higher.
- `legibility_update(nation, J, disorder_converted, params)`: `ell' = ell + j·J·(disorder converted this year) − δ_ell·ell`, `ell ∈ [0,1]`. `convert_disorder(nation, J)` moves a share `J` of `U_dis` into LABOUR's `radicalism` and returns the converted amount — this is the only route by which Labour gains authority over a long run.

### `politics/legislation.py` — step 12c and step 14 (legislative actions)
- `bar(law, nation) -> (support, opposition_term)` using `LAW_TABLE.support/opposition` (Doc 01) and each opposing Interest's `radicalism`:
  ```
  self-enacts  if  authority_I · (1 + radicalism_I)  >  θ' · (A_S + Σ_opposing authority)
  passes       if  support + spend  ≥  θ · opposition · (1 + Σ_opposing radicalism · w_r)
  ```
  `θ` (passing bar, default 1.0), `θ'` (self-enactment bar, 1.5), `w_r` (radicalism weight, 0.5) are `Params` fields. `_repeal_bar` reuses this formula with support and opposition swapped — repealing a law must overcome those who support it.
- `self_enact(nation)`: for each Interest, walk `DEMANDS[interest]` in order; the first item whose self-enactment condition holds is enacted (or repealed), emitting `law_self_enacted` with the three numbers (`authority_I`, `A_S`, `opposition`); respect cooldowns; cap at **one** self-enactment per Interest per year (so a single year can't dump an Interest's whole agenda into law, and each enactment can change the state the next demand is evaluated against).
- `enact(nation, law, spend)`, `repeal(...)`, `veto(nation, law)` (cost = gap × `veto_premium`; sets a `k_veto`-year cooldown on that Interest re-attempting the same self-enactment — a veto buys time, not a permanent block); `passes()` predicate; `cost_of(action)` for `actions.validate` (task 01 exposes the hook, this task fills it).
- `enforcement(law, nation) -> float`: `J · A_S / (A_S + opposition_of_that_law)`, floored at a new `politics.enforcement_epsilon` (1e-3 placeholder) so it is never exactly 0 even when `A_S = 0` and the law has any opposition. Written to `LawState.enforcement` each year; read by 02 (Combination Act, Serfdom, frictions), 05 (taxes), 04 (treaties). `walk_away_multiplier` and `vertical_flow` law effects (Doc 01's `EffectSpec` tags) are applied continuously off this fresh `enforcement`, every year the law stays enacted, not once at enactment time — otherwise they'd freeze at enactment year's value. For `vertical_flow`: a `forced=True` edge (Enclosure) converts a share of the source class equal to `enforcement` itself (fast); an unforced edge (Commutation) converts at `mobility.rate_v_base × enforcement` (a trickle, reusing the law-free promotion rate as the "gradual" case — there's no separately named rate for law-gated edges). `SERFDOM`'s walk-away effect: `walk_away = base + (1 − base) · (1 − enforcement)` with `base = 0.0` — 0 under full enforcement, the class's free baseline (1.0) under none. `edge_friction` (extending Doc 02's `engine/mobility.py` hook) reads the `x` magnitude on each law's `EffectSpec`: Settlement Law dampens the free-labour tier (LABOURERS/SOLDIERS) same-location, Apprenticeship dampens any edge touching CRAFTSMEN — both are an approximation (neither law names a precise same-location class pair), the best available reading until a later task builds the real cross-location/producer-hiring friction mechanic.
- Law effects application: on enact/repeal, apply `LAW_TABLE.effects` declaratively — e.g. Enclosure converts commons to land shares and forces SERFS/TENANTS → LABOURERS through 02's vertical edge with a `forced=True` flag; Standing Army Act creates the SOLDIERS record and doctrine (state only; the military maths is 04); Protection of Property triggers the handover.
- **Lapse**: `lapse_unenforceable(nation)` — a law whose payer draw is unfunded (input from 05) or whose enforcement < `enf_min` for `k_lapse` years lapses, emitting `law_lapsed` (an `O` event).

### `politics/focus.py` — step 10 support
- `Focus` state per nation: node, location, progress, upkeep; `advance_focus(nation, works_draw)` lowers the gate of the chosen node in the chosen location by the Focus's effect (public works → carriage factor on chosen edges; patent → exclusive method N years with expiry; education → skill-penalty reduction). Gate evaluation itself is 05.

## Notes
- Interest authority is recomputed each year from apportionment; only `radicalism` and `ℓ` are stored accumulators. Assert this in tests.
- All in-game text is deferred to sweep 3; this module emits event records with `numbers` only.
- Repression and price control are actions whose *effects* land here (suppress disorder events this year; cap Provisions price) but whose military cost (army inside) is 04.

## Acceptance
- `tests/test_politics.py`: a Landed Interest with authority > `θ'·(A_S + others)` self-enacts its first demand and the event carries `(authority_I, A_S, opposition)`; a sovereign with `A_S` < gap cannot push a law and the node reports the three numbers; a veto sets the cooldown and the Interest does not re-enact within it; enforcement is never 0 and equals `J·A_S/(A_S+opp)`; a record with `authority/size < a_split` and 30% subsistence shortfall emits a riot and raises `U_dis`, while a landlord record with the same shortfall raises LANDED radicalism and emits nothing; `ℓ` rises only when `J` and converted disorder are both > 0; the tamed-animal handover sets `A_S` to the largest herd-owner's authority; Interest authority is identical when recomputed twice in a year.
- Scenario: `three_bands.yaml`, 300 years, null sovereign: at least one nation reaches `seat == STATE`; at least one law is self-enacted by an Interest; no law has enforcement 0.
