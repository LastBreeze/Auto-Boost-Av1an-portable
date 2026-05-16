from __future__ import annotations

from typing import Any, Callable, Concatenate, overload

from ..exceptions import CustomRuntimeError, CustomValueError
from ..types import KwargsT

__all__ = ["fallback", "filter_kwargs", "iterate", "kwargs_fallback"]


def iterate[T, **P, R](
    base: T, function: Callable[Concatenate[T | R, P], R], count: int, *args: P.args, **kwargs: P.kwargs
) -> T | R:
    """
    Execute a given function over the base value multiple times.

    Different from regular iteration functions is that you do not need to pass a partial object.
    This function accepts *args and **kwargs. These will be passed on to the given function.

    - Example:
        ```python
        >>> iterate(5, lambda x: x * 2, 2)
        20
        ```

    Args:
        base: Base value, etc. to iterate over.
        function: Function to iterate over the base.
        count: Number of times to execute function.
        *args: Positional arguments to pass to the given function.
        **kwargs: Keyword arguments to pass to the given function.

    Returns:
        Value, etc. with the given function run over it *n* amount of times based on the given count.
    """

    if count <= 0:
        return base

    result: T | R = base

    for _ in range(count):
        result = function(result, *args, **kwargs)

    return result


_fallback_missing = object()


@overload
def fallback[T](value: T | None, *fallbacks: T | None) -> T: ...
@overload
def fallback[T](value: T | None, *fallbacks: T | None, default: T) -> T: ...
def fallback[T](value: T | None, *fallbacks: T | None, default: Any = _fallback_missing) -> T:
    """
    Utility function that returns a value or a fallback if the value is None.

    - Example:
        ```python
        >>> fallback(5, 6)
        5
        >>> fallback(None, 6)
        6
        ```

    Args:
        value: Input value to evaluate. Can be None.
        *fallbacks: Value to return if the input value is None.

    Returns:
        Input value or fallback value if input value is None.
    """
    for v in (value, *fallbacks):
        if v is not None:
            return v

    if default is not _fallback_missing:
        return default

    raise CustomRuntimeError("You need to specify a default/fallback value!")


@overload
def kwargs_fallback[T](value: T | None, kwargs: tuple[KwargsT, str], *fallbacks: T | None) -> T: ...
@overload
def kwargs_fallback[T](value: T | None, kwargs: tuple[KwargsT, str], *fallbacks: T | None, default: T) -> T: ...
def kwargs_fallback[T](
    value: T | None, kwargs: tuple[KwargsT, str], *fallbacks: T | None, default: Any = _fallback_missing
) -> T:
    """Utility function to return a fallback value from kwargs if value was not found or is None."""

    return fallback(value, kwargs[0].get(kwargs[1], None), *fallbacks, default=default)


@overload
def filter_kwargs(func: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]: ...


@overload
def filter_kwargs(func: Callable[..., Any], **kwargs: Any) -> dict[str, Any]: ...


def filter_kwargs(func: Callable[..., Any], kwargs: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    """
    Filter kwargs to only include parameters that match the callable's signature, ignoring **kwargs.

    - Examples:
        ```python
        >>> def my_func(a: int, b: str, c: bool = True):
        ...     return a, b, c
        >>> filter_kwargs(my_func, a=1, b="hello", c=False, d="extra")
        {'a': 1, 'b': 'hello', 'c': False}
        >>> filter_kwargs(my_func, {"a": 1, "b": "hello", "c": False, "d": "extra"})
        {'a': 1, 'b': 'hello', 'c': False}
        ```

    Args:
        func: The callable to filter kwargs for.
        kwargs: Dictionary of keyword arguments to filter.
        **kw: Keyword arguments to filter (used when kwargs is None).

    Returns:
        A dictionary containing only the kwargs that match the callable's parameters.
    """

    if not (filtered_kwargs := fallback(kwargs, kw)):
        return {}

    from inspect import signature

    try:
        sig = signature(func)
    except Exception as e:
        raise CustomValueError(e.args[0], filter_kwargs, func) from e

    param_names = {name for name, param in sig.parameters.items() if param.kind != param.VAR_KEYWORD}

    return {name: value for name, value in filtered_kwargs.items() if name in param_names}
