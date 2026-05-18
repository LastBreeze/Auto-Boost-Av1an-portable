import os
import sys
import psutil
import subprocess
import time
import math
import shutil

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
AV1AN_DIR = os.path.join(TOOLS_DIR, "av1an")
FORKS_DIR = os.path.join(AV1AN_DIR, "svt-av1 forks")

AV1AN_PATH = "av1an"
SAMPLE_FILE = os.path.join(BASE_DIR, "tools", "sample.mkv")
CONFIG_FILE = os.path.join(BASE_DIR, "tools", "workercount-config.txt")

def cleanup_temp_folders():
    """Deletes temp folders and the test output file with retry logic."""
    print("Cleaning up temporary test files...", file=sys.stderr)
    
    # Wait 2 seconds to let Windows release file locks from the killed process
    time.sleep(2)

    # 1. Clean up folders starting with a period
    try:
        for item in os.listdir(BASE_DIR):
            item_path = os.path.join(BASE_DIR, item)
            if os.path.isdir(item_path) and item.startswith("."):
                deleted = False
                for attempt in range(3):
                    try:
                        shutil.rmtree(item_path)
                        print(f"   - Deleted: {item}", file=sys.stderr)
                        deleted = True
                        break 
                    except OSError:
                        time.sleep(1)
                
                if not deleted:
                    print(f"   - Warning: Could not fully delete {item} (File in use).", file=sys.stderr)
    except Exception as e:
        print(f"Error during folder cleanup: {e}", file=sys.stderr)

    # 2. Clean up the test output video file (sample_svt-av1.mkv)
    output_file = os.path.join(BASE_DIR, "sample_svt-av1.mkv")
    if os.path.exists(output_file):
        deleted = False
        for attempt in range(3):
            try:
                os.remove(output_file)
                print(f"   - Deleted: sample_svt-av1.mkv", file=sys.stderr)
                deleted = True
                break
            except OSError:
                time.sleep(1)
        
        if not deleted:
            print(f"   - Warning: Could not delete sample_svt-av1.mkv (File in use).", file=sys.stderr)

def setup_svt_av1_fork(target_fork="5fish"):
    """Checks for AVX-512 support and swaps the SvtAv1EncApp.exe accordingly."""
    print(f"Setting up SVT-AV1 fork: {target_fork}", file=sys.stderr)
    avx512_supported = False
    try:
        from cpuinfo import get_cpu_info
        info = get_cpu_info()
        if 'avx512f' in info.get('flags', []):
            avx512_supported = True
            print("   - CPU supports AVX-512.", file=sys.stderr)
        else:
            print("   - CPU does not support AVX-512.", file=sys.stderr)
    except ImportError:
        print("   - Warning: py-cpuinfo not installed. Assuming no AVX-512 support.", file=sys.stderr)

    fork_parent = None
    if os.path.exists(FORKS_DIR):
        for f in os.listdir(FORKS_DIR):
            if os.path.isdir(os.path.join(FORKS_DIR, f)) and target_fork.lower() in f.lower():
                fork_parent = os.path.join(FORKS_DIR, f)
                break

    if fork_parent:
        target_subfolder = None
        subfolders = [d for d in os.listdir(fork_parent) if os.path.isdir(os.path.join(fork_parent, d))]

        if avx512_supported:
            for sub in subfolders:
                sub_lower = sub.lower()
                if 'icelake' in sub_lower or 'znver5' in sub_lower or 'znver4' in sub_lower:
                    target_subfolder = sub
                    break

        if not target_subfolder:
            for sub in subfolders:
                if 'x86-64-v3' in sub.lower():
                    target_subfolder = sub
                    break

        if not target_subfolder and subfolders:
            target_subfolder = subfolders[0]

        if target_subfolder:
            src_dir = os.path.join(fork_parent, target_subfolder)
            exe_src = os.path.join(src_dir, "SvtAv1EncApp.exe")
            exe_dest = os.path.join(AV1AN_DIR, "SvtAv1EncApp.exe")

            try:
                if os.path.exists(exe_dest):
                    os.remove(exe_dest)
            except Exception as e:
                print(f"   - Warning: Could not clean up old SVT-AV1 files: {e}", file=sys.stderr)

            if os.path.exists(exe_src):
                try:
                    shutil.copy2(exe_src, exe_dest)
                    print(f"   - Copied SvtAv1EncApp.exe from {target_subfolder}", file=sys.stderr)
                except Exception as e:
                    print(f"   - Error copying fork files: {e}", file=sys.stderr)
            else:
                print(f"   - Error: SvtAv1EncApp.exe not found in {src_dir}", file=sys.stderr)
    else:
        print(f"   - Warning: Could not find a fork directory matching '{target_fork}' in {FORKS_DIR}", file=sys.stderr)


