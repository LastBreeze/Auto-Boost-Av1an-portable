from __future__ import annotations

import sys

from .base import CustomError, CustomPermissionError

if sys.version_info < (3, 13):
    from typing_extensions import deprecated
else:
    from warnings import deprecated

__all__ = [
    "FileIsADirectoryError",
    "FileNotExistsError",
    "FilePermissionError",
    "FileTypeMismatchError",
    "FileWasNotFoundError",
    "PathIsNotADirectoryError",
]


class FileNotExistsError(CustomError, FileExistsError):
    """Raised when a file doesn't exists"""


class FileWasNotFoundError(CustomError, FileNotFoundError):
    """Raised when a file wasn't found but the path is correct, e.g. parent directory exists"""


class FilePermissionError(CustomPermissionError):
    """Raised when you try to access a file but haven't got permissions to do so"""


@deprecated("FileTypeMismatchError is deprecated and will be removed in a future version.", category=DeprecationWarning)
class FileTypeMismatchError(CustomError, OSError):
    """Raised when you try to access a file with a FileType != AUTO and it's another file type"""


class FileIsADirectoryError(CustomError, IsADirectoryError):
    """Raised when you try to access a file but it's a directory instead"""


class PathIsNotADirectoryError(CustomError, NotADirectoryError):
    """Raised when you try to access a directory but it's not a directory"""
