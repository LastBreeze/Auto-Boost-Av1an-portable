# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import contextlib
import typing as t
import vapoursynth as vs

from vsengine.policy import ManagedEnvironment


T = t.TypeVar("T")


EnvironmentTypes = t.Union[vs.Environment, ManagedEnvironment]


# Automatically set the environment within that block.
@contextlib.contextmanager
def use_inline(function_name: str, env: t.Optional[EnvironmentTypes]) -> t.Generator[None, None, None]:
    if env is None:
        # Ensure there is actually an environment set in this block.
        try:
            vs.get_current_environment()
        except Exception as e:
            raise EnvironmentError(
                f"You are currently not running within an environment. "
                f"Pass the environment directly to {function_name}."
            ) from e
        yield

    elif isinstance(env, ManagedEnvironment):
        with env.inline_section():
            yield

    else:
        with env.use():
            yield


# Variable size and format clips may require different handling depending on the actual frame size.
def wrap_variable_size(
        node: vs.VideoNode,
        force_assumed_format: vs.VideoFormat,
        func: t.Callable[[vs.VideoNode], vs.VideoNode]
) -> vs.VideoNode:
    # Check: This is not a variable format clip.
    #        Nothing needs to be done.
    if node.format is not None and node.width != 0 and node.height != 0:
        return func(node)

    def _do_resize(f: vs.VideoFrame) -> vs.VideoNode:
        # Resize the node to make them assume a specific format.
        # As the node should aready have this format, this should be a no-op.
        return func(node.resize.Point(format=f.format, width=f.width, height=f.height))

    _node_cache = {}
    def _assume_format(n: int, f: vs.VideoFrame) -> vs.VideoNode:
        nonlocal _node_cache
        selector = (int(f.format), f.width, f.height)

        if _node_cache is None or len(_node_cache) > 100:
            # Skip caching if the cahce grows too large.
            _node_cache = None
            wrapped = _do_resize(f)

        elif selector not in _node_cache:
            # Resize and cache the node.
            wrapped = _do_resize(f)
            _node_cache[selector] = wrapped

        else:
            # Use the cached node.
            wrapped = _node_cache[selector]

        return wrapped

    # This clip must not become part of the closure,
    # or otherwise we risk cyclic references.
    return (
        node.std.FrameEval(_assume_format, [node], [node])
        .resize.Point(format=force_assumed_format)
    )

