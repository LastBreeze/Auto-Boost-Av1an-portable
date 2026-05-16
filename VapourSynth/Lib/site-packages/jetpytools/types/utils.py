from __future__ import annotations

import sys
from contextlib import suppress
from functools import wraps
from threading import Lock
from types import LambdaType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Concatenate,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    NoReturn,
    ParamSpec,
    Protocol,
    Self,
    Sequence,
    TypeVar,
    cast,
    overload,
)

if TYPE_CHECKING:
    from inspect import Signature

if sys.version_info < (3, 13):
    from typing_extensions import TypeVar, deprecated
else:
    from warnings import deprecated

from .builtins import KwargsT

__all__ = [
    "KwargsNotNone",
    "LinearRangeLut",
    "Singleton",
    "cachedproperty",
    "classproperty",
    "complex_hash",
    "copy_signature",
    "get_subclasses",
    "inject_kwargs_params",
    "inject_self",
]
# ruff: noqa: N801


def copy_signature[F: Callable[..., Any]](target: F, /) -> Callable[[Callable[..., Any]], F]:
    """
    Utility function to copy the signature of one function to another one.

    Especially useful for passthrough functions.

    .. code-block::

       class SomeClass:
           def __init__(
               self, some: Any, complex: Any, /, *args: Any,
               long: Any, signature: Any, **kwargs: Any
           ) -> None:
               ...

       class SomeClassChild(SomeClass):
           @copy_signature(SomeClass.__init__)
           def __init__(*args: Any, **kwargs: Any) -> None:
               super().__init__(*args, **kwargs)
               # do some other thing

       class Example(SomeClass):
           @copy_signature(SomeClass.__init__)
           def __init__(*args: Any, **kwargs: Any) -> None:
               super().__init__(*args, **kwargs)
               # another thing
    """

    def decorator(wrapped: Callable[..., Any]) -> F:
        return cast(F, wrapped)

    return decorator


type _InnerInjectSelfType = dict[_InjectSelfMeta, dict[_InjectSelfMeta, _InnerInjectSelfType]]
_inject_self_cls: _InnerInjectSelfType = {}


class _InjectSelfMeta(type):
    """
    Metaclass used to manage subclass relationships and type flattening for the `inject_self` hierarchy.
    """

    _subclasses: frozenset[_InjectSelfMeta]
    """All descendant metaclasses of a given `inject_self` subclass."""

    def __new__[MetaSelf: _InjectSelfMeta](
        mcls: type[MetaSelf], name: str, bases: tuple[type, ...], namespace: dict[str, Any], /, **kwargs: Any
    ) -> MetaSelf:
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)

        clsd = _inject_self_cls.setdefault(cls, {})

        for k, v in _inject_self_cls.items():
            if k in namespace.values():
                clsd[k] = v

        cls._subclasses = frozenset(cls._flatten_cls())

        return cls

    def _flatten_cls(cls, d: _InnerInjectSelfType | None = None) -> Iterator[_InjectSelfMeta]:
        """
        Recursively flatten and yield all nested inject_self metaclass relationships.

        Args:
            d: Optional inner dictionary representing the hierarchy level.

        Yields:
            Each `_InjectSelfMeta` subclass found in the hierarchy.
        """

        if d is None:
            d = _inject_self_cls[cls]

        for k, v in d.items():
            yield k
            yield from cls._flatten_cls(v)

    def __instancecheck__(cls, instance: Any) -> bool:
        """Allow isinstance() checks to succeed for any flattened subclass."""
        return any(type.__instancecheck__(t, instance) for t in cls._subclasses)

    def __subclasscheck__(cls, subclass: type) -> bool:
        """Allow issubclass() checks to succeed for any flattened subclass."""
        return any(type.__subclasscheck__(t, subclass) for t in cls._subclasses)


_T = TypeVar("_T")
_T0 = TypeVar("_T0")

_T_co = TypeVar("_T_co", covariant=True)
_T0_co = TypeVar("_T0_co", covariant=True)
_T1_co = TypeVar("_T1_co", covariant=True)

_R_co = TypeVar("_R_co", covariant=True)
_R0_co = TypeVar("_R0_co", covariant=True)
_R1_co = TypeVar("_R1_co", covariant=True)

