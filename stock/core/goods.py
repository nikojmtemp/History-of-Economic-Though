"""The seven good classes (DD §1.2) and the basket unit of account (DD §4.5)."""

from __future__ import annotations

from enum import Enum, auto


class Good(Enum):
    """A good class. Stands for a family of physical goods; see DD §1.2 for the emblem
    and the family each class represents."""

    PROVISIONS = auto()
    MATERIALS = auto()
    WARES = auto()
    LUXURIES = auto()
    ARMS = auto()
    SHIPS = auto()
    ATTENDANCE = auto()


class Tier(Enum):
    """A consumption tier (DD §5.1a), filled in order: SUBSISTENCE, then COMFORT, then
    STANDING."""

    SUBSISTENCE = auto()
    COMFORT = auto()
    STANDING = auto()


#: One person-year of subsistence: mostly Provisions, a little Wares (DD §4.5). This is
#: the unit of account — all value in the game is denominated in baskets.
BASKET: dict[Good, float] = {
    Good.PROVISIONS: 0.9,
    Good.WARES: 0.1,
}

#: Which tier each good class is consumed in (DD §1.2, §5.1a). Attendance and Luxuries
#: share the standing tier so that dependents and luxuries compete on one price (DD §1.2).
TIER: dict[Good, Tier] = {
    Good.PROVISIONS: Tier.SUBSISTENCE,
    Good.WARES: Tier.COMFORT,
    Good.LUXURIES: Tier.STANDING,
    Good.ATTENDANCE: Tier.STANDING,
    # Materials, Arms, and Ships are producer inputs / route and army goods, not
    # consumed directly by a record in a tier.
}

#: All good classes, in DD §1.2 order — used wherever a stable iteration order matters
#: (ledger columns, UI glyph order).
ALL_GOODS: tuple[Good, ...] = (
    Good.PROVISIONS,
    Good.MATERIALS,
    Good.WARES,
    Good.LUXURIES,
    Good.ARMS,
    Good.SHIPS,
    Good.ATTENDANCE,
)

#: Goods a record consumes in a tier (i.e. that appear in TIER). Materials/Arms/Ships
#: are producer inputs and route/army goods only.
CONSUMABLE_GOODS: tuple[Good, ...] = tuple(g for g in ALL_GOODS if g in TIER)


def basket_cost(prices: dict[Good, float], sigma: float = 2.0) -> float:
    """The price of one subsistence basket using CES (constant elasticity of substitution).

    MM §10: shares within a tier follow weight_g · P_g^(-σ), which gives the CES price index:
    P_basket = (Σ_g w_g · P_g^(1-σ))^(1/(1-σ))

    Special case: σ = 1 → Cobb-Douglas: P_basket = Π P_g^(w_g)

    Args:
        prices: per-unit prices by good
        sigma: substitution elasticity (σ_substitution from ConsumptionParams)

    Returns:
        CES price index, floored at 1e-9 per price
    """

    # Floor each price to avoid numerical issues
    floored_prices = {g: max(prices.get(g, 1.0), 1e-9) for g in BASKET.keys()}

    if abs(sigma - 1.0) < 1e-9:
        # Cobb-Douglas: P = Π P_g^(w_g)
        result = 1.0
        for good, weight in BASKET.items():
            result *= floored_prices[good] ** weight
        return result
    else:
        # CES: P = (Σ w_g · P_g^(1-σ))^(1/(1-σ))
        exponent = 1.0 - sigma
        sum_term = sum(weight * (floored_prices[good] ** exponent) for good, weight in BASKET.items())
        return float(max(sum_term ** (1.0 / exponent), 1e-9))
