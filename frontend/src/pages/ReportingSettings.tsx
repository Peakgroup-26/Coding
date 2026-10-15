import { useEffect, useRef, useState } from "react";
import { api, download, upload } from "../api";
import { useApp } from "../App";

interface Rate {
  id?: number; kind: string; service_code: string; dn_min: number | null; dn_max: number | null; material: string; item_type: string;
  civil_category: string; keyword: string; unit: string; hours_per_unit: number; note: string; active: boolean;
}
type Workforce = Record<string, unknown> & { headcount?: Record<string, number>; stock_lengths?: Record<string, number> };

const NUMBERS: [string, string, string][] = [
  ["hours_per_day", "Hours per day", "Productive hours a person works on site each day"],
  ["days_per_week", "Days per week", "5 = Monday to Friday"],
  ["apprentice_ratio", "Apprentices per plumber", "e.g. 0.5 = one apprentice for every two plumbers"],
  ["apprentice_productivity", "Apprentice output (0–1)", "An apprentice's output compared with a plumber's"],
  ["workers_per_supervisor", "People per supervisor", "One supervisor or leading hand per this many on site"],
  ["supervisor_from_crew", "Supervisor from crew of", "Smaller crews are led by a plumber"],
  ["pm_percent", "Project management %", "PM and admin hours as a % of field hours"],
  ["default_plumbers", "Default plumbers", "Crew used when a job has no target duration"],
];

const BLANK: Rate = { kind: "hydraulic", service_code: "", dn_min: null, dn_max: null, material: "", item_type: "", civil_category: "",
  keyword: "", unit: "", hours_per_unit: 0, note: "", active: true };

