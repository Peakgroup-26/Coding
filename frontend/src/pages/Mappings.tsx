import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Mapping } from "../types";

const KIND = { pipe: "Pipe (per metre)", count: "Counted item", fitting: "Fitting / sundry" };

export default function Mappings() {
  const [rows, setRows] = useState<Mapping[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => api.get<Mapping[]>("/api/mappings").then(setRows), []);
  useEffect(() => { load(); }, [load]);
  const del = async (m: Mapping) => {
    if (!window.confirm("Delete this mapping? Items it priced become unmapped on every job that isn't final.")) return;
    try { await api.del(`/api/mappings/${m.id}`); load(); } catch (e) { setError((e as Error).message); }
  };
  const save = async (m: Mapping, patch: Partial<Mapping>) => {
    try { await api.put(`/api/mappings/${m.id}`, { ...m, ...patch }); load(); } catch (e) { setError((e as Error).message); }
  };
  const f = filter.toLowerCase();
  const shown = rows.filter((m) => !f || JSON.stringify(m).toLowerCase().includes(f));
  return (
    <main className="page">
      <h1>Price mappings</h1>
      <p className="muted small">
        How take-off items are priced: each maps to a prebuild or catalogue code by code, so mappings carry across price-book
        versions. Add them from a job's Pricing tab, where unmapped items are listed. A mapping for a specific service beats one for any service.
      </p>
      {error && <p className="error">{error}</p>}
      <section className="card">
        <input placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <table>
          <thead><tr><th>Source</th><th>Service</th><th>Matches</th><th>Priced as</th><th>Code</th><th>× per unit</th><th></th></tr></thead>
          <tbody>
            {shown.map((m) => (
              <tr key={m.id}>
                <td className="small">{KIND[m.source_kind]}</td>
                <td>{m.service_code || <span className="muted">any</span>}</td>
                <td>{m.source_kind === "pipe" ? `${m.material} DN${m.dn}` : m.source_kind === "count" ? m.item_type : m.description}</td>
                <td>{m.target_kind === "prebuild" ? "Prebuild" : "Catalogue item"}</td>
                <td><EditText v={m.target_code} onSave={(target_code) => save(m, { target_code })} /></td>
                <td><EditText v={String(m.factor)} onSave={(v) => save(m, { factor: Number(v) || 1 })} /></td>
                <td><button className="link" onClick={() => del(m)}>Delete</button></td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={7} className="muted">No mappings.</td></tr>}
          </tbody>
        </table>
      </section>
    </main>
  );
}

function EditText({ v, onSave }: { v: string; onSave: (v: string) => void }) {
  const [val, setVal] = useState(v);
  useEffect(() => setVal(v), [v]);
  return <input className="cell" value={val} onChange={(e) => setVal(e.target.value)} onBlur={() => val !== v && onSave(val)}
    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />;
}
