"""Generic, self-describing JSON (de)serialisation for the dataclass state tree (Doc
00: "The world is a tree of dataclasses ... serialisable to JSON").

Every dataclass, Enum, dict (with arbitrary key types), tuple, set, and frozenset is
tagged with enough information (module + qualname) to reconstruct itself with no
external type hints — `from_jsonable(to_jsonable(x)) == x` for any `x` built from
these primitives. `rng` (a numpy Generator) and `ledger` (output, not state) are
excluded from `World`'s round-trip; see `JSON_EXCLUDE_FIELDS`.
"""

from __future__ import annotations

import importlib
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

#: dataclass type -> field names to omit from serialisation (they're not part of the
#: "lossless" contract: transient or output, not simulation state).
JSON_EXCLUDE_FIELDS: dict[type, frozenset[str]] = {}


def _qualify(cls: type) -> tuple[str, str]:
    return cls.__module__, cls.__qualname__


def _resolve(module: str, qualname: str) -> Any:
    obj: Any = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        module, qualname = _qualify(type(obj))
        return {"__enum__": [module, qualname], "name": obj.name}
    if is_dataclass(obj) and not isinstance(obj, type):
        module, qualname = _qualify(type(obj))
        excluded = JSON_EXCLUDE_FIELDS.get(type(obj), frozenset())
        return {
            "__dataclass__": [module, qualname],
            "fields": {
                f.name: to_jsonable(getattr(obj, f.name))
                for f in fields(obj)
                if f.name not in excluded
            },
        }
    if isinstance(obj, dict):
        return {"__dict__": [[to_jsonable(k), to_jsonable(v)] for k, v in obj.items()]}
    if isinstance(obj, tuple):
        return {"__tuple__": [to_jsonable(x) for x in obj]}
    if isinstance(obj, frozenset):
        return {"__frozenset__": [to_jsonable(x) for x in obj]}
    if isinstance(obj, set):
        return {"__set__": [to_jsonable(x) for x in obj]}
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    raise TypeError(f"to_jsonable: don't know how to serialise {type(obj)!r}")


def from_jsonable(data: Any) -> Any:
    if data is None or isinstance(data, (str, int, float, bool)):
        return data
    if isinstance(data, list):
        return [from_jsonable(x) for x in data]
    if isinstance(data, dict):
        if "__enum__" in data:
            module, qualname = data["__enum__"]
            enum_cls = _resolve(module, qualname)
            return enum_cls[data["name"]]
        if "__dataclass__" in data:
            module, qualname = data["__dataclass__"]
            cls = _resolve(module, qualname)
            kwargs = {name: from_jsonable(value) for name, value in data["fields"].items()}
            return cls(**kwargs)
        if "__dict__" in data:
            return {from_jsonable(k): from_jsonable(v) for k, v in data["__dict__"]}
        if "__tuple__" in data:
            return tuple(from_jsonable(x) for x in data["__tuple__"])
        if "__frozenset__" in data:
            return frozenset(from_jsonable(x) for x in data["__frozenset__"])
        if "__set__" in data:
            return {from_jsonable(x) for x in data["__set__"]}
        raise ValueError(f"from_jsonable: untagged dict {list(data)[:5]!r}")
    raise TypeError(f"from_jsonable: don't know how to deserialise {type(data)!r}")