export default function ReportingSettings() {
  const { settings } = useApp();
  const [wf, setWf] = useState<Workforce | null>(null);
  const [rates, setRates] = useState<Rate[]>([]);
  const [form, setForm] = useState<Rate>(BLANK);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const file = useRef<HTMLInputElement>(null);

  const load = async () => {
    setWf(await api.get<Workforce>("/api/settings/workforce"));
    setRates(await api.get<Rate[]>("/api/productivity"));
  };
  useEffect(() => { load(); }, []);

  const saveWf = async () => {
    setError(""); setMsg("");
    try { setWf(await api.put<Workforce>("/api/settings/workforce", wf)); setMsg("Saved."); } catch (e) { setError((e as Error).message); }
  };
  const addRate = async () => {
    setError("");
    try { await api.post("/api/productivity", form); setForm({ ...BLANK, kind: form.kind }); load(); } catch (e) { setError((e as Error).message); }
  };
  const saveRate = async (r: Rate, patch: Partial<Rate>) => {
    try { await api.put(`/api/productivity/${r.id}`, { ...r, ...patch }); load(); } catch (e) { setError((e as Error).message); }
  };
  const importCsv = async (list: FileList | null) => {
    if (!list?.[0]) return;
    const fd = new FormData();
    fd.append("file", list[0]);
    try { const r = await upload<{ imported: number }>("/api/productivity/import", fd); setMsg(`Imported ${r.imported} rates.`); load(); }
    catch (e) { setError((e as Error).message); }
  };

  if (!wf) return <p>Loading…</p>;
  const set = (k: string, v: unknown) => setWf({ ...wf, [k]: v });
  const head = wf.headcount ?? {};
  const stock = wf.stock_lengths ?? {};
  const what = (r: Rate) => r.kind === "civil"
    ? [r.civil_category || "Any category", r.keyword && `"${r.keyword}"`, r.unit && `per ${r.unit}`].filter(Boolean).join(" · ")
    : r.item_type ? `${r.item_type} (each)` : [r.service_code, (r.dn_min || r.dn_max) && `DN${r.dn_min ?? ""}–${r.dn_max ?? ""}`, r.material, "per m"].filter(Boolean).join(" · ");

  return (
    <>
      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}
      <div className="admin-grid">
        <section className="card">
          <h2>Crew and program settings</h2>
          <div className="settings-grid">
            {NUMBERS.map(([k, label, help]) => (
              <label key={k} title={help}>{label}
                <input type="number" step="0.1" min={0} value={String(wf[k] ?? "")} onChange={(e) => set(k, Number(e.target.value))} />
              </label>
            ))}
            <label>Christmas shutdown from (MM-DD)<input value={String(wf.shutdown_from ?? "")} onChange={(e) => set("shutdown_from", e.target.value)} /></label>
            <label>to (MM-DD)<input value={String(wf.shutdown_to ?? "")} onChange={(e) => set("shutdown_to", e.target.value)} /></label>
          </div>
          <h3>Your people (for the workforce forecast)</h3>
          <div className="settings-grid">
            {["plumbers", "apprentices", "supervisors"].map((k) => (
              <label key={k}>{k[0].toUpperCase() + k.slice(1)}
                <input type="number" min={0} value={head[k] ?? 0} onChange={(e) => set("headcount", { ...head, [k]: Number(e.target.value) })} />
              </label>
            ))}
          </div>
          <h3>Pipe stock lengths (m)</h3>
          <div className="settings-grid">
            {settings.materials.filter((m) => m.active).map((m) => (
              <label key={m.id}>{m.name}
                <input type="number" min={1} step="0.5" value={stock[m.name] ?? wf.default_stock_length as number}
                       onChange={(e) => set("stock_lengths", { ...stock, [m.name]: Number(e.target.value) })} />
              </label>
            ))}
          </div>
          <button className="primary" onClick={saveWf}>Save settings</button>
        </section>

        <section className="card">
          <h2>Productivity rates (labour hours)</h2>
          <p className="small muted">
            Used for labour reports and programs where the price book has no labour for an item. Peak's own figures; none are built in.
            The most specific matching rate wins.
          </p>
          <div className="row wrap">
            <button onClick={() => download("/api/productivity.csv", "productivity-rates.csv")}>Download as CSV</button>
            <button onClick={() => file.current?.click()}>Import CSV</button>
            <input ref={file} type="file" accept=".csv" hidden onChange={(e) => importCsv(e.target.files)} />
            <span className="small muted">The download shows the column layout (docs/productivity-rates-template.csv has examples).</span>
          </div>
          <table>
            <thead><tr><th>Type</th><th>Applies to</th><th>Hours / unit</th><th>Note</th><th>In use</th><th></th></tr></thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.id} className={r.active ? "" : "inactive"}>
                  <td>{r.kind === "civil" ? "Civil" : "Plumbing"}</td>
                  <td className="small">{what(r)}</td>
                  <td><input className="tiny" type="number" step="0.01" min={0} defaultValue={r.hours_per_unit}
                             onBlur={(e) => Number(e.target.value) !== r.hours_per_unit && saveRate(r, { hours_per_unit: Number(e.target.value) })} /></td>
                  <td className="small muted">{r.note}</td>
                  <td><input type="checkbox" checked={r.active} onChange={(e) => saveRate(r, { active: e.target.checked })} /></td>
                  <td><button className="link danger" onClick={async () => { await api.del(`/api/productivity/${r.id}`); load(); }}>✕</button></td>
                </tr>
              ))}
              {rates.length === 0 && <tr><td colSpan={6} className="muted">No rates yet.</td></tr>}
            </tbody>
          </table>
          <h3>Add a rate</h3>
          <div className="row wrap">
            <select value={form.kind} onChange={(e) => setForm({ ...BLANK, kind: e.target.value })}>
              <option value="hydraulic">Plumbing</option><option value="civil">Civil</option>
            </select>
            {form.kind === "hydraulic" ? (
              <>
                <select value={form.service_code} onChange={(e) => setForm({ ...form, service_code: e.target.value, item_type: "" })}>
                  <option value="">Pipe of service…</option>
                  {settings.services.filter((s) => s.active).map((s) => <option key={s.code} value={s.code}>{s.code}</option>)}
                </select>
                <input className="tiny" type="number" placeholder="DN from" value={form.dn_min ?? ""} onChange={(e) => setForm({ ...form, dn_min: e.target.value ? Number(e.target.value) : null })} />
                <input className="tiny" type="number" placeholder="DN to" value={form.dn_max ?? ""} onChange={(e) => setForm({ ...form, dn_max: e.target.value ? Number(e.target.value) : null })} />
                <span className="muted">or item</span>
                <select value={form.item_type} onChange={(e) => setForm({ ...form, item_type: e.target.value, service_code: "" })}>
                  <option value="">—</option>
                  {settings.count_types.filter((c) => c.active).map((c) => <option key={c.id}>{c.name}</option>)}
                </select>
              </>
            ) : (
              <>
                <input placeholder="Category (blank = any)" value={form.civil_category} onChange={(e) => setForm({ ...form, civil_category: e.target.value })} />
                <input placeholder="Keyword, e.g. RCP" value={form.keyword} onChange={(e) => setForm({ ...form, keyword: e.target.value })} />
                <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
                  {["", "m", "m2", "m3", "ea", "t", "item"].map((u) => <option key={u} value={u}>{u || "any unit"}</option>)}
                </select>
              </>
            )}
            <input className="tiny" type="number" step="0.01" min={0} placeholder="hours" value={form.hours_per_unit || ""}
                   onChange={(e) => setForm({ ...form, hours_per_unit: Number(e.target.value) })} />
            <button onClick={addRate} disabled={!form.hours_per_unit}>Add</button>
          </div>
        </section>
      </div>
    </>
  );
}
