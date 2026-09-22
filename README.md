# Stock

A turn-based civ-lite about Adam Smith's four stages. The design is in
[Stock - Design Document.md](Stock%20-%20Design%20Document.md); section numbers in code (`§9.6`) point there.

## Run

```bash
.venv/Scripts/python.exe -m stock.launch
```

Opens the game in your browser on a fresh world. `--scenario random:SEED:NODES:NATIONS` replays a world.

## Check

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m tools.sweep --seeds 20
```

`tools.sweep` plays AI-only games and reports the §20 balance targets.

## Layout

| Module | Owns |
|---|---|
| `stock/game/rules.py` | Every content table and tuning number: terrain, works, discoveries, institutions |
| `stock/game/state.py` | The world as dataclasses (deep-copied for forecasts) |
| `stock/game/worldgen.py`, `names.py` | Procedural maps and names |
| `stock/game/economy.py` | Production, the wages/profit/rent split, taxes, consumption, retainers vs luxuries, accumulation, population |
| `stock/game/politics.py` | Clout, Sway, the Seat, institutions, demands, unrest |
| `stock/game/research.py` | Ingenuity, observations, diffusion |
| `stock/game/trade.py` | Contact, fog, barter routes, relations |
| `stock/game/victory.py` | Modes, world shares, hegemony, opulence |
| `stock/game/actions.py` | Every verb, shared by player and AI |
| `stock/game/ai.py` | Rival sovereigns |
| `stock/game/turn.py` | The end-of-turn order (§21.1) and forecasts (§19.5) |
| `stock/game/view.py`, `stock/server.py`, `stock/web/` | Snapshot, HTTP API, browser UI |

## Milestones (§22.3)

| | Status |
|---|---|
| M1 The band | Done: map, fog, bands (hunt, move, split, merge, follow, tame), contact, barter, Sway, discoveries |
| M2 Property and produce | Done: herds, hordes, settling, works and the investment queue, three orders, the split, Extent and DoL, prices, consumption, retainers vs luxuries, modes and moments |
| M3 The state | Mostly done: Chiefdom, Civil Government, five pillars, Treasury, revenue and incidence, budget, Security, Demands, Interregnum, Exile, forecasts. Missing: the other §18 events |
| M4 War | Done: warbands, riders, feudal host, militia, regiments, musketeers; movement, supply and cohesion, battles with odds, sieges and forts, capture (occupy, plunder, raze), raids and casus belli, war, peace, tribute and truce, rebels, war weariness, Security from real defence. Deferred: fleets and blockades (M5, with sea routes), zones of control, debt-funded wars (needs Public Credit) |
| M5 Trade and diplomacy | Barter routes only. Missing: goods flows, caravans, sea routes, blockades, treaties |
| M6 Hegemony and AI | Shares and opulence done. Tribute now exists (the force lever's input); orbits still wait on M5, so hegemony can't trigger yet |
| M7 Polish | UI shell, moments, Commonplace Book done. Missing: onboarding hints, more overlays, curves screen, end screen |
