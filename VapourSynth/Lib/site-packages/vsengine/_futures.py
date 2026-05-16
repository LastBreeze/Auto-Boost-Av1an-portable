# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import inspect
import functools
import typing as t
from concurrent.futures import Future

from vsengine.loops import Cancelled, get_loop, keep_environment


T = t.TypeVar("T")
V = t.TypeVar("V")

UnifiedRunner = t.Callable[..., t.Union[Future[T],t.Iterator[Future[T]]]]
UnifiedCallable = t.Callable[..., t.Union['UnifiedFuture', 'UnifiedIterator']]


class UnifiedFuture(Future[T]):

    @classmethod
    def from_call(cls, func: UnifiedRunner[T], *args: t.Any, **kwargs: t.Any) -> 'UnifiedFuture[T]':
        try:
            future = func(*args, **kwargs)
        except Exception as e:
            return cls.reject(e)
        else:
            return cls.from_future(t.cast(Future[T], future))

    @classmethod
    def from_future(cls, future: Future[T]) -> 'UnifiedFuture[T]':
        if isinstance(future, cls):
            return future

        result = cls()
        def _receive(_):
            if (exc := future.exception()) is not None:
                result.set_exception(exc)
            else:
                result.set_result(future.result())
        future.add_done_callback(_receive)
        return result

    @classmethod
    def resolve(cls, value: T) -> 'UnifiedFuture[T]':
        future = cls()
        future.set_result(value)
        return future

    @classmethod
    def reject(cls, error: BaseException) -> 'UnifiedFuture[t.Any]':
        future = cls()
        future.set_exception(error)
        return future

    # Adding callbacks
    def add_done_callback(self, fn: t.Callable[[Future[T]], t.Any]) -> None:
        # The done_callback should inherit the environment of the current call.
        super().add_done_callback(keep_environment(fn))

    def add_loop_callback(self, func: t.Callable[['UnifiedFuture[T]'], None]) -> None:
        def _wrapper(future):
            get_loop().from_thread(func, future)
        self.add_done_callback(_wrapper)

    # Manipulating futures
    def then(
            self,
            success_cb: t.Optional[t.Callable[[T], V]],
            err_cb: t.Optional[t.Callable[[BaseException], V]]
    ) -> 'UnifiedFuture[V]':
        result = UnifiedFuture()
        def _run_cb(cb, v):
            try:
                r = cb(v)
            except BaseException as e:
                result.set_exception(e)
            else:
                result.set_result(r)

        def _done(_):
            if (exc := self.exception()) is not None:
                if err_cb is not None:
                    _run_cb(err_cb, exc)
                else:
                    result.set_exception(exc)
            else:
                if success_cb is not None:
                    _run_cb(success_cb, self.result())
                else:
                    result.set_result(self.result())

        self.add_done_callback(_done)
        return result

    def map(self, cb: t.Callable[[T], V]) -> 'UnifiedFuture[V]':
        return self.then(cb, None)

    def catch(self, cb: t.Callable[[BaseException], V]) -> 'UnifiedFuture[V]':
        return self.then(None, cb)

    # Nicer Syntax
    def __enter__(self):
        obj = self.result()
        if hasattr(obj, "__enter__"):
            return t.cast(t.ContextManager[t.Any], obj).__enter__()
        else:
            raise NotImplementedError("(async) with is not implemented for this object.")

    def __exit__(self, exc, val, tb):
        obj = self.result()
        if hasattr(obj, "__exit__"):
            return t.cast(t.ContextManager[t.Any], obj).__exit__(exc, val, tb)
        else:
            raise NotImplementedError("(async) with is not implemented for this object.")

    async def awaitable(self):
        return await get_loop().await_future(self)

    def __await__(self):
        return self.awaitable().__await__()

    async def __aenter__(self):
        result = await self.awaitable()
        if hasattr(result, "__aenter__"):
            return await t.cast(t.AsyncContextManager[t.Any], result).__aenter__()
        elif hasattr(result, "__enter__"):
            return t.cast(t.ContextManager[t.Any], result).__enter__()
        else:
            raise NotImplementedError("(async) with is not implemented for this object.")

    async def __aexit__(self, exc, val, tb):
        result = await self.awaitable()
        if hasattr(result, "__aexit__"):
            return await t.cast(t.AsyncContextManager[t.Any], result).__aexit__(exc, val, tb)
        elif hasattr(result, "__exit__"):
            return t.cast(t.ContextManager[t.Any], result).__exit__(exc, val, tb)
        else:
            raise NotImplementedError("(async) with is not implemented for this object.")


