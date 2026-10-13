"""Geometry on one sheet: how runs, risers and counted items connect.

All coordinates are sheet points. Tolerances are in points on the page (1 pt = 0.35 mm),
so they are the same whatever the drawing scale.
"""
import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point

END_TOLERANCE_PT = 6.0  # ~2 mm on paper: a run end this close to something is connected
FIXTURE_TOLERANCE_PT = 20.0  # ~7 mm: fixture symbols are larger than the point clicked
MIN_BEND_DEG = 5.0  # smaller deflections are drafting wobble, not fittings


def deflection_angles(points) -> list[tuple[int, float]]:
    """(vertex index, change of direction in degrees) for each interior vertex."""
    out = []
    for i in range(1, len(points) - 1):
        a, b, c = points[i - 1], points[i], points[i + 1]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        out.append((i, math.degrees(math.acos(cos))))
    return out


def bends(points, angle_min: float = MIN_BEND_DEG, angle_max: float = 180.0) -> list[tuple[int, float]]:
    return [(i, a) for i, a in deflection_angles(points) if a >= MIN_BEND_DEG and angle_min <= a <= angle_max]


@dataclass
class RunShape:
    id: int
    points: list
    service_id: int
    dn: int
    is_point: bool  # a riser/drop with no plan length

    @property
    def line(self):
        return Point(self.points[0]) if self.is_point else LineString(self.points)

    @property
    def start(self):
        return self.points[0]

    @property
    def end(self):
        return self.points[-1]


@dataclass
class Connection:
    run_id: int
    end: str  # "start" | "end"
    to_kind: str  # run | riser | count | none
    to_id: int | None
    at_vertex: bool  # True if it meets the other run at one of its vertices/ends (not mid-segment)
    to_end: str | None = None  # when it meets another run's start or end


def _near_vertex(p, pts, tol):
    for idx, q in enumerate(pts):
        if math.hypot(p[0] - q[0], p[1] - q[1]) <= tol:
            return idx
    return None


def end_connections(runs: list[RunShape], count_points: dict[int, tuple[float, float]]) -> list[Connection]:
    """What each run end touches. A run end can touch several things; the first match wins in
    this order: another run, a riser, a counted item. Runs and risers only connect within the
    same service (a drain doesn't join a water pipe); counted items connect to any service."""
    out = []
    lines = [r for r in runs if not r.is_point]
    risers = [r for r in runs if r.is_point]
    for r in lines:
        for which, p in (("start", r.start), ("end", r.end)):
            pt = Point(p)
            conn = None
            for o in lines:
                if o.id == r.id or o.service_id != r.service_id:
                    continue
                if o.line.distance(pt) <= END_TOLERANCE_PT:
                    vi = _near_vertex(p, o.points, END_TOLERANCE_PT)
                    to_end = None
                    if vi == 0:
                        to_end = "start"
                    elif vi == len(o.points) - 1:
                        to_end = "end"
                    conn = Connection(r.id, which, "run", o.id, vi is not None, to_end)
                    break
            if conn is None:
                for o in risers:
                    if o.service_id == r.service_id and o.line.distance(pt) <= END_TOLERANCE_PT:
                        conn = Connection(r.id, which, "riser", o.id, True)
                        break
            if conn is None:
                for cid, cp in count_points.items():
                    if math.hypot(p[0] - cp[0], p[1] - cp[1]) <= FIXTURE_TOLERANCE_PT:
                        conn = Connection(r.id, which, "count", cid, True)
                        break
            out.append(conn or Connection(r.id, which, "none", None, False))
    return out


def branch_connections(runs: list[RunShape]) -> list[tuple[int, int, str]]:
    """(branch run id, main run id, which end of the branch) where a run end joins another run
    part-way along it, or at an interior vertex. End-to-end joins are not branches."""
    out = []
    lines = [r for r in runs if not r.is_point]
    for r in lines:
        for which, p in (("start", r.start), ("end", r.end)):
            pt = Point(p)
            for o in lines:
                if o.id == r.id or o.service_id != r.service_id or o.line.distance(pt) > END_TOLERANCE_PT:
                    continue
                vi = _near_vertex(p, o.points, END_TOLERANCE_PT)
                if vi in (0, len(o.points) - 1):
                    continue  # end to end: a straight coupling or a bend, not a junction
                out.append((r.id, o.id, which))
                break
    return out


def runs_near(runs: list[RunShape], p, tol=FIXTURE_TOLERANCE_PT) -> list[RunShape]:
    pt = Point(p)
    return [r for r in runs if r.line.distance(pt) <= tol]


def overlap_fraction(a: RunShape, b: RunShape, tol=END_TOLERANCE_PT) -> float:
    """Share of the shorter run that lies within tol of the other."""
    if a.is_point or b.is_point:
        return 0.0
    la, lb = a.line, b.line
    short, other = (la, lb) if la.length <= lb.length else (lb, la)
    if short.length < 1e-6:
        return 0.0
    return short.intersection(other.buffer(tol)).length / short.length
