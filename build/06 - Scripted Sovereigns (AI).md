# 06 — Scripted Sovereigns (Sweep 2)

**Read**: 00–05; the `core/actions.py` API from 01 and the cost hooks from 03–05.
**Owns**: `stock/ai/*`.
**Depends on**: sweep 1 complete.

## Goal

Every non-player nation acts through the **same action API** as the player, once per year at step 14, by a policy script chosen from its own politics. The AI never reads anything the player couldn't see and never bypasses `actions.validate`. Rivals must be *interesting*: they settle, arm, trade, bind, and break, and they can win.

## Design

### `ai/sovereign.py`
```python
class Sovereign(Protocol):
    def decide(self, view: NationView, rng) -> list[Action]: ...
class NullSovereign: ...                     # enqueues nothing (sweep 1's stub moves here)
class ScriptedSovereign:
    def __init__(self, scripts: dict[Mode, Script]): ...
    def decide(self, view, rng):             # pick mode → run rules → return affordable actions
```
`NationView` (in `ai/view.py`) is a read-only projection of the nation's own ledger row plus the world's public numbers (every nation's curves, shares, `M`, `h_ij`, treaties, route prices at shared borders) — exactly the UI's information set. The AI does not see other nations' internal ledgers.

### Mode selection — `ai/scripts.py`
Every ten years (and immediately on a seat handover) choose the script by the nation's **dominant Interest** (the Interest with the largest apportioned authority this year, from Doc 03's `politics/authority.py`): LANDED → *landed*; INDUSTRIAL or MERCHANT → *commercial*; no Interests yet (band or herds) → *herding*. A nation can change script mid-run as its ownership changes.

### Rules — each script ≈ 6–8 ordered rules; the first affordable rule whose condition holds fires; up to `max_actions_per_year` fire

**Herding** (band or herd-dominant)
1. If `A_subs < 1` for two years: `BAND_MOVE` to the neighbour with the best `game+grazing × (1 − depletion)`; if none, `BAND_RAID` the richest adjacent band/location where `conquest_allowed`-style odds > 0.6.
2. If wild herds are adjacent and *Domesticated herds* is unlit: `BAND_FOLLOW_HERDS`.
3. If a neighbouring band has `rare` goods and hostility < 0.5: `BAND_BARTER`.
4. Enact *Tamed animal to the tamer* when lit; enact *Herds Heritable* if the largest owner is the seat.
5. Resist settling until grazing depletion averages > 0.6 or an arable location is unowned within one edge; then `BAND_SETTLE` the largest owner record there.
6. Raid any neighbour whose `N̄ < −1` and whose local strength is below ours by `m_conq`.

**Landed** (fields, lords, host)
1. Enact Protection of Property, Land Ownable, Serfdom, Primogeniture when their bar is clear or the gap ≤ 0.2·`A_S`.
2. Block a land tax (veto if self-enacted by another Interest); set revenue to tithe + excise on Wares; farm taxes when service or defence is short.
3. Enclose when Materials price ≥ 1.5× its ten-year mean and *Wool* demand exists on a route.
4. Keep the feudal host; enact Militia Act if `PTV_ext` > `PSV`; never the Standing Army Act unless `R_private == 0`.
5. Impose a **grain guarantee** and tribute on any neighbour beaten in war; demand cession of an arable location.
6. Declare war on a neighbour when `conquest_allowed` and our Landed radicalism > 0.5 (land hunger); accept peace when a contested location has been held two years.
7. Respond to riots with repression if `M_state + host > 2·U_dis`, else Poor Rate.

**Commercial** (towns, stock, ports)
1. Enact Stock Separable, Commutation, Administration of Justice, Free trade, Public Credit when the bar is clear or the gap ≤ 0.3·`A_S`.
2. Standing Army Act once revenue covers pay for `SOLDIERS ≥ 0.02·population`; set the defence draw to hold `PSV ≥ PTV_ext + 0.5`.
3. Focus: public works on the edge that most raises `market_size` for Wares; patent when a Tree II method is lit but idle.
4. Charter a route only when its gap has fallen below `r̄` and the Merchant Interest demands it (let it self-enact; do not veto).
5. Propose a treaty (tariff ceiling on Wares, route access) to any neighbour with `h_ij < 0.4`; impose tariff ceilings and port access at any peace; breach a treaty only if our Industrial Interest would self-enact the tariff anyway (never veto that self-enactment).
6. Fund wars by bonds while `D/revenue < τ_d`; when `debt_choice` fires, ROLLOVER if `r_sovereign < 2·r_market`, else TAX (land tax if Landed is weak, excise otherwise); DEFAULT only if `service > revenue`.
7. Respond to riots with free grain trade first, then Poor Rate, then repression.
8. War: only with casus belli, or when a neighbour holds a Port and `conquest_allowed`; accept peace as soon as the Port is held.

### Common to all scripts
- Never queue an action whose `validate` cost exceeds `A_S − reserve`, where `reserve = 0.2·A_S`.
- Respond to a `breach` against us with a war declaration if `M ≥ 0.8·M_breacher`, otherwise a treaty renegotiation offer.
- Accept a proposed treaty when it lowers `PTV_ext` by more than it costs in `market_size` (estimate with the public numbers).

### Difficulty and personality
- `Params.ai`: `max_actions_per_year` (default 2), `aggression` (scales rule 6/8 thresholds), `patience` (scales the gap tolerances), `reserve`. Presets *cautious / normal / bold*. Personality is a Params override per nation in the scenario file, not code.

## Deliverables
- `ai/view.py`, `ai/sovereign.py`, `ai/scripts.py` (rules as data: a list of `(name, condition: Callable[[NationView], bool], action_factory)`), `ai/heuristics.py` (the small estimators: best neighbour, odds, treaty value), `scenarios/three_bands.yaml` updated to assign `ScriptedSovereign` to nations 2–3 and `NullSovereign` (the player's seat, headless) to nation 1.
- A `stock.sim run --ai all` flag that puts scripts in every seat for balance runs.

## Acceptance
- `tests/test_ai.py`: every action a script returns passes `actions.validate`; the AI never reads a private field (a `NationView` with private fields removed still runs every rule); mode selection follows the dominant Interest on fixtures; the landed script never enacts the Standing Army Act while `R_private > 0`; the commercial script does not veto a Merchant charter self-enactment; a breach against a script nation with superior `M` produces a war declaration next year.
- Balance runs (with 08's harness): 20 seeds × `--ai all`, 600 years: in ≥ 15 seeds at least two nations reach a manufactory; in ≥ 10 seeds a treaty is imposed and later breached; the game reaches hegemony game-over in ≥ 5 seeds and both winners are not the same nation in ≥ 2; no nation ends before year 100 in more than 4 seeds.
