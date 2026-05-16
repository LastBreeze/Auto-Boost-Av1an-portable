# vs-engine
# Copyright (C) 2022  cid-chan
# This project is licensed under the EUPL-1.2
# SPDX-License-Identifier: EUPL-1.2
import functools
import typing as t
import vapoursynth as vs

from vsengine._helpers import use_inline, wrap_variable_size, EnvironmentTypes


# The heuristics code for nodes.
# Usually the nodes are tagged so this heuristics code is not required.
@functools.lru_cache
def yuv_heuristic(width: int, height: int) -> t.Mapping[str, str]:
    result = {}

    if width >= 3840:
        result["matrix_in_s"] = "2020ncl"
    elif width >= 1280:
        result["matrix_in_s"] = "709"
    elif height == 576:
        result["matrix_in_s"] = "470bg"
    else:
        result["matrix_in_s"] = "170m"

    if width >= 3840:
        result["transfer_in_s"] = "st2084"
    elif width >= 1280:
        result["transfer_in_s"] = "709"
    elif height == 576:
        result["transfer_in_s"] = "470bg"
    else:
        result["transfer_in_s"] = "601"

    if width >= 3840:
        result["primaries_in_s"] = "2020"
    elif width >= 1280:
        result["primaries_in_s"] = "709"
    elif height == 576:
        result["primaries_in_s"] = "470bg"
    else:
        result["primaries_in_s"] = "170m"

    result["range_in_s"] = "limited"

    # ITU-T H.273 (07/2021), Note at the bottom of pg. 20
    if width >= 3840:
        result["chromaloc_in_s"] = "top_left"
    else:
        result["chromaloc_in_s"] = "left"

    return result


# Move this function out of the closure to avoid capturing clip.
def _convert_yuv(
        c: vs.VideoNode,
        *,
        core: vs.Core,
        real_rgb24: vs.VideoFormat,
        default_args: t.Dict[str, t.Any],
        scaler: t.Union[str, t.Callable[..., vs.VideoNode]]
):
    # We make yuv_heuristic not configurable so the heuristic
    # will be shared across projects.
    #
    # In my opinion, this is a quirk that should be shared.

    args = {
        **yuv_heuristic(c.width, c.height),
        **default_args
    }

    if c.format.subsampling_w != 0 or c.format.subsampling_h != 0:
        # To be clear, scaler should always be a string.
        # Being able to provide a callable just makes testing args easier.
        resizer = getattr(core.resize, scaler) if isinstance(scaler, str) else scaler
    else:
        # In this case we only do cs transforms, point resize is more then enough.
        resizer = core.resize.Point

    # Keep bitdepth so we can dither futher down in the RGB part.
    return resizer(
        c,
        format=real_rgb24.replace(
            sample_type=c.format.sample_type,
            bits_per_sample=c.format.bits_per_sample
        ),
        **args
    )


# Move this function out of the closure to avoid capturing clip.
def _actually_resize(
        c: vs.VideoNode,
        *,
        core: vs.Core,
        convert_yuv: t.Callable[[vs.VideoNode], vs.VideoNode],
        target_rgb: vs.VideoFormat
) -> vs.VideoNode:
    # Converting to YUV is a little bit more complicated,
    # so I extracted it to its own function.
    if c.format.color_family == vs.YUV:
        c = convert_yuv(c)

    # Defaulting prefer_props to True makes resizing choke
    # on GRAY clips.
    if c.format == vs.GRAY:
        c = c.std.RemoveFrameProps("_Matrix")

    # Actually perform the format conversion on a non-subsampled clip.
    if c.format.color_family != vs.RGB or c.format.sample_type != vs.INTEGER or c.format.bits_per_sample != target_rgb.bits_per_sample:
        c = core.resize.Point(
            c,
            format=target_rgb
        )

    return c


def to_rgb(
        clip: vs.VideoNode,
        env: t.Optional[EnvironmentTypes] = None,
        *,
        # Output: RGB bitdepth
        bits_per_sample: int = 8,

        # Input: YUV
        scaler: t.Union[str, t.Callable[..., vs.VideoNode]] = "Bicubic",
        default_matrix: t.Optional[str] = None,
        default_transfer: t.Optional[str] = None,
        default_primaries: t.Optional[str] = None,
        default_range: t.Optional[str] = None,
        default_chromaloc: t.Optional[str] = None,
) -> vs.VideoNode:
    """
    This function converts a clip to RGB.

    :param clip: The clip to convert to RGB
    :param env: The environment the clip belongs to. (Optional if you don't use EnvironmentPolicies)
    :param bits_per_sample: The bits per sample the resulting RGB clip should have.
    :param scaler: The name scaler function in core.resize that should be used to convert YUV to RGB.
    :param default_*: Manually override the defaults predicted by the heuristics.
    :param yuv_heuristic: The heuristic function that takes the frame size and returns a set of yuv-metadata. (For test purposes)
    """

    # This function does a lot.
    # This is why there are so many comments.

    default_args = {}
    if default_matrix is not None:
        default_args["matrix_in_s"] = default_matrix
    if default_transfer is not None:
        default_args["transfer_in_s"] = default_transfer
    if default_primaries is not None:
        default_args["primaries_in_s"] = default_primaries
    if default_range is not None:
        default_args["range_in_s"] = default_range
    if default_chromaloc is not None:
        default_args["chromaloc_in_s"] = default_chromaloc

    with use_inline("to_rgb", env):
        core = vs.core.core
        real_rgb24 = core.get_video_format(vs.RGB24)
        target_rgb = real_rgb24.replace(bits_per_sample=bits_per_sample)

        # This avoids capturing `clip` in a closure creating a self-reference. 
        convert_yuv = functools.partial(
            _convert_yuv,
            core=core,
            real_rgb24=real_rgb24,
            default_args=default_args,
            scaler=scaler
        )

        actually_resize = functools.partial(
            _actually_resize,
            core=core,
            target_rgb=target_rgb,
            convert_yuv=convert_yuv
        )

        return wrap_variable_size(
            clip,
            force_assumed_format=target_rgb,
            func=actually_resize
        )

