# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
"""
vsengine.policy implements a basic object-oriented implementation of
EnvironmentPolicies.


Here a quick run-down in how to use it, (but be sure to read on to select
the best store-implementation for you):

    >>> import vapoursynth as vs
    >>> policy = Policy(GlobalStore())
    >>> policy.register()
    >>> with policy.new_environment() as env:
    ...    with env.use():
    ...        vs.core.std.BlankClip().set_output()
    ...    print(env.outputs)
    {"0": <vapoursynth.VideoNode ...>}
    >>> policy.unregister()


To use it, you first have to pick an EnvironmentStore implementation.
A EnvironmentStore is just a simple object implementing the methods
set_current_environment and get_current_environment.
These actually implement the state an EnvironmentPolicy is responsible
for managing.

For convenience, three EnvironmentStores have already been implemented,
tailored for different uses and concurrency needs:

- The GlobalStore is useful when you are ever only using one Environment
  at the same time

- ThreadLocalStore is useful when you writing a multi-threaded applications,
  that can run multiple environments at once. This one behaves like vsscript.

- ContextVarStore is useful when you are using event-loops like asyncio,
  curio, and trio. When using this store, make sure to reuse the store 
  between successive Policy-instances as otherwise the old store might
  leak objects. More details are written in the documentation of the
  contextvars module of the standard library.

All three implementations can be instantiated without any arguments.


The instance of the EnvironmentStore is then passed to Policy, on which
you then call register on.

You can create ManagedEnvironment-instances by calling
policy.new_environment(). These instances can then be used to switch to
the given environment, retrieve its outputs or get its core.

Be aware that ManagedEnvironment-instances must call dispose() when
you are done using them. Failing to do so will result in a warning.
ManagedEnvironment is also a context-manager which does it for you.

When reloading the application, you can call policy.unregister()
"""
import typing as t

import logging
import weakref
import threading
import contextlib
import contextvars

from vsengine._hospice import admit_environment

from vapoursynth import EnvironmentPolicy, EnvironmentPolicyAPI
from vapoursynth import Environment, EnvironmentData
from vapoursynth import register_policy
import vapoursynth as vs


__all__ = [
    "GlobalStore", "ThreadLocalStore", "ContextVarStore",
    "Policy", "ManagedEnvironment"
]


logger = logging.getLogger(__name__)


class EnvironmentStore(t.Protocol):
    """
    Environment Stores manage which environment is currently active.
    """
    def set_current_environment(self, environment: t.Any):
        """
        Set the current environment in the store.
        """
        ...

    def get_current_environment(self) -> t.Any:
        """
        Retrieve the current environment from the store (if any)
        """
        ...


class GlobalStore(EnvironmentStore):
    """
    This is the simplest store: It just stores the environment in a variable.
    """
    _current: t.Optional[EnvironmentData]
    __slots__ = ("_current",)

    def __init__(self) -> None:
        self._current = None
    
    def set_current_environment(self, environment: t.Optional[EnvironmentData]):
        self._current = environment

    def get_current_environment(self) -> t.Optional[EnvironmentData]:
        return self._current


class ThreadLocalStore(EnvironmentStore):
    """
    For simple threaded applications, use this store.

    It will store the environment in a thread-local variable.
    """

    _current: threading.local

    def __init__(self) -> None:
        self._current = threading.local()

    def set_current_environment(self, environment: t.Optional[EnvironmentData]):
        self._current.environment = environment

    def get_current_environment(self) -> t.Optional[EnvironmentData]:
        return getattr(self._current, "environment", None)


class ContextVarStore(EnvironmentStore):
    """
    If you are using AsyncIO or similar frameworks, use this store.
    """
    _current: contextvars.ContextVar[t.Optional[EnvironmentData]]

    def __init__(self, name: str="vapoursynth") -> None:
        self._current = contextvars.ContextVar(name)

    def set_current_environment(self, environment: t.Optional[EnvironmentData]):
        self._current.set(environment)

    def get_current_environment(self) -> t.Optional[EnvironmentData]:
        return self._current.get(None)


