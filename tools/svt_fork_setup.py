from pathlib import Path
import shutil


def _norm(text: str) -> str:
    return text.lower().replace("_", "-").replace(" ", "")


def _find_first_file(folder: Path, name: str) -> Path | None:
    direct = folder / name
    if direct.exists():
        return direct
    matches = list(folder.rglob(name))
    return matches[0] if matches else None


def setup_svt_av1_fork(tools_dir: str | Path, fork: str = "essential", avx512: bool = False, verbose: bool = True) -> bool:
    """Select an SVT-AV1 fork binary and copy it to tools/av1an/SvtAv1EncApp.exe.

    Fork folders are matched dynamically by name; they only need to contain
    '5fish', 'essential', 'hdr', or 'custom'. 5fish/essential use an AVX-512
    subfolder only when avx512=True. hdr always uses x86-64-v3.
    Essential also copies ffms2.dll when present.
    """
    tools_dir = Path(tools_dir)
    av1an_dir = tools_dir / "av1an"
    forks_dir = av1an_dir / "svt-av1 forks"
    fork_key = (fork or "essential").strip().lower()
    if fork_key in ("svt-av1-essential", "essential"):
        match_key = "essential"
    elif fork_key in ("svt-av1-hdr", "hdr"):
        match_key = "hdr"
    elif fork_key in ("5fish", "svt-av1-psy", "psy"):
        match_key = "5fish"
    else:
        match_key = fork_key

    def log(msg: str):
        if verbose:
            print(f"[SVT Fork] {msg}")

    if not forks_dir.exists():
        log(f"Forks directory not found: {forks_dir}")
        return False

    candidates = [d for d in forks_dir.iterdir() if d.is_dir() and match_key in d.name.lower()]
    if not candidates and match_key == "custom":
        candidates = [forks_dir / "custom"] if (forks_dir / "custom").exists() else []
    if not candidates:
        log(f"No fork directory containing '{match_key}' found in {forks_dir}")
        return False

    fork_parent = sorted(candidates, key=lambda p: p.name.lower())[0]
    subfolders = [d for d in fork_parent.iterdir() if d.is_dir()]
    target_dir = fork_parent

    if subfolders:
        if match_key == "hdr":
            wanted = ["x86-64-v3"]
        elif avx512:
            wanted = ["icelake", "znver5", "znver4"]
        else:
            wanted = ["x86-64-v3"]
        for needle in wanted:
            for sub in subfolders:
                if needle in sub.name.lower():
                    target_dir = sub
                    break
            if target_dir != fork_parent:
                break
        if target_dir == fork_parent:
            exe_holder = next((sub for sub in subfolders if (sub / "SvtAv1EncApp.exe").exists()), None)
            if exe_holder:
                target_dir = exe_holder

    exe_src = _find_first_file(target_dir, "SvtAv1EncApp.exe")
    if not exe_src:
        log(f"SvtAv1EncApp.exe not found under {target_dir}")
        return False

    av1an_dir.mkdir(parents=True, exist_ok=True)
    exe_dest = av1an_dir / "SvtAv1EncApp.exe"
    shutil.copy2(exe_src, exe_dest)
    log(f"Copied {exe_src} -> {exe_dest}")

    # Essential needs ffms2.dll beside SvtAv1EncApp.exe.
    if match_key == "essential":
        dll_src = _find_first_file(target_dir, "ffms2.dll") or _find_first_file(fork_parent, "ffms2.dll")
        if dll_src:
            dll_dest = av1an_dir / "ffms2.dll"
            shutil.copy2(dll_src, dll_dest)
            log(f"Copied {dll_src} -> {dll_dest}")
        else:
            log("Warning: essential fork selected but ffms2.dll was not found")

    return True
