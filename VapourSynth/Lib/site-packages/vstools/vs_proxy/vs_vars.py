from . import proxy as vapoursynth

vs = vapoursynth
"""The VapourSynth proxy module."""

core = vapoursynth.core
"""The singleton Core object."""

VSCoreProxy = vapoursynth.VSCoreProxy

__all__ = ["VSCoreProxy", "core", "vs"]
