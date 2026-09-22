# Stock — Design Document

A browser simulation game about Adam Smith's four stages — hunting, pasturage, agriculture, commerce — built so that the stages *emerge* from what can be owned. Structure borrowed from Victoria 3 (aggregate class records, producers, needs, laws, authority) and EU4 (a clock that ticks years at a chosen speed; the player intervenes at any moment). The player holds a sovereign's seat over a nation made of locations, competing against other nations run by the same simulation. Working title: *Stock* — Smith's word for capital, and a pun on the herd.

## 0. Vision and design goals

1. **What can be owned decides everything downstream**, and the player feels it through the ledger before being told.
2. **Government emerges** from classes with something to lose, not from a build menu.
3. **The invisible hand is emergent**: landlords re-route surplus from retainers to luxuries and the retainers become free labourers because of a consumption function, not a script.
4. **Three scoreboards that pull apart** — produce per head, the labourer's share, the freedom index — never summed.
5. **Smith's vocabulary on every tooltip**; and **description, not verdict, not citation** in every in-game text: mechanical effect plus numbers, no quotations, no author, no references. Everything marked *designer* in this document stays in this document. The credits screen carries a reading list, titles only.
6. **Regression is feedback, not game over.** Societies go backwards; collapses resolve to a lower stable state and the run continues. Nothing narrates the cause.
7. **The stages are a design goal, not a game state.** The player never sees a stage name, transition, or marker — only herds becoming property, a first field, a first manufactory, as events with numbers.
8. **Every nation is the same simulation.** Rivals are not scripts with numbers; they are nations with a scripted sovereign in the seat.

### 0.1 Smith in one page (designer background)

| | Hunting | Pasturage | Agriculture | Commerce |
|---|---|---|---|---|
| Dominant property | none (tools, the kill) | herds — accumulable, mobile, stealable | land — fixed, finite, heritable | stock — liquid, divisible; labour power as a commodity |
| What is produced | today's food | livestock and more livestock | a large regular grain surplus | manufactures for exchange |
| How | solitary labour | herding with dependents | bound labour on land | division of labour, capital advanced to wage labour |
| How it is shared | whole produce to the labourer | by herd size | rent to the lord, subsistence to the serf | wages / profit / rent (the adding-up price) |
| Surplus spent on | — | followers | retainers — the only thing to buy | luxuries; retainers dismissed |
| Government | unnecessary | born to protect herds ("the defence of the rich against the poor") | feudal, personal, local | impersonal, legal, urban |
| Labour theory of value | holds exactly | bends | fails | fails |

Each transition is a change in the *physical nature* of the dominant asset, which re-answers "how is it shared," which reshapes government. Property, not demography, is the hinge: population is an *output* (it follows the demand for labour), property is where the conflict lives, property is what a legislator can change, and the asset's nature (stealable, immobile, liquid) does explanatory work that headcount cannot. Demography sets the pressure; property sets the rules. Smith is ambivalent — his labour-theory strand says class conflict, his invisible-hand strand says harmony — and the game keeps both strands visible and refuses to settle it.

Sources: Hunt & Lautzenheiser ch. 1–3; Smith, *Wealth of Nations* (esp. I.vi–x, II, III, IV, V.i–iii) and *Lectures on Jurisprudence*.

---

## 1. World, goods, time, and the end of the game

### 1.1 Locations and nations

```
location = { terrain, resources, carrying capacity, class records, producers, fixed assets, neighbours (distances),
             river/coast flags, nation }
```

- **Resources** gate what a location can produce: game, grazing, arable, timber, ore, coal, fishing, and a `rare` flag (furs, amber, dyes, wine-land, salt) that lets local craft make luxuries.
- **Carrying capacity** for game and grazing depletes under use and regenerates when idle — the reason bands move.
- **Records live in locations**; a location becomes a *town* when enough non-agricultural records live there. Producers sit in locations; occupations (hunting, herding) move with records.
- **Distance graph**: rivers, coasts, and roads cut carriage cost; reachability on the graph is the extent of the market (§4.7).

A **nation** is the set of locations under one sovereign's seat plus its mobile records (bands, herds). Locations are settled, abandoned, raided, conquered, and ceded one at a time. A nation with no location and no herds has ended. Every nation runs the same simulation; the difference is who holds the seat — the player, or a **scripted sovereign** (§16.2). Every nation starts as a band on a location with game. A nation is a few hundred numbers.

### 1.2 Goods: seven abstract classes

Goods are **classes**, each shown by an emblem but standing for a family. Every price, need, input, and route is in these seven.

| Class | Emblem | Stands for | Produced by | Consumed as |
|---|---|---|---|---|
| **Provisions** | grain | grain, meat, milk, fish, salt | hunting, herding, fields | the subsistence basket; army rations |
| **Materials** | wool | hides, wool, timber, flax, ore, coal | herding, fields (by-product), forestry, mines | inputs to Wares, Arms, Ships |
| **Wares** | cloth | cloth, tools, pottery, furniture | workshops, putting-out, manufactories | comfort tier; inputs to fields and ships |
| **Luxuries** | plate | fine cloth, plate, glass, wine, furs, dyes | workshops in `rare` locations; manufactories; routes | display, in the standing tier |
| **Arms** | musket | weapons, horses, powder | ironworks, manufactories (from Materials) | the army's equipment |
| **Ships** | hull | boats, ships, carts, wagons | Ports (from Materials + Wares) | route capacity; navy |
| **Attendance** | livery | retainers, followers, servants | a consuming record's purchase (§5.1c) | standing, in the standing tier |

Attendance is a good so that dependents and luxuries compete in one tier on one price. Herds are *stock*, not a good; their output is Provisions and Materials. Money is the subsistence basket (§4.5).

### 1.3 Time: a clock, not a button

**One turn = one year.** The clock runs at a chosen speed — *paused, slow, fast, faster, very fast* (≈10 s, 5 s, 2 s, 0.5 s per year) — and the player intervenes **at any moment**: every action is queued and takes effect at the next year boundary, where its cost is deducted. Scripted sovereigns act at the same boundary. The clock auto-pauses on configurable events (a law passed against you, a location besieged, a treaty breached, a regression warning). A run is open-ended; a typical one is 200–400 years.

**Lag rule.** Each step reads the values produced earlier in the same year, or last year's value where the input comes later in the order.

**Year order** (every nation, same steps): 1 production → 2 wage bargaining → 3 revenue and budget → 4 trade → 5 consumption → 6 credit → 7 hoards and reinvestment → 8 population and mobility → 9 stock placement → 10 trees and Focus → 11 unrest → 12 politics → 13 military, events, regression check → 14 queued sovereign actions apply.

### 1.4 The end of the game and the two winners

The game ends by **hegemony**, not by a turn count. Each year, three world shares are computed for every living nation:

```
capital share      = nation's total stock (stock in place + herds + hoards + treasure) / world total
consumption share  = nation's total consumption value / world total
production share   = nation's total productive output value / world total
flag_k             = share_k ≥ 0.75
```

When **two or more flags** hold for one nation, a **25-year countdown** starts and is shown to everyone. If, on any year, fewer than two flags hold for that nation, the countdown **resets to 25** — the end is delayed, not cancelled. When the countdown reaches zero the game ends.

Two winners are named, and they may differ:

- **Produce per head** — the living nation with the highest annual produce per head (§14.1, curve 1).
- **Labour output** — the living nation with the highest total annual produce of productive labour (the numerator of curve 1, unnormalised).

A small rich nation can take the first while the hegemon takes the second. Nations that have ended are not eligible. The final screen shows both winners, every nation's three curves, and the final ledger (§13); the player may keep the clock running afterwards.

---

## 2. Classes

### 2.1 Aggregation rule (hard constraint)

One record per **class × location** with a `size` count and one wealth vector. No individuals, no intra-record distribution. Every mechanic is a class-level function applied once per record per year.

```
record = { class, location, size, wealth: {herd, land shares, fixed assets, stock in place, hoard, bonds, tools}, debt,
           A (satisfaction by tier), E (expected by tier), walk-away, authority }
```

- **Concentration** within a class is `wealth / size` of the owner record: laws that concentrate (Primogeniture, Herds Heritable) hold `size` down while wealth grows; laws that fragment let `size` rise.
- **Wealth moves with people**: every mobility flow carries wealth and debt pro rata.

### 2.2 Records

**Walk-away** = the share of this year's income the record would keep next year if it left its present employer. One meaning everywhere.

| Class | Owns | Income | Prod.? | Walk-away | Note |
|---|---|---|---|---|---|
| Hunters | tools, the kill | whole produce | yes | 1.0 | mobile occupation |
| Herd-owners | herd (mobile stock) | herd increase, Materials | owner | 1.0 | mobile |
| Herdsmen | — | kept in kind | yes | 0.2 | mobile |
| Landlords | land shares | rent | no | 1.0 | |
| Clergy | Church land | tithe, rent | no | 1.0 | v2 |
| Serfs | —; bound | subsistence in kind | yes | 0 × enforcement(Serfdom) | |
| Retainers | — | Attendance bought by a landlord | no | 0.1 | the feudal host |
| Craftsmen | tools, materials | sale of Wares/Luxuries | yes | 0.7 | towns |
| Tenants | lease, small stock | produce − money rent | yes | 0.5 | |
| Merchants | trading stock, Ships | route gaps, charters | yes | 1.0 | |
| Capitalists | stock in producers | profit ∝ stock | owner | 1.0 | |
| Labourers | labour power | wages | yes | computed (§4.6) | |
| Servants | — | Attendance bought by any rich record | no | 0.4 | the later dependent |
| Soldiers | — | the defence draw | no | 0 enlisted; desertion is a flow | |
| Collectors | — | collection cost | no | 0.6 | v2 visible |
| **The State** | treasure, crown demesne, bonds issued | revenue | — | — | one per nation; has `A_S` |

Asset flags drive behaviour: herd `accumulates, stealable, mobile`; land `heritable, immobile, finite`; stock `divisible, mobile, convertible`; bonds `mobile`, worthless on default; fixed assets `immobile, capturable`. Dependents are purchases, not jobs; their record size *is* the purchase.

### 2.3 Population

```
size' = size × (1 + β (A_subs − 1)) − mortality(shortfall_subs²) ± flows
```
Population is an output: it grows where pay exceeds the basket, shrinks where it doesn't, and is cut by plague, war, hunger. Dependents grow with what maintains them.

### 2.4 Mobility

**Vertical** (slow, on `wealth/size`): herdsman → herd-owner; craftsman → capitalist; serf → tenant (Commutation); serf/tenant → labourer (Enclosure); retainer → labourer (dismissal); craftsman → labourer (guild closes); labourer → servant; labourer → craftsman (savings); merchant/capitalist → landlord (default under alienability, or purchase); landlord → landlord-in-debt (rent pledged).

**Horizontal** (faster; equalisation of net advantages across employments): a share of a record moves to the adjacent class with the higher net advantage — income plus agreeableness, learning cost, constancy, trust, chance of success — at `base × (1 − friction)`.

| Tier | Edges | Frictions |
|---|---|---|
| Dependent labour | herdsman ⇄ serf ⇄ retainer ⇄ levy (same records, mobilised) | Serfdom × enforcement |
| Free labour | labourer ⇄ servant ⇄ soldier ⇄ militia | Settlement Law |
| Independent | craftsman ⇄ tenant ⇄ small merchant | Apprenticeship; Guild Charter; alienability |
| Owners of stock | capitalist ⇄ merchant ⇄ improving landlord; wealth shifting between stock, bonds, loans, land | Charter; alienability; Usury; Public Credit |

**Cross-location**: every edge also runs to the same tier in neighbouring locations, friction = distance ÷ (river or road). **Cross-border**: again, friction += hostility + `(1 − f(N̄_dest))` + treaty terms; free labour crosses as emigration, stock as capital flight and foreign lending.

Horizontal mobility is the engine of natural price (§4.5): a frozen edge stops gravitation and the ledger shows the gap. The army recruits along a free-labour edge, competing with manufactories for hands. Migration on the location graph is the demographic input to the extent of the market.

### 2.5 Authority and Interests

```
authority = size^κs × W^κw + d_dep × dependents,     W = value of all assets + ℓ × size × w_natural
```
`ℓ ∈ [0,1]` is **labour legibility**, a stored accumulator raised by justice (§7.6): the only route by which labour power counts as wealth. Each record's authority is **apportioned to Interests by wealth composition**:

| Interest | Wealth held as | Typical members |
|---|---|---|
| Landed | land, herds, Church land, agricultural fixed assets | landlords, herd-owners, clergy, tenants (small) |
| Industrial | stock in producers, tools | capitalists, craftsmen |
| Merchant | trading stock, ships, routes held | merchants |
| Moneyed | bonds, loans out | whoever holds them — the Interest *emerges* |
| Labour | labour power (`ℓ`-weighted) | labourers, serfs, herdsmen, soldiers, servants |

Interest authority is recomputed yearly; **radicalism** (accumulated political-demand unrest, §8.2) is stored. Merchant and Industrial are separate because they oppose each other on tariffs, charters, and customs.

---

## 3. The opening: bands

Every run begins as a band of hunters. Hunting and herding are **occupations** — attached to records, yielding from the location the record stands on, no fixed asset. The band's loop:

- **Move or stay.** Staying depletes the ground; moving costs a year's yield and *consensus* (the band's form of `A_S`, refilling to `C₀` yearly). Two bands on one location share it and may fight for it.
- **Follow the herds.** Grazing locations carry wild herds; following gains *contact*, the gate on *Domesticated herds*. Tamed herds are mobile stock that graze where the record stands.
- **Fight or barter** with neighbouring bands: a raid takes kill, tools, herds; barter at a shared border is the first route, and how `rare` goods first cross into a band that lacks them.
- **The share rule** — the first law: *kill to the killer* or *shared by custom*. Nothing changes in totals; everything changes in the ledger once herds exist.
- **The tamed animal belongs to the tamer** — herds become property; owner and herdsman records appear; the largest owner holds the seat and `A_S` becomes his authority.
- **Settling** — a record builds the first field on arable land, stops moving, and starts to own what cannot be carried away — and therefore what is worth defending and worth taking. Nations are usually part settled, part herding for a long time.

Rude equality is a consequence of nothing being accumulable; government is *unnecessary* until the first raid on a band that has just tamed animals.

---

## 4. Production, prices, wages, and the market

### 4.1 Producers

| Producer | Kind | Jobs | Stock (profit) | Land (rent) | Makes | From |
|---|---|---|---|---|---|---|
| Hunting | occupation | hunters | — | — | Provisions, Materials | game |
| Herding | occupation | herdsmen; owners | the herd | — | Provisions, Materials, herd increase | grazing |
| Field | building | serfs or tenants | tenant's stock | landlords / clergy / State | Provisions, Materials | arable; Wares (tools) |
| Workshop | building | craftsmen | self | — | Wares; Luxuries if `rare` | Materials |
| Putting-out | dispersed | rural labourers | merchants | — | Wares | Materials |
| Manufactory | building | labourers | capitalists | landlords (site) | Wares, Luxuries, Arms | Materials; coal |
| Mine / forestry | building | labourers | capitalists | landlords | Materials | ore, coal, timber |
| Port | building | merchants, labourers | merchants | — | Ships; route capacity | Materials, Wares |
| State | building | collectors, soldiers | — | — | — | — |

### 4.2 Production functions

```
Hunting      Q = y_game(loc) × H^η × depletion(loc)
Herding      ΔHerd = γ × Herd × min(1, herdsmen / (Herd/h));   Q_prov, Q_mat ∝ Herd
Field        Q = y_arable(loc) × L_shares × labour^η × (1 + rotation) × tools
Workshop     Q = q_c × craftsmen × tools × materials
Manufactory  Q = q_m × labourers × (stock/labourers)^ζ × DoL(market_size) × machinery × materials
Mine         Q = q_x × labourers × resource(loc)
Port         capacity, §10.1
jobs         = stock / stock_per_job   (buildings)   or   L_shares × jobs_per_share   (fields)
```
Arable and carrying capacity cap the fields and herds a location can hold.

### 4.3 The split rule

`V = price × Q` at last year's price. Then, in order:
```
labour income = filled jobs × w                    (free labour: the wage; dependent labour: the basket in kind)
profit        = r̄_{t−1} × stock in place           (the normal return)
rent          = V − labour income − profit         (the residual, to land shares)          [producers with land]
profit        = V − labour income − site rent      [producers without land: the surplus goes to stock]
```
Wages first, normal profit next, rent last. This is what makes gravitation work: stock earning above `r̄` draws stock in; land absorbs surplus instead.

### 4.4 The average rate of profit and placement

```
r̄ = Σ profit / Σ stock in place           (herd increase is the profit on herd stock)
```
One number per nation per year, used everywhere a return is needed. **Placement**: each year `τ_turn` of every producer's stock is freed and, with new reinvestment, placed where the return per unit stock is highest among what the laws allow and the locations can hold. Base returns are set so that with free rules cultivation > domestic manufacture > foreign trade; a charter or bounty reorders them and the capital-flow panel shows where stock went.

### 4.5 Money, prices, natural price

**Unit of account: the subsistence basket** (one person-year of Provisions and a little Wares). In a band its price is labour time, so exchange ratios are labour-time ratios; from herds on, it is bought.

```
market price_g = base_g × (demand_g / supply_g)^ε_g     per class per location market; unsold output carried, decaying
natural price_g = (w × labour + r̄ × stock + rent) per unit, at the average rates of g's producers
```
Both are shown. Gravitation: excess profit → stock placed in and records flow in → supply up → market price falls toward natural; a frozen edge stops it. High use-value, low price: both numbers, no comment.

### 4.6 Wage bargaining

```
w_natural = price of the basket, incl. taxes on necessaries or wages
surplus   = V / filled jobs − w_natural
π         = wa_L / (wa_L + patience_M)
w         = w_natural + π × surplus × (1 − enforcement(Combination Act))

wa_L        = open jobs on the record's edges + Poor Rate transfer + hoard/head + credit available + scarcity premium,
              as shares of income; decays ρ_h per year a strike runs
patience_M  = masters' stock in place / annual wage bill, plus their silent combination modifier; no decay
```
Masters' combinations are silent (a ledger modifier); labourers' fire an event and, under an enforced Combination Act, are put down at the cost of disorder. Scarcity raises `wa_L`; a surplus lowers it. A tax in `w_natural` passes forward only as far as `π` allows.

### 4.7 Extent of the market

```
market_size(g, loc) = Σ_{locations within carriage cost c_max} spending on g's tier + army demand + route demand at capacity
```
Reachability on the location graph, with rivers, coasts, and roads (a Focus) cutting cost. `DoL = f(market_size)`. Consumption, the army, migration, and trade all feed Tree II through this number.

---

## 5. Consumption, hoards, reinvestment

### 5.1 The consumption function

**(a) Tiers, filled in order**: subsistence (Provisions, a little Wares), comfort (Wares), **standing** (Luxuries and Attendance). The subsistence share falls as income rises.
**(b) Smooth substitution** within a tier: `share_g ∝ weight_g × price_g^−σ`.
**(c) Standing, in one unit.** Attendance yields `s_att` standing per basket (a retainer costs one basket a year and also adds to the feudal host and to authority; a servant adds only to authority). Luxuries yield `s_lux × vanity` standing per basket, where `vanity` rises with the volume of Luxuries reachable and saturates. The logit allocates the standing budget between them; **the dependent record's size equals the attendance purchase.** No Luxuries reachable → all standing is attendance → surplus becomes retainers. Luxuries arrive dear → a few retainers go. Luxuries cheapen → substitution accelerates → a **retainer-dismissal event** fires when the record falls through a threshold: numbers only.
**(d) Every unit spent is tagged** productive (goods made by productive labour → `market_size`) or unproductive (attendance, clergy, soldiers, the court); the ledger shows the split.

| Class | Subsistence | Comfort | Standing |
|---|---|---|---|
| Hunters; herdsmen, serfs, retainers, servants, soldiers | all | — | — |
| Labourers | most | opens when `w > w_natural` | — |
| Craftsmen, tenants | moderate | moderate | thin |
| Herd-owners | small | some | attendance |
| Landlords | small | some | attendance ⇄ luxuries |
| Merchants | small | moderate | luxuries; competes with reinvestment |
| Capitalists | small | moderate | thin by design |
| The State | — | — | the court draw |

