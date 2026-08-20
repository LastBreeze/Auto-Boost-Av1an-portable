"""Inference backends for the rescale section of video-input\\template.vpy.

The rescale block the template writer can add descales an anime source to its
native production resolution and rebuilds it with ArtCNN, which is an ONNX model
run through vs-mlrt. vs-jetpack 2 drives that through vsscale.Backend rather
than the standalone vsmlrt module, but the plugin side is the same one: an
inference backend has to be there, and which one is available decides how fast
the rescale is:

  DirectML   ships with this package. vsort.dll plus DirectML.dll and
             onnxruntime.dll in VapourSynth\\vs-plugins\\vsort, about 40 MB, and
             it runs on any Direct3D 12 GPU - NVIDIA, AMD or Intel. Slowest of
             the three, but it works out of the box on every machine.
  TensorRT   NVIDIA only. Several times faster than DirectML, and 3.5 GB
             installed, which is why it is not in the package.
  MIGraphX   AMD only. Faster than DirectML, 385 MB installed.

The two big ones are fetched on demand from the vs-mlrt release this package is
pinned to, with the curl.exe and 7z.exe that sit in the VapourSynth folder, and
unpacked into VapourSynth\\vs-plugins. Pinning matters: vsmlrt.py, the plugin
DLLs and the runtime folders are versioned together, and mixing releases is what
produces "unable to load" errors that look like a broken install.

The plugin DLLs and their runtime folders (vsmlrt-cuda, vsmlrt-hip) are looked
for next to each other, so everything lands in vs-plugins next to vsort.dll. The
archives already carry those folder names, so they are simply extracted there.

Two things moved in vs-jetpack 2 and are no longer this file's business. The
ArtCNN ONNX models used to sit in vs-plugins\\models; vsscale now resolves them
out of a .vsjet folder beside the running script, falling back to a per-user
cache under AppData. Neither is any use to a portable package - every script
that asks for a model here is a rendered copy in a temp folder, and AppData does
not travel with the folder - so vpy_template.render() puts a few lines on the
front of any rendered script that uses vsscale, redirecting the first of those
lookups to VapourSynth\\.vsjet, where this package keeps the models. They go
there with

    python.exe -c "from vsscale.mlrt.cli import app; app()" onnx download ArtCNN --latest

run from the VapourSynth folder, which is the directory vsscale's downloader
hangs its .vsjet off. The Scripts\\vsscale.exe launcher is not used: like the
other Scripts launchers it carries the build machine's python path and exits
without doing anything here. That is also why directml_installed() below no
longer looks for the models. And vs-jetpack's TensorRT
backend builds its engine through the tensorrt Python module instead of the
trtexec in vsmlrt-cuda, so the NVIDIA download here covers the plugin but not
the engine builder.

Used by bat-builder.py's template.vpy page. Nothing in an encode imports this.
"""

import os
import shutil
import subprocess

# The vs-mlrt release everything here is pinned to. The plugin DLLs and the
# runtime folders that go with them all come from this one release. The ArtCNN
# models no longer do - vs-jetpack 2 fetches those itself, from the ArtCNN
# releases, into a .vsjet folder.
RELEASE = "v15.16"
RELEASE_URL = f"https://github.com/AmusementClub/vs-mlrt/releases/tag/{RELEASE}"
DOWNLOAD_BASE = f"https://github.com/AmusementClub/vs-mlrt/releases/download/{RELEASE}"

# Downloads land here and the folder is removed once everything is unpacked.
TEMP_DIRNAME = "mlrt-download.tmp"

# Spare room left over after the archive and its extracted contents, so the
# install cannot be the thing that fills the disk.
FREE_SPACE_MARGIN = 512 * 1024 * 1024


