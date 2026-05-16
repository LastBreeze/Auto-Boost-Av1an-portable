from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Iterable, Protocol, SupportsFloat, SupportsIndex, TypeVar, overload, runtime_checkable

__all__ = [
    "ComparatorFunc",
    "SupportsAdd",
    "SupportsAllComparisons",
    "SupportsDunderGE",
    "SupportsDunderGT",
    "SupportsDunderLE",
    "SupportsDunderLT",
    "SupportsFloatOrIndex",
    "SupportsIndexing",
    "SupportsKeysAndGetItem",
    "SupportsRAdd",
    "SupportsRichComparison",
    "SupportsRichComparisonT",
    "SupportsString",
    "SupportsSumNoDefaultT",
    "SupportsTrunc",
]


@runtime_checkable
class SupportsAdd[T_contra, T_co](Protocol):
    def __add__(self, x: T_contra, /) -> T_co: ...


@runtime_checkable
class SupportsRAdd[T_contra, T_co](Protocol):
    def __radd__(self, x: T_contra, /) -> T_co: ...


class _SupportsSumWithNoDefaultGiven(SupportsAdd[Any, Any], SupportsRAdd[int, Any], Protocol): ...


SupportsSumNoDefaultT = TypeVar("SupportsSumNoDefaultT", bound=_SupportsSumWithNoDefaultGiven)


@runtime_checkable
class SupportsTrunc(Protocol):
    def __trunc__(self) -> int: ...


@runtime_checkable
class SupportsString(Protocol):
    @abstractmethod
    def __str__(self) -> str: ...


@runtime_checkable
class SupportsDunderLT[T_contra](Protocol):
    def __lt__(self, other: T_contra, /) -> bool: ...


@runtime_checkable
class SupportsDunderGT[T_contra](Protocol):
    def __gt__(self, other: T_contra, /) -> bool: ...


@runtime_checkable
class SupportsDunderLE[T_contra](Protocol):
    def __le__(self, other: T_contra, /) -> bool: ...


@runtime_checkable
class SupportsDunderGE[T_contra](Protocol):
    def __ge__(self, other: T_contra, /) -> bool: ...


@runtime_checkable
class SupportsAllComparisons(
    SupportsDunderLT[Any], SupportsDunderGT[Any], SupportsDunderLE[Any], SupportsDunderGE[Any], Protocol
): ...


type SupportsRichComparison = SupportsDunderLT[Any] | SupportsDunderGT[Any]
SupportsRichComparisonT = TypeVar("SupportsRichComparisonT", bound=SupportsRichComparison)


class ComparatorFunc(Protocol):
    @overload
    def __call__(
        self,
        arg1: SupportsRichComparisonT,
        arg2: SupportsRichComparisonT,
        /,
        *args: SupportsRichComparisonT,
        key: None = ...,
    ) -> SupportsRichComparisonT: ...

    @overload
    def __call__[T](self, arg1: T, arg2: T, /, *_args: T, key: Callable[[T], SupportsRichComparison]) -> T: ...

    @overload
    def __call__(
        self, iterable: Iterable[SupportsRichComparisonT], /, *, key: None = ...
    ) -> SupportsRichComparisonT: ...

    @overload
    def __call__[T](self, iterable: Iterable[T], /, *, key: Callable[[T], SupportsRichComparison]) -> T: ...

    @overload
    def __call__[T, SupportsRichComparisonT: SupportsRichComparison](
        self, iterable: Iterable[SupportsRichComparisonT], /, *, key: None = ..., default: T
    ) -> SupportsRichComparisonT | T: ...

    @overload
    def __call__[T0, T1](
        self, iterable: Iterable[T0], /, *, key: Callable[[T0], SupportsRichComparison], default: T1
    ) -> T0 | T1: ...


@runtime_checkable
class SupportsIndexing[T](Protocol):
    def __getitem__(self, k: int, /) -> T: ...


@runtime_checkable
class SupportsKeysAndGetItem[KT, VT](Protocol):
    def keys(self) -> Iterable[KT]: ...

    def __getitem__(self, k: KT, /) -> VT: ...


SupportsFloatOrIndex = SupportsFloat | SupportsIndex
