# 08 — Testing, Balancing, and Tuning (cross-cutting)

**Read**: 00; all of 01–07 as they land.
**Owns**: `tests/*`, `tools/*`, `scenarios/*` beyond `three_bands.yaml`, `params/*.yaml` variants.
**Depends on**: starts with 01; extended after every task.

## Goal

Make the simulation trustworthy and the game tunable without reading code: invariants that must hold every year, scenario tests that pin the intended behaviours, a batch runner for seeds and parameter sweeps, and reports that show whether the design goals are being met.

## Deliverables

### Invariants — `tests/test_invariants.py` (run against every scenario in CI)
Per nation per year, from the ledger:
- **Value conservation**: Σ(labour income + profit + rent) == Σ V; Σ income == Σ(consumption + saved); hoards + reinvestment == saved; bonds bought == bonds issued (world).
- **Population conservation**: Σ size across records changes only by births, deaths, migration, war deaths, and conquest transfers (each logged).
- **Shares**: every share in `[0,1]`; ownership shares sum to 1; hostility symmetric.
- **Derived sizes**: RETAINERS/SERVANTS size equals Attendance purchases.
- **Lag rule**: no step reads a field written later in the same year except through `prev` (a static check over step code: forbidden attribute access list per step).
- **No NaN / no negative wealth**; `f(N) ∈ (0,1)`; enforcement in `(0,1)`.
- **Determinism**: same scenario + seed → identical ledger hash.

### Scenario tests — `tests/test_scenarios.py`
Each is a scenario YAML plus assertions on the ledger; these pin the design's intended behaviours:
- **Herds become property**: a band on grassland with wild herds tames them within 120 years and the largest owner takes the seat.
- **Retainer dismissal is emergent**: a landed nation with no Luxuries holds retainers; opening a `rare` workshop or a route dismisses ≥ 50% within 40 years without any law.
- **The Standing Army Act has a constituency**: with `R_private > 0`, merchant records' `N` < landlords'; after the Act, `A_S` rises and merchant `N` rises.
- **Incidence**: land tax borne by landlords ≈ assessed; a Wares excise under a strong Combination Act lands on labourers and raises `U_dis`.
- **Funding hides the cost of war**: identical wars, one taxed, one funded — unrest in the war years is lower under funding and higher `k` years later.
- **Regression to equilibrium**: force a blockade of Provisions; the spiral triggers; after resolution `U_dis < U_crit` and Tree II nodes remain lit.
- **Treaty breach**: an imposed tariff ceiling on a weak-State nation is breached within 30 years; on a strong-State nation it is not.
- **Hegemony**: `scenarios/late_start.yaml` (nations pre-built at different sizes) reaches game over with two distinct winners.
- **Laissez-faire viability**: a nation whose sovereign enacts only Protection of Property and repeals restraints reaches a manufactory within 500 years in ≥ 60% of seeds, with a higher labourer's share at that point than the `commercial` script's mean.

### Batch runner — `tools/batch.py`
`python -m tools.batch --scenario X --seeds 1..N --years Y --ai all --params overrides.yaml --out runs/` → one ledger per run plus `summary.csv` (per run: years to herds/field/manufactory, hegemony year, winners, regressions, ended nations, mean curves). Parallel with `multiprocessing`.

### Parameter sweeps — `tools/sweep.py`
Grid or Latin-hypercube over named `Params` fields; runs `batch`; outputs a table of design-goal metrics vs. parameters and a short report (`report.md`) with the metrics below. Used to tune the defaults in `params/default.yaml`; the tuned values are written back there with a changelog.

### Design-goal metrics — `tools/metrics.py`
- **Emergence**: share of seeds where herds are tamed, fields settled, retainers dismissed, a manufactory built, without any sovereign action (null sovereigns).
- **Divergence of the curves**: correlation between produce per head and labourer's share over a run (the design wants it weak or negative in commerce).
- **Regression frequency**: regressions per 100 years; share of seeds with ≥ 1.
- **Competitiveness**: dispersion of world shares at year 300; share of seeds reaching hegemony by year 600; winner agreement rate.
- **Pacing**: mean years between player-relevant events (law self-enacted, siege, breach, regression warning) — should be 3–8 at *fast*.
- **Stability**: price and hoard oscillation amplitude (cobweb check); a run is flagged if any price oscillates with period 2 for > 20 years.

### Balance runs to gate each sweep
- End of sweep 1: 20 seeds × 1,000 years, null sovereigns: invariants hold; emergence metrics ≥ 0.5 for herds and fields.
- End of sweep 2: the 06 acceptance runs plus competitiveness and pacing targets.
- End of sweep 3: manual checklist (07) plus a 1-hour play session at *fast* logged for pacing.

## Acceptance
- CI runs invariants and scenario tests on every push; `tools/batch` and `tools/sweep` run headless from the command line; `report.md` is produced for the current defaults; `params/default.yaml` has a changelog section.