def get_optimal_workers():
    print(f"Running one-time RAM test on {os.path.basename(SAMPLE_FILE)}...", file=sys.stderr)
    print("Please wait while we measure memory usage...", file=sys.stderr)
    
    # Check/swap for AVX-512 before starting process
    setup_svt_av1_fork("5fish")

    # 1. Start the test process with 1 worker
    cmd = [
        AV1AN_PATH,
        "-i", SAMPLE_FILE,
        "-y",
        "--workers", "1",
        "--verbose",
        "-e", "svt-av1", 
        "-m", "bestsource", 
        "--cache-mode", "temp", 
        "-v", " --preset 4 --crf 30 --lp 3", 
    ]

    try:
        # Start av1an
        process = subprocess.Popen(
            cmd, 
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        print("Error: av1an executable not found.", file=sys.stderr)
        return 1

    max_total_rss = 0
    
    # 2. Monitor RAM usage (Parent + Children)
    try:
        # Monitor for up to 20 seconds
        for _ in range(40): 
            if process.poll() is not None:
                break
            
            try:
                current_rss = 0
                parent = psutil.Process(process.pid)
                current_rss += parent.memory_info().rss
                
                # Add up memory of all child processes (the encoders)
                for child in parent.children(recursive=True):
                    try:
                        current_rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                if current_rss > max_total_rss:
                    max_total_rss = current_rss
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            time.sleep(0.5)
    finally:
        # Ensure process is killed if it's still running after timeout
        if process.poll() is None:
            process.kill()

    # 3. Perform Calculations
    if max_total_rss == 0:
        print("\nWarning: Could not measure RAM. Defaulting to 1 worker.")
        cleanup_temp_folders()
        return 1

    total_ram = psutil.virtual_memory().total
    cpu_threads = os.cpu_count()

    # Math: Leave 10% of TOTAL RAM free
    safe_ram_limit = total_ram * 0.90
    
    # Calculate Max Workers by RAM (Safe Total / Peak Usage of 1 Worker)
    max_workers_ram = int(safe_ram_limit / max_total_rss)
    
    # Calculate Max Workers by CPU (Threads / 3 for --lp 3 optimization)
    max_workers_cpu = int(cpu_threads / 3)

    # Determine bottleneck (Min of RAM or CPU limits)
    raw_worker_count = min(max_workers_ram, max_workers_cpu)

    # --- NEW LOGIC START ---
    # Thresholds: > 6 threads and > 20GB RAM
    ram_threshold_bytes = 20 * (1024**3) # 20 GB in bytes
    
    # Use physical cores if possible, otherwise fall back to logical threads
    physical_cores = psutil.cpu_count(logical=False)
    if not physical_cores:
        physical_cores = cpu_threads

    if physical_cores > 6 and total_ram > ram_threshold_bytes:
        # High spec: Use full count
        final_workers = raw_worker_count
        print(f"\n   - High Spec detected (>{physical_cores} cores, >20GB RAM). Keeping worker count at {final_workers}.")
    else:
        # Lower spec: Subtract one worker
        final_workers = raw_worker_count - 1
        print(f"\n   - Standard Spec. Reducing worker count by 1 for stability.")

    # Ensure we never return less than 1 worker
    final_workers = max(1, final_workers)
    # --- NEW LOGIC END ---

    print("\n------------------------------------------------")
    print(f"   - Total System RAM: {total_ram // (1024**2)} MB")
    print(f"   - Peak RAM (1 Worker): {max_total_rss // (1024**2)} MB")
    print(f"   - CPU Threads: {cpu_threads}")
    print(f"   - Calculated Optimal Workers: {final_workers}")
    print("------------------------------------------------")
    
    # Run cleanup before returning
    cleanup_temp_folders()

    return final_workers

if __name__ == "__main__":
    if not os.path.exists(SAMPLE_FILE):
        print(f"Error: {SAMPLE_FILE} missing. Defaulting to 1.")
        workers = 1
    else:
        workers = get_optimal_workers()

    # Save to config file
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(f"workers={workers}\n")
        print("\nOne-time test complete. Auto worker count set.")
        print("You may manually edit tools\\workercount-config.txt if needed")
    except Exception as e:
        print(f"Error writing config file: {e}")