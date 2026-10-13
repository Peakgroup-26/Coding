"""Private file storage.

Files are only ever served through authenticated API endpoints; there are no public URLs.
This local-disk implementation can be swapped for an S3-compatible bucket by implementing
the same three functions.
"""
from pathlib import Path

from . import config


def _path(key: str) -> Path:
    p = (config.STORAGE_DIR / key).resolve()
    root = config.STORAGE_DIR.resolve()
    if root not in p.parents and p != root:
        raise ValueError("Invalid storage key")
    return p


def save_bytes(key: str, data: bytes) -> str:
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def local_path(key: str) -> Path:
    """Path on disk for a stored object (used for streaming responses and PDF processing)."""
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_bytes(key: str) -> bytes:
    return _path(key).read_bytes()
