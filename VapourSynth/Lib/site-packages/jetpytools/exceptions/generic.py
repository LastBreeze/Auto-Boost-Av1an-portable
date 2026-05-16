from __future__ import annotations

from typing import Any, Iterable

from ..types import FuncExcept, SupportsString
from .base import CustomValueError

__all__ = ["MismatchError", "MismatchRefError"]


class MismatchError(CustomValueError):
    """Raised when there's a mismatch between two or more values."""

    @classmethod
    def _item_to_name(cls, item: Any) -> str:
        return str(item)

    @classmethod
    def _reduce(cls, items: Iterable[Any]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(map(cls._item_to_name, items)).keys())

    def __init__(
        self,
        func: FuncExcept,
        items: Iterable[Any],
        message: SupportsString = "All items must be equal!",
        reason: Any = "{reduced_items}",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, func, reason, **kwargs, reduced_items=iter(self._reduce(items)))

    @classmethod
    def check(cls, func: FuncExcept, /, *items: Any, **kwargs: Any) -> None:
        if len(cls._reduce(items)) != 1:
            raise cls(func, items, **kwargs)


class MismatchRefError(MismatchError):
    def __init__[T](
        self, func: FuncExcept, base: T, ref: T, message: SupportsString = "All items must be equal!", **kwargs: Any
    ) -> None:
        super().__init__(func, [base, ref], message, **kwargs)

    @classmethod
    def check(cls, func: FuncExcept, /, *items: Any, **kwargs: Any) -> None:
        if len(cls._reduce(items)) != 1:
            raise cls(func, *items, **kwargs)
