"""One app-owned Tunnel runtime per shared state directory, across Dev/install."""
import os


class RuntimeLease:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stream = (directory / 'runtime.lock').open('a+b')

    def __enter__(self):
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0, os.SEEK_END)
                if not self.stream.tell(): self.stream.write(b'\0'); self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise
        return self

    def __exit__(self, *args):
        # Closing releases the OS lock, including after abnormal owner exit.
        self.stream.close()
