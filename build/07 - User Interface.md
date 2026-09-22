# 07 — User Interface (Sweep 3)

**Read**: 00–06; the ledger schema from 01/05; `core/actions.py`.
**Owns**: `stock/api/*`, `stock/ui/*`.
**Depends on**: sweeps 1 and 2.

## Goal

A browser front end served by the Python application that makes a numbers-only game **legible and beautiful**. The constraint — every piece of in-game text is mechanical effect and numbers only, never prose, verdict, or citation — is the design brief, not an obstacle: the interface has to carry the whole experience through hierarchy, typography, colour, motion, and the shape of the data. The target feeling is *an 18th-century ledger kept by a very good clerk* — calm, precise, warm, and quietly dramatic when something moves.

## Stack

- **Backend**: FastAPI + `uvicorn`; the engine runs in a background task driven by `sim/clock.py`; snapshots and events over a WebSocket (`/ws`); actions POSTed to `/action` and validated by `actions.validate` before enqueue; `/state`, `/ledger/{nation}`, `/scenario`, `/speed`, `/pause`.
- **Frontend**: static HTML + TypeScript compiled to one file, a small reactive store, **Canvas** for map and curves, CSS grid for layout. No framework required. Target 1440×900; must degrade to 1280×800; no mobile.
- All layout data lives in `api/schemas.py`; the JS formats and draws, it does not compute.

## Visual identity — "the ledger"

### Palette (CSS custom properties, `ui/tokens.css`)
| Token | Light ("day ledger") | Dark ("night ledger") | Use |
|---|---|---|---|
| `--paper` | `#F4EFE4` | `#15161A` | page ground |
| `--paper-2` | `#EAE3D3` | `#1E2026` | panels, cards |
| `--rule` | `#CFC6B0` | `#2E313A` | hairlines, table rules |
| `--ink` | `#1E1B16` | `#E8E2D2` | primary text, numbers |
| `--ink-2` | `#6B6252` | `#9A948A` | labels, secondary |
| `--up` | `#2E6F4E` | `#5FBF8F` | increases, gains |
| `--down` | `#9B3B2E` | `#E07A6A` | decreases, losses |
| `--warn` | `#B8862B` | `#E0B04E` | warning band, countdown, breach |
| `--accent` | `#3B5B8C` | `#7FA3E0` | selection, links, the player's nation |

Nation colours: six muted, colourblind-safe inks assigned per scenario — `#3B5B8C` (player), `#8C4A3B`, `#5B7A3B`, `#7A5B8C`, `#8C7A3B`, `#3B7A8C`. Good classes have a fixed emblem glyph and a tint used only in the routes and capital panels: Provisions ochre, Materials umber, Wares indigo, Luxuries crimson, Arms iron-grey, Ships teal, Attendance sepia.

Rule: colour carries **meaning only** — nation, good class, up/down, warn, selection. Nothing is coloured for decoration. The paper carries the aesthetic.

### Typography
- **Numbers**: a humanist sans with **tabular figures** (Inter or IBM Plex Sans, `font-variant-numeric: tabular-nums`). Every number in the game aligns in columns.
- **Headings and labels**: a transitional serif (Libre Baskerville or Source Serif) — the typeface of Smith's own century, used sparingly: panel titles, nation names, the year.
- Scale: year `28px`; headline numbers `22px`; panel titles `16px`; table body `13px`; captions `11px`. Minimum body size `13px`, minimum contrast 4.5:1 in both themes.
- **Number formatting** (`ui/format.ts`, one function): baskets to 3 significant figures with thin-space grouping (`12 400`), shares as `%` to one decimal, rates to two, deltas always signed with an arrow glyph and colour (`▲ +3.2%`, `▼ −140`), zero deltas rendered in `--ink-2` without an arrow. Years are plain integers. Never a raw float.

### Texture and motion
- The page ground is flat colour with a **very faint paper grain** (a 2% noise PNG); panels are flat, separated by hairlines, no shadows, corner radius `2px`.
- The **year tick** is the heartbeat: at each boundary the year numeral does a 120 ms ink-settle (opacity 0.6 → 1), numbers that changed roll to their new value over 300 ms, and the map's changed nodes fade colour over 600 ms. At *very fast* the roll is disabled and only the year ticks.
- Events that auto-pause slide a **ledger card** in from the right (200 ms), paper-2 on paper, hairline-framed. Nothing bounces, nothing glows.
- Sound (optional, off by default): a single soft tick per year; a low tone on auto-pause. No music.

