# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import typing as t
from concurrent.futures import Future
from threading import RLock
from vapoursynth import core


T = t.TypeVar("T")
T_co = t.TypeVar("T_co", covariant=True)


def buffer_futures(futures: t.Iterable[Future[T_co]], prefetch: int=0, backlog: t.Optional[int]=None) -> t.Iterable[Future[T_co]]:
    if prefetch == 0:
        prefetch = core.num_threads
    if backlog is None:
        backlog = prefetch*3
    if backlog < prefetch:
        backlog = prefetch

    enum_fut = enumerate(futures)

    finished = False
    running = 0
    lock = RLock()
    reorder: t.MutableMapping[int, Future[T_co]] = {}

    def _request_next():
        nonlocal finished, running
        with lock:
            if finished:
                return

            ni = next(enum_fut, None)
            if ni is None:
                finished = True
                return

            running += 1

            idx, fut = ni
            reorder[idx] = fut
            fut.add_done_callback(_finished)

    def _finished(f):
        nonlocal finished, running
        with lock:
            running -= 1
            if finished:
                return

            if f.exception() is not None:
                finished = True
                return
            
            _refill()

    def _refill():
        if finished:
            return

        with lock:
            # Two rules: 1. Don't exceed the concurrency barrier.
            #            2. Don't exceed unused-frames-backlog
            while (not finished) and (running < prefetch) and len(reorder)<backlog:
                _request_next()
    _refill()

    sidx = 0
    fut: Future[T_co]
    try:
        while (not finished) or (len(reorder)>0) or running>0:
            if sidx not in reorder:
                # Spin. Reorder being empty should never happen.
                continue

            # Get next requested frame
            fut = reorder[sidx]
            del reorder[sidx]
            sidx += 1
            _refill()

            yield fut

    finally:
        finished = True


def close_when_needed(future_iterable: t.Iterable[Future[t.ContextManager[T]]]) -> t.Iterable[Future[T]]:
    def copy_future_and_run_cb_before(fut):
        f = Future()
        def _as_completed(_):
            try:
                r = fut.result()
            except Exception as e:
                f.set_exception(e)
            else:
                new_r = r.__enter__()
                f.set_result(new_r)

        fut.add_done_callback(_as_completed)
        return f

    def close_fut(f: Future[t.ContextManager[T]]):
        def _do_close(_):
            if f.exception() is None:
                f.result().__exit__(None, None, None)
        f.add_done_callback(_do_close)

    for fut in future_iterable:
        yield copy_future_and_run_cb_before(fut)
        close_fut(fut)
