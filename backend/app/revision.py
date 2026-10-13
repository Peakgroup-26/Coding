"""Revision compare: what changed between two revisions of a sheet, and which measurements it touches.

Vector sheets are compared line by line (per colour); scanned sheets fall back to an image diff.
Both sheets are assumed to share a page frame; an offset (dx, dy) in points can be given when
the new revision has shifted.
"""
import math
from collections import defaultdict

from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import unary_union

from . import storage
from .models import CountItem, Run, Sheet
from .suggest import chain_segments, extract_segments

TOL_PT = 1.5  # line work within this distance is "the same line"
MIN_PIECE_PT = 3.0  # ignore slivers shorter than this
CLUSTER_PT = 30.0  # changes this close together are reported as one region
AFFECTED_FRACTION = 0.2


def _by_colour(styles: dict, dx=0.0, dy=0.0) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for st in styles.values():
        for s in st["segments"]:
            out[st["colour"]].append([s[0] + dx, s[1] + dy, s[2] + dx, s[3] + dy])
    return out


def _pieces(geom) -> list[list]:
    if geom.is_empty:
        return []
    parts = geom.geoms if hasattr(geom, "geoms") else [geom]
    out = []
    for g in parts:
        if isinstance(g, LineString) and g.length >= MIN_PIECE_PT:
            cs = list(g.coords)
            out += [[cs[i][0], cs[i][1], cs[i + 1][0], cs[i + 1][1]] for i in range(len(cs) - 1)]
    return out


def _difference(a_segs: list, b_segs: list) -> list:
    """Parts of a's line work not within TOL of b's."""
    if not a_segs:
        return []
    a = MultiLineString([((s[0], s[1]), (s[2], s[3])) for s in a_segs])
    if not b_segs:
        return _pieces(a)
    b = unary_union([LineString([(s[0], s[1]), (s[2], s[3])]) for s in b_segs]).buffer(TOL_PT)
    return _pieces(a.difference(b))


def _regions(polylines: list[dict]) -> list[list[float]]:
    """Group nearby changes into bounding boxes to step through."""
    boxes = []
    for p in polylines:
        xs = [q[0] for q in p["points"]]
        ys = [q[1] for q in p["points"]]
        boxes.append([min(xs), min(ys), max(xs), max(ys)])
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] - CLUSTER_PT <= b[2] and b[0] - CLUSTER_PT <= a[2] and a[1] - CLUSTER_PT <= b[3] and b[1] - CLUSTER_PT <= a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    merged = True
                    break
            if merged:
                break
    return [[round(v, 1) for v in b] for b in boxes]


def vector_diff(old: Sheet, new: Sheet, dx=0.0, dy=0.0) -> dict:
    old_c = _by_colour(extract_segments(old), dx, dy)
    new_c = _by_colour(extract_segments(new))
    added, removed = [], []
    for colour in set(old_c) | set(new_c):
        for pts in chain_segments(_difference(new_c.get(colour, []), old_c.get(colour, []))):
            added.append({"colour": colour, "points": pts})
        for pts in chain_segments(_difference(old_c.get(colour, []), new_c.get(colour, []))):
            # Old line work was shifted by (dx, dy), so removed lines are already in the new sheet's frame.
            removed.append({"colour": colour, "points": pts})
    return {"method": "vector", "added": added, "removed": removed}


def raster_diff(old: Sheet, new: Sheet, dx=0.0, dy=0.0) -> dict:
    import cv2
    import numpy as np

    a = cv2.imread(str(storage.local_path(old.image_key)), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(storage.local_path(new.image_key)), cv2.IMREAD_GRAYSCALE)
    k = new.image_width_px / new.width_pt
    a = cv2.resize(a, (b.shape[1], b.shape[0]))
    if dx or dy:
        a = cv2.warpAffine(a, np.float32([[1, 0, dx * k], [0, 1, dy * k]]), (b.shape[1], b.shape[0]), borderValue=255)
    out = {"method": "image", "added": [], "removed": []}
    for name, mask in (("added", cv2.subtract(a, b)), ("removed", cv2.subtract(b, a))):  # darker in new = added
        _, m = cv2.threshold(mask, 60, 255, cv2.THRESH_BINARY)
        m = cv2.dilate(m, np.ones((5, 5), np.uint8), iterations=2)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w * h < 40:
                continue
            x0, y0, x1, y1 = x / k, y / k, (x + w) / k, (y + h) / k
            out[name].append({"colour": "#000000", "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]})
    return out


def compare(db, old: Sheet, new: Sheet, dx=0.0, dy=0.0) -> dict:
    result = vector_diff(old, new, dx, dy) if (old.has_vectors and new.has_vectors) else raster_diff(old, new, dx, dy)
    removed_lines = [LineString(p["points"]) for p in result["removed"] if len(p["points"]) > 1]
    removed_zone = unary_union(removed_lines).buffer(3.0) if removed_lines else None
    added_lines = [LineString(p["points"]) for p in result["added"] if len(p["points"]) > 1]
    added_zone = unary_union(added_lines).buffer(3.0) if added_lines else None

    affected = []
    for r in db.query(Run).filter(Run.sheet_id == old.id):
        if len(r.geometry) < 2:
            pt = box(r.geometry[0][0] + dx - 3, r.geometry[0][1] + dy - 3, r.geometry[0][0] + dx + 3, r.geometry[0][1] + dy + 3)
            hit = removed_zone is not None and removed_zone.intersects(pt)
            frac = 1.0 if hit else 0.0
        else:
            line = LineString([(x + dx, y + dy) for x, y in r.geometry])
            frac = line.intersection(removed_zone).length / line.length if removed_zone is not None and line.length else 0.0
        if frac >= AFFECTED_FRACTION:
            affected.append({"run_id": r.id, "fraction": round(frac, 2)})
    affected_counts = []
    if removed_zone is not None:
        for c in db.query(CountItem).filter(CountItem.sheet_id == old.id):
            if removed_zone.contains(box(c.x + dx - 1, c.y + dy - 1, c.x + dx + 1, c.y + dy + 1)):
                affected_counts.append(c.id)

    total = lambda ps: round(sum(sum(math.hypot(p["points"][i + 1][0] - p["points"][i][0], p["points"][i + 1][1] - p["points"][i][1])
                                     for i in range(len(p["points"]) - 1)) for p in ps), 1)
    result.update({
        "old_sheet_id": old.id, "new_sheet_id": new.id, "old_revision": old.revision, "new_revision": new.revision,
        "dx": dx, "dy": dy,
        "regions": _regions(result["added"] + result["removed"]),
        "added_length_pt": total(result["added"]), "removed_length_pt": total(result["removed"]),
        "affected_runs": affected, "affected_counts": affected_counts,
        "unmeasured_new_work": bool(added_zone is not None and not any(
            LineString(r.geometry).intersects(added_zone) for r in db.query(Run).filter(Run.sheet_id == new.id) if len(r.geometry) > 1)),
    })
    return result
