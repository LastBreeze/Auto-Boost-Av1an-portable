from cpuinfo import get_cpu_info
info = get_cpu_info()
if 'avx512f' in info.get('flags', []):
    print("AVX-512 supported")
