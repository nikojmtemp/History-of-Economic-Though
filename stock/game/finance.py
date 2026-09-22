"""Public credit (design doc §14.4): borrowing at home or abroad, interest, repayment
and default, and the credit lever a foreign lender gains (§17.2).

Borrowing at home draws on the nation's own Stock (crowding out private
investment) and pays its interest back to it. Borrowing abroad brings in a
foreign people's Stock and sends interest out to them; owe them enough and they
hold a lever over you.
"""

from __future__ import annotations

from stock.game import rules
from stock.game.economy import clamp
from stock.game.state import Decision, Nation, World

DOMESTIC = "domestic"


def revenue(n: Nation) -> float:
    return float(n.last.get("tax", {}).get("collected", 0.0)) + float(n.trade.get("tolls", 0.0))


def debt(n: Nation, lender: str | None = None) -> float:
    return float(sum(d["principal"] for d in n.debts if lender is None or d["lender"] == lender))


def loan_limit(n: Nation) -> float:
    return max(rules.LOAN_FLOOR, rules.LOAN_TURNS_OF_REVENUE * revenue(n))


def interest_rate(n: Nation) -> float:
    burden = debt(n) / max(10.0 * revenue(n), rules.LOAN_FLOOR)
    return rules.INTEREST_BASE + rules.INTEREST_RISK * clamp(burden, 0.0, 1.0)


def borrow_blocker(world: World, n: Nation, source: str, amount: float) -> str | None:
    if n.seat != "civil":
        return "needs Civil Government"
    if not n.knows("public_credit"):
        return "needs Public Credit"
    if n.credit_closed >= world.turn:
        return f"no one will lend to us until turn {n.credit_closed + 1}"
    if amount <= 0:
        return "borrow something"
    if amount > loan_limit(n) + 1e-9:
        return f"at most {loan_limit(n):.0f} at a time (five turns of revenue)"
    if source == DOMESTIC:
        return None if n.stock >= amount else f"our Stock-holders have only {n.stock:.0f} to lend"
    lender = world.nations.get(source)
    if lender is None or not lender.alive or lender.id == n.id:
        return "no such lender"
    if lender.id not in n.contacts:
        return "not in contact"
    if world.war_between(n.id, lender.id):
        return "at war"
    if lender.stock < amount + 20.0:
        return f"{lender.name} have not {amount:.0f} to spare"
    if any(d.kind == "loan" and d.data.get("from") == n.id for d in lender.decisions):
        return "a request is already waiting"
    return None


def lender_agrees(world: World, lender: Nation, borrower: Nation, amount: float) -> bool:
    """An AI lender's answer: friends and the ambitious lend; others want safety."""

    rel = lender.relations.get(borrower.id, 0.0)
    ambitious = float(lender.last.get("share", 0.0)) >= rules.AMBITION_SHARE
    # lenders stay wary for as long again after a defaulter's credit reopens
    safe = borrower.credit_closed == 0 or borrower.credit_closed < world.turn - rules.CREDIT_CLOSED_TURNS
    return safe and lender.stock >= amount + 20.0 and (rel >= 10 or (ambitious and rel >= -10))


def request_foreign(world: World, n: Nation, lender: Nation, amount: float) -> bool:
    """Ask a foreign people for a loan. An AI answers at once; a player gets a decision.
    Returns True if the money arrived."""

    if lender.player:
        rate = interest_rate(n)
        lender.decisions.append(
            Decision(
                id=world.new_id("d"),
                kind="loan",
                title=f"{n.name} ask for a loan",
                text=f"{n.name} ask to borrow {amount:.0f} of our Stock at {rate:.0%} a turn. "
                f"Their debts already stand at {debt(n):.0f}; owed enough, they fall into our orbit.",
                choices=[
                    {
                        "key": "accept",
                        "label": "Lend",
                        "effect": f"{amount:.0f} Stock leaves us; interest returns.",
                    },
                    {"key": "refuse", "label": "Refuse", "effect": "Nothing changes."},
                ],
                data={"from": n.id, "amount": amount},
            )
        )
        return False
    if not lender_agrees(world, lender, n, amount):
        return False
    lend(world, lender, n, amount)
    return True


