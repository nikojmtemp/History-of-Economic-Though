# 05 — Finance, Regression, End Condition, and the Year Loop (Sweep 1, task 5)

**Read**: 00–04.
**Owns**: `stock/finance/*`, `stock/meta/*`, `stock/sim/year.py`, `stock/sim/clock.py`, `stock/sim/__main__.py`.
**Depends on**: 01–04. Completes sweep 1.

## Goal

Credit and public debt; taxation with incidence and the budget; tree gate evaluation; exogenous events; regression detection and resolution; the end of a nation; hegemony flags, countdown, and winners; the three curves; the assembled year loop with the lag rule; and a headless runner. After this task `python -m stock.sim run` plays a complete game with null sovereigns.

## Deliverables

### `finance/credit.py` — step 6
- `rates(nation) -> (r_market, r_legal, r_sovereign)`:
  ```
  r_market    = s · r_bar + ρ(N_bar, J)
  r_legal     = min(r_market, usury_cap)
  r_sovereign = r_market + σ(D/revenue, default_history, J, treaty standing)
  ```
  `s` (lender's share, default 0.5), `ρ`, `σ` are `Params`-tuned functions/constants; interest follows profit, and lending follows security (`N_bar`) and justice (`J`) — where property is insecure, stock is hoarded, not lent.
- Private market: lenders (MERCHANTS, CAPITALISTS; foreign lenders via 04's stock routes) supply `lendable surplus × f_s(r_legal − own return)`; demand = `Σ` projects with return above `r_legal` (from 02's placement returns) plus inelastic subsistence demand (LABOURERS with a shortfall). Borrowers and what happens on default, by class: landlords borrow for display (alienable → land transfers to the creditor; primogeniture → rent pledged, title kept); tenants for improvement (default loses the lease); craftsmen for journeymen (default backs the craftsman down a tier); merchants for capacity (default loses Ships); capitalists for methods (default idles the producer); labourers for subsistence (default deepens the shortfall; sustained borrowing becomes debt bondage — a horizontal flow to the dependent tier through 02); interest is paid the following year.
- Usury Law settings (a `LawId.USURY_LAW` payload, not a separate enum): **prohibition** — all lending is informal at `r_market + penalty`; **a cap slightly above market** — display borrowing and projectors are starved, sober borrowers unaffected; **a cap below market** — the legal lending market dries up; **none** — projectors bid `r_market` up.
- Public credit: `treasure` on the STATE record until `LawId.PUBLIC_CREDIT` is enacted; then:
  ```
  bonds_t = max(0, spending − revenue)
  D'      = D · (1 + r_sovereign) − service
  default: D := 0 ; bondholders' bonds := 0 ; default_history := 1 ; Public Credit closed k years ; O −= 1
  ```
  Bonds are drawn from hoards and reinvestment by 02's one hoard rule (this module supplies `bonds_from_hoard` and a claim on `to_reinvest`); the MONEYED Interest appears through 03's apportionment automatically once `wealth.bonds > 0` for any record — there is no fixed roster of Moneyed members. `debt_choice(nation)` when `service > τ_d · revenue` (default `τ_d = 0.4`) exposes TAX / ROLLOVER / DEFAULT for the sovereign (06/07) and defaults to ROLLOVER for a null sovereign.

### `finance/taxation.py` — step 3
- Instruments as `LawId`s with a `rate` field (enum values from Doc 01's Revenue-branch table). Base and how each behaves:

  | Instrument | Assessed on | Note |
  |---|---|---|
  | `LAND_TAX` | rent | cannot shift — lands where assessed |
  | `TITHE` | gross field produce | falls on rent; discourages improvement |
  | `CAPITATION` | heads | proportioned to nothing; felt hardest at the bottom |
  | `WAGE_TAX` | wages, at the employer | raises `w_nat`; passes forward through `π` |
  | `PROFIT_TAX` | profit of stock | mobile and hard to pin down: evaded, shifted, or re-placed away |
  | `EXCISE_PROVISIONS_WARES` | subsistence and comfort classes of goods | raises `w_nat`; passes forward |
  | `EXCISE_LUXURIES` | Luxuries | stays with the buyer; shrinks the taxed base — in a landed nation, substitutes back into Attendance |
  | `CUSTOMS` | goods on a route, at the border location | splits between the merchant's gap and the consumer; above a threshold, smuggling opens an untaxed route |
  | `TOLLS` | users of a public work | user-pays |
  | `POOR_RATE` | rent, earmarked | funds transfers |
  | `TAX_FARMING` | any instrument, sold for a lump sum | a credit instrument in disguise: a high effective rate, collected by armed men |
  | `SALE_OF_CROWN_LANDS` | one-time | the State's land shares transfer to the buyer |

  `assess`, `evasion`, `collect`, `collection_cost`:
  ```
  assessed  = base · rate
  evasion   = g_e(rate, certainty, mobility of base) · (1 − enforcement_instrument)     (enforcement from 03)
  collected = assessed · (1 − evasion) · (1 − collection_cost)
  ```
  the COLLECTORS record is sized by instrument count (visible in v2 only).
- Pre-State revenue (before assessed taxation is possible at all): the chief's own herd share and tribute; the demesne (fields the STATE record itself owns); feudal dues; tithe as a flat draw. **Tax farming** advances a lump sum (a private loan from a MERCHANT record) against a higher effective rate on the farmed instrument, and raises `farmed_share`.
- **Incidence**: record each instrument's assessed-by-class this year, and compute borne-by-class the *following* year from the differences in wages, prices, and placement attributable to it — a counterfactual: re-run 02's wage and price functions with and without the instrument's contribution to `w_nat` and to producer costs; the placement effect comes from the resulting return differential. Store the lagged table for the UI. There is no single functional form specified for how a wage/necessaries-instrument's burden splits between employer and employee beyond "as far as `π` allows" (task 02's wage bargain) — for the concrete formula currently implemented and its open review flag, see `DEVIATIONS-UNRESOLVED.md` (item A25) before changing this.
- **Budget**: shares over defence, justice, works, service, court, transfers; writes the draws that 04 (pay, basket), 03 (`J`, works via Focus), this module (service), 02 (court consumption of the STATE record), and 03/02 (Poor Rate transfers) read. Unfunded draws set the flags 03's `lapse_unenforceable` reads.

### `meta/trees.py` — step 10
- `evaluate_gates(world)`: evaluates every node's `gate_met` predicate (declared in Doc 01's `core/trees.py`) against current world state — Tree I per location, Tree II per nation across all three branches. Once lit, a node stays lit (a regression, task 05's own `resolve`, keeps nodes lit but their producers may idle). Focus effects from 03 lower the specific gate `advance_focus` is pointed at.

### `meta/events.py` — step 13b
- Exogenous only — the simulation never generates these from its own state, only from a probability roll each year: plague (records shrink → `wa_L` rises → bound labour cracks under the pressure), harvest failure in a location, the Watt event (unlocks `MACHINERY_STEAM`), a trade fair becoming a town, a new ore or coal find, wild herds migrating into a location. Probabilities live in `Params`; each emits an event record with numbers and applies its effect through the existing functions of the module it touches (never new bespoke logic).

### `meta/regression.py` — step 13c
- `spiral_window(nation)`: a spiral triggers when, for `k_spiral` consecutive years, `N_bar < N_crit` and falling, `U_dis > U_crit`, `Σ to_reinvest ≈ 0`, and produce per head is falling. `discrete_triggers(nation)`: mutiny; capital loss exceeding `κ_loss · stock` in a war, or a Port taken; a revolt the army fails to contain; a Provisions route or grain guarantee broken for more than `k_food` years; a default exceeding `κ_def · stock`. A warning band state tracks how full the spiral window is while it fills, for the UI.
- `resolve(nation, world)`, one step, in order: (1) the carrying configuration becomes the largest set of producers/methods whose gates the surviving assets still meet (query `meta/trees` predicates directly — never a stage label; a manufactory economy can fall to putting-out, a settled nation back to herding if the fields are lost and the herds are not); (2) flow sizes in bulk down the vertical edges, carrying their wealth (02); (3) lapse laws the State can no longer pay for or enforce (03); (4) Tree I/II nodes stay lit but idle; (5) `E := A` at rate `α_collapse` (03's flag, faster than ordinary `α_down`); (6) `PSV := a · ln(1 + M_surviving)` (04). Emits a `regression` marker with numbers, not a narrated cause.
- `end_nation(nation)`: fires when a nation holds no location and no herd. Records dissolve to the conqueror (if the last location was lost in war) or vanish (if the last herd starved out); treaties lapse; a final-ledger snapshot is written with every field below, then the nation is marked ended and skipped thereafter:

  turns elapsed; terminal condition; regressions suffered; the three curves' final and peak values; population, class sizes, productive/unproductive population, emigrated count, military dead; locations held at peak and at end; stock, hoard share, interest, debt/revenue ratio, defaults, laws enacted/repealed/lapsed, Tree nodes lit; the top three rivals by hostility with each rival's strength, wars, trade volume, and treaties; wars declared/suffered/won/lost; locations taken/lost; plunder taken. No stage line, no chain, no reading list, no pointer to a cause — numbers only.

### `meta/hegemony.py` — step 13d
- `world_shares(world)`:
  ```
  capital_share_n     = (stock in place + herds + hoards + treasure)_n / world total
  consumption_share_n = consumption value_n / world total
  production_share_n  = Σ productive V_n / world total
  ```
  `flags_n = #{k : share_k,n ≥ H_share}` (`H_share` default 0.75). `countdown`: set to `H_years` (default 25) the first year `flags_n ≥ 2` holds for a nation, then decrements by 1 each further year `flags_n ≥ 2` holds; reset to `H_years` (not cancelled) the moment `flags_n < 2` again. `game_over` fires when the countdown reaches 0. `winners(world) -> (per_head_nation, labour_output_nation)`: `argmax` of `produce_per_head` and of `Σ productive V` respectively, among living nations only (they may be different nations). The world keeps running after game over if asked.

### `meta/scoreboards.py`
- The three curves, computed per nation per year:
  ```
  produce_per_head = Σ productive V / population
  labour_share      = labour income of productive records / (labour income + profit + rent), productive records only
  freedom_index     = Σ_{r : walk_away_r > wa_free} size_r / population
  ```
  Labour income counts only productive records' wages/in-kind pay; Attendance, soldiers', and servants' maintenance is property income spent, and must never be counted a second time as labour income. In a band, `labour_share` is 1.0 by construction (no property income exists yet). Also write the `N_bar` band (from 04) alongside curve 1, per nation per year, to the ledger.

### `sim/year.py`
- `run_year(world)`: the 14 steps, every nation, in this order: 1 production (02) → 2 wage bargaining (02) → 3 revenue and budget (05) → 4 trade, goods and stock (02 internal + 04 cross-border) → 5 consumption (02) → 6 credit (05) → 7 hoards and reinvestment (02) → 8 population and mobility (02) → 9 stock placement (02) → 10 trees and Focus (05 + 03) → 11 unrest (03) → 12 politics — authority, State, legislation (03) → 13 military, events, regression check (04 + 05) → 14 queued sovereign actions apply. Take the `world.prev` snapshot (Doc 00's lag rule) at the start of the year, before step 1 runs; flush the ledger at the end. `apply_actions(nation)` at step 14 drains the action queue through `actions.validate` and the owning module's handler. A **null sovereign** (`ai/sovereign.py` stub, owned here until task 06 replaces it) enqueues nothing.
- `sim/clock.py`: `Clock(speed)`, `speed ∈ {paused, slow, fast, faster, very_fast}` mapping to `{0, 0.1, 0.2, 0.5, 2}` years of simulated time per real second. `tick()` schedules `run_year` on a timer at the current speed; `pause/resume/set_speed`; `auto_pause` is a predicate over this year's events (configurable — e.g. a law passed against the player, a location besieged, a treaty breached, a regression warning). The clock is the only place time-in-seconds exists anywhere in the codebase. Used by task 07; the headless runner ignores it and steps years directly.
- `sim/__main__.py`: `run scenario.yaml --years N --seed S --out ledger.parquet [--until-game-over]`; `summary` of a ledger.

## Acceptance
- `tests/test_finance_meta.py`: `r_market` rises with `r̄` and with lower `J`; a bond-financed war produces no subsistence shortfall in the war year and a service line next year, a tax-financed one the reverse; default zeroes `D` and bondholders' bonds and closes Public Credit for `k` years; a wage tax's incidence table shows `borne_by[LABOURERS] < assessed_on[LABOURERS]` when `π > 0` and equality when the Combination Act is enforced at 1; land tax incidence equals its assessment; a spiral window of `k_spiral` years triggers `resolve`, after which `U_dis < U_crit`, `E ≈ A`, and Tree II nodes remain lit; a nation with no location and no herd ends and its final ledger has every field listed under `end_nation` above; hegemony flags fire at ≥ 0.75, the countdown resets when flags drop below two, and `winners()` can return two different nations on a fixture.
- Scenario: `three_bands.yaml`, `--until-game-over --seed 1..5`, null sovereigns: every seed terminates (game over or all nations ended) within 2,000 years; the ledger has no NaN and value conservation holds every year; at least one seed reaches a manufactory.
- `mypy --strict` and `ruff` clean across the package. Sweep 1 is complete.