def root_dir():
    """The portable package root, one level above this tools folder."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vapoursynth_dir():
    return os.path.join(root_dir(), "VapourSynth")


def plugins_dir():
    """VapourSynth\\vs-plugins - where the plugin DLLs and runtime folders live."""
    return os.path.join(vapoursynth_dir(), "vs-plugins")


def curl_path():
    return os.path.join(vapoursynth_dir(), "curl.exe")


def sevenzip_path():
    return os.path.join(vapoursynth_dir(), "7z.exe")


class Backend:
    """One downloadable vs-mlrt backend.

    assets   (filename, size in bytes) for each release asset, in download
             order. A multi-volume 7z is listed as its parts; only the .001 is
             handed to 7z, which pulls the rest in itself.
    markers  paths under vs-plugins that have to exist afterwards. Both the
             plugin DLL and its runtime folder are checked, because the DLL on
             its own loads and then fails at the first frame.
    """

    def __init__(self, key, title, hardware, backend_call, assets, markers,
                 installed_bytes, notes):
        self.key = key
        self.title = title
        self.hardware = hardware
        self.backend_call = backend_call
        self.assets = assets
        self.markers = markers
        self.installed_bytes = installed_bytes
        self.notes = notes

    @property
    def download_bytes(self):
        return sum(size for _, size in self.assets)

    def marker_paths(self):
        return [os.path.join(plugins_dir(), marker) for marker in self.markers]

    def is_installed(self):
        return all(os.path.exists(path) for path in self.marker_paths())

    def missing_markers(self):
        return [marker for marker, path in zip(self.markers, self.marker_paths())
                if not os.path.exists(path)]


# Sizes are the release's own, so the figures shown before a download are the
# real ones rather than an estimate.
BACKENDS = {
    "nvidia": Backend(
        key="nvidia",
        title="NVIDIA (TensorRT)",
        hardware="NVIDIA GeForce / RTX",
        backend_call="Backend.TRT(fp16=True)",
        assets=[
            ("vsmlrt-cuda.v15.16.7z.001", 2147483647),
            ("vsmlrt-cuda.v15.16.7z.002", 464467988),
            ("VSTRT-Windows-x64.v15.16.7z", 486704),
        ],
        markers=["vstrt.dll", "vsmlrt-cuda"],
        installed_bytes=3635515392,
        notes=(
            "TensorRT builds an optimised engine for your exact GPU the first "
            "time a rescale runs, which takes a few minutes and is cached "
            "afterwards. The same files also cover Backend.ORT_CUDA."
        ),
    ),
    "amd": Backend(
        key="amd",
        title="AMD (MIGraphX)",
        hardware="AMD Radeon with ROCm/HIP support",
        backend_call="Backend.MIGX(fp16=True)",
        assets=[
            ("vsmlrt-hip.v15.16.7z", 67621170),
            ("VSMIGX-Windows-x64.v15.16.7z", 130464),
        ],
        markers=["vsmigx.dll", "vsmlrt-hip"],
        installed_bytes=403595328,
        notes=(
            "MIGraphX compiles the model for your GPU on the first rescale, "
            "which takes a minute or two and is cached afterwards."
        ),
    ),
}


def human_size(num_bytes):
    """A size for reading, in the largest unit that does not round it to zero."""
    gigabytes = num_bytes / (1024 ** 3)
    if gigabytes >= 1:
        return f"{gigabytes:.1f} GB"
    megabytes = num_bytes / (1024 ** 2)
    if megabytes >= 1:
        return f"{megabytes:.0f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def pip_plugins_dir():
    """VapourSynth\\Lib\\site-packages\\vapoursynth\\plugins.

    vs-jetpack 2 ships its VapourSynth plugins as pip wheels that unpack their
    DLLs in here rather than into vs-plugins, so a plugin can now be installed
    and correctly loaded without anything appearing in vs-plugins at all.
    """
    return os.path.join(vapoursynth_dir(), "Lib", "site-packages", "vapoursynth",
                        "plugins")


def find_plugin_file(filename, max_depth=2):
    """The first copy of filename under either plugin tree, or None.

    Both trees are searched because the two ways a plugin can arrive - unpacked
    into vs-plugins by this file, or pip installed by vs-jetpack - put their
    DLLs in different places, and a check that only knew about one of them would
    report a working install as missing.

    Two levels below each root, which is what the two layouts between them need:

        vs-plugins\\vsort.dll                     depth 0, unpacked by this file
        vs-plugins\\vsort\\DirectML.dll            depth 1, its runtime folder
        ...\\vapoursynth\\plugins\\ort\\vsort.dll   depth 1, pip installed
        ...\\vapoursynth\\plugins\\ort\\vsort\\DirectML.dll
                                                 depth 2, its runtime folder

    The depth is bounded rather than walking everything so that answering a menu
    label stays cheap next to a TensorRT install, whose vsmlrt-cuda folder holds
    thousands of files in trees nothing here needs to look inside.
    """
    roots = [(plugins_dir(), 0), (pip_plugins_dir(), 0)]
    while roots:
        root, depth = roots.pop(0)
        candidate = os.path.join(root, filename)
        if os.path.exists(candidate):
            return candidate
        if depth >= max_depth:
            continue
        try:
            roots.extend((entry.path, depth + 1)
                         for entry in os.scandir(root) if entry.is_dir())
        except OSError:
            continue
    return None


def directml_installed():
    """True when the DirectML backend's plugin files are in place.

    Checked rather than assumed: it is the fallback the template's first rescale
    section uses, so a package that lost those files should say so instead of
    letting the script fail at the first frame.

    ArtCNN's ONNX model is deliberately not part of this check. vs-jetpack 2
    stopped reading vs-plugins\\models and now resolves models out of a .vsjet
    folder beside whichever script is running, with a shared user cache as the
    fallback - which is why rendered scripts are pointed at VapourSynth\\.vsjet
    instead. A missing model reports itself when the rescale asks for its first
    frame.
    """
    return all(find_plugin_file(name) for name in
               ("vsort.dll", "DirectML.dll", "onnxruntime.dll"))


def tools_present():
    """(ok, message) for the curl.exe and 7z.exe the download needs."""
    missing = [os.path.basename(path) for path in (curl_path(), sevenzip_path())
               if not os.path.exists(path)]
    if missing:
        return False, (f"{' and '.join(missing)} is missing from the VapourSynth "
                       f"folder, so the download cannot run. Re-download the package.")
    return True, ""


def free_space():
    """Bytes free on the drive the package is on, or None if it cannot be read."""
    try:
        return shutil.disk_usage(root_dir()).free
    except OSError:
        return None


def space_shortfall(backend):
    """How much more free space is needed, or 0 when there is enough.

    The archive and its extracted contents are both on the disk at once, since
    the download is only deleted after 7z has finished with it.
    """
    available = free_space()
    if available is None:
        return 0
    needed = backend.download_bytes + backend.installed_bytes + FREE_SPACE_MARGIN
    return max(0, needed - available)


def temp_dir():
    return os.path.join(vapoursynth_dir(), TEMP_DIRNAME)


def clear_temp_dir():
    """Remove the download folder. Failure is not fatal - it is only a cache."""
    try:
        shutil.rmtree(temp_dir())
    except OSError:
        pass


def _complete(path, expected_size):
    """True when this file is already the size the release says it should be."""
    try:
        return os.path.getsize(path) == expected_size
    except OSError:
        return False


def _download(url, dest):
    """Fetch one asset with curl, leaving its progress bar on screen.

    -C - resumes a part-downloaded file, which is what makes a 2.4 GB download
    survivable on a connection that drops: running the install again picks up
    where it stopped instead of starting over.
    """
    command = [
        curl_path(),
        "-L",                    # release assets redirect to a CDN
        "--fail",                # an HTML error page is not a download
        "--retry", "3",
        "--retry-delay", "5",
        "-C", "-",               # resume a partial file
        "-o", dest,
        url,
    ]
    result = subprocess.run(command)
    return result.returncode == 0


def _extract(archive, destination):
    """Unpack one archive into vs-plugins with the bundled 7-Zip.

    The archives carry their own folder names (vsmlrt-cuda\\, vsmlrt-hip\\) plus
    the plugin DLL at the root, so extracting straight into vs-plugins puts each
    runtime folder next to the DLL that goes with it.
    """
    command = [sevenzip_path(), "x", "-y", f"-o{destination}", archive]
    result = subprocess.run(command)
    return result.returncode == 0


def install(key):
    """Download and unpack one backend. Returns (ok, message).

    Everything it prints is curl's and 7-Zip's own output, so a long download
    shows real progress rather than a frozen console.
    """
    backend = BACKENDS.get(key)
    if backend is None:
        return False, f"Unknown backend {key!r}."

    ok, message = tools_present()
    if not ok:
        return False, message

    shortfall = space_shortfall(backend)
    if shortfall:
        return False, (f"Not enough free disk space: about "
                       f"{human_size(shortfall)} more is needed on the drive "
                       f"this package is on.")

    download_dir = temp_dir()
    try:
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(plugins_dir(), exist_ok=True)
    except OSError as e:
        return False, f"Could not create the download folder: {e}"

    for index, (filename, size) in enumerate(backend.assets, start=1):
        destination = os.path.join(download_dir, filename)
        print()
        # A file already at its release size is one a previous attempt finished:
        # asking curl to resume that gets a 416 back, which it reports as a
        # failure rather than as "nothing left to fetch".
        if _complete(destination, size):
            print(f"[{index}/{len(backend.assets)}] {filename} is already downloaded")
            continue
        print(f"[{index}/{len(backend.assets)}] Downloading {filename} "
              f"({human_size(size)})")
        if not _download(f"{DOWNLOAD_BASE}/{filename}", destination):
            return False, (f"Downloading {filename} failed. Check your internet "
                           f"connection and try again - a part-finished download "
                           f"is kept and resumed.")

    # A multi-volume 7z is opened through its first part; 7-Zip reads the rest
    # itself, so handing it the .002 as well would only fail.
    for filename, _ in backend.assets:
        if filename.endswith(".002"):
            continue
        print()
        print(f"Unpacking {filename}")
        if not _extract(os.path.join(download_dir, filename), plugins_dir()):
            # A damaged archive is still the right size, so the size check above
            # would skip past it forever. Throwing the parts away is what makes
            # "try again" actually fetch them again.
            clear_temp_dir()
            return False, (f"Unpacking {filename} failed. The download was "
                           f"damaged and has been discarded; run this again to "
                           f"fetch it fresh.")

    missing = backend.missing_markers()
    if missing:
        return False, (f"The files unpacked, but {', '.join(missing)} is not in "
                       f"VapourSynth\\vs-plugins. The release layout may have "
                       f"changed.")

    clear_temp_dir()
    return True, (f"{backend.title} is installed. Uncomment the "
                  f"{backend.title.split(' ')[0]} rescale section in "
                  f"video-input\\template.vpy to use it.")
