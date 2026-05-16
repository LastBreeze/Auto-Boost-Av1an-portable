from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence, overload, runtime_checkable

from ..exceptions import CustomOverflowError
from ..types import SoftRange, SoftRangeN, SoftRangesN, StrictRange, SupportsString, is_soft_range_n

__all__ = [
    "flatten",
    "invert_ranges",
    "norm_display_name",
    "norm_func_name",
    "normalize_list_to_ranges",
    "normalize_range",
    "normalize_ranges",
    "normalize_ranges_to_list",
    "normalize_seq",
    "to_arr",
]


@overload
def normalize_seq[T](val: T | Sequence[T], length: int) -> list[T]: ...


@overload
def normalize_seq(val: Any, length: int) -> list[Any]: ...


def normalize_seq[T](val: T | Sequence[T], length: int) -> list[T]:
    """
    Normalize a sequence of values.

    Args:
        val: Input value.
        length: Amount of items in the output. If original sequence length is less that this, the last item will be
            repeated.

    Returns:
        List of normalized values with a set amount of items.
    """

    val = to_arr(val)

    val += [val[-1]] * (length - len(val))

    return val[:length]


@overload
def to_arr[T](val: T | Iterable[T]) -> list[T]: ...


@overload
def to_arr(val: Any) -> list[Any]: ...


def to_arr(val: Any) -> list[Any]:
    """
    Normalize any value to a list.
    Bytes and str are not considered iterable and will not be flattened.
    """
    return list(val) if (isinstance(val, Iterable) and not isinstance(val, (str, bytes))) else [val]


@overload
def flatten[T](items: Iterable[Iterable[T]]) -> Iterator[T]: ...


@overload
def flatten(items: Iterable[Any]) -> Iterator[Any]: ...


def flatten(items: Any) -> Iterator[Any]:
    """
    Flatten an array of values.
    Bytes and str are not considered iterable and will not be flattened..
    """

    for val in items:
        if isinstance(val, Iterable) and not isinstance(val, (str, bytes)):
            for sub_x in flatten(val):
                yield sub_x
        else:
            yield val


def normalize_range(ranges: SoftRange, /, exclusive: bool = False) -> Sequence[int]:
    """
    Normalize ranges represented by a tuple to an iterable of frame numbers.

    Args:
        ranges: Ranges to normalize.
        exclusive: Whether to use exclusive (Python-style) ranges. Defaults to False.

    Returns:
        List of positive frame ranges.
    """

    if isinstance(ranges, int):
        return [ranges]

    if isinstance(ranges, tuple):
        start, stop = ranges
        step = -1 if stop < start else 1

        return range(start, stop + (not exclusive * step), step)

    return ranges


def normalize_list_to_ranges(flist: Iterable[int], min_length: int = 0, exclusive: bool = False) -> list[StrictRange]:
    flist2 = list[list[int]]()
    flist3 = list[int]()

    prev_n = -1

    for n in sorted(set(flist)):
        if prev_n + 1 != n and flist3:
            flist2.append(flist3)
            flist3 = []
        flist3.append(n)
        prev_n = n

    if flist3:
        flist2.append(flist3)

    flist4 = [i for i in flist2 if len(i) > min_length]

    return list(zip([i[0] for i in flist4], [i[-1] + exclusive for i in flist4]))


def normalize_ranges_to_list(ranges: Iterable[SoftRange], exclusive: bool = False) -> list[int]:
    out = list[int]()

    for srange in ranges:
        out.extend(normalize_range(srange, exclusive))

    return out


