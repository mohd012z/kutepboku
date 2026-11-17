"""OS-released local polling lock; cross-host ownership remains a deploy gate."""
import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def polling_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A local Telegram listener is already running') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
