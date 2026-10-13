"""S3 storage: files go to a private, encrypted bucket; the local disk is only a cache."""
import shutil

import pytest
from moto import mock_aws

from app import config, storage

from .conftest import pdf_bytes
from .helpers import new_job


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
        monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(config, "S3_BUCKET", "peak-takeoff-test")
        monkeypatch.setattr(config, "S3_PREFIX", "takeoff")
        monkeypatch.setattr(config, "AWS_REGION", "ap-southeast-2")
        storage._client.cache_clear()
        client = storage._s3()
        client.create_bucket(Bucket="peak-takeoff-test", CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"})
        yield client
        storage._client.cache_clear()


def test_uploads_go_to_the_bucket_and_come_back(client, s3):
    job = new_job(client, name="S3 job")
    r = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("s3.pdf", pdf_bytes([{"sheet_no": "H-1", "title": "PLAN"}]), "application/pdf"))])
    assert r.status_code == 200, r.text
    sheet = r.json()[0]

    keys = {o["Key"] for o in s3.list_objects_v2(Bucket="peak-takeoff-test")["Contents"]}
    prefix = f"takeoff/jobs/{job['id']}/"
    assert any(k.startswith(prefix + "originals/") for k in keys)
    assert any(k.endswith("page-1.png") for k in keys) and any(k.endswith("page-1-snaps.json") for k in keys)
    original = next(k for k in keys if "/originals/" in k)
    assert s3.head_object(Bucket="peak-takeoff-test", Key=original)["ServerSideEncryption"] == "AES256"

    # Lose the local cache (a new server, say): files are fetched back from the bucket.
    shutil.rmtree(config.STORAGE_DIR / "jobs" / str(job["id"]))
    img = client.get(f"/api/sheets/{sheet['id']}/image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/api/sheets/{sheet['id']}/line-styles").status_code == 200  # reads the original PDF


def test_save_and_delete(s3):
    storage.save_bytes("misc/a.txt", b"hello")
    assert s3.get_object(Bucket="peak-takeoff-test", Key="takeoff/misc/a.txt")["Body"].read() == b"hello"
    storage.delete("misc/a.txt")
    assert "Contents" not in s3.list_objects_v2(Bucket="peak-takeoff-test", Prefix="takeoff/misc/")


def test_keys_cannot_escape_storage():
    with pytest.raises(ValueError):
        storage.local_path("../../etc/passwd")
