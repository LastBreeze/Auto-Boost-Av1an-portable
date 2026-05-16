from __future__ import annotations

from typing import Self, overload

__all__ = ["Coordinate", "Position", "Size"]


class Coordinate:
    """
    Positive set of (x, y) coordinates.

    Raises:
        ValueError: Negative values were passed.
    """

    x: int
    """Horizontal coordinate."""

    y: int
    """Vertical coordinate."""

    @overload
    def __init__(self, other: tuple[int, int] | Self, /) -> None: ...

    @overload
    def __init__(self, x: int, y: int, /) -> None: ...

    def __init__(self, x_or_self: int | tuple[int, int] | Self, y: int | None = None, /) -> None:
        if isinstance(x_or_self, int):
            x = x_or_self
        else:
            x, y = x_or_self if isinstance(x_or_self, tuple) else (x_or_self.x, x_or_self.y)

        if y is None:
            from ..exceptions import CustomValueError

            raise CustomValueError("y coordinate must be defined!", self.__class__)

        if x < 0 or y < 0:
            from ..exceptions import CustomValueError

            raise CustomValueError("Values can't be negative!", self.__class__)

        self.x = x
        self.y = y


class Position(Coordinate):
    """Positive set of an (x,y) offset relative to the top left corner of an area."""


class Size(Coordinate):
    """Positive set of an (x,y), (horizontal,vertical), size of an area."""
