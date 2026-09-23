# Stock — Design Document (v2)

*Stock* is a turn-based civ-lite about Adam Smith's four stages of society: hunting, pasturage, agriculture, and commerce. You guide one people from a hunting band to a commercial nation, or into a dead end. What your people can own decides the stage they are in. Their economy grows through the division of labour, the extent of the market, and the accumulation of stock. Rival nations are guided by the same rules. The game ends when one nation achieves **hegemony**, holding the world's economy and pulling its neighbours into orbit. If nobody does, it ends with **opulence**: the richest people per head.

The title is Smith's word for capital, and a pun on the herd.

**Status.** This document replaces the first design (*Four Stages — Property, Production, and a Game*), its mathematical model, the build documents `00`–`08`, and the deviation logs. Those are in git history at commit `0950823`. §2 keeps what they taught us. Nothing in the old documents is binding. Where old code happens to fit this design, reuse it (§22).

---

## 0. The pitch in one paragraph

You start as fifty families by a fire. You move your band across a map of connected places, hunt out the game, follow wild herds, and meet neighbours to barter or raid. You tame animals, and herds make the first property, the first inequality, and the first chiefs. You settle a river valley and plant fields. Lords appear, keep retainers, and field armies of their own. You open trade routes. Your lords start buying luxuries instead of keeping retainers, and the men they let go become craftsmen and labourers. Towns grow, the market widens, labour divides, and manufactories rise. Across the whole run you shape institutions, direct investment, research discoveries, move armies from place to place, and compete for hegemony. You never manage individual workers. You set the rules they work under, and you watch the invisible hand go to work or fail to.

---

## 1. Design pillars

These five rules decide every argument about scope. If a mechanic serves none of them, it is cut.

1. **Every mechanic is a decision, a trade-off the player can see, or feedback they can read in one tooltip.** If a system runs identically whether or not a player is present, it is not a game mechanic. It is either a background rule, which must stay invisible and simple, or it gets cut.
2. **You always have a hand on the wheel.** There is a verb on every turn, in every stage, including before the state exists and after it collapses. You play *the society's governing will*, not a king. What that will can do changes as the society changes (§7).
3. **Smith is the engine, not the flavour text.** Each of Smith's core ideas maps to exactly one mechanic that the player can use (§3). The game teaches by letting you win or lose through Smith's logic, not by lecturing.
4. **Show both of Smith's strands, and let the player decide what they mean.** One strand is harmony: the invisible hand and the rising annual produce. The other is conflict: wages, profit, and rent drawn from the same produce. The screen shows both side by side. The game explains mechanisms and never editorializes about which system is better. This matches the course's framing question: *does market exchange harmonize our interests, or conceal a conflict between them?*
5. **Legible over realistic.** Three goods, not seven. Three orders of society, not fifteen classes. Five institution slots, not forty laws. A number that can't be explained in one tooltip line is a number the player never sees.

### Complexity budget (hard caps for v1)

| Thing | Cap |
|---|---|
| Goods | 3 (Food, Wares, Luxuries) |
| Stockpiled resources on the top bar | 5 (Food, Stock, Treasury, Sway, Ingenuity) |
| Orders of society | 3 (Labour, Proprietors, Stock-holders) |
| Institution pillars | 5, one active option each |
| Works (buildings) | 12 |
| Unit types | 9 (including civilian) |
| Discoveries | 36 |
| Nations | 3–6 (default 5) |
| Map nodes | 30–60 (default 45) |
| Turns | 150 |
| Session | 2–3 hours |

---

## 2. What the first build taught us

The first build ran to 1.3 MB of Python with a full test suite. Its deviation logs recorded what went wrong. These lessons are binding on v2:

| Lesson | Evidence | Rule for v2 |
|---|---|---|
| Sequential tech chains deadlock | A nation that never herded could never reach agriculture's next step. Zero manufactories in 2,000 years on any seed. | No discovery depends on a single chain. Prerequisites are webs with OR options, and material conditions only give discounts (§12). |
| When progress is purely emergent, the world plays itself | Null-sovereign worlds matched player worlds. Scenario tests for "retainer dismissal" and "weak state breaches treaty" could not be triggered by any player action. | Every key transition has a player lever. The invisible hand acts *within* rules the player sets. |
| Tiny populations fire huge events | A one-person record's yearly revolt caused regressions 25 years out of 26. | Events and unrest have population-share floors. Nodes have a minimum population. |
| Per-law enforcement formulas churn | Laws fell below minimum enforcement, lapsed, and were re-enacted every few years. | Institutions are on or off, with a phase-in period. No enforcement ratio. |
| Hegemony measured "who settled first" | The countdown started in year 2 with 97% of capital held against two tiny bands. | Hegemony needs production share *and* an orbit of other nations, and it cannot start before turn 50 (§17). |
| Unclamped ratios explode | Prices hit 0 or 900,000 within two years. Satisfaction reached 9,906×. | Every ratio in the model is clamped (§21). |
| A real-time clock was worse than turns | The user replaced it with an "End year" button. | Turn-based. Kept. |
| Procedural maps are the game | Authored maps were demoted to test fixtures. | Kept. |
| Symbol names alienate players | Plain-language labels and tooltips were added late. | Plain language from day one. Every number has a tooltip showing its breakdown. |
| Bands auto-settled on turn one | The opening lasted zero years. | Bands and hordes never move or settle on their own. The player or the AI decides. |
| AI rules rarely fired | 0–1 wars and 0 treaties per 300 years. | AI uses utility scoring with personality weights. CI measures wars, treaties, and routes per 100 turns (§21). |

---

## 3. Smith in the machine

Every idea on this list maps to one mechanic. If an idea is not on the list, it is not modelled.

| Smith's idea | Mechanic | Where the player touches it |
|---|---|---|
| Four stages defined by the mode of subsistence | **Modes**: the largest source of annual produce names the mode. Modes can regress. | The Mode banner. Milestone moments. Mode traits (§8). |
| Property creates government ("the defence of the rich against the poor") | The state (Treasury, taxes, justice) becomes possible only once Proprietors exist | The Council → Chiefdom → Civil Government progression (§7) |
| Division of labour is limited by the extent of the market | **Extent** is one number per market. It multiplies manufacturing and ingenuity. | Roads, rivers, ports, and trade routes all raise Extent (§9.4) |
| Stock (capital) accumulates by parsimony, and only productive labour adds to it | **Stock** is a national pool fed by savings. Retainers and the court consume without adding to it. | Investment queue, Security, luxuries vs. retainers (§9.6, §10.2) |
| Where property is insecure, stock is hoarded | **Security** multiplies how much of savings becomes Stock | Justice spending, defence, order (§9.7) |
| Lords' vanity dissolves feudal power | Proprietors choose between retainers and luxuries. Cheap luxuries dismiss retainers. | Import luxuries or build luxury workshops, and watch the feudal host shrink (§10.2) |
| Wages, profit, and rent are the three original sources of revenue | **Distribution**: every Work splits its output three ways, in a fixed order | The Annual Produce flow chart (§19.3) |
| Profit falls as stock accumulates | The rate of profit falls as Stock grows relative to available opportunities | Shown on the Stock tooltip. Pushes capital abroad or into new Works. |
| Bound labour is the dearest labour | Serfdom lets the player assign workers by hand, at 75% productivity, and serfs cannot work manufactories | Labour pillar (§13) |
| Masters combine easily and workmen cannot | Labour's political weight (clout) is structurally low until Justice or Instruction raise it | Orders panel (§6.3) |
| Taxes fall on someone other than the nominal payer | Each revenue type shows who nominally pays next to who actually pays | Treasury screen (§14) |
| The mercantile system taxes consumers to benefit producers | The Commerce pillar offers Mercantile or Free Trade, with visible winners and losers | §11.4, §13 |
| Shepherd nations are formidable in war, and after firearms standing armies prevail | Unit matchups (§15.3) | Army composition |
| Division of labour dulls the labourer, and instruction is the remedy | **Stupefaction** weakens militia and raises unrest as Extent grows. Instruction offsets it. | Budget: Instruction (§14.3) |
| Funding by public debt hides the cost of war | Wars funded by debt cause less war-weariness now and interest payments later | War financing choice (§15.8) |
| The wealth of a nation is its produce per head | The **Opulence** victory (§17) | End-of-game rankings |

---

## 4. Shape of a session

### 4.1 Turns and time

- **150 turns.** The calendar is flavour and slows down as the game goes on: turns 1–40 are 20 years each, 41–90 are 10 years, and 91–150 are 5 years. The model runs once per turn, and every rate in §21 is per turn.
- **Turn structure:**
  1. **Player phase.** Movement and battles resolve the moment you act. Policy changes, research picks, and queued builds take effect at end of turn.
  2. **AI phase.** Each AI nation acts in turn order, using the same actions and rules as the player.
  3. **Resolution.** The economy, politics, research, and victory checks run in fixed order (§21.1).
  4. **Report.** A turn summary shows what changed and why, with one-click links to the causes.
