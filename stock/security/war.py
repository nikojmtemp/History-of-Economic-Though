"""War, raids, sieges, conquest, peace (Doc 04 step 13a—step 14).

MM §15: wars resolved per contested location with outcome proportional to local
military strengths and fortification. Raids take stealable goods. Peace offers cessions,
tribute, and treaty terms. Repression suppresses disorder and reduces perceived security.

DD §9.3: raids, wars, sieges, conquest, peace; DD §7.2: action costs; DD §7.1: O events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from stock.core.actions import Action, ActionKind, register_cost_fn
from stock.core.laws import LawId
from stock.core.records import DERIVED_SIZE_CLASSES, ClassId
from stock.core.world import Location, World
from stock.security.military import (
    active_doctrine,
    has_firearms,
    matchup,
    nation_distance,
)
from stock.sim.ledger import EventRecord

if TYPE_CHECKING:
    pass


@dataclass
class PeaceTerms:
    """Terms of a peace offer: cessions, tribute, and treaty terms.

    Cession: list of location ids to transfer to the victor.
    Tribute_amount: baskets per year.
    Tribute_years: duration of tribute in years.
    Treaty_terms: any additional treaty terms (T5 fills this).
    """

    cession: list[str] = field(default_factory=list)
    tribute_amount: float = 0.0
    tribute_years: int = 0
    treaty_terms: list[Any] = field(default_factory=list)


@dataclass
class WarState:
    """State of an active war between two nations.

    Attacker: nation initiating the war.
    Defender: nation defending against the war.
    Started: year the war started.
    Contested: dict of location id → consecutive losing years for the defender.
    Peace_offer: pending peace terms, or None.
    Casus_belli: whether the war has justified cause (set by T5); defaults False.
    """

    attacker: str
    defender: str
    started: int
    contested: dict[str, int] = field(default_factory=dict)
    peace_offer: PeaceTerms | None = None
    casus_belli: bool = False


def local_strength(nation: str, location: Location, world: World) -> float:
    """Local military strength at a location, scaled by unit presence.

    For the defender: M · (units_at_location / units_total).
    For the attacker: M · attacker_projection, where
    attacker_projection = 1 / (1 + d / d0) over the carriage distance from the
    attacker's nearest location (d0 from WarParams.attack_projection_d0).

    Returns 0 if the nation has no strength."""

    nat = world.nations.get(nation)
    if nat is None or nat.ended:
        return 0.0

    M = nat.scalars.M
    if M <= 0:
        return 0.0

    if location.nation == nation:
        # Defender: scale by share of fighting units at this location
        units_at_loc = sum(
            r.size
            for r in location.records
            if r.cls in (ClassId.HERDSMEN, ClassId.HERD_OWNERS, ClassId.SERFS,
                        ClassId.RETAINERS, ClassId.SOLDIERS)
        )
        units_total = sum(
            r.size
            for loc in nat.locations(world)
            for r in loc.records
            if r.cls in (ClassId.HERDSMEN, ClassId.HERD_OWNERS, ClassId.SERFS,
                        ClassId.RETAINERS, ClassId.SOLDIERS)
        )
        if units_total <= 0:
            return 0.0
        return M * (units_at_loc / units_total)

    else:
        # Attacker: scale by projection from nearest location
        if location.nation is None:
            return 0.0
        d_ij = nation_distance(world, nation, location.nation)
        if d_ij == float("inf"):
            return 0.0
        d0 = float(world.params.war.attack_projection_d0)
        attacker_projection = 1.0 / (1.0 + d_ij / d0)
        return float(M * attacker_projection)


def fortification(location: Location, world: World) -> float:
    """Fortification bonus: 1 + fort_bonus if location is a town, else 1."""

    # A location is a town if enough non-agricultural records live there.
    # For now, use a simple heuristic: if any CRAFTSMEN, MERCHANTS, or CAPITALISTS
    # record with size > 0 exists, it's a town.
    is_town = any(
        r.size > 0
        for r in location.records
        if r.cls in (ClassId.CRAFTSMEN, ClassId.MERCHANTS, ClassId.CAPITALISTS)
    )
    if is_town:
        return float(1.0 + world.params.war.fort_bonus)
    return 1.0


def raid(world: World, attacker_id: str, location: Location, rng: Any) -> dict[str, Any]:
    """Raid on a location: strength roll and loot.

    On win: take raid_share of the location's market inventory, defender's largest
    hoard, and herd. Move loot to the attacker's nearest location.

    Returns dict with keys: won, taken_goods, taken_hoard, taken_herd, p_win.
    Emits raid/raided/defence events."""

    attacker = world.nations.get(attacker_id)
    if attacker is None or attacker.ended:
        return {"won": False, "taken_goods": 0.0, "taken_hoard": 0.0, "taken_herd": 0.0, "p_win": 0.0}

    defender_id = location.nation
    if defender_id is None:
        return {"won": False, "taken_goods": 0.0, "taken_hoard": 0.0, "taken_herd": 0.0, "p_win": 0.0}

    defender = world.nations.get(defender_id)
    if defender is None or defender.ended:
        return {"won": False, "taken_goods": 0.0, "taken_hoard": 0.0, "taken_herd": 0.0, "p_win": 0.0}

    # Compute local strengths
    S_att = local_strength(attacker_id, location, world)
    S_def = local_strength(defender_id, location, world)

    # Compute matchup
    att_doctrine = active_doctrine(attacker, world)
    def_doctrine = active_doctrine(defender, world)
    att_firearms = has_firearms(attacker, world)
    def_firearms = has_firearms(defender, world)
    mu = matchup(att_doctrine, def_doctrine, att_firearms, def_firearms, world.params)
    mu = min(mu, 1e6)  # Clamp to finite value to avoid NaN

    # Fortification
    fort = fortification(location, world)

    # Compute p_win
    numerator = S_att * mu
    denominator = numerator + S_def * fort
    if denominator <= 0:
        # No meaningful strength on either side: p_win = 0.5 (coin flip) or 0.0
        # per the advisor's guidance, 0.0 is the honest default
        p_win = 0.0
    else:
        p_win = numerator / denominator
        p_win = max(0.0, min(1.0, p_win))  # Clamp to [0, 1]

    # Roll outcome
    won = rng.random() < p_win

    taken_goods = 0.0
    taken_hoard = 0.0
    taken_herd = 0.0

    if won:
        # Take raid_share of location market inventory per good
        params = world.params.war
        for good in location.market.inventory:
            taken = location.market.inventory[good] * params.raid_share
            location.market.inventory[good] -= taken
            taken_goods += taken

        # Take raid_share of hoards from every record
        for record in location.records:
            taken = record.wealth.hoard * params.raid_share
            record.wealth.hoard -= taken
            taken_hoard += taken

        # Take raid_share of herds
        for record in location.records:
            if record.wealth.herd > 0:
                taken = record.wealth.herd * params.raid_share
                record.wealth.herd -= taken
                taken_herd += taken

        # Apply PROTECTION_OF_PROPERTY enforcement reduction
        protection_law = defender.laws.get(LawId.PROTECTION_OF_PROPERTY)
        if protection_law is not None and protection_law.enacted:
            from stock.politics.legislation import enforcement
            enf = enforcement(LawId.PROTECTION_OF_PROPERTY, defender, world)
            taken_goods *= (1.0 - enf)
            taken_hoard *= (1.0 - enf)
            taken_herd *= (1.0 - enf)

        # Move loot to attacker's nearest location (first location for simplicity)
        attacker_locs = attacker.locations(world)
        if attacker_locs:
            # Use the first attacker location; could be improved with Dijkstra if needed
            nearest_loc = attacker_locs[0]

            # Move goods to market inventory
            for good in location.market.inventory:
                if taken_goods > 0:
                    # Distribute taken_goods proportionally by good
                    share = location.market.inventory[good] / (
                        sum(location.market.inventory.values()) + 1e-9
                    )
                    nearest_loc.market.inventory[good] += taken_goods * share

            # Move hoard to attacker's largest record
            if taken_hoard > 0:
                largest_record = max(
                    (r for r in nearest_loc.records), key=lambda r: r.size, default=None
                )
                if largest_record is not None:
                    largest_record.wealth.hoard += taken_hoard

            # Move herd to HERD_OWNERS record, or largest if absent
            if taken_herd > 0:
                herd_record = nearest_loc.record(ClassId.HERD_OWNERS)
                if herd_record is not None:
                    herd_record.wealth.herd += taken_herd
                else:
                    largest_record = max(
                        (r for r in nearest_loc.records), key=lambda r: r.size, default=None
                    )
                    if largest_record is not None:
                        largest_record.wealth.herd += taken_herd

    # Emit events
    if world.ledger is not None:
        # Attacker event: raid
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=attacker_id,
                kind="raid",
                numbers={
                    "won": float(won),
                    "taken_goods": taken_goods,
                    "taken_hoard": taken_hoard,
                    "taken_herd": taken_herd,
                    "p_win": p_win,
                },
            )
        )

        # Defender event: raided or defence
        if won:
            world.ledger.add_event(
                EventRecord(
                    year=world.year,
                    nation=defender_id,
                    kind="raided",
                    numbers={
                        "lost_goods": taken_goods,
                        "lost_hoard": taken_hoard,
                        "lost_herd": taken_herd,
                    },
                )
            )
        else:
            world.ledger.add_event(
                EventRecord(
                    year=world.year,
                    nation=defender_id,
                    kind="defence",
                    numbers={"p_win": p_win},
                )
            )

    return {
        "won": won,
        "taken_goods": taken_goods,
        "taken_hoard": taken_hoard,
        "taken_herd": taken_herd,
        "p_win": p_win,
    }


def conquest_allowed(
    world: World, attacker_id: str, defender_id: str, location: Location
) -> tuple[bool, dict[str, float]]:
    """Check conquest preconditions per MM §15.

    Allowed iff:
    - N̄_target < N_conq AND
    - S_att(loc) > m_conq · S_def(loc)

    Returns (allowed, numbers_dict) where numbers_dict contains the condition values."""

    defender = world.nations.get(defender_id)
    attacker = world.nations.get(attacker_id)

    if defender is None or defender.ended or attacker is None or attacker.ended:
        return False, {}

    # Get N_bar_target (defending nation's perceived security)
    n_bar_target = defender.scalars.N_bar
    n_conq_threshold = world.params.war.n_conq

    # Get local strengths
    S_att = local_strength(attacker_id, location, world)
    S_def = local_strength(defender_id, location, world)

    # Get m_conq threshold
    m_conq = world.params.war.m_conq

    # Evaluate conditions
    condition_1 = n_bar_target < n_conq_threshold
    condition_2 = S_att > m_conq * S_def

    allowed = condition_1 and condition_2

    return allowed, {
        "N_bar_target": n_bar_target,
        "N_conq_threshold": n_conq_threshold,
        "S_att": S_att,
        "S_def": S_def,
        "m_conq": m_conq,
        "condition_1_N_bar": condition_1,
        "condition_2_strength": condition_2,
    }


def grant_casus_belli(world: World, attacker: str, defender: str) -> None:
    """Grant casus belli to attacker against defender.

    Adds (attacker, defender) to world.casus_belli so that declare_war
    between them does not incur an aggression cost.
    """

    world.casus_belli.add((attacker, defender))


def declare_war(
    world: World, attacker_id: str, defender_id: str, *, casus_belli: bool = False
) -> None:
    """Declare war between two nations.

    Creates a WarState, sets at_war=True on both, mobilises both, adds hostility,
    and emits war_declared event.

    Without casus belli, the attacker incurs an aggression cost (O event -1).
    Casus belli is set to True if the pair is in world.casus_belli."""

    attacker = world.nations.get(attacker_id)
    defender = world.nations.get(defender_id)

    if attacker is None or defender is None or attacker.ended or defender.ended:
        return

    # Check if there's a casus belli in world.casus_belli
    if (attacker_id, defender_id) in world.casus_belli:
        casus_belli = True
        world.casus_belli.discard((attacker_id, defender_id))

    # Create war state
    war_key = (attacker_id, defender_id)
    if war_key in world.wars:
        # War already exists; skip redeclaration
        return

    war_state = WarState(
        attacker=attacker_id,
        defender=defender_id,
        started=world.year,
        casus_belli=casus_belli,
    )
    world.wars[war_key] = war_state

    # Set at_war flags
    attacker.scalars.at_war = True
    defender.scalars.at_war = True

    # Mobilise both
    from stock.security.military import mobilise

    mobilise(attacker, world, True)
    mobilise(defender, world, True)

    # Add hostility
    from stock.trade.hostility import add_hostility

    h_war = world.params.trade.h_war
    add_hostility(world, attacker_id, defender_id, h_war)

    # Emit events
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=attacker_id,
                kind="war_declared",
                numbers={"vs": float(hash(defender_id) % 1000)},  # placeholder identifier
            )
        )

        # Aggression cost if no casus belli
        if not casus_belli:
            world.ledger.add_event(
                EventRecord(
                    year=world.year,
                    nation=attacker_id,
                    kind="aggression",
                    numbers={"cost": -1.0},
                )
            )


def transfer_location(world: World, location: Location, winner_id: str) -> None:
    """Transfer a location to the winner after k_siege consecutive losses.

    - Changes location.nation to winner_id
    - Records, producers, fields, fixed assets stay in place
    - Market stays in place
    - Winner's laws apply at low enforcement (new records' opposition counts in full)
    - Loser's interests recompute likewise

    Emits location_lost (loser) and location_taken (winner) events.

    If loser has no locations and no herds afterwards → set nation.ended = True
    and emit nation_ended event (Doc 05's end_nation will replace this)."""

    loser_id = location.nation
    if loser_id is None:
        return

    loser = world.nations.get(loser_id)
    winner = world.nations.get(winner_id)

    if loser is None or winner is None or winner.ended:
        return

    # Record location stats for events
    population = sum(r.size for r in location.records)
    producers_count = len(location.producers)
    stock_value = sum(p.stock_in_place for p in location.producers)

    # Transfer location
    location.nation = winner_id

    # Recompute enforcement for winner's laws
    from stock.politics.authority import interest_authority
    from stock.politics.legislation import enforcement

    interest_authority(winner, world)
    for law_id, law_state in winner.laws.items():
        if law_state.enacted:
            law_state.enforcement = enforcement(law_id, winner, world)

    # Recompute for loser
    interest_authority(loser, world)
    for law_id, law_state in loser.laws.items():
        if law_state.enacted:
            law_state.enforcement = enforcement(law_id, loser, world)

    # Emit events
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=loser_id,
                kind="location_lost",
                numbers={
                    "location": float(hash(location.id) % 1000000),
                    "population": population,
                    "producers": float(producers_count),
                    "stock": stock_value,
                },
            )
        )
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=winner_id,
                kind="location_taken",
                numbers={
                    "location": float(hash(location.id) % 1000000),
                    "population": population,
                    "producers": float(producers_count),
                    "stock": stock_value,
                },
            )
        )

    # Check if loser has ended
    loser_locs = loser.locations(world)
    loser_herds = sum(
        r.wealth.herd for r in loser.all_records(world)
    )

    if not loser_locs and loser_herds <= 0:
        loser.ended = True
        if world.ledger is not None:
            world.ledger.add_event(
                EventRecord(
                    year=world.year,
                    nation=loser_id,
                    kind="nation_ended",
                    numbers={},
                )
            )


