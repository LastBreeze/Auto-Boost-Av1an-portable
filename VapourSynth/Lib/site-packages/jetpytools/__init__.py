"""A collection of utilities useful for general Python programming."""

from .enums import *
from .exceptions import *
from .functions import *
from .types import *
from .utils import *

__version__: str
__version_tuple__: tuple[int | str, ...]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "+unknown")
