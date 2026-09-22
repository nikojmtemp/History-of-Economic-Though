"""Doc 08 cross-cutting tools: batch running, parameter sweeps, design-goal metrics.

Pure with respect to the engine — everything here reads a `Ledger` (or several, from
a batch of seeds) that `stock.sim.year.run_year` already produced. No module here
runs a simulation itself except `batch.py`, which only calls the public
`sim.scenario.load_scenario` / `sim.year.run_year` API.
"""
