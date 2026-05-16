# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import gc
import sys
import logging
import weakref
import threading
from vapoursynth import Core, EnvironmentData

logger = logging.getLogger(__name__)


lock = threading.Lock()
refctr = 0
refnanny = {}
cores = {}

stage2_to_add = set()
stage2 = set()
stage1 = set()

hold = set()


def admit_environment(environment: EnvironmentData, core: Core):
    global refctr

    with lock:
        ident = refctr
        refctr+=1

    ref = weakref.ref(environment, lambda _: _add_tostage1(ident))
    cores[ident] = core
    refnanny[ident] = ref

    logger.info(f"Admitted environment {environment!r} and {core!r} as with ID:{ident}.")

def any_alive():
    if bool(stage1) or bool(stage2) or bool(stage2_to_add):
        gc.collect()
    if bool(stage1) or bool(stage2) or bool(stage2_to_add):
        gc.collect()
    if bool(stage1) or bool(stage2) or bool(stage2_to_add):
        gc.collect()
    return bool(stage1) or bool(stage2) or bool(stage2_to_add)


def freeze():
    logger.debug(f"Freezing the hospice. Cores won't be collected anyore.")

    hold.update(stage1)
    hold.update(stage2)
    hold.update(stage2_to_add)
    stage1.clear()
    stage2.clear()
    stage2_to_add.clear()

def unfreeze():
    stage1.update(hold)
    hold.clear()


def _is_core_still_used(ident: int) -> bool:
    return sys.getrefcount(cores[ident]) > 2


def _add_tostage1(ident: int) -> None:
    logger.info(f"Environment has died. Keeping core for a few gc-cycles. ID:{ident}")
    with lock:
        stage1.add(ident)


def _collectstage1(phase, __):
    if phase != "stop":
        return

    with lock:
        for ident in tuple(stage1):
            if _is_core_still_used(ident):
                logger.warning(f"Core is still in use. ID:{ident}")
                continue

            stage1.remove(ident)
            stage2_to_add.add(ident)


def _collectstage2(phase, __):
    global stage2_to_add

    if phase != "stop":
        return

    garbage = []
    with lock:
        for ident in tuple(stage2):
            if _is_core_still_used(ident):
                logger.warn(f"Core is still in use in stage 2. ID:{ident}")
                continue

            stage2.remove(ident)
            garbage.append(cores.pop(ident))
            logger.info(f"Marking core {ident!r} for collection")

        stage2.update(stage2_to_add)
        stage2_to_add = set()

    garbage.clear()


gc.callbacks.append(_collectstage2)
gc.callbacks.append(_collectstage1)

