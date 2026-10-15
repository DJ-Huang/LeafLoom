"""Control lines without a blocking Windows CRT read during native DLL imports."""
from __future__ import annotations
import os,select,time

class ControlPipe:
    def __init__(self,stream):
        self.fd=stream.fileno()
        if os.name=='nt':
            import ctypes,msvcrt
            from ctypes import wintypes as w
            self.ctypes=ctypes;self.w=w;self.handle=msvcrt.get_osfhandle(self.fd)
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.PeekNamedPipe.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
            self.kernel.PeekNamedPipe.restype=w.BOOL
            self.kernel.ReadFile.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
            self.kernel.ReadFile.restype=w.BOOL
    def lines(self):
        pending=bytearray()
        while True:
            if os.name=='nt':
                available=self.w.DWORD()
                if not self.kernel.PeekNamedPipe(self.handle,None,0,None,self.ctypes.byref(available),None):
                    error=self.ctypes.get_last_error()
                    if error in (6,109,232):break
                    raise self.ctypes.WinError(error)
                if not available.value:time.sleep(.05);continue
                buffer=self.ctypes.create_string_buffer(min(available.value,65536));size=self.w.DWORD()
                if not self.kernel.ReadFile(self.handle,buffer,len(buffer),self.ctypes.byref(size),None):
                    error=self.ctypes.get_last_error()
                    if error in (6,109,232):break
                    raise self.ctypes.WinError(error)
                raw=buffer.raw[:size.value]
            else:
                if not select.select([self.fd],[],[],.1)[0]:continue
                raw=os.read(self.fd,65536)
            if not raw:break
            pending.extend(raw)
            while b'\n' in pending:
                line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                yield line.decode('utf-8')
            if len(pending)>1024*1024:raise ValueError('Control message exceeds one MiB')
