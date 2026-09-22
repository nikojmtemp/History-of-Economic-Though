"""Doc 07, the map: the rendered chart never has two adjacency lines crossing, and no
line runs through a node it doesn't join. Checked on every shipped scenario against
the real `compute_layout` output (the same positions `MapNode.x/y` carry), not on the
authored grid alone — the layout may move nodes, and the guarantee is about the
positions it returns."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock.api.layout import (
    compute_layout,
    count_crossings,
    graph_edges,
    min_edge_node_clearance,
    segments_cross,
)
from stock.sim.scenario import load_scenario

SCENARIOS = sorted(str(p) for p in Path("tests/scenarios").glob("*.yaml"))
assert SCENARIOS, "no scenarios found: the planarity guarantee would go unchecked"

#: Canvas px between a node's centre and any line that doesn't join it; the map caps
#: node radius at 24px, so this keeps every ring clear of every passing line.
MIN_CLEARANCE_PX = 30.0


@pytest.mark.parametrize("path", SCENARIOS)
def test_map_has_no_crossing_adjacency_lines(path: str) -> None:
    world = load_scenario(path)
    layout = compute_layout(world)
    edges = graph_edges(world)
    assert set(layout) == set(world.locations)
    assert count_crossings(layout, edges) == 0


@pytest.mark.parametrize("path", SCENARIOS)
def test_no_adjacency_line_runs_through_another_node(path: str) -> None:
    world = load_scenario(path)
    layout = compute_layout(world)
    edges = graph_edges(world)
    if not edges:
        return
    assert min_edge_node_clearance(layout, edges) >= MIN_CLEARANCE_PX


def test_layout_is_deterministic_and_stays_on_canvas() -> None:
    a = compute_layout(load_scenario("tests/scenarios/three_bands_ai.yaml"))
    b = compute_layout(load_scenario("tests/scenarios/late_start.yaml"))  # same topology, other seed
    assert a == b
    for x, y in a.values():
        assert 0 <= x <= 1000 and 0 <= y <= 600


def test_segments_cross_detects_proper_and_touching_cases() -> None:
    assert segments_cross((0, 0), (2, 2), (0, 2), (2, 0))
    assert segments_cross((0, 0), (2, 0), (1, 0), (1, 1))  # T-touch
    assert not segments_cross((0, 0), (1, 0), (2, 0), (3, 0))  # collinear, disjoint
    assert not segments_cross((0, 0), (1, 1), (0, 1), (-1, 2))