def lend(world: World, lender: Nation | None, n: Nation, amount: float) -> None:
    rate = interest_rate(n)
    if lender is None:
        n.stock -= amount
    else:
        lender.stock -= amount
    n.treasury += amount
    n.debts.append(
        {"lender": lender.id if lender else DOMESTIC, "principal": amount, "rate": rate, "since": world.turn}
    )
    who = lender.name if lender else "our own Stock-holders"
    world.emit(n.id, "loan", f"We borrow {amount:.0f} from {who} at {rate:.0%} a turn.")
    if lender is not None:
        world.emit(lender.id, "loan", f"We lend {amount:.0f} to {n.name} at {rate:.0%} a turn.")


def repay(world: World, n: Nation, lender: str | None, amount: float) -> float:
    """Pay back principal from the Treasury, the named lender's first (foreign first if none)."""

    paid_total = 0.0
    order = sorted(n.debts, key=lambda d: (d["lender"] != lender, d["lender"] == DOMESTIC))
    for d in order:
        if lender is not None and d["lender"] != lender:
            continue
        pay = min(d["principal"], amount - paid_total, n.treasury)
        if pay <= 0:
            break
        n.treasury -= pay
        d["principal"] -= pay
        paid_total += pay
        _receive(world, n, d["lender"], pay)
    n.debts = [d for d in n.debts if d["principal"] > 0.01]
    return paid_total


def _receive(world: World, n: Nation, lender: str, amount: float) -> None:
    if lender == DOMESTIC:
        n.stock += amount
        return
    other = world.nations.get(lender)
    if other is None or not other.alive:
        return
    if other.seat == "civil":
        other.treasury += amount
    else:
        other.stock += amount


def default(world: World, n: Nation, *, forced: bool = False) -> None:
    """Wipe the debt. The lenders lose it; the state's credit is closed for years."""

    foreign = {d["lender"] for d in n.debts if d["lender"] != DOMESTIC}
    domestic = debt(n, DOMESTIC)
    total = debt(n)
    n.debts = []
    n.credit_closed = world.turn + rules.CREDIT_CLOSED_TURNS
    n.sway = max(0.0, n.sway - rules.DEFAULT_SWAY)
    if domestic > 0:
        n.orders["stock"].contentment = clamp(
            n.orders["stock"].contentment - rules.DEFAULT_STOCK_CONTENTMENT, 0, 100
        )
    for f in foreign:
        other = world.nations[f]
        other.relations[n.id] = other.relations.get(n.id, 0.0) - rules.DEFAULT_RELATIONS
        world.emit(f, "default", f"{n.name} default on what they owe us.")
    why = "cannot pay its interest and " if forced else ""
    world.emit(
        n.id,
        "default",
        f"The state {why}defaults on {total:.0f} of debt. No one will lend to us for "
        f"{rules.CREDIT_CLOSED_TURNS} turns.",
    )


def service(world: World, n: Nation) -> float:
    """Pay this turn's interest from the Treasury; what cannot be paid is added to the debt."""

    due_total = 0.0
    for d in n.debts:
        due = d["principal"] * d["rate"]
        pay = min(due, max(0.0, n.treasury))
        n.treasury -= pay
        d["principal"] += due - pay
        _receive(world, n, d["lender"], pay)
        due_total += due
    n.last["debt_service"] = due_total
    if n.debts and debt(n) > rules.FORCED_DEFAULT_TURNS * max(revenue(n), rules.LOAN_FLOOR / 5.0):
        default(world, n, forced=True)
    return due_total


def credit_levers(world: World, b: Nation) -> dict[str, float]:
    """Lender -> strength of the credit lever it holds over `b` (1.0 at the threshold)."""

    threshold = max(rules.CREDIT_LEVER_FLOOR, rules.CREDIT_LEVER_TURNS * revenue(b))
    owed: dict[str, float] = {}
    for d in b.debts:
        if d["lender"] != DOMESTIC:
            owed[d["lender"]] = owed.get(d["lender"], 0.0) + d["principal"]
    return {lender: amount / threshold for lender, amount in owed.items() if amount >= threshold}
