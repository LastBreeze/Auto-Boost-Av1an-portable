"""Return the chipset maker of the dedicated GPU: "nvidia", "amd", "intel" or None.

Stdlib only (ctypes + DXGI), so it runs on the portable VapourSynth python as-is.
"""

import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_uint, c_size_t

_VENDORS = {0x10DE: "nvidia", 0x1002: "amd", 0x1022: "amd", 0x8086: "intel"}
_SOFTWARE = 2  # DXGI_ADAPTER_FLAG_SOFTWARE


class _LUID(ctypes.Structure):
    _fields_ = [("Low", wintypes.DWORD), ("High", wintypes.LONG)]


class _DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", c_uint), ("DeviceId", c_uint),
        ("SubSysId", c_uint), ("Revision", c_uint),
        ("DedicatedVideoMemory", c_size_t),
        ("DedicatedSystemMemory", c_size_t),
        ("SharedSystemMemory", c_size_t),
        ("AdapterLuid", _LUID), ("Flags", c_uint),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("d1", c_uint), ("d2", ctypes.c_ushort),
                ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _call(ptr, slot, argtypes, *args):
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtbl[slot])(ptr, *args)


def list_gpus():
    """[(vendor, name, vram_bytes), ...] for real hardware adapters."""
    iid = _GUID(0x770AAE78, 0xF26F, 0x4DBA,
                (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = c_void_p()
    if ctypes.WinDLL("dxgi").CreateDXGIFactory1(byref(iid), byref(factory)) != 0:
        return []

    out, seen, i = [], set(), 0
    try:
        while True:
            adapter = c_void_p()
            # IDXGIFactory1::EnumAdapters1 == vtable slot 12; returns
            # DXGI_ERROR_NOT_FOUND once the list is exhausted.
            if _call(factory, 12, [c_uint, POINTER(c_void_p)], i, byref(adapter)) != 0:
                break
            try:
                d = _DESC1()
                _call(adapter, 10, [POINTER(_DESC1)], byref(d))  # GetDesc1
                key = (d.VendorId, d.DeviceId, d.SubSysId, d.DedicatedVideoMemory)
                if not d.Flags & _SOFTWARE and key not in seen:
                    seen.add(key)
                    out.append((_VENDORS.get(d.VendorId), d.Description,
                                d.DedicatedVideoMemory))
            finally:
                _call(adapter, 2, [])  # Release
            i += 1
    finally:
        _call(factory, 2, [])
    return out


def gpu_vendor(min_vram_mb=512):
    """"nvidia" / "amd" / "intel" for the discrete GPU, else None.

    Integrated GPUs report only a token amount of dedicated VRAM (a few hundred
    MB at most), so the VRAM floor is what separates discrete from integrated.
    """
    gpus = [g for g in list_gpus() if g[2] >= min_vram_mb * 1024 * 1024]
    if not gpus:
        return None
    return max(gpus, key=lambda g: g[2])[0]


if __name__ == "__main__":
    for vendor, name, vram in list_gpus():
        print(f"{vendor or '?':<8} {name:<34} {vram / 2**30:5.2f} GiB")
    print("\ndedicated ->", gpu_vendor())
