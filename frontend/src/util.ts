import type { Pt } from "./types";

export const fmtM = (m: number) => m.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const dist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);

export const polyLength = (pts: Pt[]) => pts.slice(1).reduce((s, p, i) => s + dist(pts[i], p), 0);

/** Grid index over vector line ends, for snapping. Coordinates in PDF points. */
export class SnapIndex {
  private cells = new Map<string, Pt[]>();
  constructor(points: Pt[], private cell = 20) {
    for (const p of points) {
      const k = this.key(p[0], p[1]);
      const arr = this.cells.get(k);
      if (arr) arr.push(p); else this.cells.set(k, [p]);
    }
  }
  private key(x: number, y: number) { return `${Math.floor(x / this.cell)},${Math.floor(y / this.cell)}`; }
  nearest(p: Pt, radius: number): Pt | null {
    let best: Pt | null = null;
    let bestD = radius;
    const r = Math.ceil(radius / this.cell);
    const cx = Math.floor(p[0] / this.cell), cy = Math.floor(p[1] / this.cell);
    for (let i = -r; i <= r; i++) {
      for (let j = -r; j <= r; j++) {
        for (const q of this.cells.get(`${cx + i},${cy + j}`) ?? []) {
          const d = dist(p, q);
          if (d <= bestD) { bestD = d; best = q; }
        }
      }
    }
    return best;
  }
}

/** Constrain b to horizontal, vertical or 45° from a (hold Shift while tracing). */
export function ortho(a: Pt, b: Pt): Pt {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const ang = Math.atan2(dy, dx);
  const snap = Math.round(ang / (Math.PI / 4)) * (Math.PI / 4);
  const len = Math.hypot(dx, dy);
  return [a[0] + Math.cos(snap) * len, a[1] + Math.sin(snap) * len];
}