## Layout — three tiers of attention

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ HEADER  year · clock · speed      headline: produce/head  labour share  N̄  A_S │  56px
├────────┬─────────────────────────────────────────────────┬───────────────────┤
│ RAIL   │ STAGE (map | curves | a panel, one at a time)   │ NOW column        │
│ 6 icons│                                                 │ countdown         │
│        │                                                 │ warning band      │
│        │                                                 │ queued actions    │
│        │                                                 │ event feed        │
├────────┴─────────────────────────────────────────────────┴───────────────────┤
│ FOOTER  selected location / nation summary strip · credits                     │  40px
└──────────────────────────────────────────────────────────────────────────────┘
```

1. **Header — always visible.** The year in serif; the clock controls (⏸ ▸ ▸▸ ▸▸▸ ▸▸▸▸, keyboard `space`, `1–5`); the four headline numbers, each with its delta and a **30-year sparkline** beneath it (`--ink-2`, 40×14 px). When the hegemony countdown runs it replaces the sparkline row with a `--warn` bar: nation colour, the two or three flags as small filled squares, years remaining.
2. **Stage — one thing at a time.** The centre shows the map, the curves, or one of six panels, selected from the left rail (`tab` cycles). Never two panels side by side; depth comes from drawers inside a panel, not from crowding.
3. **Now column — what just happened and what is about to.** Countdown (if running), the regression **warning band** (a `--warn` hairline meter filling over `k_spiral` years), **queued actions** as chips ("Enact Enclosure · −14 authority · applies 1723" with an ✕ to withdraw before the boundary), and the **event feed**.

## The map (Canvas)
- Drawn as an **engraved chart**: nodes are circles with a hairline ring in the nation's ink and a fill at 25% opacity; node radius ∝ √population; edges are hairlines, rivers as double lines, coasts as a dotted shoreline, roads as a slightly heavier line. No terrain painting — resources show as small glyphs inside the node on hover and always for the selected node.
- Nation territories are shown by node colour only; a thin dashed hull around each nation's contiguous locations. Contested locations pulse their ring (slow, 2 s) in `--warn`.
- Each nation's label carries three tiny bars (capital, consumption, production world shares) — the hegemony race is always visible on the map.
- Hover: a compact card — resources, records (class · size), producers, the seven prices. Click: select (footer strip fills; actions that target a location become available). Right-click: the location's own ledger drawer.
- Band mode: the player's band is a ringed node with a small tent glyph; herds as a hoof glyph beside it; neighbouring grounds show their `game+grazing × (1−depletion)` number on hover so "move or stay" is a comparison, not a guess.

## Curves
- Three stacked ink plots, shared time axis, all nations as thin lines in their inks with the player's line heavier. The `N̄` band behind curve 1 as a `--warn` wash at 15% opacity. Regression markers are short vertical ticks with a numbers-only tooltip. Legend is the nation list with a toggle per nation. Hovering the axis scrubs a vertical cursor and shows all values at that year in the footer.

## The six panels — density with hierarchy
Common rules: a serif title; a one-line **summary row** of the panel's three most important numbers with deltas; then the table; tables are dense (13px, 28px rows) with hairline rules, right-aligned tabular numbers, sortable headers, and a **drawer** on each row (click → the row's inputs, numbers only). Anything that crosses a threshold this year is tinted: cell background at 12% `--up`/`--down`/`--warn`. Nothing is explained; everything is compared.

1. **Ledger** — records grouped by location; columns size, wealth by asset (a stacked hairline bar), hoard, `A`/`E` as two small bars per tier, `U` with a threshold tint, walk-away, authority. Drawer: the record's consumption split and standing allocation as a two-segment bar (Attendance vs Luxuries).
2. **Incidence** — one card per instrument: rate stepper; assessed-on / borne-by as a paired horizontal bar chart by class (the gap between the bars *is* the lesson); collected and cost; a "lagged one year" caption. Below, the **budget** as a stacked bar with drag handles on the segment boundaries, productive segments in `--ink`, unproductive in `--ink-2` hatch. `debt_choice` appears here as three equal buttons with their numbers.
3. **Capital** — producers by location: stock, jobs filled/total, `V`, and the split as a three-segment bar (labour / profit / rent); return vs `r̄` as a small deviation glyph. A Sankey-style **placement flow** for this year at the top (thin, ink-only). The rate of interest in the summary row.
4. **Politics** — top: `A_S` as a large number beside a horizontal bar chart of the five Interests (authority, with radicalism as a hatched extension). Below: laws in branches as an accordion; each law row shows an **enforcement meter** (hairline bar) and, if dark, its three numbers (support · opposition · `A_S`) and an **Enact** button labelled with the cost. Self-enactments appear with the Interest's ink and a **Veto** button with its cost and the cooldown it buys. The Focus selector is a small card with the node, location, progress meter, upkeep.
5. **Routes and treaties** — routes as rows: the two location names, a paired price strip (seven glyphs, two rows of numbers), capacity, gap, volume, customs; hover a glyph to see both prices large. Treaties as cards with terms, an enforcement meter per side, and a `--warn` "breach" tag when triggered. The hostility matrix as a small heat grid in `--down` tint.
6. **Security** — `M` as a large number with its factors as a chain of small numbers (`units × equipment × doctrine × supply × loyalty`); `PSV`, `PTV_ext`, `PTV_int` by class, `N_r`, `N̄` as a horizontal bar chart around zero; rivals as rows with `M_i`, `h_i`, distance; declare raid/war and peace terms as a form at the bottom with cost shown before submit.

## Actions — draft, cost, boundary
- Every action is **drafted in place** (the button where the thing is), shows its cost next to the button before the click, and on click becomes a chip in the Now column with "applies {year+1}". It can be withdrawn until the boundary. At the boundary the chip resolves: the cost rolls off `A_S` in the header, and the chip becomes an event in the feed. Unaffordable actions are visible but disabled, with the shortfall shown ("needs 14, have 9").
- Confirmations only for irreversible things: declare war, default, veto. Everything else is one click plus the boundary.

## Event feed — the only prose
- Events render through `ui/strings.py`, a string table mapping `kind` → a template of field names and numbers, e.g. `retainer_dismissal: "Retainers −{dismissed} · luxury spending +{delta_lux} · labourers +{added}"`, `law_self_enacted: "{interest} enacts {law} · {authority_I} vs {A_S}+{opposition}"`. Each entry is a hairline card with the year, the nation's ink dot, and a deep link to the panel row it concerns. Auto-pause events open as a **ledger card** in the Now column with the same numbers larger; `Enter` dismisses and resumes.
- A test asserts no template contains `"`, `“`, "Smith", "WoN", "HL ", "§", or the words *should*, *recommend*, *because*.