**Loop**: consumption → `market_size` → Tree II lights → prices fall → profiles shift up-tier. A run with no Focus reaches manufacture this way.

### 5.2 Hoards — one stock

```
residual = income − consumption;   saved = p_class × residual
to_reinvest = saved × f(N_rec);   to_hoard = saved × (1 − f(N_rec))
H' = H + to_hoard − ω f(N_rec) H − deposits − bonds_from_hoard
```
Banks take deposits from `H`; bonds draw from `H` and `to_reinvest` in the proportions `(1 − f)` : `f`; raids and conquest take a share of `H`. Hoards re-enter as security returns. Insecurity acts once, here.

### 5.3 Propensities

| Class | `p` | Target |
|---|---|---|
| Hunters, servants, soldiers | 0 | — |
| Herd-owners | high, automatic | the herd |
| Landlords | low | improvement, only if rent rising and land alienable |
| Craftsmen, tenants | moderate | tools, journeymen; farm stock |
| Merchants | high | trading stock, Ships, a charter if on offer |
| Capitalists | highest | the producer/method with the highest return |
| Labourers | ~0; > 0 when `w > w_natural` | savings → promotion |
| The State | revenue unspent | treasure; later the budget |

`p` rises with `r̄` for stock-holders; a charter raises the holder's and lowers others'; a saturated standing need raises `p`, and newly available Luxuries lower it — the event that frees the retainers makes landlords a worse source of capital.

---

## 6. The three trees

Three ladders that constrain each other: **I — WHAT** (good classes a location can make; lit per location by resources and contact), **II — HOW** (methods on producers; defence and credit branches; gated by market size and accumulation), **III — SHARE** (laws; the only tree the sovereign enacts). A WHAT node can be lit but unusable; a HOW node lit but idle; a SHARE node changes what the other two mean. Each dark node shows the numbers it waits on.

### 6.1 Tree I — WHAT

| Node | Puts in the market | Gate (in the location) |
|---|---|---|
| Game and gathering | Provisions, Materials | game |
| Domesticated herds | Provisions, Materials; herds as mobile stock | grazing + contact |
| Grain | Provisions at scale | arable + a settled record |
| Wares | Wares | Materials + craftsmen in a town |
| Luxuries | Luxuries | **any of**: `rare` + craftsmen; a route to a market that has them; a manufactory |
| Ships | route capacity | coast + Materials + Wares |
| Arms | Arms | ore + coal + a manufactory or ironworks |

Luxuries have three doors on purpose: a landlocked nation with furs can raise them; a coastal one imports them; a manufacturing one makes them.

### 6.2 Tree II — HOW

**Production**: Solitary labour (hunting) → Herding with dependents (herds ownable) → Bound labour (Land Ownable + Serfdom; serf walk-away 0 × enforcement) → Three-field rotation (+50% land) → Handicraft (a town) → Putting-out (merchant stock + Materials; dispersed wage jobs) → Money rent (Commutation) → Manufactory (Stock Separable + free labourers; the profit stream) → Division of labour (`market_size` threshold; `DoL`; skill falls) → Machine production (Wares at scale + ore + capital; output per labourer up) → Machinery/steam (machine production + coal + the Watt event; frees sites from rivers).

**Defence**: Every man a warrior → Nation in arms (herds) → Feudal host (fields + retainers) → Militia (Militia Act) → Standing army (Standing Army Act + defence draw + free labour) → Firearms (Arms class at scale) → Navy (Port + Ships).

**Credit**: Bills of exchange (Port + merchant stock; capacity per unit stock up) → Bank (v2).

### 6.3 Tree III — SHARE

Face: mechanical effect, cross-tree effect, last year's enforcement. Support/Opposition feed §7.5. Source is designer-only.

| Branch | Law | Effect | Support | Opposition |
|---|---|---|---|---|
| Property | Kill to the killer / shared | the band's share rule | — | — |
| Property | Tamed animal to the tamer | herds become mobile stock; owner and herdsman records | herd-holders | — |
| Property | Protection of Property | the State record; raid losses fall; a tax on all | Landed | Labour |
| Property | Herds Heritable | owner size held down as herds grow | Landed | — |
| Property | Land Ownable | fields become land shares; landlords | Landed | Labour |
| Property | Primogeniture ⇄ Alienable | size held down, default pledges rent ⇄ size rises, tenants, default transfers land | Landed ⇄ Merchant, Industrial | the other |
| Property | Stock Separable | manufactory; the profit stream | Industrial, Merchant | Landed |
| Labour | Serfdom | walk-away 0 × enforcement; no migration | Landed | Labour |
| Labour | Commutation | serf → tenant jobs; rent in coin | Labour, Merchant | Landed |
| Labour | Enclosure | commons → land shares; serfs/tenants → labourers; migration; Materials (wool) | Landed | Labour |
| Labour | Settlement Law | friction on free-labour cross-location edges | Landed | Industrial, Labour |
| Labour | Apprenticeship / Artificers | friction on producer edges; State wage ceiling | Industrial (masters) | Labour |
| Labour | Guild Charter | craftsmen cap; blocks manufactories in the town | Industrial (craftsmen) | Industrial (capitalists), Merchant |
| Labour | Combination Act | enforcement in the wage formula | Industrial | Labour |
| Commerce | Free trade (default) | routes open to all | Merchant | Industrial (protected) |
| Commerce | Tariff / Prohibition (per class) | import price up / route closed; the class dearer for all | the producer | Merchant, Labour |
| Commerce | Bounty (per class) | export price above natural; stock pulled in | the producer | whoever pays |
| Commerce | Navigation Act | domestic Ships only; carriage up; navy base; maritime hostility | Merchant (shipping) | Merchant (carriers), Industrial |
| Commerce | Chartered Company | one merchant record holds a route; the gap stays; State cut | Merchant (holder) | Industrial, Labour |
| Commerce | Treaty | terms with one nation (§10.4) | Merchant | by terms |
| Revenue | the instruments of §12.2; Single tax on rent | — | whoever escapes | the payer; Landed |
| Credit | Usury Law (prohibition / cap / none); Public Credit; Sinking Fund (v2) | §11 | varies; Merchant, Industrial; Moneyed | varies; Landed; — |
| Defence | Standing Army Act; Militia Act | Soldier record, `M` to the State; seasonal levy | Merchant, Industrial; Landed | Landed; Industrial |
| Justice | Administration of Justice | the draw raises `J` above its floor | Merchant, Industrial | Landed |
| Relief | Poor Rate; Price control on grain | transfers funded on rent; price cap, supply falls | Labour, Industrial | Landed |