def offer_peace(world: World, war_key: tuple[str, str], terms: PeaceTerms) -> None:
    """Offer peace with terms.

    Sets war.peace_offer on the WarState. The offer can be accepted by the loser
    or the null sovereign (via null_sovereign_peace_policy)."""

    if war_key not in world.wars:
        return

    war = world.wars[war_key]
    war.peace_offer = terms


def accept_peace(world: World, war_key: tuple[str, str], by_nation_id: str) -> None:
    """Accept a pending peace offer.

    On acceptance:
    - Apply cessions (transfer_location per location)
    - Append Tribute to payer's tributes
    - Add to world.tribute_pairs
    - Apply treaty terms (handed to T5 via war.peace_offer.treaty_terms)
    - Remove the war
    - Set at_war=False, mobilise(False)
    - Emit victory/defeat events
    """

    if war_key not in world.wars:
        return

    war = world.wars[war_key]
    if war.peace_offer is None:
        return

    attacker_id, defender_id = war_key
    attacker = world.nations.get(attacker_id)
    defender = world.nations.get(defender_id)

    if attacker is None or defender is None:
        return

    # Determine winner and loser
    winner_id = attacker_id
    loser_id = defender_id
    loser = defender

    # Apply cessions
    for loc_id in war.peace_offer.cession:
        location = world.locations.get(loc_id)
        if location is not None:
            transfer_location(world, location, winner_id)

    # Apply tribute
    if war.peace_offer.tribute_years > 0 and war.peace_offer.tribute_amount > 0:
        from stock.core.world import Tribute

        tribute = Tribute(
            payer=loser_id,
            payee=winner_id,
            amount=war.peace_offer.tribute_amount,
            years_left=war.peace_offer.tribute_years,
        )
        loser.tributes.append(tribute)
        world.tribute_pairs.add((loser_id, winner_id))

    # Apply treaty terms (Doc 04 task 5)
    if war.peace_offer.treaty_terms:
        from stock.trade.treaties import impose

        impose(world, winner_id, loser_id, war.peace_offer.treaty_terms)

    # End the war
    del world.wars[war_key]

    # Set at_war flags
    attacker.scalars.at_war = False
    defender.scalars.at_war = False

    # Demobilise both
    from stock.security.military import mobilise

    mobilise(attacker, world, False)
    mobilise(defender, world, False)

    # Emit victory/defeat events
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=winner_id,
                kind="victory",
                numbers={},
            )
        )
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=loser_id,
                kind="defeat",
                numbers={},
            )
        )


