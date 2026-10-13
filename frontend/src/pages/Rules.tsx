import { useCallback, useEffect, useState } from "react";
import { api, download } from "../api";
import { useApp } from "../App";
import type { Rule, RuleCondition, Trigger } from "../types";

const TRIGGERS: { value: Trigger; label: string; vars: string; example: string }[] = [
  { value: "per_fixture", label: "Per fixture", vars: "n = 1 per fixture", example: "n" },
  { value: "per_metre", label: "Per metre of run", vars: "m = metres (plan + vertical, before waste), dn", example: "ceil(m / 1.2)" },
  { value: "per_bend", label: "Per change of direction", vars: "n = bends in the angle band, dn", example: "n" },
  { value: "per_branch", label: "Per branch connection", vars: "n = branches joining another run, dn", example: "n" },
  { value: "per_io", label: "Per IO requirement", vars: "n = IO locations, dn", example: "n" },
  { value: "per_job", label: "Per job (sundries)", vars: "m = total metres of matching runs, fixtures = fixture count", example: "ceil(m / 50)" },
];

const EMPTY: Omit<Rule, "id" | "version"> = {
  name: "", trigger_type: "per_metre", condition: {}, formula: "n", output_item_id: null,
  output_description: "", uom: "ea", stage_id: null, active: true,
};

export default function Rules() {
  const { user, settings } = useApp();
  const isAdmin = user.role === "admin";
  const [rules, setRules] = useState<Rule[]>([]);
  const [editing, setEditing] = useState<(Omit<Rule, "id" | "version"> & { id?: number }) | null>(null);
  const [disclaimer, setDisclaimer] = useState("");
  const [error, setError] = useState("");
  const [importMsg, setImportMsg] = useState("");

  const load = useCallback(() => api.get<Rule[]>("/api/rules").then(setRules), []);
  useEffect(() => {
    load();
    api.get<{ disclaimer: string }>("/api/rules/meta").then((m) => setDisclaimer(m.disclaimer));
  }, [load]);

  const save = async () => {
    if (!editing) return;
    setError("");
    const { id, ...body } = editing;
    try {
      if (id) await api.put(`/api/rules/${id}`, body);
      else await api.post("/api/rules", body);
      setEditing(null);
      load();
    } catch (e) { setError((e as Error).message); }
  };
  const remove = async (r: Rule) => {
    if (!window.confirm(`Delete rule "${r.name}"? Lines it generated stay on jobs until they are regenerated.`)) return;
    try { await api.del(`/api/rules/${r.id}`); load(); } catch (e) { setError((e as Error).message); }
  };
  const importCsv = async (files: FileList | null) => {
    if (!files?.[0]) return;
    setImportMsg(""); setError("");
    const fd = new FormData();
    fd.append("file", files[0]);
    try {
      const r = await api.post<{ created: number; updated: number; errors: { row: number; name: string; error: string }[] }>("/api/rules/import", fd);
      setImportMsg(`${r.created} added, ${r.updated} updated.`);
      if (r.errors.length) setError(r.errors.map((e) => `Row ${e.row} (${e.name}): ${e.error}`).join(" · "));
      load();
    } catch (e) { setError((e as Error).message); }
  };

  const stageName = (id: number | null) => settings.stages.find((s) => s.id === id)?.name ?? "Source's stage";

  return (
    <main className="page">
      <div className="row wrap">
        <h1>Fitting and sundry rules</h1>
        <span className="spacer" />
        <button onClick={() => download("/api/rules/export.csv", "peak_fitting_rules.csv")}>Export CSV</button>
        {isAdmin && (
          <label className="upload">
            <input type="file" accept=".csv,text/csv" onChange={(e) => { importCsv(e.target.files); e.target.value = ""; }} />
            <span className="button">Import CSV</span>
          </label>
        )}
        {isAdmin && <button className="primary" onClick={() => setEditing({ ...EMPTY })}>New rule</button>}
      </div>
      <p className="disclaimer">{disclaimer}</p>
      <p className="muted small">
        Rules are Peak's own allowances; none are built in. Import a CSV (export first to get the columns) or add them here.
        Each rule runs once per matching source: a fixture, a run, or the whole job.
      </p>
      {importMsg && <p className="ok">{importMsg}</p>}
      {error && <p className="error">{error}</p>}

      {editing && <RuleEditor rule={editing} onChange={setEditing} onSave={save} onCancel={() => { setEditing(null); setError(""); }} />}

      <section className="card">
        <table>
          <thead><tr><th>Rule</th><th>Trigger</th><th>Applies to</th><th>Quantity</th><th>Output</th><th>Stage</th><th>Active</th><th></th></tr></thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className={r.active ? "" : "closed"}>
                <td>{r.name}<div className="muted small">v{r.version}</div></td>
                <td className="small">{TRIGGERS.find((t) => t.value === r.trigger_type)?.label}</td>
                <td className="small">{describeCondition(r.trigger_type, r.condition)}</td>
                <td><code>{r.formula}</code></td>
                <td className="small">{r.output_description || r.name} <span className="muted">({r.uom})</span></td>
                <td className="small">{stageName(r.stage_id)}</td>
                <td>{r.active ? "Yes" : "No"}</td>
                <td className="actions">
                  {isAdmin && <>
                    <button className="link" onClick={() => setEditing({ ...r })}>Edit</button>
                    <button className="link" onClick={() => remove(r)}>Delete</button>
                  </>}
                </td>
              </tr>
            ))}
            {rules.length === 0 && <tr><td colSpan={8} className="muted">No rules yet.</td></tr>}
          </tbody>
        </table>
      </section>
    </main>
  );
}