### 6.4 The Sovereign's Focus

On Trees I and II the sovereign may **Focus** — spend revenue to *lower the gate* on one node in one location, never to open it; one at a time; switching forfeits progress. **Public works** (cut carriage cost on chosen edges; tolls may fund it), **Patent** (one capitalist record holds a method N years; profit above `r̄` draws imitation on expiry; the labourer's share dips meanwhile), **Education** (reduces the skill penalty of division of labour; raises `wa_L` slightly; no distortion, slow). A run with no Focus — Protection of Property and the removal of restraints only — must be viable and reach manufacture, slower, with a better labourer's-share curve.

---

## 7. Politics: order, authority, the State, laws

### 7.1 The order signal — events only
```
O = Σ events:  victory +2, defence +1, raid −1, defeat −2, location lost −2, riot −1, revolt −2, mutiny −3,
               default −1, law lapsed −1 each, treaty broken against us −1
```
`R_private` (lords' armed retainers) and `U_disorder` are *state variables*, read once each by threat (§9.1) and by State authority (§7.3). Nothing is debited twice.

### 7.2 The sovereign's currency
Every action costs **State authority** `A_S`; no action limit, only the stock. Laws: 0 if Interests clear the bar, else the gap. Veto: the gap at a premium, plus a cooldown. Focus: upkeep. Tax and budget changes: small. War, siege, peace, treaty: a fixed spend. Repression: a spend, and the army is inside. Band decisions: consensus. A sovereign with no authority can still enact what the Interests want for free.

### 7.3 State authority
```
A_S' = (1−δ) A_S + a₁ (M_state/M) ln(1+M) + a₂ J + a₃ Σ_laws weight×enforcement + a₄ (direct/revenue) + a₅ max(0,O)
       + a₆ ln(1+court) − b₁ max(0,−O) − b₂ ln(1+R_private) − b₃ ln(1+U_disorder) − b₄ farmed_share − spent
```
**Handover**: a band's `A_S` is consensus (refills to `C₀`); at *Tamed animal*, `A_S := authority of the largest herd-owner`; at Protection of Property the State record is created with `A_S` unchanged — small beside the Landed Interest, which holds the host, the courts, the dues. A nation that never builds a standing army or collects directly reaches manufacture with a weak State; that is a viable run.

### 7.4 The political pipeline
```
shortfall → political-demand unrest (high-authority records) → radicalism_I += Σ; decays as demands are met
→ a NAMED demand from the Interest's table
     Landed: corn tariff; no land tax; Poor Rate on others; Serfdom or Settlement; Militia Act
     Industrial: Combination Act; Apprenticeship; Guild Charter (craftsmen) or its repeal (capitalists); tariffs on rival Wares; no profit tax; Standing Army Act; justice
     Merchant: free trade; a charter on a closing route; Navigation Act; Public Credit; no customs
     Moneyed: service by land tax; no default; Sinking Fund
     Labour: repeal Combination Act; free grain trade; Poor Rate; Commutation
→ if authority_I (1 + radicalism_I) > θ' (A_S + Σ opposing authority):  the Interest ENACTS it
  else the demand stands and adds radicalism_I × w_r to the bar of every law the Interest opposes
```
Low-authority unrest takes the disorder branch (§8.2). Justice converts a share of disorder to lawful demand — into Labour's radicalism and its legibility `ℓ` — so over a long run Labour becomes a party.

### 7.5 Passing, veto, enforcement
```
passes if  support + spend ≥ θ × opposition × (1 + Σ opposing radicalism × w_r)
enforcement_law = J × A_S / (A_S + opposition_of_that_law)
```
Interest-supported: free. State-pushed: `A_S` for the gap; opposing radicalism rises. Blocked: dark, with the three numbers. **Veto** of an Interest's self-enactment: the gap at a premium, and that demand goes on a `k_veto`-year cooldown — a veto buys time. Enforcement multiplies every law's effects and is never zero (§7.6): Serfdom under a weak king is enforced by the lords' courts; a Combination Act is enforced against Labour and not against masters; evasion reads `(1 − enforcement)`.

### 7.6 Justice and legibility
```
J = J_cust + (1 − J_cust) min(1, justice_draw / justice_need)   if Administration of Justice;  else J_cust
J_cust = 0.3 (band, herds), 0.4 (fields);   justice_need ∝ population × (1 + town share)
ℓ' = ℓ + j J (disorder converted) − δ_ℓ ℓ
```
Justice multiplies enforcement, gates credit, converts disorder, raises `ℓ` (the only way Labour gains authority), and feeds `A_S`.

**Loops**: cheap Luxuries dismiss retainers → `R_private` falls → merchants' `N` and `A_S` both rise. Direct collection and a standing army feed `A_S`, cost revenue, and enforceable taxes need `A_S`. Pushing enclosure, the army, collection, and the land tax through the Landed Interest in a decade yields a modern State and a nobility in revolt. `A_S` has no scoreboard.

---

## 8. Unrest

### 8.1 Expected needs
```
E' = E + α_up max(0, A − E) − α_down max(0, E − A);   α_up > α_down > 0;   α_collapse ≫ α_down (during a regression)
```
Comforts long satisfied migrate toward the subsistence weight and back slowly; stalled growth generates unrest with no decline; a decline that stops eventually goes quiet; recovery from a low base is cheap.

### 8.2 Unrest and its expression
```
U = size × Σ_tier w_tier φ(shortfall);  w = 8:2:0.5;  φ_subs = shortfall²;  others linear
```
Records with authority/head below `a_split` → **disorder**: strike (`U/size > u₁`), riot (`u₂`), revolt (`u₃`), desertion (soldiers), emigration continuously along cross-border edges. `U_disorder` is a standing variable; the events enter `O`. Records above → **political demand** (§7.4). Causes: war prices, harvest failure, a closed route or broken treaty, masters' combinations, enclosure, taxes, a stalled economy through the ratchet alone. The Soldier record's shortfall cuts `loyalty`; mutiny is the worst event.

**The spiral**: unmet subsistence → disorder → `N` and `A_S` fall → `f(N)` falls → hoarding → fewer jobs → wages fall → more unmet needs. `N̄` and `U` are on the ledger; rivals run the same spiral.

### 8.3 Closing a subsistence gap — one choice set
| Response | Who pays | Lag | Next year |
|---|---|---|---|
| Let wages rise (repeal Combination Act / Artificers) | masters via `π` | 1 | `E` rises; Industrial demand |
| Free grain trade | domestic grain rent | 1 | cheapest; a dependence |
| Consumption credit | the labourer, later | 0 | shortfall deepens; bondage if sustained |
| Poor Rate + transfers | landlords | 1 | Landed demand; Settlement friction if attached |
| Price control on grain | grain producers | 0 | supply falls; worse |
| Administration of justice | the budget | slow | disorder converts; `ℓ` grows |
| Repression | `A_S`; the army is inside | 0 | `E` unchanged; external `M` down |

---

## 9. Security and war

### 9.1 Perceived security
```
M          = Σ units (size × equipment) × doctrine × supply × loyalty
PSV'       = λ PSV + (1−λ) a ln(1+M) + p O                              (one per nation)
PTV_ext    = Σ_i b ln(1+M_i) h_i g(d_i)
PTV_int,r  = c_r ln(1+R_private) + u ln(1+U_disorder)                  (c_r: merchants/capitalists high, landlords 0)
N_r        = PSV − PTV_ext − PTV_int,r;   N̄ = authority-weighted mean;   f(N_r) = 1/(1+e^{−κf (N_r − N₀)})
```
Logs make the first regiment worth much and the twentieth little, and arms races self-limiting; `h_i` falls with routes so trade is a security instrument; `λ` makes perception sticky. To a merchant the lords' host is a threat first (`c_r` set so `c_r ln(1+R_private)` exceeds his share of `a ln(1+M_host)`); to a landlord it is pure defence — the Standing Army Act's constituency.

### 9.2 Organisation and the army as a consumer
| Node | Fights | Pays | Eats |
|---|---|---|---|
| Every man a warrior | hunters | nobody | nothing |
| Nation in arms | herdsmen + owners; herds go too | nobody | nothing; production stops while mobilised |
| Feudal host | retainers + serf levy | landlords (their attendance) | Provisions |
| Militia | tenants, craftsmen, seasonally | themselves | Provisions, Arms |
| Standing army | Soldiers | the defence draw | Provisions, Wares, Arms |
| Firearms; Navy | equipment; Soldiers at a Port | the State | Arms; Ships |

**Army size has no slider**: the defence draw sets pay; the free-labour edge sets size; more draw at the same pay buys Arms. The army buys through the market: peacetime `size × basket`; underpaid → `supply < 1`; hungry → `loyalty < 1` → mutiny. Mobilising an occupation stops its output. War multiplies the basket and every class pays through prices; the units are unproductive — but Arms demand also feeds `market_size`. **Matchup** by doctrine: nation in arms > host ≈ militia > standing army in cost-effectiveness before Firearms; standing army + Firearms > all after.

### 9.3 Raids, wars, sieges, conquest
Raid: on a location; takes stealable goods, hoards, herds. War: on a nation, resolved **per contested location**:
```
outcome ∝ M_att × matchup × supply  vs  M_def × matchup × supply × fortification(loc);  falls after k_siege losing years
```
A fallen location **changes nation** with its records and fixed assets; the winner's laws apply there at low enforcement (the new subjects' opposition counts in full); `market_size` extends for the winner, contracts for the loser. Peace, offered or imposed: cession, tribute (revenue for `k` years), or a treaty (§10.4). A nation whose last location and last herd are gone has ended (§13). Costs: record sizes, the war basket, radicalism, `O`. A nation attempts conquest of a location only when the target's `N̄` is deeply negative and its `M` there is large; the regression warning band covers it.

---

## 10. Trade and treaties

### 10.1 Routes between locations
```
capacity = k_cap × merchant stock committed × (1 + bills) × Ships on route × method ÷ carriage_cost × (1 − law friction) × treaty_factor
```
Goods flow low price → high price, carried by either nation's merchants, who earn the gap net of carriage; capacity caps volume so the gap persists — *that gap is merchant profit*. As merchant stock enters, the gap narrows toward `r̄` and the Merchant Interest demands a charter (§7.4). The first routes are border barter between bands; `rare` goods cross them. Effects through existing machinery: foreign demand → `market_size`; imported Luxuries dismiss retainers; cheap imports capture a tier and the producer's Interest demands a tariff; a Provisions import is a dependence.

### 10.2 Stock routes
The same route carries stock along the owners-of-stock cross-border edge: capital flight under a profit tax, foreign lending at `r_sovereign`, a better `r̄` next door. Stock abroad earns there and may return.

### 10.3 Hostility
`h_ij`: up with war, route competition, capturing a route another nation held, breach; down with trade volume, a kept treaty, tribute. A rich neighbour raises `PTV_ext` and `market_size`; which dominates is set by `h_i`, and `h_i` by trade and treaties. Nations war among themselves by the same logic; a belligerent demands Provisions and Arms, is a weaker target, sheds refugees, and pays neutrals a carrying premium.

### 10.4 Treaties: terms, enforcement, consequences
A treaty is a law binding **two** nations, negotiated (both spend `A_S`) or **imposed** at a peace (the loser's consent is not asked). Terms, any combination: **tariff ceiling** on classes; **route / port access**; **exclusive route**; **most-favoured terms**; **tribute**; **cession**; **grain guarantee** (no Provisions prohibition in a dearth); **non-aggression / alliance** (v2). Benefits flow through the machinery: `h_ij` down, carriage friction down, `market_size` extended, `PTV_ext` down, lenders' premium down.

**Enforcement** on each side is that side's own enforcement ratio against the Interest the term binds: a tariff ceiling is only as good as the bound sovereign's authority over its Industrial Interest. A **breach** (the bound Interest re-enacts a tariff; a Port closes; grain is prohibited) jumps `h_ij`, gives the beneficiary a *casus belli* (war without the aggression cost in `O`, with its own Interests' support), and raises the breacher's foreign premium and lowers its `treaty_factor` on every route for `k` years. **Consequence for the bound side**: an imposed term that opens its market produces, through §7.4, exactly the demand it forbids — a weak State breaches; a strong one keeps a durable market. Hard terms on a weak State buy a future war. Treaties lapse when a signatory ends and are renegotiated when `h_ij` and relative `M` have moved enough.

---

## 11. Credit and debt

```
r_market = s r̄ + ρ(N̄, J);   r_legal = min(r_market, usury_cap);   r_sovereign = r_market + σ(D/revenue, default_history, J, treaty standing)
```
Interest follows profit; lending follows security and justice; where property is insecure stock is hoarded, not lent. The rate of interest is a ledger indicator. Bands: none. Herds: cattle-lending (a dependents mechanism). Fields: prohibited by default; lords borrow informally against rent; the State holds treasure. Towns and Ports: bills, then banks; interest under a cap; the State borrows once `J` is above its floor, lendable stock exists, and the army or court needs it.

**Private credit.** Lenders: merchants, capitalists, banks (v2), foreign lenders on stock routes. Borrowers and default: landlords for display (alienable → land to the creditor; primogeniture → rent pledged, title kept); tenants for improvement (lose the lease); craftsmen for journeymen (back down); merchants for capacity (Ships lost); capitalists for methods (producer idle); labourers for subsistence (service deepens the shortfall; sustained → debt bondage, a horizontal edge down); projectors (v2). Supply = lendable surplus × `f(r_legal − own return)`; demand = projects above `r_legal` + inelastic subsistence demand. **Usury Law**: prohibition (all informal at `r_market + penalty`); a cap slightly above market (display and projectors starved; sober borrowers unaffected); a cap below (the legal market dries); none (projectors bid up `r_market`). Private credit moves stock from low-`p` to high-return holders, finances the craftsman → capitalist and tenant → improver edges, transfers land by default, and smooths subsistence then deepens it.

**Banks (v2)**: deposits from hoards, lent — the one thing that lifts the hoarding penalty without lifting `N`; over-issue → run → deposits destroyed → credit at zero `k` years → demand falls → `market_size` falls → Tree II idles; a capital-loss regression trigger.

**Public credit.** Treasure before funding. With Public Credit: `bonds = spending − revenue; D' = D(1 + r_sov) − service`. Bonds are an employment of stock drawn from hoards and reinvestment by the one rule (§5.2); foreign holders buy along stock routes; **bondholding creates the Moneyed Interest** by apportionment — it backs the State against disorder, wants service by land tax, opposes default; Landed wants the reverse. **Funding hides the cost of war**: a tax-financed war produces a shortfall and resistance now; a bond-financed one produces nothing now and service later on classes that didn't choose it; the ledger shows what is deferred and to whom. When `service > τ_d × revenue`: tax, roll over at a rising `r_sov`, debase (v2), or **default** — `D` wiped, bondholders' stock destroyed (foreign holders raise `h`), `default_history` set, Public Credit closed `k` years, `O −1`, revenue relieved. Sinking Fund (v2) earmarks and can be raided. Regression chains: debt collapse; bank failure; the bondage spiral.

---

## 12. Taxation

The mechanic is **incidence**: who nominally pays is almost never who actually pays. Revenue as it grows: a band, none; herds, the chief's own herd and tribute; fields, the crown demesne (fields the State owns), feudal dues, tithe, tax farming; towns, assessed taxes by Collectors, crown lands sold. Assessed taxes need collectors, a money economy, and authority — without them an excise becomes tax farming.

### 12.1 Instruments
| Instrument | Base | Designer note |
|---|---|---|
| Land tax | rent | cannot shift |
| Tithe | gross field produce | falls on rent; discourages improvement |
| Capitation | heads | proportioned to nothing; felt at the bottom |
| Wage tax | wages, at the employer | raises `w_natural`; passes forward |
| Profit tax | profit of stock | mobile and hard to see: evaded, shifted, or gone |
| Excise on Provisions/Wares | subsistence and comfort classes | raises `w_natural`; passes forward |
| Excise on Luxuries | Luxuries | stays with the buyer; shrinks the base — in a landed nation, back into Attendance |
| Customs | classes on a route, at the border location | above a threshold, smuggling opens an untaxed route |
| Tolls | users of a public work | user-pays |
| Poor Rate | rent, earmarked | — |
| Tax farming | any instrument sold for a lump sum | a credit instrument with a high effective rate and armed men |
| Sale of crown lands | one-time | the State's land shares transfer |

### 12.2 Incidence, evasion, budget
```
assessed = base × rate;   collected = assessed × (1 − evasion) × (1 − collection_cost)
evasion  = g(rate, certainty, mobility of base) × (1 − enforcement_instrument)
burden by class: recorded after the following year's wage, price, and placement adjustment (one-year lag, labelled)
```
Wage and Provisions taxes enter `w_natural` and pass forward through `π` and the split rule into prices — where `π ≈ 0` they land on the labourer as disorder. Profit taxes are re-placed away (hoards, bonds, land, abroad) until returns re-equalise. Rent taxes don't shift. Luxury excises shrink the base by substitution. Customs split between the merchant's gap and the consumer, and fall off a cliff above the smuggling threshold. Four hidden attributes — proportion, certainty, convenience, economy — show only as an unrest multiplier, evasion, subsistence credit, and `collection_cost` (the Collector record grows with the number of instruments). Revenue capacity peaks per instrument, differently for every property structure.

The **incidence table** — assessed on / borne by, per class, in baskets, last year — is the teaching device. A sovereign who cannot tax rent ends up taxing bread and sees it arrive as riots.

**The budget** is the State's consumption function, one stacked bar tagged productive/unproductive: defence (pay and basket; underfunded → `supply`, `loyalty` fall), justice (`J`), works (the Focus), service, court (feeds `A_S`, diminishing), transfers. Instruments are laws; a Landed Interest that blocks the land tax pushes the burden to excise; Moneyed and Landed fight over whose tax funds the debt; tax farming needs no law; the single tax on rent is available and whether Landed permits it is the physiocrats' failure re-enacted. Under-taxation lapses laws; over-taxation past the peak is a spiral whose signature is falling revenue at rising rates.

---

## 13. Regression and the end of a nation

**Triggers** — discrete: mutiny; capital loss after a war above a share of stock or a Port taken; a revolt the army fails to contain; a Provisions route or grain guarantee broken past the threshold; default above a share; a bank run (v2). **Spiral**: `k_spiral` years with `N̄ < N_crit` and falling, `U_disorder > U_crit`, reinvestment ≈ 0, produce per head falling; a warning band shows while the window fills.

**Resolution**, one step: (1) find the highest configuration whose gates the surviving assets still meet — nodes, not stage labels; a manufactory economy can fall to putting-out, a settled nation back to herding if the fields are lost and the herds are not; (2) flow sizes in bulk down the vertical edges, with their wealth; (3) lapse laws the State can no longer pay for or enforce; (4) keep Tree I/II nodes lit but idle; (5) backslide `E` at `α_collapse`; (6) reset `PSV` to what the surviving `M` justifies. Poorer, quiet, stable, temporary. Rivals regress by the same rules.

**Shown**: ordinary regressions get a marker on the curves with a numbers-only tooltip. **The final ledger** appears only when a nation ends (no location, no herds — by collapse or conquest): turns elapsed; terminal condition; regressions; the three curves final and peak; population, class sizes, productive/unproductive, emigrated, military dead; locations at peak and end; stock, hoard share, interest, debt/revenue, defaults, laws enacted/repealed/lapsed, nodes lit; top three rivals by hostility with strength, wars, trade, treaties; wars declared/suffered/won/lost, locations taken/lost, plunder. No stage line, no chain, no reading, no pointer.

---

## 14. Events, display, credits

**Events** are exogenous only: plague (records shrink → `wa_L` up → bound labour cracks), harvest failure in a location, the Watt event, a trade fair becoming a town, a new ore or coal find, wild herds migrating. Raids, foreign demand, revolts, dismissals, and regressions are outcomes and are marked as such.

### 14.1 The three curves
1. **Produce per head** = value in baskets of productive output ÷ population. 2. **Labourer's share** = labour income ÷ (labour income + property income), labour income being wages and in-kind pay to *productive* records only — attendance, soldiers, and servants are property income spent, never counted twice; in a band the curve is 1.0. 3. **Freedom index** = share of population in records with walk-away above `wa_free`. Plus the `N̄` band behind curve 1, regression markers, and — for every nation — visible to all. Never summed. The hegemony countdown (§1.4), when running, sits above the curves.

### 14.2 Panels and the headline
Six all-number panels: class ledger; incidence tables; capital flow; politics (`A_S` beside each Interest's authority and radicalism; enforcement on each law; the three numbers on each dark node); routes and treaties; security. Above them a **headline strip** — produce per head, labourer's share, `N̄`, `A_S`, each with its change since last year — and the map of locations coloured by nation with the three world shares per nation. The clock and its speed sit with the headline.

### 14.3 Credits
Reading list, titles only: *An Inquiry into the Nature and Causes of the Wealth of Nations*; *Lectures on Jurisprudence*; *The Theory of Moral Sentiments*; Hunt & Lautzenheiser, *History of Economic Thought: A Critical Perspective*.

---

## 15. Parameters

| Name | Meaning | Default |
|---|---|---|
| `κs`, `κw`, `d_dep` | authority exponents; per dependent | 0.5, 1.0, 0.5 |
| `ℓ₀`, `j`, `δ_ℓ` | legibility start, gain, decay | 0, 0.02, 0.01 |
| `β` | population response | 0.02/yr |
| `η`, `ζ`, `γ`, `h` | labour elasticity; stock elasticity; herd breeding; head per herdsman | 0.7, 0.3, 0.08, 40 |
| `τ_turn` | stock freed per year | 0.08 |
| `ε_g` | price elasticity: Provisions, Materials, Wares, Luxuries, Arms, Ships | 0.5, 0.8, 1.0, 1.5, 1.0, 1.0 |
| `σ` | substitution sharpness | 2.0 |
| `s_att`, `s_lux`, vanity cap | standing per basket | 1.0; 0.6 → 1.6 |
| `ω` | hoard re-entry | 0.2 |
| `a`, `λ`, `p` | security scale, lag, event weight | 1.0, 0.7, 0.3 |
| `b`, `d₀` | threat scale; distance decay `1/(1+d/d₀)` | 1.0, 3 |
| `c_r` | internal threat: merchants/capitalists, craftsmen, labourers, landlords | 1.2, 0.6, 0.3, 0 |
| `u` | disorder weight | 0.8 |
| `κf`, `N₀` | sigmoid slope, centre | 1.0, 0 |
| `k_siege`, `k_cap` | siege years; capacity per stock | 2; tune |
| `s`, `ρ`, `σ` | lender's share; risk premia | 0.5; tune |
| `τ_d` | service/revenue that forces a choice | 0.4 |
| `θ`, `θ'`, `w_r`, `k_veto` | passing bar; self-enactment bar; radicalism weight; veto cooldown | 1.0, 1.5, 0.5, 5 |
| `δ`, `a₁–a₆`, `b₁–b₄`, `C₀` | `A_S` decay, weights, consensus | 0.05; tune; 1.0 |
| `J_cust` | justice floor | 0.3 / 0.4 |
| `α_up`, `α_down`, `α_collapse` | expectation adaptation | 0.3, 0.1, 0.8 |
| `w_tier`, `a_split`, `u₁–u₃` | unrest weights; split; thresholds | 8:2:0.5; tune; 0.2, 0.5, 1.0 |
| `ρ_h` | strike decay | 0.3 |
| `N_crit`, `U_crit`, `k_spiral` | spiral window | −2; tune; 4 |
| `wa_free` | freedom threshold | 0.3 |
| `H_share`, `H_years` | hegemony threshold; countdown | 0.75; 25 |
| clock | years per real second at slow/fast/faster/very fast | 0.1, 0.2, 0.5, 2 |

---

## 16. Scope and open questions

### 16.1 First build (one table)
| Area | In | Deferred |
|---|---|---|
| World | ~24 locations, 3 nations, all full simulations with scripted sovereigns; every nation a band at start; the clock with four speeds and auto-pause; hegemony end with two winners | more nations; presets |
| Opening | move/stay, follow the herds, raid and barter, share rule, tamed-animal law, settling | — |
| Classes | hunters, herd-owners, herdsmen, landlords, serfs, retainers, craftsmen, tenants, merchants, capitalists, labourers, soldiers, State | clergy, servants, visible Collectors |
| Goods | all seven classes | — |
| Producers | hunting, herding; field, workshop, manufactory, Port, State | putting-out, mine as separate, ironworks |
| Trees | I all; II production 9 + defence 3 + bills; III property 6, labour 5, commerce 4, revenue 4, usury, public credit, standing army, justice, poor rate | the rest |
| Economy | production functions, split rule, `r̄`, placement, basket money, logit tiers, standing, one hoard rule, propensities, wage formula, `market_size` | specie; ethic bonus |
| Politics | order signal, five Interests, `ℓ`, `A_S` with handovers, passing/veto/enforcement, `J` | — |
| Unrest | `E` subsistence and comfort; `U`; disorder vs demand; strike, riot, revolt, desertion, mutiny; six responses | luxury-tier `E`; price control |
| Military | `M`, `PSV`, `PTV`, `N_r`, `N̄`, `f`; size from the draw; raids; wars per location; cession, tribute | militia, navy, alliances |
| Trade | routes with the capacity formula; stock routes; `h_ij`; treaties: tariff ceiling, access, tribute, cession, grain guarantee; breach and casus belli | exclusive, most-favoured, non-aggression |
| Credit | private (landlords, craftsmen, labourers); public (treasure, bonds, service, rollover, default); Moneyed by apportionment | banks, projectors, sinking fund, debasement |
| Taxation | land tax, two excises, customs, tithe as a flat draw, tax farming; incidence table; budget | the rest |
| Regression | all triggers but bank run; resolution 1–6; markers; final ledger | — |
| Display | curves, `N̄` band, headline, map with world shares, six panels, countdown, credits | — |

### 16.2 Open questions
- **Scripted sovereigns.** Three scripts of ~6 rules over the action list — *herding* (raid when short; follow grazing; resist settling), *landed* (defend the host; block land tax; enclose when Materials are dear; impose grain guarantees on weaker neighbours), *commercial* (free trade; charters on closing routes; standing army; public credit; impose tariff ceilings) — selected each decade by the nation's dominant Interest. Their quality decides whether rivals are interesting.
- **Map size and pacing.** 24 locations and a 200–400-year run at "fast" is a guess; the first build should expose both.
- **Hegemony tuning.** 75% on two of three shares may be unreachable with three evenly matched nations or trivial with one runaway; the threshold and the countdown are parameters for that reason.
- **Later-chapter hooks.** Malthus is the population rule at its limit; Ricardo's rent is the yield difference between locations; Marx is the labourer's-share curve extrapolated. Stubs only.
