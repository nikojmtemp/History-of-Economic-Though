"""Tooltips: what a law does, what a number means, what an action will do (Doc 07).

A display layer like `ui/labels.py`: keyed by the same model symbols and enum names,
shipped whole in `Snapshot.help`, read by the front end's `H(group, key)`. Every entry
states a mechanic the engine actually applies (the module that applies it is named in
a comment where it is not obvious); a law whose effect is not modelled yet says so.
Plain sentences, no quotes, under the in-game text rule (`ui/strings.check_forbidden`).
"""

from __future__ import annotations

from stock.core.laws import LAW_TABLE, LawId
from stock.ui.labels import label

# --- laws ---------------------------------------------------------------------------

LAW_HELP: dict[str, str] = {
    # Property (engine/band.py, politics/state.py, meta/trees.py, security/war.py)
    "KILL_TO_KILLER": "The hunter keeps the kill. The first rule of a band; carries a little authority and no other effect.",
    "SHARED_BY_CUSTOM": "The band shares by custom. Carries a little authority; no other effect is modelled.",
    "TAMED_ANIMAL_TO_TAMER": "Herds belong to whoever tamed them. Enacted by the taming itself: herd owners and herdsmen appear and the largest owner takes the seat.",
    "PROTECTION_OF_PROPERTY": "The State protects what is owned. Enacted by settling; while enforced, a raid takes that much less of the goods, hoards and herds it reaches, and every class is taxable.",
    "HERDS_HERITABLE": "Herds pass to heirs. The concentration it stands for is not modelled yet, so it adds authority only.",
    "LAND_OWNABLE": "Land can be held in shares. With Serfdom it opens the bound-labour method.",
    "PRIMOGENITURE": "The eldest inherits the whole estate. Its concentration of land is not modelled yet, so it adds authority only.",
    "ALIENABLE": "Land can be sold freely. The break-up of estates is not modelled yet, so it adds authority only.",
    "STOCK_SEPARABLE": "Stock can be owned apart from land. Needed before a manufactory can open.",
    # Labour (engine/mobility.py, engine/wages.py, engine/capital.py, finance/taxation.py)
    "SERFDOM": "Labour is bound to the land. Serfs cannot walk away from a bargain, a share of their income goes to the State as feudal dues, and with Land as property it opens the bound-labour method.",
    "COMMUTATION": "Labour services are commuted to rent. Serfs become tenant farmers over time and the money-rent method opens.",
    "ENCLOSURE": "Common land is enclosed. Each year a share of serfs and tenant farmers, in proportion to enforcement, are pushed into wage labour; the commons themselves are not modelled.",
    "SETTLEMENT_LAW": "Free labour is tied to its parish. Moving between free occupations meets friction in proportion to the law's enforcement.",
    "APPRENTICESHIP": "Seven years before a craft may be practised. Becoming or leaving a craftsman meets friction in proportion to enforcement.",
    "GUILD_CHARTER": "The guild controls its craft. While enacted no manufactory is founded in the nation.",
    "COMBINATION_ACT": "Workers may not combine. Their share of a bargain's surplus falls by the law's enforcement, and the wage tax stays where it is assessed.",
    # Commerce (trade/routes.py, trade/treaties.py)
    "FREE_TRADE": "Routes are open to all. Its opening of routes is not modelled yet, so it adds authority only.",
    "NAVIGATION_ACT": "Only domestic ships carry the trade. Route capacity meets friction in proportion to enforcement, and it breaches any route-access term you granted.",
    "CHARTERED_COMPANY": "One company holds a route. On enactment your merchants take the route with the widest price gap and hold it exclusively.",
    # Revenue (finance/taxation.py)
    "LAND_TAX": "A rate on land shares, assessed on and borne by landlords.",
    "TITHE": "A tenth-style rate on the produce of fields, borne by whoever holds the land.",
    "CAPITATION": "A flat sum per head, assessed on people rather than wealth.",
    "WAGE_TAX": "A rate on wages. Assessed on labourers, but part shifts onto employers through the bargain unless the Combination act is enforced.",
    "PROFIT_TAX": "A rate on profit, assessed on owners of stock; part shifts to prices and wages the next year.",
    "EXCISE_PROVISIONS": "A rate on provisions bought at home. Falls hardest on those who spend most of their income on food.",
    "EXCISE_WARES": "A rate on wares bought at home.",
    "EXCISE_LUXURIES": "A rate on luxuries bought at home; only the standing tier pays it.",
    "CUSTOMS": "A rate on the value of goods crossing a route; it raises the price at the far end.",
    "TOLLS": "A charge on carriage. Raises the cost of every route through your territory.",
    "TAX_FARMING": "Your largest merchant advances next year's expected revenue now and keeps what is collected. Revenue arrives early; the difference is the farmer's.",
    "SALE_OF_CROWN_LANDS": "Sells State land for a one-off sum. Revenue this year, less rent afterwards.",
    "SINGLE_TAX_ON_RENT": "One rate on rent alone, borne by landlords. Replaces the burden other taxes put on labour and stock.",
    # Credit (finance/credit.py)
    "USURY_PROHIBITION": "Lending at interest is forbidden. All lending goes informal at a legal rate of zero.",
    "USURY_CAP": "Interest is capped at the rate you set. Lending above it stops; below the market rate, credit dries up.",
    "PUBLIC_CREDIT": "The State may borrow by selling bonds. Opens the bond market; a default closes it again for some years.",
    "SINKING_FUND": "A fund set aside to retire the debt. The fund itself is not modelled yet, so it adds authority only.",
    # Defence (security/military.py)
    "STANDING_ARMY_ACT": "A paid soldiers record is raised and kept. Doctrine becomes standing army while soldiers exist; the defence budget line pays them.",
    "MILITIA_ACT": "Every free man drills. Doctrine becomes militia; cheaper than an army, weaker in the field.",
    # Justice (politics/justice.py)
    "ADMINISTRATION_OF_JUSTICE": "Courts paid from the justice budget line. Justice rises from its customary floor toward 1 as the draw meets the need, which raises every law's enforcement.",
    # Relief (finance/taxation.py, engine/market.py)
    "POOR_RATE": "A transfer to labourers and serfs short of subsistence, funded by a rate on rent.",
    "PRICE_CONTROL_ON_GRAIN": "Lets the sovereign cap the price of provisions in a territory (the Cap price order on the Ledger).",
}