- **End Turn** is blocked, Civ-style, by pending decisions: an unanswered demand, units without orders (can be dismissed), or no research selected.

### 4.2 The arc

| Phase | Turns (typical) | Player is mostly doing |
|---|---|---|
| **Hunting** | 1–20 | Moving bands, splitting them to spread, exploring, first contact, choosing customs |
| **Pasturage** | 15–45 | Hordes and herds, raiding, tribute, the first chiefs, deciding where to settle |
| **Agriculture** | 35–90 | Fields and lords, forts, the first state and treasury, feudal politics, the first trade routes |
| **Commerce** | 80–150 | Market towns, manufactories, trade networks, institutions and taxes, standing armies, hegemony or opulence |

Nations move through these phases at different speeds, and can go backwards. A nomad empire that never settles can win. Diverging paths are intended.

---

## 5. The world

### 5.1 Nodes

The map is a **graph of 30–60 nodes**, generated procedurally (the existing `worldgen` and planar layout carry over). A node is a region. Each node has:

- **Terrain** (one of six), which sets its base yields:

| Terrain | Game | Grazing | Arable | Other |
|---|---|---|---|---|
| Forest | high | — | low | timber (Wares +) |
| Grassland / steppe | medium | high | low | wild herds common, open ground (Horde bonus) |
| River valley | low | medium | high | river edge(s), easy to reach the market |
| Hills | medium | medium | low | ore common, defender bonus |
| Coast | low (fish: food) | low | medium | harbour possible, sea lanes |
| Marsh / mountain | low | low | — | rough edges, defender bonus, few people |

- **Features** (0–2): *wild herds* (lets you research Taming), *rare* (furs, dyes, wine, salt, or amber, which lets a Workshop make Luxuries), *ore*, *coal* (late game).
- **Population**, counted in **hands**. On screen, one hand reads as 100 people early and scales up with the calendar. The raw hand count is what the player manages.
- **Works** (§9.2), up to a slot cap: 2 + 1 per 5 hands, maximum 6.
- **Owner**: a nation, or *unclaimed*.
- **Depletion** (game only). Hunting depletes the game and resting a node restores it.

### 5.2 Edges

| Edge | Move cost | Connects markets? |
|---|---|---|
| Path | 1 | Only once a Road is built |
| Rough path (marsh, mountain) | 2 | Never, not even with a Road |
| River | 1 | Yes, always |
| Road (built on a path) | 1, +1 bonus move for regiments | Yes |
| Sea lane (coast to coast) | Needs Sail, 1 for fleets | Yes, once both ends have a Port |

### 5.3 Fog and contact

You see your own nodes and everything within one edge of them, plus the endpoints of your trade routes. Everything else shows its last-seen state. Before you can trade, make treaties, or benefit from research diffusion with a nation, you need **contact**: one of your units adjacent to one of theirs, or a node of yours next to a node of theirs.

### 5.4 The start

Each nation starts with one **Band** of 5 hands on a node that has game, near a node with wild herds or arable land. Starting positions are spread apart so that first contact happens around turns 5–12. Everything else starts unclaimed.

---

## 6. People

### 6.1 Hands

Population lives in nodes as hands. Hands are worked by Works and move between nodes as described in §9.5. A node's population grows or shrinks each turn based on how much food it has and how contented its people are (§21). A node never drops below 1 hand. If it would, it is abandoned and becomes unclaimed.

### 6.2 The three orders

Smith identifies three original sources of revenue: wages, profit, and rent. Each has an **order**, a national bloc of people who live by it. Orders are computed each turn from who owns what. They are not tracked per node.

| Order | Lives by | Who they are, by mode | Appears when |
|---|---|---|---|
| **Labour** | wages, or the whole produce when nobody owns the means | Hunters, herdsmen, peasants, serfs, labourers | From the start. At first they are the only order: "rude equality". |
| **Proprietors** | rent from land, or the increase of herds | Herd-owners, then lords and landlords | Herds become property, or land becomes property |
| **Stock-holders** | profit on stock | Merchants, master craftsmen, manufacturers, bankers | The first Workshop, Market Town, or trade route that has a stock owner |

Each order has four values:

- **Size**: the hands whose main income comes from this order's source. Proprietors' size includes their **dependents** (retainers, servants), who are hands taken out of productive work (§10.2).
- **Income share**: that order's slice of the annual produce.
- **Contentment**, 0–100: needs met compared with expectations (§10.3).
- **Clout**: political weight, calculated as wealth share × 0.7 + size share × 0.3 × *organisation*. Organisation is 1.0 for Proprietors and Stock-holders. For Labour it is 0.3, raised by Justice, Instruction, and Free Labour (with combinations allowed). This is the one place where the game encodes Smith's point that masters can combine and workmen cannot.

### 6.3 What orders want

