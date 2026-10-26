"""Release only this Python process's finished working allocations."""
import gc,sys


def release_working_memory():
    gc.collect()
    if sys.platform.startswith('linux'):
        import ctypes
        try:
            trim=ctypes.CDLL(None).malloc_trim
            trim.argtypes=[ctypes.c_size_t];trim.restype=ctypes.c_int
            trim(0)
        except AttributeError:pass
