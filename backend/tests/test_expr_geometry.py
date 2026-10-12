import pytest

from app.expr import FormulaError, evaluate, validate
from app.geometry import RunShape, bends, branch_connections, deflection_angles, end_connections, overlap_fraction


def test_formulas():
    assert evaluate("n", n=3) == 3
    assert evaluate("ceil(m / 1.2)", m=15) == 13
    assert evaluate("max(1, m * 0.05)", m=10) == 1
    assert evaluate("2 * n + 1", n=2) == 5
    assert evaluate("fixtures / 4", fixtures=8) == 2


@pytest.mark.parametrize("bad", ["__import__('os')", "n.real", "open('x')", "lambda: 1", "m ** 1000", "q + 1", "1 / 0", ""])
def test_unsafe_or_invalid_formulas_rejected(bad):
    with pytest.raises(FormulaError):
        validate(bad)


def test_deflection_and_bends():
    pts = [(0, 0), (10, 0), (10, 10), (20, 20), (30, 20.01)]
    angles = [round(a) for _, a in deflection_angles(pts)]
    assert angles == [90, 45, 45]
    assert len(bends(pts, 67.5, 95)) == 1
    assert len(bends(pts, 22.5, 67.5)) == 2
    assert bends([(0, 0), (10, 0), (20, 0.1)]) == []  # wobble, not a bend


def test_connections_and_branches():
    main = RunShape(1, [(0, 0), (100, 0), (100, 100)], 1, 100, False)
    branch = RunShape(2, [(50, 60), (50, 2)], 1, 100, False)  # ends on main mid-segment
    tail = RunShape(3, [(100, 100), (100, 200)], 1, 100, False)  # continues from main's end
    riser = RunShape(4, [(0, 0)], 1, 100, True)
    conns = {(c.run_id, c.end): c for c in end_connections([main, branch, tail, riser], {9: (50, 70)})}
    assert conns[(2, "end")].to_kind == "run" and conns[(2, "end")].to_id == 1 and not conns[(2, "end")].at_vertex
    assert conns[(2, "start")].to_kind == "count" and conns[(2, "start")].to_id == 9
    assert conns[(1, "start")].to_kind == "riser"
    assert conns[(1, "end")].to_kind == "run" and conns[(1, "end")].to_id == 3
    assert conns[(3, "end")].to_kind == "none"
    assert branch_connections([main, branch, tail]) == [(2, 1, "end")]


def test_overlap():
    a = RunShape(1, [(0, 0), (100, 0)], 1, 100, False)
    b = RunShape(2, [(10, 1), (90, 1)], 1, 100, False)
    c = RunShape(3, [(0, 50), (100, 50)], 1, 100, False)
    assert overlap_fraction(a, b) == pytest.approx(1.0)
    assert overlap_fraction(a, c) == 0