def step_tributes(world: World) -> None:
    """Each year move tribute amounts from payer to payee (Doc 05: routed to revenue).

    Decrement years_left; drop at 0."""

    for nation in world.nations.values():
        tributes_to_remove = []

        for tribute in nation.tributes:
            if tribute.payer == nation.id:
                # We are the payer; move funds
                payer = nation
                payee = world.nations.get(tribute.payee)

                if payee is not None:
                    amount = tribute.amount
                    # Debit payer's revenue first, then treasure, then largest record's hoard (Doc 05)
                    if payer.scalars.revenue >= amount:
                        payer.scalars.revenue -= amount
                    elif payer.scalars.treasure >= amount:
                        payer.scalars.treasure -= amount
                    else:
                        # Take from largest record's hoard
                        deficit = amount
                        if payer.scalars.revenue > 0:
                            taken = min(payer.scalars.revenue, deficit)
                            payer.scalars.revenue -= taken
                            deficit -= taken
                        if payer.scalars.treasure > 0 and deficit > 0:
                            taken = min(payer.scalars.treasure, deficit)
                            payer.scalars.treasure -= taken
                            deficit -= taken
                        if deficit > 0:
                            source_record = max(
                                (r for r in payer.all_records(world)),
                                key=lambda r: r.wealth.hoard,
                                default=None,
                            )
                            if source_record is not None:
                                taken = min(source_record.wealth.hoard, deficit)
                                source_record.wealth.hoard -= taken

                    # Credit payee's revenue (Doc 05)
                    payee.scalars.revenue += amount
                    payer.add_flow("tribute", -amount)
                    payee.add_flow("tribute", amount)

            # Decrement years_left
            tribute.years_left -= 1
            if tribute.years_left <= 0:
                tributes_to_remove.append(tribute)

        # Remove expired tributes
        for tribute in tributes_to_remove:
            nation.tributes.remove(tribute)
            # Remove from tribute_pairs if no other tribute flows
            if not any(
                t.payer == tribute.payer and t.payee == tribute.payee
                for t in nation.tributes
            ):
                world.tribute_pairs.discard((tribute.payer, tribute.payee))


