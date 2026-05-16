from __future__ import annotations

from abc import ABCMeta
from enum import Enum, EnumMeta, ReprEnum
from enum import property as enum_property
from typing import TYPE_CHECKING, Any, Self

from ..exceptions import CustomTypeError, NotFoundEnumValueError
from ..types import FuncExcept, copy_signature

__all__ = ["CustomEnum", "CustomIntEnum", "CustomStrEnum", "EnumABCMeta"]


class EnumABCMeta(EnumMeta, ABCMeta):
    """Metaclass combining EnumMeta and ABCMeta to support abstract enumerations."""

    @copy_signature(EnumMeta.__new__)
    def __new__(mcls, *args: Any, **kwargs: Any) -> Any:
        enum_cls = super().__new__(mcls, *args, **kwargs)

        if len(enum_cls) == 0:
            return enum_cls

        if enum_cls.__abstractmethods__:
            raise CustomTypeError(
                "Can't instantiate abstract class {cls_name} without an implementation "
                "for abstract method{plural} {methods}.",
                enum_cls,
                cls_name=enum_cls.__name__,
                plural="s" if len(enum_cls.__abstractmethods__) > 1 else "",
                methods=", ".join(f"'{n}'" for n in sorted(enum_cls.__abstractmethods__)),
            )

        return enum_cls


class CustomEnum(Enum):
    """Base class for custom enums."""

    @classmethod
    def from_param(cls, value: Any, func_except: FuncExcept | None = None) -> Self:
        """
        Return the enum value from a parameter.

        Args:
            value: Value to instantiate the enum class.
            func_except: Exception function.

        Returns:
            Enum value.

        Raises:
            NotFoundEnumValue: Variable not found in the given enum.
        """
        func_except = func_except or cls.from_param

        try:
            return cls(value)
        except (ValueError, TypeError):
            pass

        if isinstance(func_except, tuple):
            func_name, var_name = func_except
        else:
            func_name, var_name = func_except, repr(cls)

        raise NotFoundEnumValueError(
            'The given value for "{var_name}" argument must be a valid {enum_name}, not "{value}"!\n'
            "Valid values are: [{readable_enum}].",
            func_name,
            var_name=var_name,
            enum_name=cls,
            value=value,
            readable_enum=(f"{name} ({value!s})" for name, value in cls.__members__.items()),
            reason=value,
        ) from None


class CustomIntEnum(int, CustomEnum, ReprEnum):
    """Base class for custom int enums."""

    if TYPE_CHECKING:
        _value_: int
        _value2member_map_: dict[int, Enum]

        @enum_property
        def value(self) -> int: ...


class CustomStrEnum(str, CustomEnum, ReprEnum):
    """Base class for custom str enums."""

    if TYPE_CHECKING:
        _value_: str
        _value2member_map_: dict[str, Enum]

        @enum_property
        def value(self) -> str: ...
