from __future__ import annotations

from typing import Any

__all__ = ["deepmerge"]


def deepmerge(source: dict[Any, Any], destination: dict[Any, Any]) -> dict[Any, Any]:
    for key, value in source.items():
        if isinstance(value, dict):
            node = destination.setdefault(key, {})
            deepmerge(value, node)
        else:
            destination[key] = value

    return destination
