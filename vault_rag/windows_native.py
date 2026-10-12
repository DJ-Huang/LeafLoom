"""Windows named objects: single instances and cooperative shutdown, never PID kills."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
from vault_rag.platform_support import current_sid


def object_name(directory: Path, role: str, kind: str) -> str:
    key = hashlib.sha256((current_sid() + '|' + os.path.normcase(str(directory.resolve()))).encode()).hexdigest()[:24]
    return f'Local\\VaultRag-{key}-{role}-{kind}'


def kernel():
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    dll.CreateMutexW.restype = wintypes.HANDLE
    dll.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    dll.OpenMutexW.restype = wintypes.HANDLE
    dll.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    dll.CreateEventW.restype = wintypes.HANDLE
    dll.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    dll.OpenEventW.restype = wintypes.HANDLE
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.SetEvent.argtypes = [wintypes.HANDLE]
    dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    dll.WaitForSingleObject.restype = wintypes.DWORD
    return dll


class Instance:
    def __init__(self, directory: Path, role: str):
        self.dll = kernel()
        self.mutex = self.dll.CreateMutexW(None, False, object_name(directory, role, 'instance'))
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
        self.event = None
        if self.primary:
            self.event = self.dll.CreateEventW(None, True, False, object_name(directory, role, 'stop'))
            if not self.event:
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def wait_for_stop(self, timeout_ms=1000) -> bool:
        result = self.dll.WaitForSingleObject(self.event, timeout_ms)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        for attr in ('event', 'mutex'):
            handle = getattr(self, attr, None)
            if handle:
                self.dll.CloseHandle(handle)
                setattr(self, attr, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def running(directory: Path, role='service') -> bool:
    dll = kernel()
    handle = dll.OpenMutexW(0x00100000, False, object_name(directory, role, 'instance'))
    if not handle:
        error = ctypes.get_last_error()
        if error != 2:  # ERROR_FILE_NOT_FOUND; access denied must not mean stopped
            raise ctypes.WinError(error)
        return False
    dll.CloseHandle(handle)
    return True


def signal_stop(directory: Path, role='service') -> bool:
    dll = kernel()
    handle = dll.OpenEventW(0x0002, False, object_name(directory, role, 'stop'))
    if not handle:
        error = ctypes.get_last_error()
        if error != 2:
            raise ctypes.WinError(error)
        return False
    try:
        if not dll.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    finally:
        dll.CloseHandle(handle)