def null_sovereign_peace_policy(world: World) -> None:
    """Null sovereign accepts any pending peace offer each year.

    For any nation with ai in (None, "null"), if it's the defender in a war with
    a pending peace offer, accept it."""

    wars_to_accept = []

    for (attacker_id, defender_id), war in list(world.wars.items()):
        if war.peace_offer is None:
            continue

        defender = world.nations.get(defender_id)
        if defender is None or defender.ended:
            continue

        # Check if defender is null sovereign
        if defender.ai in (None, "null"):
            wars_to_accept.append((attacker_id, defender_id))

    for war_key in wars_to_accept:
        accept_peace(world, war_key, war_key[1])  # by_nation_id is the defender


def war_year(world: World, war: WarState) -> None:
    """Resolve one year of war.

    For every location of the defender that is adjacent to any attacker location,
    or already contested: compute outcome; increment/reset contested[loc];
    casualties on both sides; after k_siege consecutive losses, transfer_location.

    Emit defence/location_lost/victory/defeat events."""

    attacker_id = war.attacker
    defender_id = war.defender

    attacker = world.nations.get(attacker_id)
    defender = world.nations.get(defender_id)

    if attacker is None or defender is None or attacker.ended or defender.ended:
        return

    params = world.params.war
    rng = world.rng

    # Find contested locations
    attacker_locs = {loc.id for loc in attacker.locations(world)}
    defender_locs = defender.locations(world)

    contested_this_year = []

    for def_loc in defender_locs:
        # Check if location is already contested
        if def_loc.id in war.contested:
            contested_this_year.append(def_loc)
        else:
            # Check if adjacent to any attacker location
            for neighbour_id in def_loc.neighbours:
                if neighbour_id in attacker_locs:
                    contested_this_year.append(def_loc)
                    break

    # Resolve combat for each contested location
    for location in contested_this_year:
        S_att = local_strength(attacker_id, location, world)
        S_def = local_strength(defender_id, location, world)

        # Matchup and fortification
        att_doctrine = active_doctrine(attacker, world)
        def_doctrine = active_doctrine(defender, world)
        att_firearms = has_firearms(attacker, world)
        def_firearms = has_firearms(defender, world)
        mu = matchup(att_doctrine, def_doctrine, att_firearms, def_firearms, world.params)
        mu = min(mu, 1e6)
        fort = fortification(location, world)

        # Compute p_win
        numerator = S_att * mu
        denominator = numerator + S_def * fort
        if denominator <= 0:
            p_win = 0.5
        else:
            p_win = numerator / denominator
            p_win = max(0.0, min(1.0, p_win))

        # Roll outcome
        attacker_wins = rng.random() < p_win

        # Update contested counter
        if attacker_wins:
            war.contested[location.id] = 0
        else:
            war.contested[location.id] = war.contested.get(location.id, 0) + 1

        # Check for location transfer
        if war.contested[location.id] >= params.k_siege:
            transfer_location(world, location, attacker_id)
            del war.contested[location.id]

        # Apply casualties. RETAINERS/SERVANTS are excluded: their size is derived
        # solely from their masters' Attendance spend (`set_size`'s guard;
        # `engine.consumption.attendance_to_dependents`) — writing it directly here
        # would desync that invariant until the next dismissal. Their masters take
        # casualties like everyone else, which carries through to a smaller derived
        # size next year regardless.
        casualty_rate = params.casualty_rate
        for record in location.records:
            if record.cls in DERIVED_SIZE_CLASSES:
                continue
            if record.cls in (
                ClassId.HERDSMEN, ClassId.HERD_OWNERS, ClassId.SERFS,
                ClassId.SOLDIERS, ClassId.CRAFTSMEN, ClassId.TENANTS,
                ClassId.LABOURERS, ClassId.MERCHANTS, ClassId.CAPITALISTS,
            ):
                if attacker_wins:
                    # Defender loses casualties
                    casualties = record.size * casualty_rate * (1.0 - p_win)
                else:
                    # Attacker loses casualties (via the defender's records)
                    casualties = record.size * casualty_rate * p_win
                record.size = max(0.0, record.size - casualties)

        # Emit events
        if world.ledger is not None:
            if attacker_wins:
                world.ledger.add_event(
                    EventRecord(
                        year=world.year,
                        nation=attacker_id,
                        kind="defence",
                        numbers={"location": float(hash(location.id) % 1000000), "p_win": p_win},
                    )
                )
            else:
                world.ledger.add_event(
                    EventRecord(
                        year=world.year,
                        nation=defender_id,
                        kind="defence",
                        numbers={"location": float(hash(location.id) % 1000000), "p_win": p_win},
                    )
                )