class UnifiedIterator(t.Generic[T]):

    def __init__(self, future_iterable: t.Iterator[Future[T]]) -> None:
        self.future_iterable = future_iterable

    @classmethod
    def from_call(cls, func: UnifiedRunner[T], *args: t.Any, **kwargs: t.Any) -> 'UnifiedIterator[T]':
        return cls(t.cast(t.Iterator[Future[T]], func(*args, **kwargs)))

    @property
    def futures(self):
        return self.future_iterable

    def run_as_completed(self, callback: t.Callable[[Future[T]], t.Any]) -> UnifiedFuture[None]:
        state = UnifiedFuture()

        def _is_done_or_cancelled() -> bool:
            if state.done():
                return True
            elif state.cancelled():
                state.set_exception(Cancelled())
                return True
            else:
                return False

        def _get_next_future() -> t.Optional[Future[T]]:
            if _is_done_or_cancelled():
                return None

            try:
                next_future = self.future_iterable.__next__()
            except StopIteration:
                state.set_result(None)
                return None
            except BaseException as e:
                state.set_exception(e)
                return None
            else:
                return next_future

        def _run_callbacks():
            try:
                while (future := _get_next_future()) is not None:
                    # Wait for the future to finish.
                    if not future.done():
                        future.add_done_callback(_continuation_in_foreign_thread)
                        return

                    # Run the callback.
                    if not _run_single_callback(future):
                        return

                    # Try to give control back to the event loop.
                    next_cycle = get_loop().next_cycle()
                    if not next_cycle.done():
                        next_cycle.add_done_callback(_continuation_from_next_cycle)
                        return

                    # We do not have a real event loop here.
                    # If the next_cycle causes an error to bubble, forward it to the state future.
                    if next_cycle.exception() is not None:
                        state.set_exception(next_cycle.exception())
                        return
            except Exception as e:
                import traceback
                traceback.print_exception(e)
                state.set_exception(e)

        def _continuation_from_next_cycle(fut):
            if fut.exception() is not None:
                state.set_exception(fut.exception())
            else:
                _run_callbacks()

        def _continuation_in_foreign_thread(fut: Future[T]):
            # Optimization, see below.
            get_loop().from_thread(_continuation, fut)

        def _continuation(fut: Future[T]):
            if _run_single_callback(fut):
                _run_callbacks()

        @keep_environment
        def _run_single_callback(fut: Future[T]) -> bool:
            # True   => Schedule next future.
            # False  => Cancel the loop.
            if _is_done_or_cancelled():
                return False

            try:
                result = callback(fut)
            except BaseException as e:
                state.set_exception(e)
                return False
            else:
                if result is None or bool(result):
                    return True
                else:
                    state.set_result(None)
                    return False

        # Optimization:
        # We do not need to inherit any kind of environment as
        # _run_single_callback will automatically set the environment for us.
        get_loop().from_thread(_run_callbacks)
        return state

    def __iter__(self):
        return self

    def __next__(self) -> T:
        fut = self.future_iterable.__next__()
        return fut.result()

    def __aiter__(self):
        return self

    async def __anext__(self) -> T:
        try:
            fut = self.future_iterable.__next__()
        except StopIteration:
            raise StopAsyncIteration
        return await get_loop().await_future(fut)


def unified(
        type: t.Literal["auto","generator","future"] = "auto",
        future_class: t.Type[UnifiedFuture[T]] = UnifiedFuture,
        iterable_class: t.Type[UnifiedIterator[T]] = UnifiedIterator,
) -> t.Callable[[UnifiedRunner[T]], UnifiedCallable]:
    def _wrap_generator(func: UnifiedRunner[T]) -> UnifiedCallable:
        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            return iterable_class.from_call(func, *args, **kwargs)
        return _wrapped

    def _wrap_future(func: UnifiedRunner[T]) -> UnifiedCallable:
        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            return future_class.from_call(func, *args, **kwargs)
        return _wrapped

    def _wrapper(func: UnifiedRunner[T]) -> UnifiedCallable:
        if type == "auto":
            if inspect.isgeneratorfunction(func):
                return _wrap_generator(func)
            else:
                return _wrap_future(func)
        elif type == "generator":
            return _wrap_generator(func)
        else:
            return _wrap_future(func)

    return _wrapper

