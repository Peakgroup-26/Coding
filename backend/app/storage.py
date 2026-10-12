"""Private file storage: local disk, or an S3 bucket with the local disk as a working cache.

Files are only ever served through authenticated API endpoints; there are no public URLs.

STORAGE_BACKEND=s3 keeps every file in a private bucket (S3_BUCKET, AWS_REGION, default
ap-southeast-2 Sydney), encrypted at rest. The local copy under STORAGE_DIR is just a cache:
reads fetch from the bucket when the cache doesn't have the file, so app servers can be
replaced or scaled without losing drawings.
"""
import logging
from functools import lru_cache
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def _path(key: str) -> Path:
    p = (config.STORAGE_DIR / key).resolve()
    root = config.STORAGE_DIR.resolve()
    if root not in p.parents and p != root:
        raise ValueError("Invalid storage key")
    return p


def _s3_enabled() -> bool:
    return config.STORAGE_BACKEND == "s3"


@lru_cache(maxsize=4)
def _client(region: str, endpoint: str | None):
    import boto3

    return boto3.client("s3", region_name=region, endpoint_url=endpoint or None)


def _s3():
    return _client(config.AWS_REGION, config.S3_ENDPOINT_URL)


def _object_key(key: str) -> str:
    return f"{config.S3_PREFIX.strip('/')}/{key}" if config.S3_PREFIX.strip("/") else key


def commit(key: str) -> None:
    """Upload a file written to writable_path(key). No-op on local storage."""
    if _s3_enabled():
        _s3().upload_file(str(_path(key)), config.S3_BUCKET, _object_key(key),
                          ExtraArgs={"ServerSideEncryption": "AES256"})


def save_bytes(key: str, data: bytes) -> str:
    p = writable_path(key)
    p.write_bytes(data)
    commit(key)
    return key


def writable_path(key: str) -> Path:
    """Where to write a new file locally. Call commit(key) once it's complete."""
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def local_path(key: str) -> Path:
    """Path on disk for a stored file, fetching it from the bucket if it isn't cached."""
    p = writable_path(key)
    if not p.exists() and _s3_enabled():
        from botocore.exceptions import ClientError

        try:
            _s3().download_file(config.S3_BUCKET, _object_key(key), str(p))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
                raise
            log.warning("Stored file %s is missing from the bucket", key)
    return p


def delete(key: str) -> None:
    _path(key).unlink(missing_ok=True)
    if _s3_enabled():
        _s3().delete_object(Bucket=config.S3_BUCKET, Key=_object_key(key))


def read_bytes(key: str) -> bytes:
    return local_path(key).read_bytes()