## Onboarding without narration
- The first year opens **paused** on the map in band mode with three things visible: the band node (selected), the neighbouring grounds' numbers, and the Now column's single card: "Consensus 1.0 · move / stay". Controls are introduced by being the only enabled controls; each newly enabled control gets a one-time hairline pulse. No tutorial text beyond control labels.
- Panels unfold as the seat changes; each newly unlocked panel's rail icon pulses once.

## End of game and final ledger
- A regression is a marker and a card. A nation's end fades its nodes to `--ink-2` and shows the final ledger as a full-stage table in serif headings. Hegemony game over: the two winners' names in serif, each with the number that won; every nation's curves beneath; the final ledger; **Keep playing**.

## Credits
- Paper-2 page, serif, the reading list as titles only — *An Inquiry into the Nature and Causes of the Wealth of Nations*; *Lectures on Jurisprudence*; *The Theory of Moral Sentiments*; Hunt & Lautzenheiser, *History of Economic Thought: A Critical Perspective* — and the palette swatches as a small colophon.

## Accessibility and settings
- Day/night theme toggle; colourblind-safe inks (verified with a deuteranopia simulation); all meaning conveyed by colour also conveyed by glyph or position; keyboard for clock, panels, and drawers; a **density** setting (comfortable 32px rows / compact 24px); reduced-motion honours `prefers-reduced-motion`.

## API schemas (`api/schemas.py`)
Pydantic models: `Snapshot` (everything a panel needs for one nation plus the public world), `Event`, `ActionRequest/Result`, `LedgerRow`, `Curves`, `Sparklines` (the header's four 30-year series). No number on screen exists outside these models.

## Acceptance
- `tests/test_api.py`: `/state` returns a valid `Snapshot`; posting an unaffordable `ENACT` returns 422 with the three numbers; `/speed` changes years-per-second; a WebSocket client receives one `Snapshot` per year and the event list.
- `tests/test_strings.py`: every template references only fields present in the event's `numbers`; the forbidden-token test passes.
- `tests/test_format.py`: `format()` never emits more than 3 significant figures for baskets, always signs deltas, always uses tabular grouping.
- Visual checklist (screenshots committed under `ui/reference/`): header at day and night; map in band mode and with three nations; each panel with a threshold tint visible; a queued action chip; an auto-pause ledger card; the curves with a regression tick; the game-over screen. A reviewer can read every number at 1440×900 without zoom, and no colour appears that is not in the token table.
- Manual play: 200 years at *fast* from a band to a settled nation, one law by spend, one veto, one imposed treaty and its breach, one regression, one game over on `scenarios/late_start.yaml`.
