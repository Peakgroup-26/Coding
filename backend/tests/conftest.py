import os
import shutil
import tempfile

_tmp = tempfile.mkdtemp(prefix="takeoff-test-")
os.environ["TAKEOFF_DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "admin-password"

import pymupdf as fitz  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.scale import MM_PER_PT  # noqa: E402

A1_PT = (841 / MM_PER_PT, 594 / MM_PER_PT)  # landscape
A3_PT = (420 / MM_PER_PT, 297 / MM_PER_PT)


def mm(x):
    return x / MM_PER_PT


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "admin@test.local", "password": "admin-password"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
    engine.dispose()
    Base.metadata.drop_all(engine)
    shutil.rmtree(_tmp, ignore_errors=True)


def make_sheet_page(doc, sheet_no, title, rev="A", scale_text="1:100 @ A1", size=A1_PT, factor=1.0):
    """A drawing page with a title block, a 100 mm test line and a 50 mm check line (at A1 size).

    factor shrinks the drawing, e.g. 420/841 for a sheet drawn at A1 but saved at A3.
    """
    w, h = size
    page = doc.new_page(width=w, height=h)
    # Test line: 100 mm on paper at A1 = 10 m at 1:100.
    page.draw_line((mm(100) * factor, mm(100) * factor), (mm(200) * factor, mm(100) * factor), color=(0, 0, 1), width=1)
    # Check line: 50 mm = 5 m.
    page.draw_line((mm(100) * factor, mm(150) * factor), (mm(100) * factor, mm(200) * factor), color=(1, 0, 0), width=1)
    x0, y0 = w * 0.70, h * 0.75
    fs = 14 * factor
    page.insert_text((x0, y0), title, fontsize=fs * 1.4)
    page.insert_text((x0, y0 + 30 * factor), f"DRAWING NO: {sheet_no}", fontsize=fs)
    page.insert_text((x0, y0 + 55 * factor), f"REV: {rev}", fontsize=fs)
    page.insert_text((x0, y0 + 80 * factor), f"SCALE {scale_text}", fontsize=fs)
    page.insert_text((x0, y0 + 105 * factor), "DATE 01/10/2026", fontsize=fs)
    return page


def pdf_bytes(pages: list[dict]) -> bytes:
    doc = fitz.open()
    for p in pages:
        make_sheet_page(doc, **p)
    data = doc.tobytes()
    doc.close()
    return data
