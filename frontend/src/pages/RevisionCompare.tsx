import { Line, Rect } from "react-konva";
import type { Pt } from "../types";

export interface Diff {
  method: "vector" | "image";
  old_revision: string; new_revision: string; old_sheet_id: number;
  added: { colour: string; points: Pt[] }[];
  removed: { colour: string; points: Pt[] }[];
  regions: [number, number, number, number][];
  added_length_pt: number; removed_length_pt: number;
  affected_runs: { run_id: number; fraction: number }[];
  affected_counts: number[];
  unmeasured_new_work: boolean;
}

/** Konva shapes for a revision diff: added line work green, removed red dashed, regions boxed. */
export function DiffOverlay({ diff, scale }: { diff: Diff; scale: number }) {
  const w = 3 / scale;
  return (
    <>
      {diff.regions.map((r, i) => (
        <Rect key={`r${i}`} x={r[0] - 8} y={r[1] - 8} width={r[2] - r[0] + 16} height={r[3] - r[1] + 16}
          stroke="#d08000" strokeWidth={1.5 / scale} dash={[6 / scale, 4 / scale]} listening={false} />
      ))}
      {diff.removed.map((p, i) => (
        <Line key={`d${i}`} points={p.points.flat()} stroke="#c42b2b" strokeWidth={w} dash={[8 / scale, 5 / scale]}
          opacity={0.9} listening={false} lineCap="round" />
      ))}
      {diff.added.map((p, i) => (
        <Line key={`a${i}`} points={p.points.flat()} stroke="#1f9a4a" strokeWidth={w} opacity={0.9} listening={false} lineCap="round" />
      ))}
    </>
  );
}

export const SHORTCUTS: [string, string][] = [
  ["T", "Trace a run: click points, double-click or Enter to finish"],
  ["Backspace", "Remove the last traced point"],
  ["Shift", "Lock the trace to 45° steps"],
  ["N", "Count"],
  ["R", "Riser or drop"],
  ["K", "Calibrate the scale"],
  ["H / Esc", "Pan and select (Esc also cancels a trace)"],
  ["[ / ]", "Previous / next service"],
  ["S", "Snapping on or off"],
  ["F", "Fit the sheet to the window"],
  ["Space + drag", "Pan"],
  ["Scroll", "Zoom"],
  ["Del", "Delete the selected item"],
  ["?", "Show or hide this list"],
];

export function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="card" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2>Keyboard shortcuts</h2><span className="spacer" /><button onClick={onClose}>Close</button></div>
        <table>
          <tbody>{SHORTCUTS.map(([k, v]) => <tr key={k}><td><kbd>{k}</kbd></td><td>{v}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