Each order has a short list of preferences over institutions and policy (§13 notes each option's supporters and opponents), plus one standing want:

- **Labour** wants food, then wares, then higher wages.
- **Proprietors** want standing, whether as retainers or luxuries, plus secure title and low land taxes.
- **Stock-holders** want profitable outlets, security, and low barriers to trade (unless an institution protects their own branch).

When an order's contentment is below 35 and its clout is at least 25%, it makes a **Demand** (§18). Demands are the main way society talks back to the player.

---

## 7. The Seat: control with or without a state

You play the society's governing will. The **Seat** is the shape that will takes. It changes as property changes, and you never lose it, even when the state collapses.

### 7.1 Sway

**Sway** is the one political currency for the whole game, capped at 100. Its sources depend on the Seat:

| Seat | Named on screen | Sway comes from | What only this seat can do |
|---|---|---|---|
| **Council** (band) | *Consensus* | +2 base; +1 per contented band; Feasts | Move/split/merge bands; hunt; follow herds; barter; raid; choose customs |
| **Chiefdom** (herds or fields are property, no state yet) | *Prestige* | +2 base; the chief's share of herds; victories; tribute received; Gifts | Everything above, plus Hordes; demand tribute; Gift (spend herds for Sway); settle |
| **Civil Government** (enacted *Magistracy*) | *Authority* | +3 base; contented orders weighted by clout; Justice and Court spending; victories | Treasury, taxes, budget, forts, public works, standing army, public debt, full diplomacy |
| **Interregnum** (collapse) | *Remnant* | +1 base; the order that stays loyal | Chiefdom verbs only, plus **Restore** (§7.3) |

The same verbs cost Sway everywhere: changing an institution, answering or refusing a Demand, declaring war without a casus belli, signing a treaty, repression, embargoes. How much Sway you earn depends on whether society is behind you, measured as contented orders weighted by clout. The practical question is always "who backs me, and how much do I have to spend to overrule them?"

### 7.2 Council and Chiefdom: playing without a state

Before the state exists, you move people, not policies. The band-era verbs are real map play:

- **Band** (a civilian unit carrying 2–10 hands): **Hunt** (camp and produce food; the node depletes), **Move**, **Split** (costs 5 Sway; creates a new band of at least 2 hands; this is how you expand), **Merge**, **Follow the herds** (costs one turn of food; 3 turns spent following wild herds makes Taming cheaper), **Barter** (next to a foreign band or node: opens a Barter route, §11), **Raid** (take food or herds), **Feast** (spend food, ½ per person, for Sway, contentment and a one-turn burst of births, +6% people), **Claim** (make the node yours; needs 2 turns camped).
- **Horde** (a Band once herds are owned): moves with its herds, grazes, and herds grow with it. It can fight while moving (§15). It can **Settle** on arable ground, turning into a Settlement with Fields.
- **Customs**: while in Council, the Property and Labour pillars offer "custom" options: *the kill is shared by custom* or *the kill goes to the killer*. Each has small, clear effects (§13).

Nations can mix modes. A settled core with hordes still roaming the steppe is common and strong.

### 7.3 Collapse and continuity

- **Interregnum.** When Sway hits 0 while an order with at least 30% clout is in revolt, Civil Government falls. Taxes stop, the standing army falls to half and costs full Sway upkeep, and institutions that need a state (Revenue, Standing Army, Public Credit) fall back to their pre-state options. You keep playing with Chiefdom verbs. **Restore** costs 30 Sway and needs one order to be at least 50 contented. It brings back Civil Government, with your earlier institutions available again at half their usual cost.
- **Exile.** If you lose every node, your surviving hands (at least 2) become a **Band or Horde** on the nearest unclaimed node, or in hiding inside the conqueror's land, and your Seat drops to Council. You can wander, rebuild, or wait for a revolt to join. A nation is **eliminated** only when it has no hands left, or after 10 consecutive turns in exile with no free node reachable.

This is the answer to "control when the state doesn't exist": the state is one possible shape of your Seat, not a condition for playing.

---

## 8. Modes: the four stages, visible

The old design hid the stages. v2 puts them on the banner, because players need goals and Smith's stages are the best goal structure this game has.

### 8.1 How the mode is set

Each turn, the annual produce is split into four sources:

- **Hunting**: Hunting Grounds and fishing.
- **Pasturage**: herd increase and Pasture output.
- **Agriculture**: Fields.
- **Commerce**: Workshops, Manufactories, Market Towns, and trade profit.

The **mode** is the largest source. To switch modes, the challenger must lead by at least 10% for 3 consecutive turns. Falling back to an earlier mode works the same way. That is a **regression**. It is not a game over. It gets marked on the curves and triggers a moment.

### 8.2 What each mode gives you

| Mode | Traits (always on while in this mode) |
|---|---|
| Hunting | Every hand can fight (Warbands cost no upkeep). Proprietors cannot exist. Population cap is low (game only). Contentment floor 50. |
| Pasturage | Herds compound. Hordes move 2 and keep herding at half output while mobilised. Raids yield double herds. |
| Agriculture | Fields yield +25%. Forts are possible. Retainers give Proprietors +50% clout. Population cap is high. |
| Commerce | Extent counts double toward division of labour (the DoL multiplier). Luxuries cost 25% less to buy. Stock-holders save 10% more. Stupefaction applies. |

### 8.3 Moments

Your first tamed herd, first field, first town, first retainers dismissed, first manufactory, a mode change, and a regression all trigger a **moment**. A moment is a full-width card with an illustration, one sentence about what just changed in *your* numbers, and a short line from Smith. The first build banned quotations. v2 restores them on purpose: Civ's technology quotes are part of what makes that game memorable, and *The Wealth of Nations* is public domain. Quotes appear on moments and discoveries only, never on warnings or advice.

---

## 9. Economy

### 9.1 Three goods

| Good | What it stands for | Who needs it |
|---|---|---|
| **Food** | Grain, meat, milk, fish: the necessaries | Everyone, 1 per hand per turn. Armies. |
| **Wares** | Cloth, tools, pottery, carts: the conveniences | Labour's comforts, everyone's comforts, building costs, units' equipment |
| **Luxuries** | Fine cloth, plate, wine, furs, dyes | Proprietors' and Stock-holders' standing (§10.2) |

Herds are **stock**, not a good. They produce Food and grow. Arms and ships are not goods either. Units cost Wares and need the right Work somewhere in the nation (a Foundry for firearms, a Port for fleets).

### 9.2 Works

Works are built on nodes and create jobs. The player queues them (§9.6).

| Work | Needs | Jobs | Makes | Paid as | Notes |
|---|---|---|---|---|---|
| **Hunting Ground** | Game (always present, no build) | Any | Food | Whole produce to Labour | Depletes |
| **Pasture** | Taming, grazing | 1 per 10 herds | Food, herd increase | Increase to herd-owners, keep to herdsmen | Grazing caps the herd |
| **Fields** | Tillage, arable | 3 | Food ×3 | Wages → profit → rent | Rotation discovery +50% |
| **Workshop** | Weaving | 2 | Wares; Luxuries if the node is rare | Profit to masters | DoL at half strength |
| **Market Town** | Fairs & Markets | 2 | Extent +3, Ingenuity +2, route slot +1 | Profit | Guilds live here |
| **Port** | Sail, coast | 2 | Food (fish), sea lanes, fleets, route slots +2 | Profit | |
| **Mine** | Metalworking, ore or coal | 2 | Wares; coal for Steam | Wages → profit → rent | |
| **Fort** | Masonry | 0 | Siege time +2 per level (max 2) | — | Public work |
| **Manufactory** | Division of Labour, free labour | 4 | Wares ×4; Luxuries ×2 if configured | Profit | Full DoL |
| **Foundry** | Firearms, Mine in the nation | 2 | Firearms supply for units | Profit | |
| **Academy** | Public Instruction | 1 | Ingenuity +3, offsets Stupefaction | — | Public work |
| **Bank** | Banking | 1 | Stock ×1.1 per turn (circulating capital) | Profit | Crash risk (§18) |

**Roads** and **canals** are edge works (public works, paid from the Treasury): roads connect markets, and a canal turns a path into a river-class edge.

### 9.3 Output

```
output(work) = jobs_filled × base_yield × terrain × discoveries × DoL^m × (0.75 if bound labour)
```

The exponent `m` is 1 for Manufactories, 0.5 for Workshops, and 0 otherwise.

### 9.4 Extent of the market and division of labour

A **market** is a set of connected nodes owned by one nation, joined by rivers, roads, or sea lanes between ports. Most nations have one market. Remote holdings and colonies may form their own.

```
Extent = hands in the market + Σ over routes (0.5 × partner market's hands, capped at route capacity × 10)
DoL    = clamp(1 + 0.6 × log2(Extent / 8), 1, 4)
```

Extent is the most important number in the game. It sits on the top bar, next to Ingenuity. It rises with population, roads, rivers, ports, and trade. Tariffs, war, and blockades shrink it. When a player asks why their manufactories are poor, the answer is always on the Extent tooltip.

**Stupefaction.** In Commerce mode, while DoL is above 2, Labour contentment drops by `(DoL − 2) × 5` and militia strength drops by `(DoL − 2) × 10%`. An Academy in the market, or Instruction spending, cancels this out. That is Smith's remedy, and in this game it costs Treasury.

### 9.5 Who works where: the invisible hand, or not

- **Free labour** (Free Labour institution): each turn, 20% of unfilled or underpaid hands move to the best-paying job in their market. The game shows this as a "moved" arrow. The player **cannot** assign free labourers directly. They can only change what pays: build, trade, and tax.
- **Bound labour** (Serfdom): nobody moves on their own. The player assigns hands to Works by hand, like Civ citizens, at 75% productivity. Serfs cannot staff Manufactories, and population can't migrate.
- **Custom and Guilds**: labour fills the oldest jobs first. Guild Workshops get first pick of craftsmen.

The trade-off is Smith's point, made into a game system: coercion gives you control, and freedom gives you output.

Migration between markets, including emigration to foreign nations with open routes, follows wage differences at 5% of the gap per turn. It is blocked under Serfdom and slowed under Settlement Laws.

### 9.6 Stock and investment

**Stock** is the national pool of productive capital, shown on the top bar. Building a Work costs Stock (costs are in §20). Herds count as Stock in pastoral nations.

- **Savings** come from income (§21): Stock-holders save 70% of profit, Proprietors 30% of rent (plus whatever they cannot spend), Labour 10% of wages above 1.2 × subsistence.
- **Security** turns savings into Stock: `Stock += savings × Security`. The rest is **hoarded**. Hoards are shown and can be plundered, but they build nothing.
- **The rate of profit** falls as Stock grows relative to open opportunities: `r = r0 × sqrt(opportunities / Stock)`, clamped between 0.03 and 0.25. Here, opportunities is the combined value of Works the market could profitably support.

**The investment queue: steering the invisible hand.** The player queues Works on nodes. When Stock covers the cost of the item at the top of the queue, it gets built. Before building, each item is checked for **expected return**:

- **If the return is at or above `r`**, private stock builds it. It costs only Stock, and a ✓ appears in the queue.
- **If the return is below `r`**, investors won't touch it unless the state pays a **bounty**. The Treasury covers the gap each turn for 5 turns, and the queue shows the price in advance.

So if you build what the market wants, it's cheap. If you force a manufactory where there is no market, you pay for it. The player learns the invisible hand by running into it, and the mercantilist alternative has a visible price.

Pre-state, there is no Treasury, so there are no bounties. A chiefdom can only invest in what pays, plus herds.

**Investors choose.** Once **Coinage** is known, the player may leave investment to the Stock-holders (a switch on the Settlements screen, off by default). Each turn, once the player's own queue is served (nothing in it is waiting for Stock), investors build the private work with the best expected return at or above `r`, anywhere the nation holds, up to 2 a turn. They always keep 10 Stock in hand. They never pay bounties or build public works; the player's queue always comes first.

**Capital moves.** Once **Commutation** is also known (land can be sold, so it can be put to a new use), investors facing a town with no free slot may pull down its poorest-paying private work (a pasture with no herds to tend earns nothing) and build in its place a work whose expected return beats `r` and is at least twice the old one's. One such replacement a turn; market towns and ports are never pulled down.

**Demolish.** A work can be pulled down to free its slot; nothing is refunded. This is how a manufactory replaces the workshops of a town that has no room left.

### 9.7 Security

```
Security = clamp(0.55 + 0.3 × justice_level/3 + 0.2 × defence_ratio − 0.2 × disorder + property_bonus, 0.2, 1.0)
```

- `defence_ratio` is your military strength compared with the strongest hostile neighbour, clamped to 0–1.
- `disorder` is the share of nodes in riot or revolt.
- `property_bonus` is +0.1 under Alienable Land or Free Labour, and −0.1 under Tax Farming.

Security appears as a percentage beside Stock: "of every 100 saved, 74 become stock."

### 9.8 Prices

Each market has one price per good:

```
price = base × clamp((demand / supply)^0.7, 0.25, 4)
```

Base prices are Food 1, Wares 2, Luxuries 6, all in baskets. Trade routes move prices toward each other (§11). Prices matter for trade profit, for the choice between luxuries and retainers, and for the value of the annual produce. They are shown in the market tooltip and the trade screen. They are never a separate panel.

---

## 10. Distribution and consumption

### 10.1 The split: wages first, profit next, rent last

The value of each Work's output is split in fixed order:

```
wages  = hands × w,   w = subsistence × (1 + bargaining)
profit = r × stock in the Work
rent   = max(0, value − wages − profit)          (land Works; otherwise the remainder goes to profit)
```

**Bargaining** ranges from 0 to 1.5. It rises when jobs outnumber hands and falls when hands outnumber jobs. Institutions shift it: Guilds give +0.2 for craftsmen, Combinations Allowed gives +0.2, Poor Laws give a +0.1 floor. Under Serfdom it is 0.

Who receives rent depends on the Property pillar. Under Common Use it goes to Labour. Under Herds to the Tamer, herd increase goes to Proprietors. Under either land option, rent goes to Proprietors.

### 10.2 Standing: retainers or luxuries

This is the best mechanic in the old design, simplified.

After Proprietors meet their own food and wares needs, what's left of their income is their **standing budget**. They spend it one of two ways:

- **Retainers**: they take hands out of productive work and feed them. Each retainer costs 1 Food per turn. Retainers raise Proprietors' clout (+50% in Agriculture), become levies in the Feudal Host, and reduce the Seat's Sway (`−0.5 × ln(1 + retainers)`), because private power competes with public power.
- **Luxuries**: they buy from the market, whether domestic output or imports.

```
share spent on luxuries = clamp(luxury_availability × vanity, 0, 1)
luxury_availability     = (luxury supply in the market) / (Proprietors' standing budget / luxury price)
vanity                  = 0.6 at first, rising to 1.6 as Luxuries have been available for 10 turns
```

With no luxuries on offer, the whole standing budget goes to retainers, and the surplus feeds armed dependents. When luxuries arrive, retainers are **dismissed**. They go back to the labour pool as productive hands, the feudal host shrinks, and the Seat's Sway rises. The first time a turn's dismissals exceed 20% of retainers, a moment fires.

The player controls this through what they import, where they put Workshops (rare nodes), and whether they tax luxuries. It is the whole of Smith's Book III, as a lever.

### 10.3 Needs, expectations, contentment

Each order has needs in tiers. Tiers are **satisfied** as the ratio of met to needed, and the three ratios are averaged with the weights shown:

| Tier | Labour | Proprietors | Stock-holders | Weight |
|---|---|---|---|---|
| Subsistence | 1 Food/hand | 1 Food/hand | 1 Food/hand | 8 |
| Comfort | 0.5 Wares/hand once wages exceed subsistence | 1 Wares/hand | 1 Wares/hand | 2 |
| Standing | — | Standing budget met (§10.2) | 0.3 Luxuries/hand | 0.5 |

Expectations follow satisfaction. They rise quickly and fall slowly, like a ratchet:

```
E' = E + 0.3 × max(0, S − E) − 0.1 × max(0, E − S)
contentment = clamp(50 + 100 × (S − E), 0, 100)
```

Long periods of plenty teach people to expect plenty. A stalled economy produces unrest even without a decline. Recovering from a low point is cheap.

### 10.4 Unrest

Each node has Unrest from 0 to 100. It is driven by Labour's contentment in that node (food shortfall counts double), plus: a node recently conquered (+30, fading over 10 turns), Stupefaction, heavy taxes, and war-weariness.

| Unrest | Effect |
|---|---|
| > 40 | **Strikes / disorder**: output −25%, Security falls |
| > 70 | **Riot**: output −50%. Emigration doubles. |
| > 90 for 2 turns | **Revolt**: a Rebel unit spawns (§15.7) |

Events fire only if the node holds at least 2 hands *and* at least 3% of the nation's population (lesson from §2).

---

## 11. Trade

### 11.1 Routes

A **route** links two different markets: a foreign market, or your own separate colony.

- **Barter route** (band era): opened by the Barter verb between adjacent bands or nodes. Capacity 1, and it closes if either side moves away.
- **Caravan route**: send a **Caravan** unit (costs 10 Stock) from a Market Town to a foreign node you have contact with, along land edges. It opens on arrival. Capacity 3.
- **Sea route**: send a **Merchantman** (costs 20 Stock) from a Port to a foreign Port over sea lanes. Capacity 5.

Route slots are limited by Market Towns and Ports (§9.2). Bills of Exchange give +50% capacity.

### 11.2 What a route does each turn

1. **Goods flow** from the cheaper market to the dearer one, one good at a time, up to capacity, until the price gap closes to carriage cost (10% per edge, or 3% by sea). Flows are worked out from last turn's prices and surpluses. A market takes at most 60% of its demand from abroad, across all its routes.
2. **Profit** (price gap × volume) goes to the route owner's Stock-holders. Customs go to the Treasury under the Commerce pillar (§13).
3. **Extent** rises in both markets (§9.4).
4. **Relations** rise by 1 per turn, up to 50: trade makes friends, not allies. **Research diffusion** strengthens (§12.3).
5. **Dependence** is recorded: what share of each partner's consumption this route supplies. Dependence feeds orbits (§17.2).

### 11.3 Breaking routes

War closes all routes between the belligerents. A fleet on a sea lane, or an army on a route's endpoint, **blockades** it. Embargo is an action (10 Sway) that closes routes with one nation. A closed route that was supplying Food causes a food shock the next turn. Players should feel what dependence means.

### 11.4 Trade policy

Trade policy is set by the Commerce pillar (§13): tariffs, bounties, navigation acts, chartered companies, or free trade. Each shows its winners and losers in the preview. For example: "Mercantile: domestic Wares +12% price; Workshops' return +3%; Labour comfort −6%; route capacity −30%; partner relations −1/turn."

---

## 12. Discoveries: the interactive tech web

### 12.1 Ingenuity

**Ingenuity** is the research currency, and it grows with the division of labour. Smith credits invention to specialists: workmen, and "philosophers or men of speculation".

```
Ingenuity per turn = 0.1 × hands + 1 per Workshop + 2 per Market Town + 3 per Academy
                     + (DoL − 1) × 2 + 1 per trade route
```

### 12.2 Structure

Thirty-six discoveries are laid out in **four era columns** (Hunting, Pasturage, Agriculture, Commerce) and **four lanes**:

- **Subsistence**: how we produce.
- **Exchange**: how we trade and hold capital.
- **Force**: how we fight.
- **Order**: how we're governed.

Each discovery has:

- **Knowledge prerequisites**: at most two, and whenever possible either one will do (OR). There are no single-chain dependencies.
- **An Observation**: a material condition in the world, such as "have followed wild herds for 3 turns" or "Extent ≥ 40". Meeting it **halves the cost**. Observations are never hard gates. The only hard limits are physical: you can research Sail with no coast, but you can't build a Port without one.
- **Unlocks**: Works, units, institution options, verbs.
- **Cost** by era: 20, 45, 90, and 160 Ingenuity.

### 12.3 Diffusion

Each contacted nation that already knows a discovery cuts its cost by 10%. Each trade route with such a nation cuts it by another 10%. The total discount is capped at 60%. Knowledge travels along trade routes. That makes isolation expensive and gives trade a second payoff.

### 12.4 The web

| Era | Lane | Discovery | Observation (halves cost) | Unlocks |
|---|---|---|---|---|
| I | Subsistence | Tracking *(known)* | — | Hunt, Move |
| I | Order | Kin & Custom *(known)* | — | Customs options |
| I | Subsistence | **Taming** | Followed wild herds 3 turns | Pasture, Horde, *Herds to the Tamer* |
| I | Exchange | **Barter** | Met another people | Barter routes, Gift |
| I | Force | **Ambush** | Won a skirmish | Warband +1 strength |
| I | Subsistence | **Fishing** | Band on a coast | Coast food +1 |
| I | Order | **Elders' Council** | 3 bands | Feast gives +1 Sway; Split costs 3 |
| II | Force | **Horsemanship** | 20 herds | Horse Horde (move 3) |
| II | Subsistence | **Weaving** | A Pasture | Workshop |
| II | Subsistence | **Tillage** | Band camped on arable river node | Fields, Settle |
| II | Order | **Chieftainship** | Proprietors exist | Demand tribute, Chiefdom verbs |
| II | Force | **Tribute** | Won a raid | Tribute peace terms |
| II | Subsistence | **Metalworking** | Own an ore node | Mine, +1 strength for all units |
| II | Exchange | **Gift & Hostage** | Relations > 50 with anyone | Non-aggression pacts |
| III | Subsistence | **Rotation** | 3 Fields | Fields +50% |
| III | Order | **Land Tenure** | Fields on 3 nodes | *Entailed Land*, *Serfdom* |
| III | Order | **Magistracy** | Proprietors' clout ≥ 40% | **Civil Government**, Treasury, Revenue pillar, Justice |
| III | Force | **Masonry** | A node besieged | Fort, Walls |
| III | Force | **Feudal Tenure** | Retainers ≥ 5 hands | *Feudal Host* |
| III | Exchange | **Coinage** | 2 routes | Customs, Market prices shown; Tax Farming |
| III | Exchange | **Fairs & Markets** | Extent ≥ 20 | Market Town, Caravan |
| III | Subsistence | **Sail** | Own a coast node | Port, Merchantman, sea lanes |
| III | Order | **Guilds** | 3 Workshops | *Guilds* |
| III | Order | **Commutation** | Rent ≥ 30% of produce | *Alienable Land*, money rents |
| III | Force | **Militia Drill** | Stock-holders ≥ 15% of hands | *Militia* |
| III | Exchange | **Mercantile System** | A route into deficit | *Mercantile* commerce, bounties |
| IV | Exchange | **Bills of Exchange** | 4 routes | Route capacity +50% |
| IV | Subsistence | **Division of Labour** | Extent ≥ 40 | **Manufactory** |
| IV | Exchange | **Navigation** | 2 Ports | Ocean lanes, Colonists |
| IV | Force | **Standing Army** | Treasury ≥ 50 | *Standing Army*, Regiments |
| IV | Force | **Firearms** | A Mine | Foundry, Musket regiments |
| IV | Exchange | **Banking** | Stock ≥ 200 | Bank, Public Credit |
| IV | Order | **Public Credit** | A deficit | Borrowing (§14.4) |
| IV | Order | **Natural Liberty** | Free Labour enacted | *Free Trade*; institution changes −25% Sway |
| IV | Subsistence | **Machinery** | 2 Manufactories | Manufactory +50% |
| IV | Order | **Public Instruction** | Stupefaction active | Academy, Instruction budget line |

(Chartered Companies, Steam, and Canals are post-v1. See §22.)

### 12.5 The tech web screen

- A full-screen, pannable web with era columns and lane rows. It uses the existing ledger aesthetic: ink lines on paper.
- Each card shows cost, turns at the current rate, the Observation (✓ met, or a progress bar), unlock icons, and badges for contacted nations that already know it (with their diffusion discount).
- **Click** to research. **Shift-click** a distant node to queue the cheapest path to it, highlighted. Hovering shows what the discovery changes *in your nation*, for example "Fields +50% → Food +18/turn".
- Completing a discovery triggers a moment with its quote.

---

## 13. Institutions: five pillars

Every nation has five **pillars**, and exactly one option is active in each. It works like choosing a government in Civ. This replaces the forty laws, Interest demand tables, and per-law enforcement ratios of the old design.

**Changing an option costs Sway:**

```
cost = 10 + 30 × (clout share of opposing orders) − 10 × (clout share of supporting orders)    (minimum 0)
```

- The change **phases in over 2 turns**, and the old option's effects fade out over the same 2 turns.
- The same pillar can't change again for 5 turns.
- The preview shows the full one-turn forecast before you commit (§19.5).

| Pillar | Option | Needs | Effect | Supports | Opposes |
|---|---|---|---|---|---|
| **Property** | Common Use *(start)* | — | All output goes to Labour. No Proprietors. | Labour | — |
| | Herds to the Tamer | Taming | Herds become Proprietors' stock. Herd growth +20%. | Proprietors | Labour |
| | Entailed Land | Land Tenure | Rent goes to Proprietors. Land can't be sold. Field improvement is slow. | Proprietors | Stock-holders |
| | Alienable Land | Commutation | Stock can buy estates. Field yield +1%/turn up to +25%. Security +0.1. | Stock-holders | Proprietors (old) |
| **Labour** | Kin & Custom *(start)* | — | Oldest jobs fill first. No wage bargaining. | — | — |
| | Serfdom | Land Tenure | Bound labour: player assigns workers, 75% productivity, no migration, no Manufactories. Proprietors' rent +20%. | Proprietors | Labour |
| | Guilds | Guilds | Workshop output +20%. Manufactories cost double in Market-Town nodes. Craftsmen bargaining +0.2. | Stock-holders (masters) | Stock-holders (manufacturers), Labour |
| | Free Labour | Commutation | Invisible-hand allocation. Full productivity. Migration. | Stock-holders | Proprietors |
| | Free Labour + Poor Laws | Free Labour | As Free Labour, plus a wage floor (+0.1 bargaining) paid from rent. Migration −50% (settlement). | Labour | Proprietors |
| **Commerce** | Barter *(start)* | — | Barter routes only | — | — |
| | Staples & Tolls | Coinage | Treasury +10% of route profit. Route capacity −20%. | Proprietors | Stock-holders |
| | Mercantile System | Mercantile System | Tariffs: imported Wares and Luxuries +30% price. Bounties on exports, paid by the Treasury. Navigation: foreigners can't open sea routes into you. | Stock-holders (domestic) | Labour, partners |
| | Free Trade | Natural Liberty | No tariffs. Route capacity +30%. Extent from routes ×1.5. Partner relations +1/turn. | Stock-holders (merchants), Labour | Stock-holders (protected), Proprietors |
| **Revenue** | Gifts & Plunder *(pre-state)* | — | Tribute and raids only | — | — |
| | Feudal Dues | Magistracy | Tax on rent, collected by lords. Efficiency 50%. | Proprietors | Labour |
| | Tax Farming | Coinage | Efficiency 90% now, 30% skimmed by Stock-holders. Unrest +10. Security −0.1. | Stock-holders | Labour |
| | Excise on Necessaries | Magistracy | Tax on Food and Wares. Incidence shifts by bargaining (§14.2). | — | Labour |
| | Land Tax | Commutation | Tax on rent. Doesn't shift. Efficiency 85%. | Stock-holders, Labour | Proprietors |
| | Customs | Coinage | Tax on routes. Smuggling above a moderate rate. | Proprietors | Stock-holders (merchants) |
| **Defence** | Every Man a Warrior *(start)* | — | Warbands (§15) | — | — |
| | Nation in Arms | Taming | Hordes | Proprietors (herd) | — |
| | Feudal Host | Feudal Tenure | Levies raised from retainers, free to the state. Proprietors can refuse to muster if contentment < 35. | Proprietors | Stock-holders |
| | Militia | Militia Drill | Cheap part-time units. Stupefaction weakens them. | Labour, Stock-holders | Proprietors |
| | Standing Army | Standing Army | Regiments paid by the Treasury. Drill improves them over time. | Stock-holders | Proprietors |

In the Council seat, Property and Labour show their customs as the **starting** choice between *Shared by custom* and *Kill to the killer*. *Kill to the killer* gives hunting +10% but lets Proprietors appear one era early once herds exist. Everything else is locked until the state exists. Pillars never lock you out of the game.

---

## 14. The state's purse (Civil Government only)

### 14.1 Revenue

```
revenue = base(Revenue option) × rate × efficiency × (0.5 + 0.5 × justice_level/3)
```

Rate is Light, Moderate, or Heavy: 0.05, 0.10, or 0.18 of the base. Each step up adds unrest (+5 or +15) and raises the cost of evasion. Revenue rises with the rate up to a peak, which differs by base, and then falls. The tooltip shows the curve.

### 14.2 Who really pays

The Treasury screen shows two bars per order: **nominal** (who hands over the money) and **actual** (who ends up poorer next turn after wages, prices, and investment adjust).

| Revenue | Nominal | Actual |
|---|---|---|
| Excise on Necessaries | Labour | Labour keeps `(1 − bargaining/1.5)` of it. The rest raises wages and comes out of profit (70%) and rent (30%). |
| Land Tax | Proprietors | Proprietors |
| Customs | Importers (Stock-holders) | Consumers of the taxed good, in proportion to who buys it |
| Feudal Dues | Proprietors | Labour (through rent squeezed from them) 60%, Proprietors 40% |
| Tax Farming | Everyone | As excise, plus 30% taken by Stock-holders who farm it |

This is the old incidence lesson with one line of arithmetic per tax, and it's the kind of thing players remember: a sovereign who can't tax rent ends up taxing bread, and the cost comes back as riots.

### 14.3 Spending

Spending lines are set as levels 0–3, not sliders:

| Line | Cost per level (per turn) | Effect per level |
|---|---|---|
| **Army** | Automatic: sum of unit upkeep | — |
| **Justice** | 2 per 10 hands | Security +0.1. Labour organisation +0.1. Revenue efficiency up. Unrest −5. |
| **Public Works** | Build items: roads, canals, forts, academies | Placed on the map |
| **Instruction** | 1 per 10 hands | Cancels Stupefaction by 1/3. Ingenuity +2. |
| **Court** | 3 | Sway +2. Standing sink for the Treasury. |
| **Bounties** | Automatic, from the investment queue (§9.6) | — |
| **Debt service** | Automatic | — |

A deficit draws down the Treasury. If the Treasury is empty and the deficit continues, the player must choose: borrow (with Public Credit), cut spending, or let the army's pay fall into arrears, which makes cohesion drop.

### 14.4 Public debt

Public debt requires Public Credit. You can borrow up to 5 turns of revenue per turn, from one of two sources:

- **Domestic Stock-holders**: this reduces national Stock (crowding out) and pays interest to Stock-holders, raising their contentment and clout.
- **A foreign nation's Stock-holders** (with a Loan treaty): this brings in Stock from abroad, and creates a **credit lever** (§17.2) for the lender.

Interest is `r + risk`, where risk rises with debt / revenue. **Default** wipes the debt. Stock-holders' contentment drops by 40. Relations with foreign lenders drop by 50. Credit is closed for 10 turns, and the nation loses 15 Sway.

---

## 15. War

War is map play. Armies are stacks of units on nodes, moved along edges.

### 15.1 Units

| Unit | Needs | Raised from | Cost | Upkeep/turn | Move | Strength | Notes |
|---|---|---|---|---|---|---|---|
| **Band** (civilian) | — | — | Split | Food | 1 | 1 | Carries hands. §7.2. |
| **Warband** | Every Man a Warrior | 1 hand | — | Food only | 1 | 3 | Its hand stops hunting while mobilised |
| **Horde** | Nation in Arms | 2 hands + 10 herds | — | Food | 2 | 6 | Keeps herding at half output. Raids ×2. |
| **Feudal Host** | Feudal Host | 2 retainers | Free to the state | Proprietors pay | 1 | 4 | Disbands after 4 turns (seasonal). Can refuse to muster. |
| **Militia** | Militia | 2 hands | 5 Wares | 1 Food | 1 | 5 | −Stupefaction. Hands go back to work when it disbands. |
| **Regiment** | Standing Army | 2 hands | 10 Wares, 10 Treasury | 2 Food, 3 Treasury | 1 (+1 on roads) | 7, +1 per 5 turns of drill (max +3) | |
| **Musket Regiment** | Firearms + a Foundry | Upgrade a Regiment | +10 Wares | +1 Treasury | 1 (+1 on roads) | 10 | |
| **Fleet** | Port | — | 20 Wares, 10 Treasury | 3 Treasury | 3 (sea) | 6 at sea | Blockade, escort, transport |
| **Caravan / Merchantman / Colonists** (civilian) | §11, Navigation | — | Stock | — | 2 / 3 / 3 | 0 | Colonists found a node overseas with 2 hands |

Every military unit except the Fleet takes hands out of production while it exists. That is the central trade-off of war.

### 15.2 Movement and supply

- Units have move points and edges cost move points (§5.2). Entering an enemy-held node ends the move.
- **Supply.** A node supports `2 + its Food output / 2` units without trouble. Units beyond that, or in enemy territory more than 2 edges from a friendly node, lose 15 cohesion per turn. Hordes forage and ignore the 2-edge rule on grassland.
- **Zones of control.** An enemy army on a node stops your movement through it.

### 15.3 Combat

A battle happens when your army enters a node that holds an enemy army. You see the odds before you commit.

```
power = Σ strength × cohesion% × matchup × terrain × fort × supply
result: casualties to both sides ∝ enemy power; the loser retreats to an adjacent friendly node or is destroyed if it can't
luck: ±15% on each side's power
```

**Matchups** (attacker vs. defender multipliers) follow Smith's history of war:

| | vs Warband | vs Horde | vs Host | vs Militia | vs Regiment | vs Musket |
|---|---|---|---|---|---|---|
| **Horde** | 1.5 | 1.0 | 1.3 (open) / 0.8 (hills, fort) | 1.3 | 1.0 | 0.6 |
| **Host** | 1.3 | 0.8 | 1.0 | 1.0 | 0.8 | 0.6 |
| **Militia** | 1.3 | 0.8 | 1.0 | 1.0 | 0.9 | 0.7 |
| **Regiment** | 1.5 | 1.0 | 1.2 | 1.2 | 1.0 | 0.8 |
| **Musket** | 1.8 | 1.5 | 1.5 | 1.5 | 1.2 | 1.0 |

In short: nomads outclass the early settled world, especially in the open. Settled peoples hold them off with forts and hills. Standing armies prevail once firearms arrive.

### 15.4 Sieges and capture

- An undefended node without a Fort is **captured** when you enter it. A settlement's own people turn out to defend it (strength 0.5 per hand), but not for a conqueror: a lately conquered town must be garrisoned or it is easily retaken.
- A node with a Fort must be **besieged**: 2 turns per Fort level, during which the besieger takes attrition, and the defender's hands and food stores run down.
- **On capture**, choose one:
  - **Occupy**: the node becomes yours with its hands and Works. Unrest is +30 for 10 turns (fading).
  - **Plunder**: take its Stock share, hoards, and herds. Damage one Work. Unrest +50.
  - **Raze**: only for nodes of 3 hands or fewer. It becomes unclaimed.

### 15.5 Raids

Warbands and Hordes can **Raid**: enter an enemy node, take Food, herds, or a slice of hoards, then leave the following turn without capturing. Raids are the pastoral economy's second income, and a constant pressure on settled neighbours before forts exist.

### 15.6 War declaration, casus belli, war score

- Peace brings a **truce** of 15 turns between the two peoples: neither can declare war on the other until it ends.
- Declaring war costs 15 Sway, or 0 with a **casus belli**. You get a casus belli when they raided you, broke a treaty, blockaded you, or embargoed you. A Coalition against the hegemon also has one (§17.4).
- **War score** comes from nodes held, battles won, and blockades. It decides which peace terms the other side will accept (§16).

### 15.7 Rebels

A revolt spawns a **Rebel** army of `node hands / 3` units at strength 4. If it holds its node for 3 turns, the node **breaks away** as a free node, or joins an adjacent nation of the order's liking. Rebels can be fought, bought off (answer their Demand), or ignored at the cost of more unrest.

### 15.8 Paying for war

War-weariness is added to all orders' unrest: `+1 per turn at war + 2 per unit lost + (tax rate increase since the war began) × 20`. Wars funded by public debt skip the tax term. They feel cheap now and cost interest for years afterwards. The Treasury screen shows this in a war summary: "This war: 140 paid, 310 borrowed, 22/turn interest for 14 turns."

---

## 16. Diplomacy and the AI

### 16.1 Relations and treaties

Relations run from −100 to +100. They move with trade routes (+), shared enemies (+), raids (−), border tension (−), and hegemony fear (−, §17.4).

| Treaty | Cost | Effect |
|---|---|---|
| Peace | — | Ends a war. Terms can include cession of nodes, tribute (N turns), reparations (Stock), or open markets. |
| Non-aggression | 5 Sway | Breaking it gives the victim a casus belli and relations −50 |
| Trade Pact | 5 Sway | Tariffs waived between the two. Route capacity +25%. |
| Alliance | 10 Sway | Defensive: when one is attacked, the other joins the war. Allies share vision. Peoples ally only against a common enemy. |
| Protection | 5 Sway | Offered by the stronger side: the protected people pay 5% of their produce each turn, and the protector joins any war against them. Creates a **force lever** (§17.2). The weak accept when threatened. |
| Loan | — | One side lends Stock at interest. Creates a **credit lever**. |

### 16.2 AI

- **Same rules, same actions.** No bonuses on normal difficulty. Higher difficulties give better utility weights and more actions per turn, not free resources.
- **Personality** comes from the nation's mode and dominant order:

| Mode / order | Personality | Leans toward |
|---|---|---|
| Hunting | **Wanderer** | Split, explore, barter, skirmish |
| Pasturage | **Khan** | Raid, tribute, horde conquests, settling late |
| Agriculture + Proprietors | **Lord** | Land hunger, forts, feudal host, serfdom, customs revenue |
| Commerce + Stock-holders | **Merchant** | Routes, trade pacts, navy, loans, standing army, free trade or mercantile |

- **Decision method.** Each turn, the AI scores its available actions with a utility function: expected change to its produce and its hegemony progress, weighted by personality. It then takes the best actions until it runs out of move points and Sway.
- **Guaranteed behaviours.** Every AI answers peace offers and treaty proposals. It re-evaluates wars every turn. It opens at least one route within 15 turns of getting a Market Town. It joins coalitions against a hegemon (§17.4).

---

## 17. Victory

### 17.1 Two ways to win

**Hegemony** (dominance, and Smith's conflict strand) comes from the size of your economy plus an orbit of dependent nations.

**Opulence** (per-head wealth, and Smith's harmony strand) is scored at turn 150. The winner is the nation with the highest **produce per head** among nations that are sovereign (in nobody's orbit) and have at least 25% of the average population. If every nation is in someone's orbit, the orbit condition is dropped.

The tension from the old design is still here. A small, rich, free nation can win on opulence while a big empire chases hegemony. And a hegemon's orbit disqualifies its satellites from opulence.

### 17.2 Orbits

Every turn, each nation's **levers** over each other nation are measured:

| Lever | Held by A over B when |
|---|---|
| **Trade** | A's routes supply at least 25% of B's consumption of any one good, *or* at least 15% of B's total consumption value |
| **Credit** | B owes A more than 5 turns of B's revenue |
| **Force** | B pays A tribute or protection, *or* A occupies at least 25% of B's nodes |

B is **in A's orbit** if A holds at least one lever over B. If several nations hold levers, B is in the orbit of the one with the strongest. Lever strength is how far past its threshold the lever is. Orbits are never mutual: B cannot orbit A if B's lever over A is as strong. A nation's **sphere** is its orbit plus its satellites' satellites, and hegemony counts the sphere. The trade lever is a running average of dependence over several turns, so one turn's flows neither make nor break an orbit. The map's Orbit overlay draws these as lines. B sees its own dependence on a meter, with what it would take to break free: diversify imports, repay the debt, or win the war.

### 17.3 Hegemony

A nation holds **Ascendancy** when:

1. it produces at least **40%** of the world's annual produce (among living nations), *and*
2. at least **half of the other living nations** (rounded up) are in its orbit, *and*
3. it is turn 50 or later.

While Ascendancy holds, a **10-turn countdown** runs, visible to everyone. If a condition fails, the countdown **pauses**. If a condition fails 3 turns in a row, it **resets**. When the countdown reaches 0, that nation wins. Conquering everyone also wins, trivially.

### 17.4 The balance of power

Once a nation's countdown starts, every other nation gets:

- a **Coalition** casus belli against it,
- relations +20 with each other,
- and an AI utility bonus for breaking orbits: opening rival routes, repaying debts, making war.

The leader has to hold on for 10 turns while the world closes in.

### 17.5 End screen

The end screen names the winner and how they won. It also shows every nation's **three curves** as a report card, not a score:

- produce per head,
- **labour's share** (wages as a share of produce),
- the **freedom index** (share of hands in free labour).

It ends with the option to **Keep playing**.

---

## 18. Events and decisions

Events are the other way society talks to you, besides Demands. Each is a card with 2–3 choices and the effect of each. At most one new card a turn, from turn 15. Plague is rare (0.6% a turn, doubled at most by trade) but takes 10–25% of the people. Before Civil Government a failed harvest simply costs food: there is no Treasury to answer it.

| Event | Trigger | Choices |
|---|---|---|
| **Demand** | Order contentment < 35 and clout ≥ 25% | **Grant** (enact their option at 0 cost) · **Refuse** (Sway −10, their unrest +10) · **Repress** (needs an army in the capital: Sway −5, unrest −20 now, contentment −15 and E unchanged) |
| **Harvest failure** | Random, per node, weighted to Fields | **Open the grain trade** (import at cost) · **Price cap** (supply −20%, unrest now −10) · **Relief** (Treasury, from rent) |
| **Plague** | Random, more likely with many routes | Lose 10–25% of hands. Wages rise and bound labour cracks (Serfdom costs +20 Sway to keep for 10 turns). |
| **An ingenious workman** | Manufactory or Workshop, random | **Patent** (Stock-holders +, one Work +30% for 10 turns) · **Publish** (Ingenuity +20, and diffusion to partners) |
| **Enclosure petition** | Proprietors under Alienable Land, pasture profitable | **Enclose** (Fields → Pasture, hands freed into labour, Labour unrest +20) · **Refuse** |
| **Smuggling** | Customs at Heavy rate | **Crack down** (Justice cost) · **Lower rate** · **Ignore** (revenue leaks) |
| **Mutiny** | Regiments unpaid 2 turns | **Pay arrears** (Treasury ×2) · **Disband** · **Promise** (Sway −10, gain 1 turn) |
| **Bank crash** | Bank and Stock growth > 15%/turn for 3 turns | Stock −20%. Credit frozen 3 turns. Choose a bailout (Treasury) or let it fail (Stock-holders' contentment −20). |
| **Wild herds migrate** | Random, grassland | A new node gets wild herds and an old one loses them |
| **Colonists petition** | Navigation, a Port, Labour contentment < 40 | **Charter a colony** (a free band of 2 hands at the port; with Navigation, a band at its own port can take ship along sea lanes) · **Refuse** |

---

## 19. User interface

The ledger visual identity carries over: paper, ink, a serif for headings, tabular figures, and the existing `tokens.css`. What changes is the **structure**: map-first, fewer tables, and every number explained.

### 19.1 Layout (1440×900, workable at 1280×800)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ MODE BANNER │ Turn 64 · 1340 │ Food +12 │ Stock 180 (+9) │ Treasury 42 (+3) │ Sway 37 (+4) │
│             │ Ingenuity 11 → Coinage 3t │ Extent 34 · DoL 1.9 │   HEGEMONY  you 22% · 1/2 orbits │
├────────┬───────────────────────────────────────────────────────────────┬─────────────┤
│SOCIETY │                                                               │  THIS TURN  │
│ Labour │                         MAP (node graph)                      │  decisions  │
│ Props  │                                                               │  events     │
│ Stock  │   overlays: Political · Produce · Trade · Orbits · Unrest ·   │  report     │
│ ────── │             Supply · Security                                 │             │
│ Annual │                                                               │             │
│ Produce│                                                               │             │
│ (flow) │                                                               │ [END TURN]  │
├────────┴───────────────────────────────────────────────────────────────┴─────────────┤
│ SELECTION: node card (hands, works, jobs, output, build queue)  or  army card (units, │
│ moves, supply, cohesion, actions: move · attack (odds) · raid · siege · fortify)      │
└──────────────────────────────────────────────────────────────────────────────────────┘
  Screens (full-screen overlays, one key each): Discoveries · Institutions · Treasury ·
  Trade & Diplomacy · Reports · Commonplace Book
```

### 19.2 The map

- The map is an engraved-chart node graph, with the existing planar layout annealer. Node size is proportional to √hands. Nation colour shows as the ring and a territory hull. Works appear as small glyphs, units as tokens on nodes, and routes as animated dotted lines coloured by good.
- **Overlays** re-colour the nodes to answer one question each: Who owns it? What does it make? Where does trade flow? Who is in whose orbit? Where is unrest? Where can my army be supplied? Where is property secure?
- **Clicking a unit** shows its reachable nodes, shaded by move cost. Hovering an enemy node shows **battle odds**. Right-click moves or attacks.

### 19.3 The Annual Produce

The left **Society** column holds the game's signature visual: a compact **flow diagram** (Sankey) of the annual produce.

**sources** (hunting · herds · fields · commerce) → **distribution** (wages · profit · rent) → **uses** (subsistence · comforts · luxuries · retainers · taxes · savings → Stock)

Above it are the three order cards: size, income share, contentment, clout, and their current want. Hovering any band of the flow shows its number and what feeds it. This one picture is Smith's whole system at once: the growing total (harmony) and the three-way split (conflict), side by side, with no verdict attached.

### 19.4 Tooltips: every number, broken down

Every number on screen has a Civ-style breakdown tooltip:

```
Food +12/turn
  +31  Fields (4 nodes)
  +9   Hunting grounds
  +6   Pasture
  −28  People (28 hands)
  −4   Retainers (4 hands, kept by Proprietors)
  −2   Army
```

The old *numbers only, no prose* rule is replaced by **explain, don't editorialize**. Tooltips say what a thing does and why a number moved, in plain words. They never say which institution is better.

### 19.5 Forecasts before commitment

Every policy action (institution change, tax rate, budget level, trade policy, answer to a demand) shows a **one-turn forecast**. The forecast comes from running the model once on a copy of the world state: "Food +4 · Proprietors contentment −12 · Stock +3/turn · Security +0.1." The model is small enough to run this instantly. This feature does more than anything else to make the economics learnable.

### 19.6 Screens

- **Settlements** (S): every settlement we hold, with its hands, produce, works and slots, unrest, and the works it could build with their expected return against the rate of profit; the whole **investment queue**, which the player can reorder and trim; and every other place we know, with who holds it. Clicking a place selects it and zooms the map to it.
- **Discoveries**: §12.5. Discoveries can be **queued**. Clicking a discovery when something is already under study, or one still locked, queues it together with whatever it needs first (of an either-or requirement, one already known or planned will do, else the earliest). When a discovery completes, study moves to the first queued discovery that is now open. Choosing another discovery to study now puts the current one back at the head of the queue, and banked Ingenuity is never lost.
- **Institutions**: five pillar columns. Each option is a card with its effect, supporters and opponents (as order icons with clout bars), Sway cost, and forecast. Locked options show which discovery unlocks them.
- **Treasury**: revenue by source with the nominal-vs-actual incidence bars (§14.2), the Laffer-style peak curve for the current base, spending levels, debt, and the war summary.
- **Trade & Diplomacy**: partners, routes (goods, volume, profit, dependence), treaties, relations, orbits (yours and the ones you're in), and a proposals inbox.
- **Reports**: the three curves for every known nation, the produce and mode timeline, and the rankings.
- **Commonplace Book**: the in-game encyclopedia. Every concept (Extent, the split, Security, Standing, Stupefaction, Incidence, Orbits) gets a short plain explanation, a diagram, and the Smith passage it models. It is optional reading that the game never requires. It is linked from tooltips by a ⓘ.

### 19.7 The regent

A **Regent** button lets the same AI that runs the rivals rule the player's people for 10 turns, taking every decision. It is for skipping quiet stretches, and for seeing what the machine would do.

### 19.8 Onboarding

Early turns show one contextual hint at a time, read from the board: choosing a discovery, moving on when the game thins, following and taming herds, settling, investing Stock, bartering with a new people, founding a government, choosing a revenue. The hints can be turned off. There is no tutorial campaign.

### 19.9 Accessibility

Keep day and night themes, the colour-blind-safe nation inks, reduced motion, and keyboard control of every screen. Add hotkeys: End Turn (Enter), next unit (Tab), and one key per overlay and per screen. The map zooms (mouse wheel about the pointer, + and −, or the corner buttons) and pans by dragging; ⤢ or 0 shows everything we know again.

---

## 20. Starting numbers

These are starting values for tuning, not commitments.

| Thing | Value |
|---|---|
| Starting band | 5 hands, 10 Food, Sway 20 |
| Hunting yield | 1.6 Food/hand × game (1.0 at full, falling 0.1/turn per 3 hands camped, recovering 0.05/turn when idle) |
| Herd growth | 8%/turn × grazing fit, capped at 20 × grazing |
| Pasture | 1 Food per 5 herds; 1 herdsman per 10 herds |
| Fields | 3 jobs, 1.4 Food/job × arable |
| Workshop | 2 jobs, 0.8 Wares/job (or 0.3 Luxuries/job on a rare node) |
| Manufactory | 4 jobs, 1.0 Wares/job × DoL |
| Work costs (Stock) | Pasture 5 (plus herds) · Fields 10 · Workshop 15 · Market Town 25 · Port 30 · Mine 25 · Manufactory 60 · Foundry 40 · Bank 50 |
| Public work costs (Treasury) | Road 10/edge · Fort 20/level · Academy 30 · Canal 40/edge |
| Subsistence | 1 Food per hand per turn |
| Base rate of profit `r0` | 0.12 |
| Population growth | `+3% × (food_satisfaction − 0.9)` per turn, clamped to −10%…+5%; +1% more if wages > 1.5 × subsistence |
| Sway cap | 100 |
| Discovery costs | 20 / 45 / 90 / 160 by era |

### Balance targets (checked by `tools/` sweeps in CI)

| Target | Value |
|---|---|
| First nation leaves Hunting | turns 12–25 |
| All nations have left Hunting | by turn 45 in ≥ 90% of seeds |
| At least one nation reaches Agriculture | by turn 60 in ≥ 90% of seeds |
| A player pursuing it reaches Commerce | turns 85–110 |
| At least one manufactory in the world | by turn 110 in ≥ 90% of seeds (the first build: 0%) |
| AI wars | ≥ 1 per 25 turns across the world; ≥ 1 treaty per 20 turns |
| Hegemony achieved by turn 150 | in 30–60% of AI-only seeds (the rest end on opulence) |
| Game length | 150 turns, 2–3 hours |
| Decisions | At least one meaningful decision per turn |
| Turn time after turn 50 | Under 60 seconds on average |

---

## 21. Model reference

### 21.1 Resolution order (end of every turn)

1. Queued policy changes phase in. Queued builds complete if Stock covers them (§9.6).
2. **Production**: every Work (§9.3), plus herds growing and game depleting or recovering.
3. **Distribution**: the wages → profit → rent split (§10.1). Taxes are levied (§14.1).
4. **Trade**: routes move goods, prices update (§9.8, §11.2), Extent is recomputed (§9.4).
5. **Consumption**: orders fill their tiers, standing is split between retainers and luxuries (§10.2), satisfaction and expectations update (§10.3).
6. **Accumulation**: savings × Security → Stock, the remainder is hoarded, and `r` updates (§9.6).
7. **People**: population grows or declines, free labour reallocates, migration happens (§9.5).
8. **Politics**: contentment, clout, and Sway update. Demands and events fire. Unrest, strikes, riots, and revolts (§6, §7, §10.4, §18).
9. **Research**: Ingenuity is applied to the current discovery (§12).
10. **World**: supply and cohesion for units, sieges tick, mode check (§8), levers and orbits, Ascendancy and countdown (§17).

### 21.2 Invariants (tests)

- Every ratio used in the model is clamped. No NaN or inf values in any state.
- Value is conserved: produce = wages + profit + rent + taxes, and uses = produce ± trade balance.
- Hands are conserved: births − deaths ± migration ± casualties.
- The same seed and the same actions give the same world.
- The one-turn forecast (§19.5) equals the actual next turn when there is no randomness and no other nation acts.

---

## 22. Scope and build plan

### 22.1 v1

Everything in §§5–19 as written.

**Deferred:** Chartered Companies, Steam, Canals as a discovery (canals exist as a public work), Landmark projects (Great Fair, Royal Exchange, Grand Canal), hot-seat multiplayer, sound, colonies beyond one node, bank runs beyond the single event.

### 22.2 What carries over from the current codebase

| Keep (adapt) | Replace | Drop |
|---|---|---|
| `sim/worldgen` (graph generation, terrain, features); `api/layout` (planar annealer); `ui/names.py` (procedural names); `api/server` turn loop (`/turn`, `/action`, `/state`, `/new`, WebSocket); `ui/static/tokens.css`, `format.js`, the tooltip plumbing (`ui.js` `tip()`, `help.py` pattern); `tests/_harness.py`, determinism and invariant test patterns; `tools/batch.py`, `sweep.py` harnesses; CI workflow; exe build script | `core/*` (world, actions, trees, laws), all of `engine/`, `politics/`, `security/`, `trade/`, `finance/`, `meta/`; `ai/*`; `api/snapshot.py`, `schemas.py`; `ui/static/panels.js`, `map.js`, `trees.js`, `main.js` | The 15-class record model, per-location markets, the 7-good system, per-law enforcement, the Interest demand tables, the regression spiral detector, the old incidence and credit engines, `params/default.yaml` (rewritten for §20) |

Existing code docstrings cite the old design's section numbers (`DD §x`). Those citations point at the superseded document and should be removed as each module is replaced.

### 22.3 Milestones

Each milestone ends with something playable and a 30-minute play check: *did at least one decision per turn matter?*

1. **M1: The band.** Map, fog, bands (hunt, move, split, merge, claim), depletion, contact, barter routes, Sway as Consensus, the discoveries screen shell with Era I. *Playable for 20 turns.*
2. **M2: Property and produce.** Herds, hordes, settling, Fields, Works and the investment queue, the three orders, the split, Extent and DoL, prices, consumption, standing, contentment, the Annual Produce flow, modes and moments. *Playable into Agriculture.*
3. **M3: The state.** Chiefdom and Civil Government, the five pillars, Treasury, revenue and incidence, spending levels, Security, Demands, events, Interregnum and Exile, the forecast engine.
4. **M4: War.** Units, movement, supply, combat and odds, sieges, raids, capture choices, rebels, war-weariness and debt.
5. **M5: Trade and diplomacy.** Caravans, merchantmen, routes and dependence, trade policy, blockades, treaties, relations, diffusion.
6. **M6: Hegemony and AI.** Levers, orbits, Ascendancy and countdown, coalitions, opulence scoring, AI personalities and utility scoring, balance sweeps against §20's targets.
7. **M7: Polish.** Commonplace Book, moments and quotes, onboarding hints, overlays, the end screen and curves, accessibility pass.

New build documents, one per milestone, are written from this document when each milestone starts. Keep them short: the deliverable, the acceptance test, and the fun check.

---

## 23. Open questions

1. **Turn length vs. herd/population rates.** A 20-year early turn makes 8% herd growth per turn slow in historical terms and fast in game terms. Tune by feel, not by history.
2. **Should the player be able to pin free labour?** The design says no, because the invisible hand is the point. If playtests show frustration, add a node-level *Encourage* toggle that raises one Work's wage by 10% from the Treasury. That is a Smith-legible subsidy, not a command.
3. **Orbit thresholds.** 25% of one good's consumption may make Food importers too easy to capture. Watch this in M6 sweeps.
4. **Opulence population floor.** 25% of the average may still let a tiny island city win. Consider scaling it with the number of nations.
5. **Later writers as scenarios.** Malthus (population at the limit), Ricardo (rent as the difference between node yields, comparative advantage in routes), and Marx (labour's-share curve extrapolated). These would be post-v1 scenario variants, not core systems.
