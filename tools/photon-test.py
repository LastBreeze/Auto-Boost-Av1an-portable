import shutil
import subprocess
import sys
from pathlib import Path


# Match bat-builder.py's essential fork distortion/fidelity level 0 output:
#   final_params = "--scd 0 --enable-dlf 3 --photon-noise 200"
# For this comparison script only the photon ISO value changes.
PHOTON_LEVELS = [200, 400, 600, 800, 1000]
CRF = "30"
PRESET = "8"
WORKERS = "1"


def run_streamed(cmd, cwd):
    """Run a command attached to the real console so av1an can show live progress."""
    print(" ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd), flush=True)
    # Do not capture stdout/stderr here. Av1an detects redirected output and may
    # suppress or mangle its progress UI. Inheriting the batch window's console
    # keeps the normal progress display visible.
    return subprocess.call(cmd, cwd=cwd)


def select_essential_fork(tools_dir):
    """Copy the essential SvtAv1EncApp.exe into tools/av1an, matching normal dispatch."""
    sys.path.insert(0, str(tools_dir))
    try:
        from svt_fork_setup import setup_svt_av1_fork
    except Exception as exc:
        print(f"Warning: Could not import svt_fork_setup.py: {exc}")
        return False
    return setup_svt_av1_fork(tools_dir, "essential", avx512=False, verbose=True)


def main():
    script_dir = Path(__file__).resolve().parent          # ...\tools
    av1an_exe = script_dir / "av1an" / "av1an.exe"
    work_dir = Path.cwd()
    source_file = work_dir / "0source.mkv"

    print("\n--- Auto-Boost Photon Noise Test ---")
    print("Using essential fork distortion/fidelity level 0 settings from bat-builder.py")
    print("Base encoder params: --crf 30 --preset 8 --scd 0 --enable-dlf 3")
    print("Photon levels: " + ", ".join(str(level) for level in PHOTON_LEVELS))
    print(f"Working folder: {work_dir}")

    if not source_file.exists():
        print("Error: 0source.mkv was not found in the current folder.")
        print("Place one AV1 MKV sample in extras and run photon-noise-test.bat again.")
        return 1

    if not av1an_exe.exists():
        print(f"Error: av1an.exe was not found: {av1an_exe}")
        return 1

    if not select_essential_fork(script_dir):
        print("Error: Could not select the essential SVT-AV1 fork.")
        return 1

    files_created = 0
    for level in PHOTON_LEVELS:
        suffix = level // 100
        output_file = work_dir / f"photon{suffix:02d}.mkv"
        temp_dir = work_dir / f"photon{suffix:02d}-av1an-temp"
        encoder_params = f"--crf {CRF} --preset {PRESET} --scd 0 --enable-dlf 3 --photon-noise {level}"

        if output_file.exists():
            print(f"Removing existing output: {output_file.name}")
            output_file.unlink()
        if temp_dir.exists():
            print(f"Removing stale av1an temp folder: {temp_dir.name}")
            shutil.rmtree(temp_dir, ignore_errors=True)

        print("\n" + "=" * 72)
        print(f"Creating {output_file.name} with built-in --photon-noise {level}")
        print(f"Encoder params: {encoder_params}")
        print("=" * 72)

        cmd = [
            str(av1an_exe),
            "-i", str(source_file),
            "-e", "svt-av1",
            "--no-defaults",
            "--split-method", "none",
            "-y",
            "--temp", str(temp_dir),
            "-w", WORKERS,
            "-o", str(output_file),
            "-v", encoder_params,
        ]

        rc = run_streamed(cmd, cwd=work_dir)
        if rc != 0:
            print(f"Error: av1an failed for photon noise {level} (exit code {rc}).")
            return rc
        if not output_file.exists():
            print(f"Error: Expected output was not created: {output_file}")
            return 1
        files_created += 1

    print("\nSuccessfully created photon noise comparison files:")
    for level in PHOTON_LEVELS:
        suffix = level // 100
        print(f"  photon{suffix:02d}.mkv  (--photon-noise {level})")
    print("External photon noise table files are not used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
