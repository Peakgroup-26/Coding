"""Local suggestion tools. Nothing here leaves the server.

- Line styles: vector line work grouped by colour, dash pattern, width and CAD layer. Once a
  style is assigned to a service/size/material, its connected segments become suggested runs.
- Symbol matching: given one counted symbol, find others like it on the rendered sheet.

Everything created here is status "suggested", source "ai", and stays out of totals and
pricing until someone confirms it.
"""
import json
import math
from collections import defaultdict

import pymupdf

from . import storage
from .geometry import MIN_BEND_DEG, deflection_angles
from .models import Sheet

SNAP_PT = 1.0  # segment ends closer than this are the same point
GAP_PT = 4.0  # bridge gaps this small between aligned pieces (dash patterns exploded by CAD)
MAX_SEGMENTS = 200_000


def _hex(c) -> str:
    if not c:
        return "none"
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c[:3])


def style_key(colour: str, dashes: str, width: float, layer: str) -> str:
    return f"{colour}|{dashes or 'solid'}|{width:.2f}|{layer or ''}"


def extract_segments(sheet: Sheet) -> dict:
    """{style key: {colour, dashes, width, layer, segments: [[x1, y1, x2, y2], ...]}}, cached per sheet."""
    cache_key = sheet.image_key.replace(".png", "-segments.json")
    p = storage.local_path(cache_key)
    if p.exists():
        return json.loads(p.read_text())
    doc = pymupdf.open(storage.local_path(sheet.file.storage_key))
    page = doc[sheet.page_no - 1]
    mat = page.rotation_matrix
    styles: dict[str, dict] = {}
    n = 0
    for dr in page.get_drawings():
        colour = _hex(dr.get("color"))
        if colour == "none":
            continue  # fill only (hatching, solid symbols)
        dashes = (dr.get("dashes") or "").strip()
        if dashes in ("[] 0", "[] 0.0", ""):
            dashes = "solid"
        width = float(dr.get("width") or 0)
        layer = dr.get("layer") or ""
        key = style_key(colour, dashes, width, layer)
        st = styles.setdefault(key, {"colour": colour, "dashes": dashes, "width": round(width, 2), "layer": layer, "segments": []})
        for item in dr.get("items", []):
            if item[0] == "l":
                a, b = pymupdf.Point(item[1]) * mat, pymupdf.Point(item[2]) * mat
            elif item[0] == "c":  # curve: treat as a straight piece between its ends
                a, b = pymupdf.Point(item[1]) * mat, pymupdf.Point(item[4]) * mat
            else:
                continue
            if math.hypot(b.x - a.x, b.y - a.y) < 0.5:
                continue
            st["segments"].append([round(a.x, 2), round(a.y, 2), round(b.x, 2), round(b.y, 2)])
            n += 1
            if n >= MAX_SEGMENTS:
                break
    doc.close()
    styles = {k: v for k, v in styles.items() if v["segments"]}
    storage.save_bytes(cache_key, json.dumps(styles).encode())
    return styles


