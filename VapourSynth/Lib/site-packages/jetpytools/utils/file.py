from __future__ import annotations

import sys
from os import F_OK, R_OK, W_OK, X_OK, access, getenv, path
from pathlib import Path
from typing import Callable

from ..exceptions import FileIsADirectoryError, FileNotExistsError, FilePermissionError, FileWasNotFoundError
from ..types import FilePathType, FuncExcept, OpenBinaryMode, OpenTextMode, SPath

__all__ = [
    "add_script_path_hook",
    "check_perms",
    "get_script_path",
    "get_user_data_dir",
    "remove_script_path_hook",
]

_script_path_hooks = list[Callable[[], SPath | None]]()


def add_script_path_hook(hook: Callable[[], SPath | None]) -> None:
    _script_path_hooks.append(hook)


def remove_script_path_hook(hook: Callable[[], SPath | None]) -> None:
    _script_path_hooks.remove(hook)


def get_script_path() -> SPath:
    for hook in reversed(_script_path_hooks):
        if (script_path := hook()) is not None:
            return script_path

    import __main__

    try:
        path = SPath(__main__.__file__)
        return path if path.exists() else SPath.cwd()
    except AttributeError:
        return SPath.cwd()


def get_user_data_dir() -> Path:
    """Get user data dir path."""

    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPathW(None, 28, None, 0, buf)

        if any(ord(c) > 255 for c in buf):
            buf2 = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(buf.value, buf2, 1024):
                buf = buf2

        return Path(path.normpath(buf.value))
    elif sys.platform == "darwin":
        return Path(path.expanduser("~/Library/Application Support/"))
    else:
        return Path(getenv("XDG_DATA_HOME", path.expanduser("~/.local/share")))


def check_perms(
    file: FilePathType, mode: OpenTextMode | OpenBinaryMode, strict: bool = False, *, func: FuncExcept | None = None
) -> bool:
    """
    Confirm whether the user has write/read access to a file.

    Args:
        file: Path to file.
        mode: Read/Write mode.
        func: Function that this was called from, only useful to *func writers.

    :param:                         True if the user has write/read access, else False.

    Raises:
        FileNotExistsError: File could not be found.
        FilePermissionError: User does not have access to the file.
        FileIsADirectoryError: Given path is a directory, not a file.
        FileWasNotFoundError: Parent directories exist, but the given file could not be found.
    """

    file = Path(str(file))
    got_perms = False

    mode_i = F_OK

    if func is not None and not str(file):
        raise FileNotExistsError(file, func)

    for char in "rbU":
        mode_str = mode.replace(char, "")

    if not mode_str:  # pyright: ignore[reportPossiblyUnboundVariable]
        mode_i = R_OK
    elif "x" in mode_str:
        mode_i = X_OK
    elif "+" in mode_str or "w" in mode_str:
        mode_i = W_OK

    check_file = file

    if not strict and mode_i != R_OK:
        while not check_file.exists():
            check_file = check_file.parent

    if strict and file.is_dir():
        raise FileIsADirectoryError(file, func)

    got_perms = access(check_file, mode_i)

    if func is not None and not got_perms:
        if strict and not file.exists():
            if file.parent.exists():
                raise FileWasNotFoundError(file, func)

            raise FileNotExistsError(file, func)

        raise FilePermissionError(file, func)

    return got_perms