def normalize_ranges(
    ranges: SoftRangeN | SoftRangesN, length: int, exclusive: bool = False, *, strict: bool = True
) -> list[StrictRange]:
    """
    Normalize ranges to a list of positive ranges.

    Frame ranges can include None and negative values.
    None will be converted to either 0 if it's the first value in a SoftRange, or the end if it's the second item.
    Negative values will be subtracted from the end.

    - Examples:
        ```python
        >>> normalize_ranges((None, None), length=1000)
        [(0, 999)]
        >>> normalize_ranges((24, -24), length=1000)
        [(24, 975)]
        >>> normalize_ranges([(24, 100), (80, 150)], length=1000)
        [(24, 150)]
        ```

    Args:
        ranges: Frame range or list of frame ranges.
        length: Number of frames.
        exclusive: Whether to use exclusive (Python-style) ranges. Defaults to False.
        strict: Whether to enforce strict checking for out-of-range values.

    Returns:
        List of positive frame ranges.
    """
    from ..utils import clamp

    ranges = [ranges] if is_soft_range_n(ranges) else ranges

    out = list[tuple[int, int]]()
    exceptions = list[Exception]()

    for r in ranges:
        if r is None:
            r = (None, None)

        if isinstance(r, tuple):
            start, end = r
            if start is None:
                start = 0
            if end is None:
                end = length - (not exclusive)
        else:
            start = r
            end = r + exclusive

        if start < 0:
            start = length + start

        if end < 0:
            end = length + end - (not exclusive)

        # Always throws an error if start and end are negative
        # or higher than length
        # or start is higher than end (likely mismatched)
        if any(
            [
                start < 0 and end < 0,
                start >= length and end + (not exclusive) > length,
                start >= end + (not exclusive),
            ]
        ):
            exception = CustomOverflowError(
                f"Range `{r}` with length `{length}` could not be normalized!", normalize_ranges
            )
            exceptions.append(exception)
            continue

        if strict:
            if start < 0:
                exception = CustomOverflowError(
                    f"Start frame `{start}` in range `{r}` with length `{length}` could not be normalized!",
                    normalize_ranges,
                )
                exceptions.append(exception)
                continue
            if end + (not exclusive) > length:
                exception = CustomOverflowError(
                    f"End frame `{end}` in range `{r}` with length `{length}` could not be normalized!",
                    normalize_ranges,
                )
                exceptions.append(exception)
                continue
        else:
            start = clamp(start, 0, length - 1)
            end = clamp(end, int(exclusive), length - (not exclusive))

        out.append((start, end))

    if exceptions:
        raise ExceptionGroup("Multiple exceptions occurred!", exceptions)

    return normalize_list_to_ranges(
        [x for start, end in out for x in range(start, end + (not exclusive))], exclusive=exclusive
    )


def invert_ranges(
    ranges: SoftRangeN | SoftRangesN, lengtha: int, lengthb: int | None, exclusive: bool = False
) -> list[StrictRange]:
    norm_ranges = normalize_ranges(ranges, lengtha if lengthb is None else lengthb, exclusive)

    b_frames = {*normalize_ranges_to_list(norm_ranges, exclusive)}

    return normalize_list_to_ranges({*range(lengtha)} - b_frames, exclusive=exclusive)


@runtime_checkable
class _HasSelfAttr(Protocol):
    __self__: type | object

    def __call__(self, *args: Any, **kwds: Any) -> Any: ...


def norm_func_name(func_name: SupportsString | Callable[..., Any]) -> str:
    """Normalize a class, function, or other object to obtain its name"""

    if isinstance(func_name, str):
        return func_name.strip()

    if not isinstance(func_name, type) and not callable(func_name):
        return str(func_name).strip()

    func = func_name

    if hasattr(func_name, "__name__"):
        func_name = func.__name__
    elif hasattr(func_name, "__qualname__"):
        func_name = func.__qualname__

    if isinstance(func, _HasSelfAttr):
        func = func.__self__ if isinstance(func.__self__, type) else func.__self__.__class__
        func_name = f"{func.__name__}().{func_name}"

    return str(func_name).strip()


def norm_display_name(obj: object) -> str:
    """Get a fancy name from any object."""

    if isinstance(obj, Iterator):
        return ", ".join(norm_display_name(v) for v in obj).strip()

    from fractions import Fraction

    if isinstance(obj, Fraction):
        return f"{obj.numerator}/{obj.denominator}"

    if isinstance(obj, dict):
        return "(" + ", ".join(f"{k}={v}" for k, v in obj.items()) + ")"

    return norm_func_name(obj)
