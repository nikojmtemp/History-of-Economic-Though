# 00 — Build Plan and Conventions

This folder is a set of **modular build prompts** for implementing *Stock* as a Python application. Each numbered document is self-contained enough to hand to a coding agent as a task: it names its inputs, its deliverables (modules, classes, functions), and its acceptance tests. Read this document first with every task.

## Source of truth

Each numbered document below is **self-contained**: it states every rule, formula, and constant an
agent needs to build its deliverables, in its own words. An agent working a single document should
not need to open the design document or the mathematical model to do its job.

The design document (`../Four Stages - Property, Production, and a Game.md`) and the mathematical
model (`../Stock - Mathematical Model.md`) remain the project's source of truth behind these
documents, and are the record to check against in an **end-of-project or other high-level review
pass** — reconciling the whole implementation against the original design — or if a document here
turns out to be ambiguous or wrong and someone needs to trace a rule back to its origin. Day-to-day
task work does not need them. Where the two source documents disagreed during the writing of these
build docs, the formula (mathematical model) was taken for exact equations and the design intent
was taken for scope and behaviour; any such call is recorded in `DEVIATIONS-RESOLVED.md`.

## The three sweeps

| Sweep | Documents | Outcome |
|---|---|---|
| **1. Backend mechanics** | 01 Core data model · 02 Economy · 03 Politics and unrest · 04 Security, war, trade, treaties · 05 Finance, regression, end condition, year loop | A headless simulation: `stock` package; `python -m stock.sim run scenario.yaml` runs N years and writes a ledger. No UI, no AI beyond a null sovereign. |
| **2. AI for non-player nations** | 06 Scripted sovereigns | Every non-player nation acts through a policy script over the same action API the player uses. |
| **3. UI** | 07 User interface | A browser front end served by the Python app: clock, headline, map, six panels, curves, countdown, credits. |
| Cross-cutting | 08 Testing, balancing, tuning | Scenario tests, invariants, parameter sweeps, a tuning harness. Built alongside sweep 1 and extended in 2 and 3. |

Order within sweep 1 is 01 → 02 → 03 → 04 → 05; each depends on the previous. 08 starts with 01.

## Architecture

```
stock/
  core/        params.py  goods.py  world.py  records.py  producers.py  laws.py  trees.py  actions.py
  engine/      production.py  market.py  wages.py  consumption.py  capital.py  population.py  mobility.py
  politics/    authority.py  interests.py  state.py  legislation.py  justice.py  unrest.py
  security/    military.py  war.py
  trade/       routes.py  hostility.py  treaties.py
  finance/     credit.py  taxation.py
  meta/        regression.py  hegemony.py  scoreboards.py  events.py
  sim/         year.py  clock.py  scenario.py  ledger.py  rng.py
  ai/          scripts.py  sovereign.py
  api/         server.py  schemas.py          (sweep 3)
  ui/          static/…                       (sweep 3)
tests/
scenarios/
```

- **Pure engine.** Everything under `core/`, `engine/`, `politics/`, `security/`, `trade/`, `finance/`, `meta/`, `sim/` is deterministic given a seed, has no I/O, and imports nothing from `ai/`, `api/`, or `ui/`.
- **State is data.** The world is a tree of dataclasses (`World → Nation → Location → Record | Producer`), serialisable to JSON. Steps are functions `step(world, params, rng) -> None` that mutate in place and append to the ledger. No step holds state of its own.
- **Lag rule**: a step reads what earlier steps produced *this* year and last year's value otherwise. Implement by keeping `world.prev` (a shallow snapshot of the scalar fields each step reads lagged) taken at the start of the year; never read a field a later step writes except via `prev`.
- **One place per formula.** Every named formula in the numbered documents below lives in exactly one function named for it (`split_rule`, `average_rate_of_profit`, `perceived_security`, …). Callers call the function; nobody re-derives it.
- **Parameters** are a single frozen dataclass `Params` loaded from YAML (`params/default.yaml`). Each numbered document lists the parameter fields it introduces, with a docstring naming the symbol it stands for; `core/params.py` collects them all. No literal constants in step code.
- **Actions.** The player and the AI use the same `Action` objects (`core/actions.py`), validated and costed by the same code, queued on the nation, applied at step 14.

## Conventions

- Python 3.12, `dataclasses` (or `attrs`), type hints everywhere, `numpy` allowed for vector maths, no pandas in the engine. `ruff` + `mypy --strict` clean. `pytest`.
- Units: value in **baskets**; time in **years**; sizes in **persons**; shares in `[0,1]`.
- Naming: mathematical symbols keep their names in code where legal (`r_bar`, `w_nat`, `A_S` → `state_authority`, `N_bar` → `n_bar`); the mapping is in `core/params.py` docstrings.
- Every step logs what it changed to `ledger`: every scalar in `NationScalars`, the three curves, world shares, class sizes and wealth totals, law states, and events, per nation per year (01 owns the row shape; 05 adds the fields the final-ledger snapshot needs when a nation ends). The ledger is the only output of sweep 1 and the only input of the UI's panels.
- RNG: one `numpy.random.Generator` per world, seeded; steps take it as an argument. Same seed → same run.
- In-game text is produced only in sweep 3, and is mechanical effect and numbers only: no citations, no verdicts, no author, no quotations, no references. The engine emits **event records**, not prose.

## Definition of done, per document

Each document ends with **Acceptance**: tests that must pass and a short scenario that must run. A task is done when its acceptance passes, `ruff`/`mypy` are clean, and the summary lists any place the implementation deviated from this document and why (logged to `build/DEVIATIONS-IN-PROGRESS.md` or `build/DEVIATIONS-UNRESOLVED.md`, per the classification rule at the top of those files).

## How to use these documents as prompts

Give the agent: this document, the numbered document for the task, and the current repository. That is enough — each numbered document is written to stand alone. Do **not** also hand over the design document or the mathematical model; pulling in either one mid-task is a sign the numbered document is missing something and should be corrected instead. Reserve those two source documents for an end-of-project or other high-level review pass across the whole implementation. Ask for the deliverables in the task document only; forbid touching modules owned by other documents except through their public functions. Ask for the deviation list in the summary.