_T_Any = TypeVar("_T_Any", default=Any)
_T0_Any = TypeVar("_T0_Any", default=Any)

_P = ParamSpec("_P")
_P0 = ParamSpec("_P0")
_P1 = ParamSpec("_P1")


class _InjectedSelfFunc(Protocol[_T_co, _P, _R_co]):  # type: ignore[misc]
    """
    Protocol defining the callable interface for wrapped functions under `inject_self`.

    This allows the injected function to be called in any of the following forms:
    - As a normal function: `f(*args, **kwargs)`
    - As a bound method: `f(self, *args, **kwargs)`
    - As a class method: `f(cls, *args, **kwargs)`
    """

    @overload
    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...
    @overload
    def __call__(_self, self: _T_co, /, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...  # type: ignore[misc]  # noqa: N805
    @overload
    def __call__(self, cls: type[_T_co], /, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...  # pyright: ignore[reportGeneralTypeIssues]


_self_objects_cache = dict[type[Any], Any]()


class _InjectSelfBase(Generic[_T_co, _P, _R_co]):
    """
    Base descriptor implementation for `inject_self`.
    """

    __isabstractmethod__ = False
    __slots__ = ("_function", "_init_signature", "_signature", "args", "kwargs")

    _signature: Signature | None
    _init_signature: Signature | None

    def __init__(self, function: Callable[Concatenate[_T_co, _P], _R_co], /, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the inject_self descriptor.

        Args:
            function: The function or method to wrap.
            *args: Positional arguments to pass when instantiating the target class.
            **kwargs: Keyword arguments to pass when instantiating the target class.
        """
        self._function = function

        self._signature = self._init_signature = None

        self.args = args
        self.kwargs = kwargs

    @overload
    def __get__(self, instance: None, owner: type) -> _InjectedSelfFunc[_T_co, _P, _R_co]: ...  # pyright: ignore[reportGeneralTypeIssues]
    @overload
    def __get__(self, instance: Any, owner: type | None = None) -> Callable[_P, _R_co]: ...  # pyright: ignore[reportGeneralTypeIssues]
    def __get__(self, instance: Any | None, owner: type | None = None) -> Any:
        """
        Return a wrapped callable that automatically injects an instance as the first argument when called.
        """

        @wraps(self._function)
        def _wrapper(*args: Any, **kwargs: Any) -> _R_co:
            """
            Call wrapper that performs the actual injection of `self`.
            """
            nonlocal instance, owner

            if instance is None and args:
                # Instance or class explicitly provided as first argument
                first_arg = args[0]

                if owner and isinstance(first_arg, owner):
                    instance, args = first_arg, args[1:]
                elif isinstance(first_arg, type(owner)):
                    owner, args = first_arg, args[1:]

            if instance is None:
                # Accessed via class

                if owner is None:
                    from ..exceptions import CustomTypeError

                    raise CustomTypeError(
                        "Cannot determine owner type for class access.", self.__class__, self._function
                    )

                obj, kwargs = self._handle_class_access(owner, kwargs)
            else:
                # Accessed via instance
                obj = instance

            return self._function(obj, *args, **kwargs)  # type: ignore[arg-type]

        return _wrapper

    def _handle_class_access(self, owner: type, kwargs: dict[str, Any]) -> tuple[object, dict[str, Any]]:
        """
        Handle logic when the descriptor is accessed from the class level.

        Args:
            owner: The class object owning the descriptor.
            kwargs: Keyword arguments passed to the wrapped function.

        Returns:
            A tuple of `(self_object, updated_kwargs)`.
        """
        if isinstance(self, inject_self.cached):
            # Cached instance creation
            try:
                return _self_objects_cache[owner], kwargs
            except KeyError:
                return _self_objects_cache.setdefault(owner, owner(*self.args, **self.kwargs)), kwargs

        if isinstance(self, (inject_self.init_kwargs, inject_self.init_kwargs.clean)):
            # Constructor accepts forwarded kwargs
            has_kwargs = any(
                param.kind in (param.VAR_KEYWORD, param.KEYWORD_ONLY)
                for param in self.__signature__.parameters.values()
            )

            if not has_kwargs:
                from ..exceptions import CustomValueError

                raise CustomValueError(
                    f"Function {self._function.__name__} doesn't accept keyword arguments.",
                    "inject_self.init_kwargs",
                    self._function,
                )

            if not self._init_signature:
                from inspect import Signature

                self._init_signature = Signature.from_callable(owner)

            init_kwargs = self.kwargs | {k: kwargs[k] for k in kwargs.keys() & self._init_signature.parameters.keys()}

            obj = owner(*self.args, **init_kwargs)

            if isinstance(self, inject_self.init_kwargs.clean):
                # Clean up forwarded kwargs
                kwargs = {k: v for k, v in kwargs.items() if k not in self._init_signature.parameters}

            return obj, kwargs

        return owner(*self.args, **self.kwargs), kwargs

    def __call__(self_, self: _T_co, *args: _P.args, **kwargs: _P.kwargs) -> _R_co:  # type: ignore[misc]  # noqa: N805
        return self_.__get__(self, None)(*args, **kwargs)

    @property
    def __func__(self) -> Callable[Concatenate[_T_co, _P], _R_co]:
        """Return the original wrapped function."""
        return self._function

    @property
    def __signature__(self) -> Signature:
        """Return (and cache) the signature of the wrapped function."""
        if not self._signature:
            from inspect import Signature

            self._signature = Signature.from_callable(self._function)
        return self._signature

    @classmethod
    def with_args[T0, **P0, R0](
        cls, *args: Any, **kwargs: Any
    ) -> Callable[[Callable[Concatenate[T0, P0], R0]], inject_self[T0, P0, R0]]:
        """
        Decorator factory to construct an `inject_self` or subclass (`cached`, `init_kwargs`, etc.)
        with specific instantiation arguments.
        """

        # TODO: The precise subclass type cannot be expressed yet when the class is itself generic.
        def _wrapper(function: Callable[Concatenate[T0, P0], R0]) -> inject_self[T0, P0, R0]:
            return cls(function, *args, **kwargs)  # type: ignore[return-value, arg-type]

        return _wrapper


class inject_self(_InjectSelfBase[_T_co, _P, _R_co], metaclass=_InjectSelfMeta):
    """
    Descriptor that ensures the wrapped function always has a constructed `self`.

    When accessed via a class, it will automatically instantiate an object before calling the function.
    When accessed via an instance, it simply binds.

    Subclasses such as `cached`, `init_kwargs`, and `init_kwargs.clean`
    define variations in how the injected object is created or reused.
    """

    __slots__ = ()

    class cached(_InjectSelfBase[_T0_co, _P0, _R0_co], metaclass=_InjectSelfMeta):
        """
        Variant of `inject_self` that caches the constructed instance.

        The first time the method is accessed via the class, a `self` object is created and stored.
        Subsequent calls reuse it.
        """

        __slots__ = ()

        class property(Generic[_T1_co, _P1, _R1_co], metaclass=_InjectSelfMeta):
            """Property variant of `inject_self.cached` that auto-calls the wrapped method."""

            __slots__ = ("__func__",)

            def __init__(self, function: Callable[[_T1_co], _R1_co], /) -> None:
                self.__func__ = inject_self.cached(function)

            def __get__(self, instance: _T1_co | None, owner: type[_T1_co]) -> _R1_co:  # pyright: ignore[reportGeneralTypeIssues]
                """Return the result of calling the cached method without arguments."""
                return self.__func__.__get__(instance, owner)()

    class init_kwargs(_InjectSelfBase[_T0_co, _P0, _R0_co], metaclass=_InjectSelfMeta):
        """
        Variant of `inject_self` that forwards function keyword arguments to the class constructor
        when instantiating `self`.
        """

        __slots__ = ()

        class clean(_InjectSelfBase[_T1_co, _P1, _R1_co], metaclass=_InjectSelfMeta):
            """
            Variant of `inject_self.init_kwargs` that removes any forwarded kwargs from the final function call
            after using them for construction.
            """

            __slots__ = ()

    class property(Generic[_T0_co, _R0_co], metaclass=_InjectSelfMeta):
        """Property variant of `inject_self` that auto-calls the wrapped method."""

        __slots__ = ("__func__",)

        def __init__(self, function: Callable[[_T0_co], _R0_co], /) -> None:
            self.__func__ = inject_self(function)

        def __get__(self, instance: _T0_co | None, owner: type[_T0_co]) -> _R0_co:  # pyright: ignore[reportGeneralTypeIssues]
            """Return the result of calling the injected method without arguments."""
            return self.__func__.__get__(instance, owner)()


class _InjectKwargsParamsBase(Generic[_T_co, _P, _R_co]):
    """
    Base descriptor implementation for `inject_kwargs_params`.
    """

    __isabstractmethod__ = False
    __slots__ = ("_function", "_signature")

    _kwargs_name = "kwargs"
    _signature: Signature | None

    def __init__(self, func: Callable[Concatenate[_T_co, _P], _R_co], /) -> None:
        """
        Initialize the inject_kwargs_params descriptor.

        Args:
            func: The target function or method whose parameters will be injected
                from the instance's `self.kwargs` mapping.
        """
        self._function = func
        self._signature = None

    @overload
    def __get__(self, instance: None, owner: type) -> Self: ...
    @overload
    def __get__(self, instance: Any, owner: type | None = None) -> Callable[_P, _R_co]: ...
    def __get__(self, instance: Any | None, owner: type | None = None) -> Any:
        """
        Descriptor binding logic.

        When accessed via an instance, returns a wrapped function that injects values from `instance.<_kwargs_name>`
        into matching function parameters.

        When accessed via the class, returns the descriptor itself.
        """
        if instance is None:
            return self

        if not hasattr(instance, self._kwargs_name):
            from ..exceptions import CustomRuntimeError

            raise CustomRuntimeError(
                f'Missing attribute "{self._kwargs_name}" on {type(instance).__name__}.', owner, self.__class__
            )

        @wraps(self._function)
        def wrapper(*args: Any, **kwargs: Any) -> _R_co:
            """
            Wrapper that performs parameter injection before calling the wrapped function.
            """
            injectable_kwargs = dict(getattr(instance, self._kwargs_name))

            if not injectable_kwargs:
                return self._function(instance, *args, **kwargs)

            args_list = [instance, *args]
            kwargs = kwargs.copy()

            for i, (name, param) in enumerate(self.__signature__.parameters.items()):
                if name not in injectable_kwargs:
                    continue

                value_from_kwargs = injectable_kwargs.pop(name)

                if i < len(args_list):
                    # Positional arg case
                    if args_list[i] == param.default:
                        args_list[i] = value_from_kwargs
                else:
                    # Keyword arg case
                    if kwargs.get(name, param.default) == param.default:
                        kwargs[name] = value_from_kwargs

            # Merge leftover kwargs if subclass allows
            if isinstance(self, inject_kwargs_params.add_to_kwargs):
                kwargs |= injectable_kwargs

            return self._function(*tuple(args_list), **kwargs)

        return wrapper

    def __call__(self_, self: _T_co, *args: _P.args, **kwargs: _P.kwargs) -> _R_co:  # type: ignore[misc]  # noqa: N805
        return self_.__get__(self, type(self))(*args, **kwargs)

    @property
    def __func__(self) -> Callable[Concatenate[_T_co, _P], _R_co]:
        """Return the original wrapped function."""
        return self._function

    @property
    def __signature__(self) -> Signature:
        """Return (and cache) the signature of the wrapped function."""
        if not self._signature:
            from inspect import Signature

            self._signature = Signature.from_callable(self._function)
        return self._signature

    @classmethod
    def with_name[T0, **P0, R0](
        cls, kwargs_name: str = "kwargs"
    ) -> Callable[[Callable[Concatenate[T0, P0], R0]], inject_kwargs_params[T0, P0, R0]]:
        """
        Decorator factory that creates a subclass of `inject_kwargs_params` with a custom name
        for the keyword argument store.
        """
        ns = cls.__dict__.copy()
        ns["_kwargs_name"] = kwargs_name

        custom_cls = type(cls.__name__, cls.__bases__, ns)

        # TODO: The precise subclass type cannot be expressed yet when the class is itself generic.
        def _wrapper(function: Callable[Concatenate[T0, P0], R0]) -> inject_kwargs_params[T0, P0, R0]:
            return custom_cls(function)  # pyright: ignore[reportReturnType, reportArgumentType]

        return _wrapper


class inject_kwargs_params(_InjectKwargsParamsBase[_T_co, _P, _R_co]):
    """
    Descriptor that injects parameters into functions based on an instance's keyword mapping.

    When a method wrapped with `@inject_kwargs_params` is called, the descriptor inspects the function's signature
    and replaces any arguments matching keys in `self.kwargs` (or another mapping defined by `_kwargs_name`)
    if their values equal the parameter's default.
    """

    __slots__ = ()

    class add_to_kwargs(_InjectKwargsParamsBase[_T0_co, _P0, _R0_co]):
        """
        Variant of `inject_kwargs_params` that merges unused entries from `self.kwargs` into the keyword arguments
        passed to the target function.

        This allows additional context or configuration values to be forwarded without requiring explicit parameters.
        """

        __slots__ = ()


class _ComplexHash[**P, R]:
    __slots__ = "_func"

    def __init__(self, func: Callable[P, R]) -> None:
        self._func = func

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return self._func(*args, **kwargs)

    @staticmethod
    def hash(*args: Any) -> int:
        """
        Recursively hash every unhashable object in ``*args``.

        Args:
            *args: Objects to be hashed.

        Returns:
            Hash of all the combined objects' hashes.
        """
        values = list[str]()

        for value in args:
            try:
                new_hash = hash(value)
            except TypeError:
                new_hash = complex_hash.hash(*value) if isinstance(value, Iterable) else hash(str(value))

            values.append(str(new_hash))

        return hash("_".join(values))


@_ComplexHash
def complex_hash[T](cls: type[T]) -> type[T]:
    """
    Class decorator that automatically adds a ``__hash__`` method to the target class.

    The generated ``__hash__`` method computes a hash value derived from:
    - the class's name
    - the values of all attributes listed in its type annotations.

    This is particularly useful for immutable data structures (e.g., NamedTuples or dataclasses).
    """

    def __hash__(self: T) -> int:  # noqa: N807
        if sys.version_info >= (3, 14):
            from annotationlib import get_annotations
        else:
            from inspect import get_annotations

        return complex_hash.hash(self.__class__.__name__, *(getattr(self, key) for key in get_annotations(cls)))

    setattr(cls, __hash__.__name__, __hash__)

    return cls


def get_subclasses[T](family: type[T], exclude: Sequence[type[T]] = []) -> list[type[T]]:
    """
    Get all subclasses of a given type.

    Args:
        family: "Main" type all other classes inherit from.
        exclude: Excluded types from the yield. Note that they won't be excluded from search. For examples, subclasses
            of these excluded classes will be yield.

    Returns:
        List of all subclasses of "family".
    """

    def _subclasses(cls: type[T]) -> Iterator[type[T]]:
        for subclass in cls.__subclasses__():
            yield from _subclasses(subclass)
            if subclass in exclude:
                continue
            yield subclass

    return list(set(_subclasses(family)))


class classproperty_base(Generic[_T, _R_co, _T_Any]):
    __isabstractmethod__: bool = False

    fget: Callable[[type[_T]], _R_co]
    fset: Callable[Concatenate[type[_T], _T_Any, ...], None] | None
    fdel: Callable[[type[_T]], None] | None

    def __init__(
        self,
        fget: Callable[[type[_T]], _R_co] | classmethod[_T, ..., _R_co],
        fset: Callable[Concatenate[type[_T], _T_Any, ...], None]
        | classmethod[_T, Concatenate[_T_Any, ...], None]
        | None = None,
        fdel: Callable[[type[_T]], None] | classmethod[_T, ..., None] | None = None,
        doc: str | None = None,
    ) -> None:
        self.fget = fget.__func__ if isinstance(fget, classmethod) else fget
        self.fset = fset.__func__ if isinstance(fset, classmethod) else fset
        self.fdel = fdel.__func__ if isinstance(fdel, classmethod) else fdel

        self.__doc__ = doc
        self.__name__ = self.fget.__name__

    def __set_name__(self, owner: object, name: str) -> None:
        self.__name__ = name

    def _get_cache(self, owner: type[_T]) -> dict[str, Any]:
        cache_key = getattr(self, "cache_key")

        if not hasattr(owner, cache_key):
            setattr(owner, cache_key, {})

        return getattr(owner, cache_key)

    def __get__(self, instance: Any | None, owner: type | None = None) -> _R_co:
        if owner is None:
            owner = type(instance)

        if not isinstance(self, classproperty.cached):
            return self.fget(owner)

        if self.__name__ in (cache := self._get_cache(owner)):
            return cache[self.__name__]

        value = self.fget(owner)
        cache[self.__name__] = value
        return value

    def __set__(self, instance: Any, value: _T_Any) -> None:
        if not self.fset:
            raise AttributeError(
                f'classproperty with getter "{self.__name__}" of "{instance.__class__.__name__}" object has no setter.'
            )

        owner = type(instance)

        if not isinstance(self, classproperty.cached):
            return self.fset(owner, value)

        if self.__name__ in (cache := self._get_cache(owner)):
            del cache[self.__name__]

        self.fset(owner, value)

    def __delete__(self, instance: Any) -> None:
        if not self.fdel:
            raise AttributeError(
                f'classproperty with getter "{self.__name__}" of "{instance.__class__.__name__}" object has no deleter.'
            )

        owner = type(instance)

        if not isinstance(self, classproperty.cached):
            return self.fdel(owner)

        if self.__name__ in (cache := self._get_cache(owner)):
            del cache[self.__name__]

        self.fdel(owner)


class classproperty(classproperty_base[_T, _R_co, _T_Any]):
    """
    A combination of `classmethod` and `property`.
    """

    class cached(classproperty_base[_T0, _R0_co, _T0_Any]):
        """
        A combination of `classmethod` and `property`.

        The value is computed once and then cached in a dictionary (under `cache_key`)
        attached to the class type. If a setter or deleter is defined and invoked,
        the cache is cleared.
        """

        cache_key = "_jetpt_classproperty_cached"

        @classmethod
        def clear_cache(cls, type_: type, names: str | Iterable[str] | None = None) -> None:
            """
            Clear cached properties of an type instance.

            Args:
                type_: The type whose cache should be cleared.
                names: Specific property names to clear. If None, all cached properties are cleared.
            """
            if names is None:
                with suppress(AttributeError):
                    getattr(type_, cls.cache_key).clear()
                return None

            from ..functions import to_arr

            cache = getattr(type_, cls.cache_key, {})

            for name in to_arr(names):
                with suppress(KeyError):
                    del cache[name]


class cachedproperty(property, Generic[_R_co, _T_Any]):
    """
    Wrapper for a one-time get property, that will be cached.

    You shouldn't hold a reference to itself or it will never get garbage collected.
    """

    __isabstractmethod__: bool = False

    cache_key = "_jetpt_cachedproperty_cache"

    @deprecated(
        "The cache dict is now set automatically. You no longer need to inherit from it", category=DeprecationWarning
    )
    class baseclass:
        """Inherit from this class to automatically set the cache dict."""

    if TYPE_CHECKING:

        def __init__(
            self,
            fget: Callable[[Any], _R_co],
            fset: Callable[[Any, _T_Any], None] | None = None,
            fdel: Callable[[Any], None] | None = None,
            doc: str | None = None,
        ) -> None: ...

        def getter(self, fget: Callable[..., _R_co]) -> cachedproperty[_R_co, _T_Any]: ...

        def setter(self, fset: Callable[[Any, _T_Any], None]) -> cachedproperty[_R_co, _T_Any]: ...

        def deleter(self, fdel: Callable[..., None]) -> cachedproperty[_R_co, _T_Any]: ...

    if sys.version_info < (3, 13):

        def __init__(
            self,
            fget: Callable[[Any], _R_co],
            fset: Callable[[Any, _T_Any], None] | None = None,
            fdel: Callable[[Any], None] | None = None,
            doc: str | None = None,
        ) -> None:
            self.__name__ = fget.__name__ + f"_{id(fget)}" if isinstance(fget, LambdaType) else fget.__name__
            super().__init__(fget, fset, fdel, doc)

        def __set_name__(self, owner: object, name: str) -> None:
            self.__name__ = name

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> Self: ...

    @overload
    def __get__(self, instance: Any, owner: type | None = None) -> _R_co: ...

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self

        if self.__name__ in (cache := instance.__dict__.setdefault(self.cache_key, {})):
            return cache[self.__name__]

        value = super().__get__(instance, owner)
        cache[self.__name__] = value
        return value

    def __set__(self, instance: Any, value: _T_Any) -> None:
        if self.__name__ in (cache := instance.__dict__.setdefault(self.cache_key, {})):
            del cache[self.__name__]

        return super().__set__(instance, value)

    def __delete__(self, instance: Any) -> None:
        if self.__name__ in (cache := instance.__dict__.setdefault(self.cache_key, {})):
            del cache[self.__name__]

        return super().__delete__(instance)

    @classmethod
    def clear_cache(cls, obj: object, names: str | Iterable[str] | None = None) -> None:
        """
        Clear cached properties of an object instance.

        Args:
            obj: The object whose cache should be cleared.
            names: Specific property names to clear. If None, all cached properties are cleared.
        """
        if names is None:
            obj.__dict__.get(cls.cache_key, {}).clear()
            return None

        from ..functions import to_arr

        cache = obj.__dict__.get(cls.cache_key, {})

        for name in to_arr(names):
            with suppress(KeyError):
                del cache[name]

    @classmethod
    def update_cache(cls, obj: object, name: str, value: Any) -> None:
        """
        Update cached property of an object instance.

        Args:
            obj: The object whose cache should be updated.
            name: Property name to update.
            value: The value to assign.
        """
        obj.__dict__.setdefault(cls.cache_key, {})[name] = value


class KwargsNotNone(KwargsT):
    """Remove all None objects from this kwargs dict."""

    @copy_signature(KwargsT.__init__)
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__({key: value for key, value in dict(*args, **kwargs).items() if value is not None})


class SingletonMeta(type):
    _instances: ClassVar[dict[SingletonMeta, Any]] = {}
    _lock = Lock()

    _singleton_init: bool

    def __new__[MetaSelf: SingletonMeta](
        mcls: type[MetaSelf],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        init: bool = False,
        **kwargs: Any,
    ) -> MetaSelf:
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        cls._singleton_init = init
        return cls

    if not TYPE_CHECKING:

        def __call__(cls, *args: Any, **kwargs: Any) -> Any:
            if cls in cls._instances and not cls._singleton_init:
                return cls._instances[cls]

            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = obj = super().__call__(*args, **kwargs)
                    return obj

                if cls._singleton_init:
                    cls._instances[cls].__init__(*args, **kwargs)

            return cls._instances[cls]


class Singleton(metaclass=SingletonMeta):
    """Handy class to inherit to have the SingletonMeta metaclass."""

    __slots__ = ()


class LinearRangeLut(Mapping[int, int]):
    __slots__ = ("_misses_n", "_ranges_idx_lut", "ranges")

    def __init__(self, ranges: Mapping[int, range]) -> None:
        self.ranges = ranges

        self._ranges_idx_lut = list(self.ranges.items())
        self._misses_n = 0

    def __getitem__(self, n: int) -> int:
        missed_hit = 0

        for missed_hit, (idx, k) in enumerate(self._ranges_idx_lut):
            if n in k:
                break

        if missed_hit:
            self._misses_n += 1

            if self._misses_n > 2:
                self._ranges_idx_lut = self._ranges_idx_lut[missed_hit:] + self._ranges_idx_lut[:missed_hit]

        return idx  # pyright: ignore[reportPossiblyUnboundVariable]

    def __len__(self) -> int:
        return len(self.ranges)

    def __iter__(self) -> Iterator[int]:
        for i in range(len(self)):
            yield i

    def __setitem__(self, n: int, _range: range) -> NoReturn:
        raise NotImplementedError

    def __delitem__(self, n: int) -> NoReturn:
        raise NotImplementedError