def style_summary(styles: dict, m_per_pt: float | None) -> list[dict]:
    out = []
    for key, st in styles.items():
        length_pt = sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in st["segments"])
        xs = [v for s in st["segments"] for v in (s[0], s[2])]
        ys = [v for s in st["segments"] for v in (s[1], s[3])]
        out.append({"key": key, "colour": st["colour"], "dashes": st["dashes"], "width": st["width"], "layer": st["layer"],
                    "segments": len(st["segments"]), "length_pt": round(length_pt, 1),
                    "length_m": round(length_pt * m_per_pt, 1) if m_per_pt else None,
                    "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    out.sort(key=lambda s: -s["length_pt"])
    return out


def _node(x: float, y: float) -> tuple[int, int]:
    return (round(x / SNAP_PT), round(y / SNAP_PT))


def _simplify(pts: list) -> list:
    """Drop vertices that don't change direction, so bend counting sees only real bends."""
    if len(pts) < 3:
        return pts
    keep = [pts[0]]
    for (i, angle) in deflection_angles(pts):
        if angle >= MIN_BEND_DEG:
            keep.append(pts[i])
    keep.append(pts[-1])
    # Collapse duplicates
    out = [keep[0]]
    for p in keep[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def chain_segments(segments: list[list[float]]) -> list[list[list[float]]]:
    """Join segments into polylines. Chains run through points where exactly two segments
    meet and break at ends and junctions (where a branch joins), so each polyline is one run."""
    adj: dict[tuple, list[int]] = defaultdict(list)
    for i, s in enumerate(segments):
        adj[_node(s[0], s[1])].append(i)
        adj[_node(s[2], s[3])].append(i)
    used = [False] * len(segments)

    def other_end(i, node):
        s = segments[i]
        a, b = _node(s[0], s[1]), _node(s[2], s[3])
        return (b, [s[2], s[3]]) if a == node else (a, [s[0], s[1]])

    def walk(start_node, start_pt, first_seg):
        pts = [start_pt]
        node, i = start_node, first_seg
        while True:
            used[i] = True
            node, pt = other_end(i, node)
            pts.append(pt)
            nxt = [j for j in adj[node] if not used[j]]
            if len(adj[node]) != 2 or not nxt:
                return pts
            i = nxt[0]

    lines = []
    # Start from ends and junctions first, then any closed loops left over.
    for node, segs in list(adj.items()):
        if len(segs) != 2:
            for i in segs:
                if not used[i]:
                    s = segments[i]
                    start_pt = [s[0], s[1]] if _node(s[0], s[1]) == node else [s[2], s[3]]
                    lines.append(walk(node, start_pt, i))
    for i, s in enumerate(segments):
        if not used[i]:
            lines.append(walk(_node(s[0], s[1]), [s[0], s[1]], i))
    return _bridge_gaps([_simplify(l) for l in lines])


def _direction(a, b):
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d else (0.0, 0.0)


def _bridge_gaps(lines: list[list]) -> list[list]:
    """Join polylines whose ends are a small gap apart and pointing the same way (exploded dashes)."""
    changed = True
    while changed:
        changed = False
        for i in range(len(lines)):
            if not lines[i]:
                continue
            a = lines[i]
            for j in range(len(lines)):
                if i == j or not lines[j]:
                    continue
                b = lines[j]
                for b_rev in (False, True):
                    bb = b[::-1] if b_rev else b
                    gap = math.hypot(bb[0][0] - a[-1][0], bb[0][1] - a[-1][1])
                    if gap > GAP_PT:
                        continue
                    da = _direction(a[-2], a[-1]) if len(a) > 1 else None
                    db = _direction(bb[0], bb[1]) if len(bb) > 1 else None
                    if da and db and da[0] * db[0] + da[1] * db[1] < math.cos(math.radians(15)):
                        continue
                    lines[i] = _simplify(a + (bb[1:] if gap < 1e-6 else bb))
                    lines[j] = []
                    changed = True
                    break
                if changed:
                    break
            if changed:
                break
    return [l for l in lines if len(l) > 1]


def match_symbols(image_path: str, sheet: Sheet, x_pt: float, y_pt: float, box_pt: float = 24.0,
                  threshold: float = 0.75, max_results: int = 300) -> list[tuple[float, float, float]]:
    """Find symbols like the one centred at (x_pt, y_pt). Returns (x, y, score) in sheet points."""
    import cv2
    import numpy as np

    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Couldn't read the sheet image")
    k = sheet.image_width_px / sheet.width_pt  # px per pt
    half = max(4, int(box_pt * k / 2))
    cx, cy = int(x_pt * k), int(y_pt * k)
    if cx - half < 0 or cy - half < 0 or cx + half > img.shape[1] or cy + half > img.shape[0]:
        raise ValueError("The example symbol is too close to the edge of the sheet")
    tpl = img[cy - half:cy + half, cx - half:cx + half]
    if float(tpl.std()) < 8:
        raise ValueError("There's nothing to match at that spot. Click on the symbol itself.")

    best = np.full((img.shape[0] - tpl.shape[0] + 1, img.shape[1] - tpl.shape[1] + 1), -1.0, dtype=np.float32)
    for rot in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        t = tpl if rot is None else cv2.rotate(tpl, rot)
        res = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        best = np.maximum(best, res[:best.shape[0], :best.shape[1]])

    out = []
    work = best.copy()
    for _ in range(max_results):
        _, score, _, loc = cv2.minMaxLoc(work)
        if score < threshold:
            break
        px, py = loc[0] + half, loc[1] + half
        out.append((px / k, py / k, float(score)))
        x0, y0 = max(0, loc[0] - half), max(0, loc[1] - half)
        work[y0:loc[1] + half + 1, x0:loc[0] + half + 1] = -1.0  # suppress this match's neighbourhood
    return out
