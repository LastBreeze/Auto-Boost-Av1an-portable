import vapoursynth as vs
from vssource import BestSource
from vstools import initialize_clip, depth, finalize_clip
import vsdehalo as deh

core = vs.core
core.max_cache_size = 1024

src = BestSource.source("replace.mkv")

src = initialize_clip(src)

#denoise = DFTTest(sigma=0.2).denoise(src)

dehalo = deh.dehalo_alpha(src, rx=2.0, ry=2.0, brightstr=1.0)

#detail_mask = deband_detail_mask(dehalo)
#debanded = deband.std.MaskedMerge(dehalo, detail_mask)

deband = core.placebo.Deband(dehalo, iterations=1, threshold=1.5, radius=16.0, grain=8.0)

final = finalize_clip(deband)

final.set_output(0)
#src.set_output(1)