def step_war(world: World) -> None:
    """Year step 13b (after step 13a security).

    Run war_year for every active war, step_tributes, null-sovereign peace acceptance,
    and at_war bookkeeping."""

    # Run war_year for each active war
    for war in list(world.wars.values()):
        war_year(world, war)

    # Process tributes
    step_tributes(world)

    # Null sovereign peace policy
    null_sovereign_peace_policy(world)

    # Clean up wars where all locations are lost or no contested locations remain
    wars_to_remove = []
    for (attacker_id, defender_id), war in list(world.wars.items()):
        defender = world.nations.get(defender_id)
        if defender is not None and not defender.locations(world):
            # Defender has no locations; war is won
            wars_to_remove.append((attacker_id, defender_id))
        elif not war.contested:
            # No more contested locations
            wars_to_remove.append((attacker_id, defender_id))

    for war_key in wars_to_remove:
        if war_key in world.wars:
            war = world.wars[war_key]
            attacker_id, defender_id = war_key
            attacker = world.nations.get(attacker_id)
            defender = world.nations.get(defender_id)

            if attacker is not None and defender is not None:
                # End war without peace (auto-victory)
                attacker.scalars.at_war = False
                defender.scalars.at_war = False

                from stock.security.military import mobilise

                mobilise(attacker, world, False)
                mobilise(defender, world, False)

                if world.ledger is not None:
                    world.ledger.add_event(
                        EventRecord(
                            year=world.year,
                            nation=attacker_id,
                            kind="victory",
                            numbers={},
                        )
                    )

            del world.wars[war_key]


