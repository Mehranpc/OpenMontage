"""Stable JSON-safe normalization for durable result/checkpoint persistence."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def to_json_safe(value: Any) -> Any:
    """Recursively normalize common OpenMontage result values for JSON persistence.

    Persistence boundaries must not depend on every tool remembering to convert its
    own dataclass/Path/set members. Unknown objects are stringified only as a last
    resort so reporting cannot retroactively invalidate expensive execution.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return to_json_safe(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [to_json_safe(item) for item in value]
        try:
            return sorted(normalized)
        except TypeError:
            return sorted(normalized, key=lambda item: repr(item))
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_json_safe(to_dict())
        except Exception:
            pass
    return str(value)


__all__ = ["to_json_safe"]
