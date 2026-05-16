# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2

from concurrent.futures import Future
import typing as t
import contextlib

from trio import Cancelled as TrioCancelled
from trio import CapacityLimiter
from trio import CancelScope
from trio import Nursery
from trio import to_thread
from trio import Event
from trio.lowlevel import current_trio_token

from vsengine.loops import Cancelled, EventLoop


T = t.TypeVar("T")


class TrioEventLoop(EventLoop):
    _scope: Nursery

    def __init__(
            self,
            nursery: Nursery,
            limiter: t.Optional[CapacityLimiter]=None
    ) -> None:
        if limiter is None:
            limiter = t.cast(CapacityLimiter, to_thread.current_default_thread_limiter())

        self.nursery = nursery
        self.limiter = limiter
        self._token = None

    def attach(self) -> None:
        """
        Called when set_loop is run.
        """
        self._token = current_trio_token()

    def detach(self) -> None:
        """
        Called when another event-loop should take over.
        """
        self.nursery.cancel_scope.cancel()

    def from_thread(
            self,
            func: t.Callable[..., T],
            *args: t.Any,
            **kwargs: t.Any
    ) -> Future[T]:
        """
        Ran from vapoursynth threads to move data to the event loop.
        """
        assert self._token is not None

        fut = Future()
        def _executor():
            if not fut.set_running_or_notify_cancel():
                return

            try:
                result = func(*args, **kwargs)
            except BaseException as e:
                fut.set_exception(e)
            else:
                fut.set_result(result)
            
        self._token.run_sync_soon(_executor)
        return fut

    async def to_thread(self, func: t.Callable[..., t.Any], *args: t.Any, **kwargs: t.Any):
        """
        Run this function in a worker thread.
        """
        result = None
        error: BaseException|None = None
        def _executor():
            nonlocal result, error
            try:
                result = func(*args, **kwargs)
            except BaseException as e:
                error = e

        await to_thread.run_sync(_executor, limiter=self.limiter)
        if error is not None:
            assert isinstance(error, BaseException)
            raise t.cast(BaseException, error)
        else:
            return result

    def next_cycle(self) -> Future[None]:
        scope = CancelScope()
        future = Future()
        def continuation():
            if scope.cancel_called:
                future.set_exception(Cancelled())
            else:
                future.set_result(None)
        self.from_thread(continuation)
        return future

    async def await_future(self, future: Future[T]) -> T:
        """
        Await a concurrent future.

        This function does not need to be implemented if the event-loop
        does not support async and await.
        """
        event = Event()

        result: T|None = None
        error: BaseException|None = None
        def _when_done(_):
            nonlocal error, result
            if (error := future.exception()) is not None:
                pass
            else:
                result = future.result()
            self.from_thread(event.set)

        future.add_done_callback(_when_done)
        try:
            await event.wait()
        except TrioCancelled:
            raise

        if error is not None:
            with self.wrap_cancelled():
                raise t.cast(BaseException, error)
        else:
            return t.cast(T, result)

    @contextlib.contextmanager
    def wrap_cancelled(self):
        """
        Wraps vsengine.loops.Cancelled into the native cancellation error.
        """
        try:
            yield
        except Cancelled:
            raise TrioCancelled.__new__(TrioCancelled) from None
