# Stock

A turn-based civ-lite about Adam Smith's four stages. The design is in
[Stock - Design Document.md](Stock%20-%20Design%20Document.md); section numbers in code (`§9.6`) point there.

## Run

```bash
.venv/Scripts/python.exe -m stock.launch
```

Opens the game in your browser on a fresh world. `--scenario random:SEED:NODES:NATIONS` replays a world.

## Package

```bash
.venv/Scripts/python.exe -m pip install pyinstaller pillow
.venv/Scripts/python.exe scripts/make_icon.py
.venv/Scripts/python.exe scripts/build_exe.py --desktop
```

Builds a windowed app in `dist/Stock/`. With `--desktop` it installs the app to `%LOCALAPPDATA%\Programs\Stock` and puts a **Stock** shortcut with the logo on the desktop. Double-clicking opens the game in the default browser, with no console window. The app quits by itself three minutes after the last game tab is closed, and launching it again while it runs reopens the same game. What it would print goes to `%LOCALAPPDATA%\Stock\stock.log`.

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

## Balance (tools.sweep, 30 AI-only games)

First people leaves Hunting at turn 15 (median); all peoples out of Hunting by turn 45 in every game; someone farming by turn 60 in every game; a manufactory by turn 110 in 97%; at least 6 wars in 53%; hegemony in 37% (target 30–60%); Commerce reached in every game, first at median turn 80. By turn 150 a people knows about 10 of 12 Agriculture-era and 5 of 10 Commerce-era discoveries.

## Milestones (§22.3)

| | Status |
|---|---|
| M1 The band | Done: map, fog, bands (hunt, move, split, merge, follow, tame), contact, barter, Sway, discoveries |
| M2 Property and produce | Done: herds, hordes, settling, works and the investment queue, three orders, the split, Extent and DoL, prices, consumption, retainers vs luxuries, modes and moments |
| M3 The state | Mostly done: Chiefdom, Civil Government, five pillars, Treasury, revenue and incidence, budget, Security, Demands, Interregnum, Exile, forecasts. Missing: the other §18 events |
| M4 War | Done: warbands, riders, feudal host, militia, regiments, musketeers; movement, supply and cohesion, battles with odds, sieges and forts, capture (occupy, plunder, raze), raids and casus belli, war, peace, tribute and truce, rebels, war weariness, Security from real defence. Deferred: fleets and blockades (M5, with sea routes), zones of control, debt-funded wars (needs Public Credit) |
| M5 Trade and diplomacy | Done: goods flows on barter, caravan and sea routes (merchants' profit, carriage, shared import cap), caravans and merchantmen that walk or sail to a foreign town to open a route, Staples & Tolls, Mercantile tariffs, bounties and Navigation Act, Free Trade, blockades by armies and fleets, fleets and naval battle, embargo, gifts, non-aggression, trade pacts, alliances that join defensive wars, broken faith, dependence by partner and for food, the Trade screen, and the Regent |
| M6 Hegemony and AI | Done: public credit (borrow at home or abroad, interest, repay, default, forced default), trade, credit and force levers, orbits and spheres, Ascendancy with a public countdown, the coalition against a leader, Protection treaties, an AI that borrows, lends, protects the weak when ambitious and combines against a leader; Reports screen with everyone's curves and levers, Orbits overlay, end screen. AI games: hegemony 30%, wars median 12, manufactories by turn 110 in 73% (target 90%) |
| M7 Polish | Done: the §18 events (harvest failure, plague, the ingenious workman, enclosure, smugglers, bank crash, wild herds wandering, colonists who can take ship), onboarding hints, Produce and Supply overlays, Demolish, day/night toggle, hotkey help, a fuller Commonplace Book, pop-ups for plague, coalitions and Ascendancy |
