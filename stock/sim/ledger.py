"""The ledger: the only output of sweep 1, the only input of the UI's panels (Doc 00).

Append-only. Row and event shapes are plain dicts of numbers — DD §14's rule that the
engine emits **event records, not prose** applies here: an `EventRecord.numbers` dict
never contains a string meant to be read as a sentence.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LedgerRow:
    year: int
    nation: str
    scalars: dict[str, float] = field(default_factory=dict)
    curves: dict[str, float] = field(default_factory=dict)
    world_shares: dict[str, float] = field(default_factory=dict)
    class_sizes: dict[str, float] = field(default_factory=dict)
    class_wealth: dict[str, float] = field(default_factory=dict)
    law_states: dict[str, dict[str, float]] = field(default_factory=dict)
    flows: dict[str, float] = field(default_factory=dict)

    def flatten(self) -> dict[str, Any]:
        flat: dict[str, Any] = {"year": self.year, "nation": self.nation}
        for prefix, d in (
            ("scalar", self.scalars),
            ("curve", self.curves),
            ("share", self.world_shares),
            ("size", self.class_sizes),
            ("wealth", self.class_wealth),
        ):
            for k, v in d.items():
                flat[f"{prefix}.{k}"] = v
        for law, state in self.law_states.items():
            for k, v in state.items():
                flat[f"law.{law}.{k}"] = v
        for k, v in self.flows.items():
            flat[f"flow.{k}"] = v
        return flat


@dataclass
class EventRecord:
    """{year, nation, kind, numbers} — no prose (DD §14, Doc 00 conventions)."""

    year: int
    nation: str
    kind: str
    numbers: dict[str, float] = field(default_factory=dict)


class Ledger:
    def __init__(self) -> None:
        self.rows: list[LedgerRow] = []
        self.events: list[EventRecord] = []
        #: year -> events, kept in step with `self.events` by `add_event`. A run of
        #: several hundred to a few thousand years calls `events_in_year` at least
        #: once per nation per year (meta/regression.discrete_triggers);
        #: scanning the full, ever-growing `self.events`
        #: list each time made that O(years) per call and O(years^2) overall — found
        #: chasing a "run forever" scenario-test slowdown once `tests/_harness.py`
        #: started delegating to the real 14-step year loop.
        self._events_by_year: dict[int, list[EventRecord]] = {}
        self._events_indexed_count = 0

    def add_row(self, row: LedgerRow) -> None:
        self.rows.append(row)

    def add_event(self, event: EventRecord) -> None:
        self.events.append(event)
        self._events_by_year.setdefault(event.year, []).append(event)
        self._events_indexed_count = len(self.events)

    def rows_for(self, nation: str) -> list[LedgerRow]:
        return [r for r in self.rows if r.nation == nation]

    def _reindex_events(self) -> None:
        """Rebuilds the year index from `self.events` — the fallback for code that
        reassigns or clears `.events` directly instead of going through
        `add_event` (`Ledger.load_json`; a couple of tests reset `.events = []`)."""

        self._events_by_year = {}
        for e in self.events:
            self._events_by_year.setdefault(e.year, []).append(e)
        self._events_indexed_count = len(self.events)

    def events_in_year(self, year: int) -> list[EventRecord]:
        if self._events_indexed_count != len(self.events):
            self._reindex_events()
        return list(self._events_by_year.get(year, []))

    def hash(self) -> str:
        """SHA256 hash of the ledger's rows and events (JSON-serialized with sorted keys)."""
        import hashlib

        data = {
            "rows": [asdict(r) for r in self.rows],
            "events": [asdict(e) for e in self.events],
        }
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def to_json(self, path: str | Path) -> None:
        data = {
            "rows": [asdict(r) for r in self.rows],
            "events": [asdict(e) for e in self.events],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def to_csv(self, path: str | Path) -> None:
        flat_rows = [r.flatten() for r in self.rows]
        fieldnames: list[str] = []
        seen = set()
        for r in flat_rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    fieldnames.append(k)
        with Path(path).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in flat_rows:
                writer.writerow(r)

    def to_parquet(self, path: str | Path) -> None:
        try:
            import pyarrow as pa  # type: ignore[import-untyped]
            import pyarrow.parquet as pq  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "to_parquet requires pyarrow (`pip install pyarrow`); use to_json/"
                "to_csv if it isn't available"
            ) from exc
        flat_rows = [r.flatten() for r in self.rows]
        table = pa.Table.from_pylist(flat_rows)
        pq.write_table(table, str(path))

    @staticmethod
    def load_json(path: str | Path) -> Ledger:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        ledger = Ledger()
        ledger.rows = [LedgerRow(**r) for r in data["rows"]]
        ledger.events = [EventRecord(**e) for e in data["events"]]
        ledger._reindex_events()
        return ledger


def build_row(nation: Any, world: Any) -> LedgerRow:
    """Build a LedgerRow from a Nation and World state (Doc 08 task C).

    Fills:
    - scalars: every float/int/bool field of NationScalars (via dataclasses.fields)
    - class_sizes: record size totals by ClassId.name
    - class_wealth: total wealth by ClassId.name (using land_share_value from params)
    - law_states: {law name: {"enacted": 0/1, "enforcement": x}} for laws in nation.laws
    - flows: copy of nation.flows
    - curves and world_shares left empty (Doc 05 fills them)
    """
    from dataclasses import fields as dataclass_fields

    row = LedgerRow(year=world.year, nation=nation.id)

    # Extract all float/int/bool fields from NationScalars. `world.py` has
    # `from __future__ import annotations`, so `fld.type` is the string "float" /
    # "int" / "bool", not the builtin type — comparing against the builtins here
    # always failed and left `row.scalars` empty (found while wiring meta/regression's
    # end_nation, which reads it; see DEVIATIONS-RESOLVED.md A41).
    for fld in dataclass_fields(nation.scalars):
        if fld.type in ("float", "int", "bool"):
            row.scalars[fld.name] = getattr(nation.scalars, fld.name)

    # Accumulate class_sizes and class_wealth by ClassId
    class_sizes: dict[str, float] = {}
    class_wealth: dict[str, float] = {}

    for location in nation.locations(world):
        for record in location.records:
            class_name = record.cls.name
            class_sizes[class_name] = class_sizes.get(class_name, 0.0) + record.size
            land_share_value = world.params.production.land_share_value
            total_wealth = record.wealth.total(land_share_value)
            class_wealth[class_name] = class_wealth.get(class_name, 0.0) + total_wealth

    row.class_sizes = class_sizes
    row.class_wealth = class_wealth

    # Extract law states
    for law_id, law_state in nation.laws.items():
        law_name = law_id.name if hasattr(law_id, "name") else str(law_id)
        row.law_states[law_name] = {
            "enacted": 1.0 if law_state.enacted else 0.0,
            "enforcement": law_state.enforcement,
        }

    # Copy flows
    row.flows = dict(nation.flows)

    # Curves (meta/scoreboards.py) and world shares (meta/hegemony.py) — Doc 05
    row.curves = dict(nation.curves)
    h = world.hegemony
    row.world_shares = {
        "capital": h.capital_share.get(nation.id, 0.0),
        "consumption": h.consumption_share.get(nation.id, 0.0),
        "production": h.production_share.get(nation.id, 0.0),
        "flags": float(h.flags.get(nation.id, 0)),
    }

    return row
