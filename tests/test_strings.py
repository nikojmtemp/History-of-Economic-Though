"""Doc 07 acceptance: every template references only fields present in the event's
`numbers`, and the forbidden-token test passes.

The kind -> numbers-keys set is re-derived empirically here (running both scenarios
for a handful of seeds) rather than hand-copied from the engine's call sites, so this
test catches drift the moment an engine module's `numbers` dict changes shape —
exactly the failure mode `stock/ui/strings.py`'s docstring warns about.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from stock.sim.ledger import EventRecord
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from stock.sim.year import run_year
from stock.ui.strings import (
    FORBIDDEN_SUBSTRINGS,
    FORBIDDEN_WORDS,
    TEMPLATES,
    check_forbidden,
    render_event,
    template_fields,
)

SCENARIOS = ["tests/scenarios/three_bands_ai.yaml", "tests/scenarios/three_bands.yaml"]
SEEDS = [1, 2, 3]
YEARS = 250

LiveEvents = tuple[dict[str, set[str]], list[EventRecord]]


def _collect_events() -> LiveEvents:
    keys_by_kind: dict[str, set[str]] = defaultdict(set)
    events: list[EventRecord] = []
    for path in SCENARIOS:
        for seed in SEEDS:
            world = load_scenario(path)
            world.rng = make_rng(seed)
            for _ in range(YEARS):
                if all(n.ended for n in world.nations.values()):
                    break
                run_year(world)
            for e in world.ledger.events:
                keys_by_kind[e.kind] |= set(e.numbers.keys())
                events.append(e)
    return keys_by_kind, events


@pytest.fixture(scope="module")
def live_events() -> LiveEvents:
    return _collect_events()


def test_templates_reference_only_fields_present_in_numbers(live_events: LiveEvents) -> None:
    keys_by_kind, _events = live_events
    for kind, template in TEMPLATES.items():
        if kind not in keys_by_kind:
            continue  # a synthesised (resolved_*) or rare kind this run didn't see
        referenced = template_fields(template)
        available = keys_by_kind[kind]
        assert referenced <= available, (
            f"template {kind!r} references {referenced - available}, "
            f"not present in observed numbers keys {available}"
        )


def test_every_observed_engine_kind_has_a_template(live_events: LiveEvents) -> None:
    keys_by_kind, _events = live_events
    missing = set(keys_by_kind) - set(TEMPLATES)
    assert not missing, f"engine emits kinds with no template: {sorted(missing)}"


def test_no_template_contains_a_forbidden_token() -> None:
    for kind, template in TEMPLATES.items():
        for token in FORBIDDEN_SUBSTRINGS:
            assert token not in template, f"template {kind!r} contains forbidden token {token!r}"
        lowered = template.lower()
        for word in FORBIDDEN_WORDS:
            assert word not in lowered, f"template {kind!r} contains forbidden word {word!r}"


def test_check_forbidden_raises_on_each_forbidden_token() -> None:
    for token in FORBIDDEN_SUBSTRINGS:
        with pytest.raises(ValueError):
            check_forbidden(f"prefix {token} suffix")
    for word in FORBIDDEN_WORDS:
        with pytest.raises(ValueError):
            check_forbidden(f"this {word} works")


def test_render_event_never_raises_on_live_events(live_events: LiveEvents) -> None:
    _keys_by_kind, events = live_events
    for e in events:
        text = render_event(e)
        assert isinstance(text, str) and text
        check_forbidden(text)