class _ManagedPolicy(EnvironmentPolicy):
    """
    This class directly interfaces with VapourSynth.
    """

    _api: t.Optional[EnvironmentPolicyAPI]
    _store: EnvironmentStore
    _mutex: threading.Lock
    _local: threading.local

    __slots__ = ("_api", "_store", "_mutex", "_local")

    def __init__(self, store: EnvironmentStore) -> None:
        self._store = store
        self._mutex = threading.Lock()
        self._api = None
        self._local = threading.local()

    # For engine-calls that require vapoursynth but
    # should not make their switch observable from the outside.

    # Start the section.
    def inline_section_start(self, environment: EnvironmentData):
        self._local.environment = environment

    # End the section.
    def inline_section_end(self):
        self._local.environment = None

    @property
    def api(self):
        if self._api is None:
            raise RuntimeError("Invalid state: No access to the current API")
        return self._api

    def on_policy_registered(self, special_api: EnvironmentPolicyAPI) -> None:
        logger.debug("Successfully registered policy with VapourSynth.")
        self._api = special_api

    def on_policy_cleared(self) -> None:
        self._api = None
        logger.debug("Policy cleared.")

    def get_current_environment(self) -> t.Optional[EnvironmentData]:
        # For small segments, allow switching the environment inline.
        # This is useful for vsengine-functions that require access to the
        # vapoursynth api, but don't want to invoke the store for it.
        if (env := getattr(self._local, "environment", None)) is not None:
            if self.is_alive(env):
                return env

        # We wrap everything in a mutex to make sure
        # no context-switch can reliably happen in this section.
        with self._mutex:
            current_environment = self._store.get_current_environment()
            if current_environment is None:
                return

            if current_environment() is None:
                logger.warning(f"Got dead environment: {current_environment()!r}")
                self._store.set_current_environment(None)
                return None

            received_environment = current_environment()

            if not self.is_alive(received_environment):
                logger.warning(f"Got dead environment: {received_environment!r}")
                # Remove the environment.
                self._store.set_current_environment(None)
                return None

            return t.cast(EnvironmentData, received_environment)

    def set_environment(self, environment: EnvironmentData) -> t.Optional[EnvironmentData]:
        with self._mutex:
            previous_environment = self._store.get_current_environment()

            if environment is not None and not self.is_alive(environment):
                logger.warning(f"Got dead environment: {environment!r}")
                self._store.set_current_environment(None)
            else:
                logger.debug(f"Setting environment: {environment!r}")
                if environment is None:
                    self._store.set_current_environment(None)
                else:
                    self._store.set_current_environment(weakref.ref(environment))

            if previous_environment is not None:
                return previous_environment()


class ManagedEnvironment:
    _environment: Environment
    _data: EnvironmentData
    _policy: 'Policy'
    __slots__ = ("_environment", "_data", "_policy")

    def __init__(self, environment: Environment, data: EnvironmentData, policy: 'Policy') -> None:
        self._environment = environment
        self._data = data
        self._policy = policy

    @property
    def vs_environment(self):
        """
        Returns the vapoursynth.Environment-object representing this environment.
        """
        return self._environment

    @property
    def core(self) -> vs.Core:
        """
        Returns the core representing this environment.
        """
        with self.inline_section():
            return vs.core.core

    @property
    def outputs(self) -> t.Mapping[int, vs.VideoOutputTuple]:
        """
        Returns the output within this environment.
        """
        with self.inline_section():
            return vs.get_outputs()

    @contextlib.contextmanager
    def inline_section(self) -> t.Generator[None, None, None]:
        """
        Private API!

        Switches to the given environment within the block without
        notifying the store.

        If you follow the rules below, switching the environment
        will be invisible to the caller.
        
        Rules for safely calling this function:
        - Do not suspend greenlets within the block!
        - Do not yield or await within the block!
        - Do not use __enter__ and __exit__ directly.
        - This function is not reentrant.
        """
        self._policy.managed.inline_section_start(self._data)
        try:
            yield
        finally:
            self._policy.managed.inline_section_end()

    @contextlib.contextmanager
    def use(self) -> t.Generator[None, None, None]:
        """
        Switches to this environment within a block.
        """
        prev_environment = self._policy.managed._store.get_current_environment()
        with self._environment.use():
            yield

        # Workaround: On 32bit systems, environment policies do not reset.
        self._policy.managed.set_environment(prev_environment)

    def switch(self):
        """
        Switches to the given environment without storing
        which environment has been defined previously.
        """
        self._environment.use().__enter__()

    def dispose(self):
        if self.disposed:
            return

        logger.debug(f"Disposing environment {self._data!r}.")
        admit_environment(self._data, self.core)
        self._policy.api.destroy_environment(self._data)
        self._data = None

    @property
    def disposed(self) -> bool:
        """
        Checks if the environment is disposed
        """
        return self._data is None

    def __enter__(self):
        return self

    def __exit__(self, _, __, ___):
        self.dispose()

    def __del__(self):
        if self._data is None:
            return

        import warnings
        warnings.warn(f"Disposing {self!r} inside __del__. This might cause leaks.", ResourceWarning)
        self.dispose()


class Policy:
    """
    A managed policy is a very simple policy that just stores the environment
    data within the given store.

    For convenience (especially for testing), this is a context manager that
    makes sure policies are being unregistered when leaving a block.
    """
    _managed: _ManagedPolicy

    def __init__(self, store: EnvironmentStore) -> None:
        self._managed = _ManagedPolicy(store)

    def register(self):
        """
        Registers the policy with VapourSynth.
        """
        register_policy(self._managed)
    
    def unregister(self):
        """
        Unregisters the policy from VapourSynth.
        """
        self._managed.api.unregister_policy()

    def __enter__(self):
        self.register()
        return self

    def __exit__(self, _, __, ___):
        self.unregister()

    def new_environment(self) -> ManagedEnvironment:
        """
        Creates a new VapourSynth core.

        You need to call `dispose()` on this environment when you are done
        using the new environment.

        For convenience, a managed environment will also serve as a
        context-manager that disposes the environment automatically.
        """
        data = self.api.create_environment()
        env = self.api.wrap_environment(data)
        logger.debug("Created new environment")
        return ManagedEnvironment(env, data, self)

    @property
    def api(self):
        """
        Returns the API instance for more complex interactions.

        You will rarely need to use this directly.
        """
        return self._managed.api

    @property
    def managed(self):
        """
        Returns the actual policy within VapourSynth.

        You will rarely need to use this directly.
        """
        return self._managed