function describeCondition(t: Trigger, c: RuleCondition): string {
  const parts: string[] = [];
  if (c.service_codes?.length) parts.push(c.service_codes.join(", "));
  if (c.materials?.length) parts.push(c.materials.join(", "));
  if (c.dn_min || c.dn_max) parts.push(`DN ${c.dn_min ?? "any"}–${c.dn_max ?? "any"}`);
  if (t === "per_fixture") parts.push(c.item_types?.length ? c.item_types.join(", ") : "all fixtures");
  if ((t === "per_bend" || (t === "per_io" && c.io_at_bends)) && (c.angle_min != null || c.angle_max != null))
    parts.push(`${c.angle_min ?? 0}°–${c.angle_max ?? 180}°`);
  if (t === "per_io") {
    const at = [c.io_at_ends && "free ends", c.io_at_bends && "bends", c.io_interval_m && `every ${c.io_interval_m} m`].filter(Boolean);
    parts.push(`IO at ${at.join(", ")}`);
  }
  return parts.join(" · ") || "everything";
}

type Draft = Omit<Rule, "id" | "version"> & { id?: number };

function RuleEditor({ rule, onChange, onSave, onCancel }: { rule: Draft; onChange: (r: Draft) => void; onSave: () => void; onCancel: () => void }) {
  const { settings } = useApp();
  const c = rule.condition;
  const t = rule.trigger_type;
  const setC = (patch: Partial<RuleCondition>) => onChange({ ...rule, condition: { ...c, ...patch } });
  const trig = TRIGGERS.find((x) => x.value === t)!;
  const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));
  const toggle = (list: string[] | undefined, v: string) => (list?.includes(v) ? list.filter((x) => x !== v) : [...(list ?? []), v]);

  return (
    <section className="card editor-card">
      <h2>{rule.id ? "Edit rule" : "New rule"}</h2>
      <div className="form-grid">
        <label>Name<input value={rule.name} onChange={(e) => onChange({ ...rule, name: e.target.value })} placeholder="e.g. SAN DN100 88° bends" /></label>
        <label>Trigger
          <select value={t} onChange={(e) => {
            const nt = e.target.value as Trigger;
            onChange({ ...rule, trigger_type: nt, formula: TRIGGERS.find((x) => x.value === nt)!.example });
          }}>
            {TRIGGERS.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
          </select>
        </label>
        <label>Quantity formula
          <input value={rule.formula} onChange={(e) => onChange({ ...rule, formula: e.target.value })} />
          <span className="hint">{trig.vars}. Use + − × ÷, ceil, floor, round, min, max.</span>
        </label>
        <label>Output item
          <input value={rule.output_description} onChange={(e) => onChange({ ...rule, output_description: e.target.value })}
            placeholder="e.g. {material} DN{dn} 88° bend" />
          <span className="hint">Fields: {"{dn} {material} {service}"}{t === "per_branch" && " {main_dn} {branch_dn}"}{t === "per_fixture" && " {item_type}"}</span>
        </label>
        <label>Unit<input value={rule.uom} onChange={(e) => onChange({ ...rule, uom: e.target.value })} /></label>
        <label>Stage
          <select value={rule.stage_id ?? ""} onChange={(e) => onChange({ ...rule, stage_id: Number(e.target.value) || null })}>
            <option value="">Same as the source run or fixture</option>
            {settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
      </div>

      <h3>Applies to</h3>
      <div className="chips">
        <span className="muted small">Services (none = all):</span>
        {settings.services.map((s) => (
          <button key={s.id} className={c.service_codes?.includes(s.code) ? "chip on" : "chip"} onClick={() => setC({ service_codes: toggle(c.service_codes, s.code) })}>{s.code}</button>
        ))}
      </div>
      {t !== "per_fixture" && (
        <>
          <div className="chips">
            <span className="muted small">Materials (none = all):</span>
            {settings.materials.map((m) => (
              <button key={m.id} className={c.materials?.includes(m.name) ? "chip on" : "chip"} onClick={() => setC({ materials: toggle(c.materials, m.name) })}>{m.name}</button>
            ))}
          </div>
          <div className="form-grid">
            <label>DN from<input type="number" value={c.dn_min ?? ""} onChange={(e) => setC({ dn_min: numOrNull(e.target.value) })} /></label>
            <label>DN to<input type="number" value={c.dn_max ?? ""} onChange={(e) => setC({ dn_max: numOrNull(e.target.value) })} /></label>
          </div>
        </>
      )}
      {t === "per_fixture" && (
        <div className="chips">
          <span className="muted small">Fixture types (none = all fixtures):</span>
          {settings.count_types.map((ct) => (
            <button key={ct.id} className={c.item_types?.includes(ct.name) ? "chip on" : "chip"} onClick={() => setC({ item_types: toggle(c.item_types, ct.name) })}>{ct.name}</button>
          ))}
        </div>
      )}
      {(t === "per_bend" || t === "per_io") && (
        <div className="form-grid">
          <label>Change of direction from (°)<input type="number" value={c.angle_min ?? ""} onChange={(e) => setC({ angle_min: numOrNull(e.target.value) })} placeholder="e.g. 67.5" /></label>
          <label>to (°)<input type="number" value={c.angle_max ?? ""} onChange={(e) => setC({ angle_max: numOrNull(e.target.value) })} placeholder="e.g. 95" /></label>
          <span className="hint">Measured as the change of direction at each traced vertex: a square corner is 90°. Under 5° is ignored.</span>
        </div>
      )}
      {t === "per_io" && (
        <div className="form-grid">
          <label className="inline"><input type="checkbox" checked={!!c.io_at_ends} onChange={(e) => setC({ io_at_ends: e.target.checked })} /> At free run ends (not joined to another run)</label>
          <label className="inline"><input type="checkbox" checked={!!c.io_at_bends} onChange={(e) => setC({ io_at_bends: e.target.checked })} /> At changes of direction in the angle band</label>
          <label>Every (m) along the run<input type="number" value={c.io_interval_m ?? ""} onChange={(e) => setC({ io_interval_m: numOrNull(e.target.value) })} /></label>
        </div>
      )}
      <div className="row">
        <label className="inline"><input type="checkbox" checked={rule.active} onChange={(e) => onChange({ ...rule, active: e.target.checked })} /> Active</label>
        <span className="spacer" />
        <button onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={!rule.name} onClick={onSave}>Save rule</button>
      </div>
    </section>
  );
}
