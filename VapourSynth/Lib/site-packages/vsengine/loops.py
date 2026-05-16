# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
from concurrent.futures import Future, CancelledError
import contextlib
import functools
import typing as t

import vapoursynth


T = t.TypeVar("T")
T_co = t.TypeVar("T_co", covariant=True)


__all__ = [
    "EventLoop", "Cancelled",
    "get_loop", "set_loop",
    "to_thread", "from_thread", "keep_environment"
]


class Cancelled(Exception): pass


@contextlib.contextmanager
def _noop():
    yield


DONE = Future()
DONE.set_result(None)


class EventLoop:
    """
    These functions must be implemented to bridge VapourSynth
    with the event-loop of your choice.
    """

    def attach(self) -> None:
        """
        Called when set_loop is run.
        """
        ...

    def detach(self) -> None:
        """
        Called when another event-loop should take over.

        For example, when you restarting your application.
        """
        ...

    def from_thread(
            self,
            func: t.Callable[..., T],
            *args: t.Any,
            **kwargs: t.Any
    ) -> Future[T]:
        """
        Ran from vapoursynth threads to move data to the event loop.
        """
        ...

    def to_thread(self, func: t.Callable[..., t.Any], *args: t.Any, **kwargs: t.Any) -> t.Any:
        """
        Run this function in a worker thread.
        """
        fut = Future()
        def wrapper():
            if not fut.set_running_or_notify_cancel():
                return

            try:
                result = func(*args, **kwargs)
            except BaseException as e:
                fut.set_exception(e)
            else:
                fut.set_result(result)

        import threading
        threading.Thread(target=wrapper).start()
        return fut

    def next_cycle(self) -> Future[None]:
        """
        Passes control back to the event loop.

        If there is no event-loop, the function will always return a resolved future.
        If there is an event-loop, the function will never return a resolved future.

        Throws vsengine.loops.Cancelled if the operation has been cancelled by that time.

        Only works in the main thread.
        """
        future = Future()
        self.from_thread(future.set_result, None)
        return future

    def await_future(self, future: Future[T]) -> t.Awaitable[T]:
        """
        Await a concurrent future.

        This function does not need to be implemented if the event-loop
        does not support async and await.
        """
        raise NotImplementedError

    @contextlib.contextmanager
    def wrap_cancelled(self):
        """
        Wraps vsengine.loops.Cancelled into the native cancellation error.
        """
        try:
            yield
        except Cancelled:
            raise CancelledError from None


class _NoEventLoop(EventLoop):
    """
    This is the default event-loop used by 
    """

    def attach(self) -> None:
        pass

    def detach(self) -> None:
        pass

    def next_cycle(self) -> Future[None]:
        return DONE

    def from_thread(
            self,
            func: t.Callable[..., T],
            *args: t.Any,
            **kwargs: t.Any
    ) -> Future[T]:
        fut = Future()
        try:
            result = func(*args, **kwargs)
        except BaseException as e:
            fut.set_exception(e)
        else:
            fut.set_result(result)
        return fut


NO_LOOP = _NoEventLoop()
current_loop = NO_LOOP


def get_loop() -> EventLoop:
    """
    :return: The currently running loop.
    """
    return current_loop

def set_loop(loop: EventLoop) -> None:
    """
    Sets the currently running loop.

    It will detach the previous loop first. If attaching fails,
    it will revert to the NoLoop-implementation which runs everything inline

    :param loop: The event-loop instance that implements features.
    """
    global current_loop
    current_loop.detach()
    try:
        current_loop = loop
        loop.attach()
    except:
        current_loop = NO_LOOP
        raise


def keep_environment(func: t.Callable[..., T]) -> t.Callable[..., T]:
    """
    This decorator will return a function that keeps the environment
    that was active when the decorator was applied.

    :param func: A function to decorate.
    :returns: A wrapped function that keeps the environment.
    """
    try:
        environment = vapoursynth.get_current_environment().use
    except RuntimeError:
        environment = _noop

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        with environment():
            return func(*args, **kwargs)

    return _wrapper


def from_thread(func: t.Callable[..., T], *args: t.Any, **kwargs: t.Any) -> Future[T]:
    """
    Runs a function inside the current event-loop, preserving the currently running
    vapoursynth environment (if any).

    .. note:: Be aware that the function might be called inline!

    :param func: A function to call inside the current event loop.
    :param args: The arguments for the function.
    :param kwargs: The keyword arguments to pass to the function.
    :return: A future that resolves and reject depending on the outcome.
    """

    @keep_environment
    def _wrapper():
        return func(*args, **kwargs)

    return get_loop().from_thread(_wrapper)


def to_thread(func: t.Callable[..., t.Any], *args: t.Any, **kwargs: t.Any) -> t.Any:
    """
    Runs a function in a dedicated thread or worker, preserving the currently running
    vapoursynth environment (if any).

    :param func: A function to call inside the current event loop.
    :param args: The arguments for the function.
    :param kwargs: The keyword arguments to pass to the function.
    :return: An loop-specific object.
    """
    @keep_environment
    def _wrapper():
        return func(*args, **kwargs)
    
    return get_loop().to_thread(_wrapper)


async def make_awaitable(future: Future[T]) -> T:
    """
    Makes a future awaitable.

    :param future: The future to make awaitable.
    :return: An object that can be awaited.
    """
    return t.cast(T, await get_loop().await_future(future))

