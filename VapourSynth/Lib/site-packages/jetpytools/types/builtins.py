from __future__ import annotations

from typing import Any, Sequence, SupportsFloat, SupportsIndex

__all__ = [
    "ByteData",
    "KwargsT",
    "SimpleByteData",
    "SimpleByteDataArray",
    "SingleOrArr",
    "SingleOrArrOpt",
    "SingleOrSeq",
    "SingleOrSeqOpt",
    "SoftRange",
    "SoftRangeN",
    "SoftRangesN",
    "StrictRange",
]

type StrictRange = tuple[int, int]
type SoftRange = int | StrictRange | Sequence[int]

type SoftRangeN = int | tuple[int | None, int | None] | None

type SoftRangesN = Sequence[SoftRangeN]

type SingleOrArr[T] = T | list[T]
type SingleOrSeq[T] = T | Sequence[T]
type SingleOrArrOpt[T] = SingleOrArr[T] | None
type SingleOrSeqOpt[T] = SingleOrSeq[T] | None

type SimpleByteData = str | bytes | bytearray
type SimpleByteDataArray = SimpleByteData | Sequence[SimpleByteData]

type ByteData = SupportsFloat | SupportsIndex | SimpleByteData | memoryview

KwargsT = dict[str, Any]
