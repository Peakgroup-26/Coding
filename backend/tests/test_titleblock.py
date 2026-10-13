from app.titleblock import classify, read_title_block, revision_rank


def test_read_labelled_title_block():
    tb = read_title_block("PROJECT X\nDRAWING NO: H-101\nREV: C\nSCALE 1:100 @ A1\nDATE 01/10/2026",
                          ["SANITARY DRAINAGE PLAN - GROUND FLOOR", "SCALE 1:100 @ A1"])
    assert tb.sheet_no == "H-101"
    assert tb.revision == "C"
    assert tb.drawing_date == "01/10/2026"
    assert tb.title == "SANITARY DRAINAGE PLAN - GROUND FLOOR"


def test_read_unlabelled_sheet_number():
    tb = read_title_block("HYD-201 rev B")
    assert tb.sheet_no == "HYD-201"
    assert tb.revision == "B"


def test_classify_drainage_plan():
    c = classify("sewer drainage, floor waste, IO", "SANITARY DRAINAGE PLAN GROUND FLOOR")
    assert c.classification == "plan"
    assert "SAN" in c.services
    assert c.is_hydraulic
    assert c.confidence > 0.5


def test_classify_cover_sheet():
    assert classify("", "HYDRAULIC COVER SHEET AND DRAWING REGISTER").classification == "cover"


def test_revision_order():
    revs = ["B", "P2", "A", "P1", "C", "10", "2"]
    assert sorted(revs, key=revision_rank)[:2] == ["P1", "P2"]
    assert sorted(["A", "C", "B"], key=revision_rank) == ["A", "B", "C"]
    assert sorted(["10", "2"], key=revision_rank) == ["2", "10"]
