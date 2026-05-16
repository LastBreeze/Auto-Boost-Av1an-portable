from __future__ import annotations

from functools import update_wrapper
from types import FunctionType
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

__all__ = ["copy_func", "erase_module"]


def copy_func(f: Callable[..., Any]) -> FunctionType:
    """Try copying a function."""

    try:
        g = FunctionType(f.__code__, f.__globals__, name=f.__name__, argdefs=f.__defaults__, closure=f.__closure__)
        g.__kwdefaults__ = f.__kwdefaults__
        g = update_wrapper(g, f)
        return g  # type: ignore[return-value]
    except BaseException:
        return f  # type: ignore[return-value]


@runtime_checkable
class _HasModule(Protocol):
    __module__: str


def erase_module[F: Callable[..., Any]](func: F, modules: Sequence[str] | None = None) -> F:
    """Delete the __module__ of the function."""

    if isinstance(func, _HasModule) and (modules is None or func.__module__ in modules):
        func.__module__ = ""

    return func
