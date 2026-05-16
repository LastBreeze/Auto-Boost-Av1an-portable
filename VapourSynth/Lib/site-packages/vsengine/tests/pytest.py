# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2

import pathlib
import pytest
from vsengine.policy import Policy, GlobalStore
from vsengine._hospice import any_alive, freeze


DEFAULT_STAGES = (
    "initial-core",
    "reloaded-core"
)

KNOWN_STAGES = [
    "no-core",
    "initial-core",
    "reloaded-core",
    "unique-core"
]


DEFAULT_ERROR_MESSAGE = [
    "Your test suite left a dangling object to a vapoursynth core.",
    "Please make sure this does not happen, "
    "as this might cause some previewers to crash "
    "after reloading a script."
]


###
# Add the marker to the docs
def pytest_configure(config: "Config") -> None:
    config.addinivalue_line(
        "markers",
        'vpy(*stages: Literal["no_core", "first_core", "second_core"]): '
        'Mark what stages should be run. (Defaults to first_core+second_core)'
    )

###
# Make sure a policy is registered before tests are collected.
current_policy = None
current_env = None
def pytest_sessionstart(session):
    global current_policy
    current_policy = Policy(GlobalStore())
    current_policy.register()

def pytest_sessionfinish():
    global current_policy, current_env
    if current_env is not None:
        current_env.dispose()
    current_policy.unregister()


###
# Ensure tests are ordered correctly
@pytest.fixture(params=DEFAULT_STAGES)
def vpy_stages(request) -> str:
    return request.param


class CleanupFailed:
    def __init__(self, previous, next_text) -> None:
        self.previous = previous
        self.next_text = next_text

    def __str__(self):
        if self.previous is None:
            return self.next_text

        return f"{self.previous}\n\n{self.next_text}"

    def __repr__(self) -> str:
        return "<{} instance at {:0x}>".format(self.__class__, id(self))

    def toterminal(self, tw):
        if self.previous is not None:
            self.previous.toterminal(tw)
            tw.line("")
            color = {"yellow": True}
            tw.line("vs-engine has detected an additional problem with this test:", yellow=True, bold=True)
            indent = "  "
        else:
            color = {"red": True}
            indent = ""

        for line in self.next_text.split("\n"):
            tw.line(indent + line, **color)


class VapoursynthEnvironment(pytest.Item):
    pass


class EnsureCleanEnvironment(pytest.Item):
    def __init__(self, *, stage, **kwargs) -> None:
        super().__init__(**kwargs)
        self.stage = stage
        self.path = "<vapoursynth>"

    def runtest(self):
        global current_env
        if current_env is not None:
            current_env.dispose()
            current_env = None
            any_alive_left = any_alive()
            freeze()
            assert not any_alive_left, "Expected all environments to be cleaned up."
        current_env = None

    def repr_failure(self, excinfo):
        return CleanupFailed(None, "\n".join(DEFAULT_ERROR_MESSAGE))

    def reportinfo(self):
        return pathlib.Path("<vapoursynth>"), None, f"cleaning up: {self.stage}"


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector, name, obj) -> None:
    if collector.istestfunction(obj, name):
        inner_func = obj.hypothesis.inner_test if hasattr(obj, "hypothesis") else obj
        marker = collector.get_closest_marker("vpy")
        own_markers = getattr(obj, "pytestmark", ())
        if marker or any(marker.name == "vpy" for marker in own_markers):
            real_marker = marker or tuple(marker for marker in own_markers if marker.name == "vpy")[0]
            obj._vpy_stages = real_marker.args
        else:
            obj._vpy_stages = DEFAULT_STAGES

def pytest_generate_tests(metafunc):
    obj = metafunc.function
    if hasattr(obj, "_vpy_stages"):
        stages = obj._vpy_stages
        metafunc.fixturenames += ["__vpy_stage"]
        metafunc.parametrize(("__vpy_stage",), tuple((stage,) for stage in stages), ids=stages)


def pytest_collection_modifyitems(session, config, items):
    stages = {}
    for stage in KNOWN_STAGES:
        stages[stage] = []

    for item in items:
        spec = item.callspec
        stages[spec.params.get("__vpy_stage", "no-core")].append(item)

    new_items = []

    virtual_parent = VapoursynthEnvironment.from_parent(session, name="@vs-engine")
    for stage in KNOWN_STAGES:
        new_items.extend(stages[stage])
        # Add two synthetic tests that make sure the environment is clean.
        if stage in ("initial-core", "reloaded-core"):
            new_items.append(EnsureCleanEnvironment.from_parent(virtual_parent, name=f"@check-clean-environment[{stage}]", stage=stage))

    items[:] = new_items


###
# Do the magic
current_stage = "no-core"
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    global current_stage, current_env
    spec = pyfuncitem.callspec
    stage = spec.params.get("__vpy_stage", "no-core")

    if stage != current_stage:
        if stage == "initial-core":
            current_env = current_policy.new_environment()

        if stage == "reloaded-core":
            if current_env is None:
                current_env = current_policy.new_environment()
            current_env.dispose()
            current_env = current_policy.new_environment()

        if stage == "unique-core":
            if current_env is not None:
                current_env.dispose()
            current_env = None

        current_stage = stage

    funcargs = pyfuncitem.funcargs
    testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}

    if stage == "unique-core":
        env = current_policy.new_environment()
        try:
            with env.use():
                pyfuncitem.obj(**testargs)
        except BaseException as e:
            failed = e
        else:
            failed = False
        finally:
            if env is not None:
                env.dispose()
                env = None

        if any_alive():
            freeze()
            if failed is False:
                pyfuncitem._repr_failure_py = lambda _, style=None: CleanupFailed(None, "\n".join(DEFAULT_ERROR_MESSAGE))
                assert False
            else:
                pre_rfp = pyfuncitem._repr_failure_py
                def _new_rfp(*args, **kwargs):
                    previous = pre_rfp(*args, **kwargs)
                    err = "\n".join(DEFAULT_ERROR_MESSAGE)
                    return CleanupFailed(previous, err)
                pyfuncitem._repr_failure_py = _new_rfp
                raise failed
        elif failed:
            raise failed

        return True

    elif current_env is not None:
        with current_env.use():
            pyfuncitem.obj(**testargs)
        return True
