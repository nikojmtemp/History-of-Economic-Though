"""RNG: one Generator per world, seeded (Doc 00 conventions). Same seed -> same run."""

from __future__ import annotations

import numpy as np
from numpy.random import Generator


def make_rng(seed: int) -> Generator:
    return np.random.default_rng(seed)


def draw(rng: Generator, p: float) -> bool:
    """A single Bernoulli draw with probability `p`."""

    return bool(rng.random() < p)