LAW_HELP_PREFIX: dict[str, str] = {
    "TARIFF_": "A duty on this good coming in over a route: the import price rises by the rate. Breaches any tariff ceiling you granted.",
    "BOUNTY_": "A payment on this good going out: the export sells above its natural price, paid from revenue.",
    "PROHIBITION_": "This good may not cross a route at all: the route is closed to it.",
}


def law_help(key: str) -> str:
    text = LAW_HELP.get(key)
    if text is not None:
        return text
    for prefix, prefix_text in LAW_HELP_PREFIX.items():
        if key.startswith(prefix):
            return prefix_text
    return ""


def law_politics(key: str) -> str:
    """Who supports and opposes a law, from the law table, as a trailing sentence."""

    try:
        spec = LAW_TABLE[LawId[key]]
    except KeyError:
        return ""
    parts = []
    if spec.support:
        parts.append("Supported by " + ", ".join(sorted(label("interest", i.name) for i in spec.support)))
    if spec.opposition:
        parts.append("opposed by " + ", ".join(sorted(label("interest", i.name) for i in spec.opposition)))
    if not parts:
        return ""
    return "; ".join(parts) + "."


# --- numbers and mechanics --------------------------------------------------------

HELP: dict[str, dict[str, str]] = {
    "headline": {
        "produce_per_head": "Output value per person this year, in baskets. Below 1 the nation does not feed itself from its own work.",
        "labour_share": "The share of output value paid as wages and kept by those who work for themselves, rather than profit or rent.",
        "n_bar": "Perceived security: felt protection less foreign and internal threat, averaged over the classes by size. Negative for years is one of the spiral conditions.",
        "a_s": "What the seat can spend on actions this year. A band refills it to its consensus each year; a State earns it from enforced laws, justice and order and loses it to disorder.",
    },
    "symbol": {
        "A_S": "State authority: the budget for actions. Enforced laws (by their weight), justice and good order add to it; strikes, riots and defeats take from it.",
        "consensus": "A band's authority, refilled to the same number every year. A move spends part of it.",
        "N_bar": "Perceived security: felt protection less foreign and internal threat, averaged over the classes.",
        "N_r": "Net security as one class feels it: protection less the threats that class is exposed to.",
        "PSV": "Felt protection: rises with military strength and with years of peace, falls after a defeat or a raid.",
        "PTV_ext": "Foreign threat: rivals' strength, discounted by distance and hostility.",
        "PTV_int": "Internal threat: what a class fears from the classes above or below it.",
        "M": "Military strength: units times equipment times doctrine times supply times loyalty.",
        "M_state": "The strength the State itself commands, apart from the classes' own arms.",
        "r_bar": "The average rate of profit on stock across all producers this year.",
        "r_market": "The interest rate lenders ask: rises with the profit rate and falls with justice.",
        "r_legal": "The highest interest the law allows. Lending above it stops.",
        "r_sovereign": "What the State pays on new bonds: the market rate plus a premium for its record of default.",
        "J": "Justice, 0 to 1: how far a law is enforced beyond custom. Courts paid from the justice line raise it.",
        "V": "Output value: everything produced this year at this year's prices, in baskets.",
        "U": "Unrest: how far a class's needs fall short of what it has come to expect.",
        "U_dis": "Disorder: unrest of classes with no authority to press a demand, so it turns to strikes, riots and revolt.",
        "O": "Order signal: this year's tally of events for and against the seat, added to authority.",
        "hoard": "Coin and goods kept back from spending. Re-enters as spending when needs are met.",
        "walk_away": "How readily a class leaves a wage bargain: its outside options over what it is offered. Below 0.2 it takes what it is given.",
        "authority": "A class's weight in politics: its wealth composition scaled by the State's legibility.",
        "radicalism": "How pressing an Interest's demand has become. At the threshold it enacts its law itself.",
        "freedom_index": "The share of classes free to walk away from a bargain.",
        "enforcement": "How far a law actually binds, 0 to 1: justice, the State's authority and the opposing Interest's weight. Below the floor for several years the law lapses.",
        "support": "The Interests that want this law; their authority lowers its bar.",
        "opposition": "The Interests that resist this law; their authority raises its bar and weakens its enforcement.",
        "treasure": "The State's coin in hand.",
        "debt": "Bonds outstanding; the service line pays their interest.",
        "revenue": "What the taxes collected this year, after the cost of collecting.",
    },
    "action": {
        "ENACT": "Passes the law if its bar is met: the cost shown is spent from authority and the law starts enforced according to justice and its opposition.",
        "REPEAL": "Strikes the law out at the cost shown. Its supporters lose what it gave them.",
        "VETO": "Blocks this Interest's demand for a while. The Interest cools, then presses again; it costs authority each time.",
        "SET_FOCUS": "Spends part of revenue every year to lower one node's gate in one territory. One focus at a time; switching forfeits what was built.",
        "CLEAR_FOCUS": "Stops the focus and its upkeep. Progress toward the node is lost.",
        "SET_TAX_RATE": "Changes the rate of an enacted tax. Takes effect next year; incidence follows a year later.",
        "SET_BUDGET": "Splits collected revenue between the lines. Defence and justice draws that fall short leave soldiers unpaid and laws less enforced.",
        "SET_DEBT_POLICY": "What happens when the debt falls due: tax to pay it, roll it over with new bonds, or default and lose the bond market for years.",
        "SET_FUNDING_MODE": "How a war is paid for: bonds hide the cost until the service falls due; taxes take it from this year's income.",
        "DECLARE_RAID": "A single strike over the frontier for goods, hoards and herds, against the defence there. No war follows and nobody is mobilised.",
        "DECLARE_WAR": "Opens a war: every year your army meets theirs on the frontier, land changes hands with the odds, and both sides pay the wartime basket.",
        "BESIEGE": "Concentrates the war on one territory: after enough lost years in a row it changes hands.",
        "OFFER_PEACE": "Proposes to end the war, with the tribute shown paid to the other side. They answer at the turn.",
        "ACCEPT_PEACE": "Ends the war on the terms offered.",
        "PROPOSE_TREATY": "Offers terms that bind the other party in your favour. They accept when the balance of strength says so; a breach later gives you cause for war.",
        "ACCEPT_TREATY": "Binds you to the terms offered. Breaking them later gives the other side cause for war.",
        "REPRESS": "Turns the army inward for a year: no strikes, riots or revolts are recorded, and the disorder that caused them still counts.",
        "PRICE_CONTROL": "Caps the price of provisions in this territory. Below the market price, supply goes elsewhere.",
        "BAND_MOVE": "Moves the whole band to that ground next year. Costs a share of consensus and the contact built where you stand.",
        "BAND_FOLLOW_HERDS": "Stays with the wild herds. Builds contact; at the threshold the herds are tamed and become property.",
        "BAND_SETTLE": "Half the band founds a field here and stops moving. Land becomes property and the largest holder takes the seat.",
        "BAND_RAID": "Takes goods and herds from a neighbouring band, against its defence.",
        "BAND_BARTER": "Opens a barter route with a neighbouring band at labour-time prices.",
    },
    "panel": {
        "warning_band": "How full the spiral window is: security below the threshold and falling, disorder above it, nothing reinvested, produce per head falling. Full for the set number of years, a regression follows.",
        "countdown": "One nation holds three quarters of two world shares. It wins when this reaches zero; the count resets if its share slips.",
        "hegemony_band": "Your share of world capital, consumption and output, against three quarters.",
        "queued": "Orders waiting for the end of the year. They apply in order at the year's end, each at the cost it then has.",
        "events": "What happened this year, newest first. Coloured by nation.",
        "ground": "Ground quality: game yield less depletion, plus one for grazing. What a band can live on.",
        "depletion": "How far the ground here is worked out. Yields fall with it; it recovers when the ground rests.",
        "contact": "Years of living beside the wild herds. At the threshold they are tamed.",
        "interests": "The five Interests and their authority. The strongest sets the nation's mode; each presses its own laws when radical enough.",
        "focus": "Revenue spent every year to lower one node's gate in one territory.",
        "laws": "Each law's enforcement, and its cost to enact or repeal now. Vetoes block an Interest that is about to enact its demand.",
        "budget": "How collected revenue is split. A line that draws less than it needs has consequences: unpaid soldiers, unenforced laws, unserviced debt.",
        "debt_due": "What you do when the debt falls due.",
        "incidence": "For each tax, who it is assessed on and who ends up paying after wages and prices shift, a year later.",
        "capital": "Every producer: its stock, its jobs, its output value and how that value splits between labour, profit and rent.",
        "routes": "Trade routes with prices at both ends. Goods move from the cheap end to the dear one within capacity.",
        "treaties": "Terms in force, who they bind and whether they are kept.",
        "hostility": "Rivals' hostility toward you, 0 to 1. Raids and breaches raise it; time and trade lower it.",
        "protection_threat": "Felt protection to the right, threats to the left, for the nation and by class.",
        "trees": "Advances light when their gate has held for a year. A regression leaves them lit but idle.",
    },
    "column": {
        "people": "Heads in this record.",
        "wealth_by_asset": "What this class owns: herds, land shares, buildings, stock, hoard, bonds, tools and loans out.",
        "hoard": "Coin and goods kept back from spending.",
        "need_met": "Subsistence, comfort and standing: how far each tier of need was met this year, 0 to 1.",
        "shortfall": "Baskets short of subsistence this year. Starvation shrinks the record.",
        "walk_away": "How readily this class leaves a wage bargain. Below 0.2 it takes what it is given.",
        "authority": "This class's weight in politics.",
        "stock": "Stock in place: the capital this producer works with, in baskets.",
        "jobs": "Jobs filled of jobs the stock can employ. Unfilled jobs are output not made.",
        "output_value": "Everything this producer made this year at this year's prices.",
        "split": "How output value divides: wages and own labour, profit on stock, rent on land.",
        "return_vs_average": "This producer's profit rate against the nation's average. Stock moves toward the higher return.",
        "method": "The way of working in use. Better methods need their advance lit and enough stock.",
        "capacity": "Baskets a route can carry this year: ships and carriage, less legal friction.",
        "gap": "The widest price difference between the two ends. Goods move from the cheap end.",
        "volume": "Baskets carried this year.",
        "customs": "Duty collected on this route.",
        "M": "Military strength.",
        "hostility": "0 calm, 1 open enmity. Above 0.5 a treaty is unlikely.",
        "distance": "Carriage distance from your nearest territory; threat and trade both fall with it.",
        "works_at": "The producers whose jobs this class fills here, with the jobs filled. A class with no jobs may still own stock or land (owns).",
        "income": "This year's income in baskets after taxation: wages for jobs, profit on stock owned, rent on land held, transfers. Below 1 per head the class cannot buy its subsistence.",
        "taxed": "What taxation took from this class before it could spend: the difference between what its producers paid it and its income. Feudal dues, land and poll taxes and the rest of the Incidence panel land here.",
        "spends_on": "What the income bought this year, by good. Subsistence first, then comfort, then standing; what is left is saved.",
        "makes": "Goods made this year, by class of good, from the method and stock in use.",
        "worked_by": "The classes filling this producer's jobs, and how many jobs each fills.",
        "owners": "Who owns the stock (or, for fields, the land), by share. Profit goes to the stock owners, rent to the land holders.",
        "assessed_on": "The class the law names as the taxpayer.",
        "borne_by": "Who actually paid, after wages and prices shifted the burden.",
        "collected": "Revenue actually raised, after evasion.",
        "collection_cost": "What collecting cost: tax collectors and their record.",
    },
    "flow": {
        "made": "The value of everything this territory's producers put on its market this year, at this year's prices.",
        "spent": "What this territory's people spent this year, in baskets: the consumption its production paid for.",
        "unsold": "The value of goods carried over unsold. It decays each year; more unsold than made means prices will fall.",
        "market": "This producer's goods against the territory's whole market: made by all producers here, wanted by all its people at this year's prices, and left unsold.",
    },
    "focus": {
        "PUBLIC_WORKS": "Roads, harbours, drainage: lowers a production node's gate in the territory.",
        "PATENT": "A grant to whoever brings a method: lowers a method node's gate.",
        "EDUCATION": "Schooling for the trade: lowers a craft or credit node's gate.",
    },
    "budget": {
        "defence": "Pays soldiers and equipment. Short, and strength falls with supply and loyalty.",
        "justice": "Pays courts. Short, and justice stays at its customary floor.",
        "works": "Pays the focus upkeep.",
        "service": "Interest on the public debt. Short, and the debt rolls or defaults according to policy.",
        "court": "The seat's own standing: attendance and luxuries for the court.",
        "transfers": "Relief under the poor rate.",
    },
    "debt_policy": {
        "TAX": "Raise the revenue to pay what falls due.",
        "ROLLOVER": "Issue new bonds to pay the old. The debt stays, the service grows.",
        "DEFAULT": "Write the debt off. Bondholders lose it and the bond market closes for years.",
    },
    "funding_mode": {
        "BONDS": "Borrow for the war. No shortfall this year; a service line next year.",
        "TAX": "Tax for the war. Less in every pocket this year; nothing owed after.",
    },
    "term": {
        "TARIFF_CEILING": "The bound party may not tariff the named goods.",
        "ROUTE_ACCESS": "The bound party keeps its routes open to the other.",
        "PORT_ACCESS": "The bound party admits the other's ships to its ports.",
        "EXCLUSIVE_ROUTE": "The bound party trades the route with the other alone.",
        "MOST_FAVOURED": "The bound party grants the other every term it grants anyone.",
        "TRIBUTE": "The bound party pays a sum each year.",
        "CESSION": "The bound party gives up a territory.",
        "GRAIN_GUARANTEE": "The bound party keeps provisions flowing to the other.",
        "NON_AGGRESSION": "Neither party declares war on the other.",
    },
    "doctrine": {
        "EVERY_MAN": "Every hunter fights. Numbers, no equipment.",
        "NATION_IN_ARMS": "Herdsmen on the move fight as they live. Mobile, self-supplied.",
        "FEUDAL_HOST": "Landlords bring their retainers. Strength rests on the estates.",
        "MILITIA": "Free men drill by law. Cheap; weaker in the field than professionals.",
        "STANDING_ARMY": "Paid soldiers, kept year round. Strongest, and the defence line must pay them.",
    },
    "seat": {
        "BAND": "No government. Decisions by consensus, refilled each year; moves spend it.",
        "CHIEF": "The largest owner rules. Laws can pass; authority comes from what is owned.",
        "STATE": "A State with revenue, courts and an army. Authority comes from enforced laws.",
    },
    "tier": {
        "SUBSISTENCE": "Food and shelter. Short of it, the record shrinks.",
        "COMFORT": "Wares and better provisions. Short of it, unrest builds.",
        "STANDING": "Luxuries and attendance. What rank is shown by.",
    },
}


def help_tables() -> dict[str, dict[str, str]]:
    """Everything the front end needs, including one entry per law with its politics."""

    laws = {}
    for law in LawId:
        text = law_help(law.name)
        politics = law_politics(law.name)
        laws[law.name] = f"{text} {politics}".strip() if politics else text
    return {**HELP, "law": laws, "law_prefix": dict(LAW_HELP_PREFIX)}
