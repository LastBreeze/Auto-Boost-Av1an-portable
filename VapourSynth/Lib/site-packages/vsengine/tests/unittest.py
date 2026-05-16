# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import sys
from unittest.main import TestProgram
from vsengine.policy import Policy, GlobalStore
from vsengine._hospice import any_alive, freeze


DEFAULT_ERROR_MESSAGE = [
    "Your test suite left a dangling object to a vapoursynth core.",
    "Please make sure this does not happen, "
    "as this might cause some previewers to crash "
    "after reloading a script."
]


class MultiCoreTestProgram(TestProgram):

    def __init__(self, *args, **kwargs):
        self._policy = Policy(GlobalStore())
        self._policy.register()
        super().__init__(*args, **kwargs)

    def _run_once(self):
        try:
            super().runTests()
        except SystemExit as e:
            return e.code
        else:
            return 0

    def parseArgs(self, argv: list[str]) -> None:
        self.argv = argv
        return super().parseArgs(argv)

    def runTests(self):
        any_alive_left = False

        with self._policy.new_environment() as e1:
            with e1.use():
                self._run_once()
        del e1

        if self.exit and not self.result.wasSuccessful():
            sys.exit(1)

        if any_alive():
            print(*DEFAULT_ERROR_MESSAGE, sep="\n", file=sys.stderr)
            any_alive_left = True
            freeze()

        super().parseArgs(self.argv)
        with self._policy.new_environment() as e2:
            with e2.use():
                self._run_once()
        del e2

        if any_alive():
            print(*DEFAULT_ERROR_MESSAGE, sep="\n", file=sys.stderr)
            any_alive_left = True
            freeze()

        if self.exit:
            if not self.result.wasSuccessful():
                sys.exit(1)
            elif any_alive_left:
                sys.exit(2)

        sys.exit(0)



def main():
    MultiCoreTestProgram(module=None)

if __name__ == "__main__":
    main()

