"""Payload files: <uuid4>.bin, written fsync'd before the DB row that points at them commits."""
import hashlib
import os
import re
import uuid
from pathlib import Path

from . import contracts

_REF = re.compile(r"^[0-9a-f-]{36}\.bin$")


class PayloadStore:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._root = self.dir.resolve()

    def _path(self, ref):
        if not isinstance(ref, str) or not _REF.match(ref):
            raise contracts.IntError(contracts.Err.NOT_FOUND, "no such payload")
        p = (self._root / ref).resolve()
        if not p.is_relative_to(self._root) or p.parent != self._root:
            raise contracts.IntError(contracts.Err.NOT_FOUND, "no such payload")
        return self._root / ref      # unresolved: O_NOFOLLOW then rejects a symlink at the leaf

    def write(self, data: bytes):
        ref = "%s.bin" % uuid.uuid4()
        final, tmp = self._root / ref, self._root / ("." + ref + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        dfd = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return ref, hashlib.sha256(data).hexdigest()

    def read(self, ref) -> bytes:
        path = self._path(ref)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:      # missing, or a symlink (ELOOP)
            raise contracts.IntError(contracts.Err.NOT_FOUND, "no such payload") from None
        with os.fdopen(fd, "rb") as f:
            return f.read()

    def delete(self, ref):
        try:
            os.unlink(self._path(ref))
        except FileNotFoundError:
            pass

    def total_bytes(self) -> int:
        # ponytail: stat per file; at most MAX_ROWS files, fine on a Pi
        total = 0
        for e in os.scandir(self._root):
            if e.is_file(follow_symlinks=False):
                total += e.stat(follow_symlinks=False).st_size
        return total

    def sweep(self, keep, now, tmp_age) -> int:
        """Unlink .bin files not in `keep` and .tmp files older than tmp_age (0 = any). Symlinks are never touched."""
        n = 0
        with os.scandir(self._root) as it:
            for e in it:
                if not e.is_file(follow_symlinks=False):
                    continue
                if _REF.match(e.name):
                    orphan = e.name not in keep
                elif e.name.endswith(".tmp"):
                    orphan = not tmp_age or now - e.stat(follow_symlinks=False).st_mtime >= tmp_age
                else:
                    continue
                if orphan:
                    try:
                        os.unlink(e.path)
                        n += 1
                    except OSError:
                        pass
        return n
