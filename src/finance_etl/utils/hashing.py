"""File and content hashing utilities."""
import hashlib
from pathlib import Path


CHUNK_SIZE = 65_536  # 64 KB


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 hex digest of a file (streaming, memory-safe)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def sha256_str(value: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
