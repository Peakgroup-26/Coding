import { useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { CountItem, LineStyle, Run, Sheet } from "../types";

type Assign = { service_id: number; dn: number; material: string; on: boolean };

/** Suggest runs from line styles and counts from a symbol. Everything it creates starts as suggested. */
export function AiAssist({ sheet, runs, counts, selectedCount, onChanged, onHighlight, onError }: {
  sheet: Sheet; runs: Run[]; counts: CountItem[]; selectedCount?: CountItem;
  onChanged: () => void; onHighlight: (bbox: [number, number, number, number] | null) => void; onError: (e: unknown) => void;
}) {
  const { settings } = useApp();
  const [styles, setStyles] = useState<LineStyle[] | null>(null);
  const [assign, setAssign] = useState<Record<string, Assign>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [threshold, setThreshold] = useState(0.75);
  const [box, setBox] = useState(24);

  const pendingRuns = runs.filter((r) => r.status === "suggested").length;
  const pendingCounts = counts.filter((c) => c.status === "suggested").length;

  const loadStyles = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await api.get<{ styles: LineStyle[] }>(`/api/sheets/${sheet.id}/line-styles`);
      setStyles(r.styles);
      const a: Record<string, Assign> = {};
      for (const s of r.styles) {
        a[s.key] = s.mapping ? { ...s.mapping, on: true } : { service_id: 0, dn: 100, material: settings.materials[0]?.name ?? "", on: false };
      }
      setAssign(a);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const suggestRuns = async () => {
    const chosen = Object.entries(assign).filter(([, a]) => a.on && a.service_id);
    if (!chosen.length) { setMsg("Tick at least one line style and choose its service."); return; }
    setBusy(true); setMsg("");
    try {
      const r = await api.post<{ created: number; skipped_overlapping: number; skipped_short: number; skipped_viewport_edge: number }>(
        `/api/sheets/${sheet.id}/suggest-runs`,
        { styles: chosen.map(([key, a]) => ({ key, service_id: a.service_id, dn: a.dn, material: a.material })), remember: true });
      setMsg(`${r.created} suggested run(s). Skipped ${r.skipped_overlapping} already measured, ${r.skipped_short} too short` +
        (r.skipped_viewport_edge ? `, ${r.skipped_viewport_edge} crossing a detail viewport` : "") + ".");
      onChanged();
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const findSymbols = async () => {
    if (!selectedCount) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.post<{ created: number; matches: number }>(`/api/sheets/${sheet.id}/suggest-counts`,
        { count_id: selectedCount.id, threshold, box_pt: box });
      setMsg(`${r.created} new suggested ${selectedCount.item_type}(s) from ${r.matches} match(es).`);
      onChanged();
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const bulk = async (action: "accept" | "reject") => {
    if (action === "reject" && !window.confirm(`Reject all ${pendingRuns + pendingCounts} suggestions on this sheet?`)) return;
    try { await api.post(`/api/sheets/${sheet.id}/suggestions/${action}`, { kind: "all" }); onChanged(); }
    catch (e) { onError(e); }
  };

  const set = (key: string, patch: Partial<Assign>) => setAssign({ ...assign, [key]: { ...assign[key], ...patch } });

  return (
    <section>
      <h3>Suggest</h3>
      {(pendingRuns > 0 || pendingCounts > 0) && (
        <div className="row wrap">
          <span className="warn small">{pendingRuns} run(s) and {pendingCounts} count(s) waiting for review (dashed)</span>
          <button onClick={() => bulk("accept")}>Accept all</button>
          <button className="danger" onClick={() => bulk("reject")}>Reject all</button>
        </div>
      )}
      <p className="muted small">Suggestions are dashed and stay out of totals and pricing until confirmed. Check each one before accepting.</p>

      <div className="row wrap">
        <button disabled={busy || !sheet.has_vectors} onClick={loadStyles}>Line styles on this sheet</button>
        {!sheet.has_vectors && <span className="muted small">No vector line work (scanned sheet)</span>}
      </div>
      {styles && (
        <>
          <p className="muted small">Tick the styles that are pipework and say what each one is. Hover to see where it's drawn. Choices are remembered for this client.</p>
          <ul className="items styles">
            {styles.slice(0, 40).map((s) => {
              const a = assign[s.key];
              return (
                <li key={s.key} onMouseEnter={() => onHighlight(s.bbox)} onMouseLeave={() => onHighlight(null)}>
                  <input type="checkbox" checked={a.on} onChange={(e) => set(s.key, { on: e.target.checked })} />
                  <span className="line-sample" style={{ borderTopColor: s.colour, borderTopStyle: s.dashes === "solid" ? "solid" : "dashed", borderTopWidth: Math.max(1, Math.min(4, s.width * 1.5)) }} />
                  <span className="small style-meta">
                    {s.length_m !== null ? `${s.length_m} m` : `${Math.round(s.length_pt)} pt`} · {s.segments} seg{s.layer && ` · ${s.layer}`}
                  </span>
                  {a.on && (
                    <span className="style-assign">
                      <select value={a.service_id} onChange={(e) => set(s.key, { service_id: Number(e.target.value) })}>
                        <option value={0}>Service…</option>
                        {settings.services.filter((x) => x.active).map((x) => <option key={x.id} value={x.id}>{x.code}</option>)}
                      </select>
                      <input className="tiny" type="number" value={a.dn} onChange={(e) => set(s.key, { dn: Number(e.target.value) })} title="DN" />
                      <select value={a.material} onChange={(e) => set(s.key, { material: e.target.value })}>
                        {settings.materials.filter((m) => m.active).map((m) => <option key={m.id}>{m.name}</option>)}
                      </select>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          <button className="primary" disabled={busy || !sheet.scale_verified} onClick={suggestRuns}>Suggest runs</button>
          {!sheet.scale_verified && <span className="warn small"> Verify the scale first.</span>}
        </>
      )}

      <div className="row wrap" style={{ marginTop: 8 }}>
        <button disabled={busy || !selectedCount} onClick={findSymbols}>
          {selectedCount ? `Find more ${selectedCount.item_type} symbols like this one` : "Select a counted symbol to find similar ones"}
        </button>
        {selectedCount && (
          <>
            <label className="inline small">match<input className="tiny" type="number" step={0.05} min={0.4} max={0.99} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} /></label>
            <label className="inline small">box pt<input className="tiny" type="number" min={6} max={200} value={box} onChange={(e) => setBox(Number(e.target.value))} /></label>
          </>
        )}
      </div>
      {msg && <p className="ok small">{msg}</p>}
    </section>
  );
}