def repress(world: World, nation_id: str) -> None:
    """Set army_inside flag to suppress disorder this year.

    Costs A_S and sets nation.scalars.army_inside = True, which:
    - Reduces M_eff in perceived_security (M_eff = 0 for PSV's ln(1+M) term)
    - Suppresses strike/riot/revolt events in step_unrest

    Flag is reset at the end of step_security each year."""

    nation = world.nations.get(nation_id)
    if nation is not None:
        nation.scalars.army_inside = True


# Action cost functions
def _cost_raid(world: World, action: Action) -> float:
    return float(world.params.war.cost_raid)


def _cost_war(world: World, action: Action) -> float:
    return float(world.params.war.cost_war)


def _cost_siege(world: World, action: Action) -> float:
    return float(world.params.war.cost_siege)


def _cost_peace(world: World, action: Action) -> float:
    return float(world.params.war.cost_peace)


def _cost_repress(world: World, action: Action) -> float:
    return float(world.params.war.cost_repress)


# Handler
def apply_action(world: World, action: Action) -> bool:
    """Dispatcher for war-related actions at step 14."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return False

    if action.kind is ActionKind.DECLARE_RAID:
        target_location_id = action.payload.get("location")
        target_location = world.locations.get(target_location_id) if target_location_id else None
        if target_location is None:
            return False
        raid(world, nation.id, target_location, world.rng)
        return True

    if action.kind is ActionKind.DECLARE_WAR:
        target_nation = action.payload.get("target")
        casus_belli = action.payload.get("casus_belli", False)
        if target_nation is None:
            return False
        declare_war(world, nation.id, target_nation, casus_belli=casus_belli)
        return True

    if action.kind is ActionKind.BESIEGE:
        # No-op marker that adds a location to contested at 0
        location_id = action.payload.get("location")
        target_nation = action.payload.get("target")
        if location_id is None or target_nation is None:
            return False

        war_key = (nation.id, target_nation)
        if war_key in world.wars:
            war = world.wars[war_key]
            if location_id not in war.contested:
                war.contested[location_id] = 0
        return True

    if action.kind is ActionKind.OFFER_PEACE:
        target_nation = action.payload.get("target")
        cession = action.payload.get("cession", [])
        tribute_amount = action.payload.get("tribute_amount", 0.0)
        tribute_years = action.payload.get("tribute_years", 0)
        treaty_terms = action.payload.get("treaty_terms", [])

        war_key = (nation.id, target_nation)
        if war_key not in world.wars:
            return False

        terms = PeaceTerms(
            cession=cession,
            tribute_amount=tribute_amount,
            tribute_years=tribute_years,
            treaty_terms=treaty_terms,
        )
        offer_peace(world, war_key, terms)
        return True

    if action.kind is ActionKind.ACCEPT_PEACE:
        attacker_nation = action.payload.get("target")
        peace_war_key: tuple[str, str] | None = (str(attacker_nation), nation.id) if attacker_nation else None

        if peace_war_key is None or peace_war_key not in world.wars:
            return False

        accept_peace(world, peace_war_key, nation.id)
        return True

    if action.kind is ActionKind.REPRESS:
        repress(world, nation.id)
        return True

    return False


# Register cost functions
register_cost_fn(ActionKind.DECLARE_RAID, _cost_raid)
register_cost_fn(ActionKind.DECLARE_WAR, _cost_war)
register_cost_fn(ActionKind.BESIEGE, _cost_siege)
register_cost_fn(ActionKind.OFFER_PEACE, _cost_peace)
register_cost_fn(ActionKind.ACCEPT_PEACE, _cost_peace)
register_cost_fn(ActionKind.REPRESS, _cost_repress)
