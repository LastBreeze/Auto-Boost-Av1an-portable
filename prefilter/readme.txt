===================================================================
                     NVIDIA PREFILTER TOOL
===================================================================

This tool allows you to Denoise, Deband, and Downscale your video files
using your NVIDIA GPU. It combines three steps into one efficient process.

HOW TO USE:
1. Open "prefilter\settings.txt" to configure which filters you want 
   to enable (True/False).
2. Place your MKV files in this folder (same folder as nvidia-prefilter.bat).
3. Run "nvidia-prefilter.bat".

-------------------------------------------------------------------
                      SETTINGS REFERENCE
-------------------------------------------------------------------

--- DOWNSCALING ALGORITHMS (nvidia-downscale-filter) ---

  bilinear, cubic, hermite, lanczos, gaussian, spline36, spline64, mitchell

Recommendations:
  * Anime:       hermite
  * Live Action: spline36

--- DENOISE SETTINGS (nvidia-denoise-filter) ---

Format: vpp_fft3d=sigma=X
  * sigma: Strength of the denoise. Higher = Stronger.
  * Range: 0.0 to 1.0 (usually).
  * Default: vpp_fft3d=sigma=0.2 (Light denoise)

--- DEBAND SETTINGS (nvidia-deband-threshold/radius) ---

Threshold:
  * How aggressively to detect bands. 
  * Lower = Less sensitive. Higher = More aggressive (might lose detail).
  * Good range: 1.0 to 4.0.

Radius:
  * The size of the area to blur when banding is found.
  * Good range: 16 to 32.
  
+==================================================================
                     x265 PREFILTER TOOL
===================================================================

This tool allows you to Denoise, Deband, and Downscale your video files
using x265 lossless mode and VapourSynth filters. This is useful if you
do not have an NVIDIA GPU or need specific VapourSynth filters (DFTTest, etc).

HOW TO USE:
1. Open "prefilter\settings.txt" to configure which filters you want 
   to enable (True/False).
2. Place your MKV files in the same folder as "x265-prefilter.bat".
3. Run "x265-prefilter.bat".

-------------------------------------------------------------------
                      SETTINGS REFERENCE
-------------------------------------------------------------------

--- DOWNSCALING ALGORITHMS (x265-downscale-kernel) ---

Standard Kernels:
  bilinear, bicubic, hermite, lanczos, spline36

Recommendations:
  * Anime:       hermite
  * Live Action: spline36

--- DENOISE FILTER (x265-denoise-filter) ---

This accepts a full VapourSynth command string. The variable 'src' is
the input video clip.

Default (DFTTest): 
  DFTTest().denoise(src, {0.00:0.30, 0.40:0.30, 0.60:0.60, 0.80:1.50, 1.00:2.00}, planes=[0, 1, 2])

--- DEBAND FILTER (x265-deband-filter) ---

This accepts a full VapourSynth command string. The variable 'src' is 
the input video clip (or the result of the previous filter).

Default (Placebo Deband):
  core.placebo.Deband(src, threshold=2.0, planes=1)