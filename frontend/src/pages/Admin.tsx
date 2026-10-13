import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { Benchmark, User } from "../types";

const SERVICE_KINDS = ["drainage", "stormwater", "water", "fire", "gas", "other"];

/** Admin-maintained lists. Items are retired (unticked "active"), never deleted, so old jobs keep their references. */
export default function Admin() {
  const { settings, reloadSettings } = useApp();
  const [error, setError] = useState("");

  const save = async (path: string, id: number | null, body: object) => {
    setError("");
    try {
      if (id) await api.put(`/api/${path}/${id}`, body);
      else await api.post(`/api/${path}`, body);
      await reloadSettings();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <main className="page">
      <h1>Admin</h1>
      {error && <p className="error">{error}</p>}
      <div className="admin-grid">
        <section className="card">
          <h2>Services</h2>
          <table>
            <thead><tr><th>Code</th><th>Name</th><th>Colour</th><th>Kind</th><th>Default stage</th><th>Order</th><th>Active</th></tr></thead>
            <tbody>
              {settings.services.map((s) => (
                <tr key={s.id}>
                  <td><Cell v={s.code} onSave={(code) => save("services", s.id, { ...s, code })} /></td>
                  <td><Cell v={s.name} onSave={(name) => save("services", s.id, { ...s, name })} /></td>
                  <td><input type="color" value={s.colour} onChange={(e) => save("services", s.id, { ...s, colour: e.target.value })} /></td>
                  <td>
                    <select value={s.kind} onChange={(e) => save("services", s.id, { ...s, kind: e.target.value })}>
                      {SERVICE_KINDS.map((k) => <option key={k}>{k}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={s.default_stage_id ?? ""} onChange={(e) => save("services", s.id, { ...s, default_stage_id: Number(e.target.value) || null })}>
                      <option value="">–</option>
                      {settings.stages.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
                    </select>
                  </td>
                  <td><Cell v={String(s.order)} onSave={(o) => save("services", s.id, { ...s, order: Number(o) })} /></td>
                  <td><input type="checkbox" checked={s.active} onChange={(e) => save("services", s.id, { ...s, active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <AddRow fields={["Code", "Name"]} onAdd={([code, name]) => save("services", null, { code, name, order: settings.services.length })} />
        </section>

        <section className="card">
          <h2>Stages</h2>
          <table>
            <thead><tr><th>Name</th><th>Order</th><th>Active</th></tr></thead>
            <tbody>
              {settings.stages.map((s) => (
                <tr key={s.id}>
                  <td><Cell v={s.name} onSave={(name) => save("stages", s.id, { ...s, name })} /></td>
                  <td><Cell v={String(s.order)} onSave={(o) => save("stages", s.id, { ...s, order: Number(o) })} /></td>
                  <td><input type="checkbox" checked={s.active} onChange={(e) => save("stages", s.id, { ...s, active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <AddRow fields={["Name"]} onAdd={([name]) => save("stages", null, { name, order: settings.stages.length })} />
        </section>

        <section className="card">
          <h2>Materials and waste allowance</h2>
          <p className="muted small">Waste % is added on top of measured length, shown separately. New runs take the material's current value.</p>
          <table>
            <thead><tr><th>Material</th><th>Waste %</th><th>Active</th></tr></thead>
            <tbody>
              {settings.materials.map((m) => (
                <tr key={m.id}>
                  <td><Cell v={m.name} onSave={(name) => save("materials", m.id, { ...m, name })} /></td>
                  <td><Cell v={String(m.waste_pct)} onSave={(w) => save("materials", m.id, { ...m, waste_pct: Number(w) })} /></td>
                  <td><input type="checkbox" checked={m.active} onChange={(e) => save("materials", m.id, { ...m, active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <AddRow fields={["Material"]} onAdd={([name]) => save("materials", null, { name })} />
        </section>

        <section className="card">
          <h2>Count items</h2>
          <table>
            <thead><tr><th>Item</th><th>Default service</th><th>Default stage</th><th>Fixture</th><th>Needs drain</th><th>Needs water</th><th>Active</th></tr></thead>
            <tbody>
              {settings.count_types.map((c) => (
                <tr key={c.id}>
                  <td><Cell v={c.name} onSave={(name) => save("count-types", c.id, { ...c, name })} /></td>
                  <td>
                    <select value={c.default_service_id ?? ""} onChange={(e) => save("count-types", c.id, { ...c, default_service_id: Number(e.target.value) || null })}>
                      <option value="">–</option>
                      {settings.services.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={c.default_stage_id ?? ""} onChange={(e) => save("count-types", c.id, { ...c, default_stage_id: Number(e.target.value) || null })}>
                      <option value="">Service default</option>
                      {settings.stages.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
                    </select>
                  </td>
                  <td><input type="checkbox" checked={c.is_fixture} onChange={(e) => save("count-types", c.id, { ...c, is_fixture: e.target.checked })} /></td>
                  <td><input type="checkbox" checked={c.needs_drainage} onChange={(e) => save("count-types", c.id, { ...c, needs_drainage: e.target.checked })} /></td>
                  <td><input type="checkbox" checked={c.needs_water} onChange={(e) => save("count-types", c.id, { ...c, needs_water: e.target.checked })} /></td>
                  <td><input type="checkbox" checked={c.active} onChange={(e) => save("count-types", c.id, { ...c, active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <AddRow fields={["Item"]} onAdd={([name]) => save("count-types", null, { name })} />
        </section>

        <Benchmarks />
        <SimproTemplate />
        <Users />
      </div>
    </main>
  );
}

function Users() {
  const { user: me } = useApp();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ email: "", name: "", role: "estimator", password: "" });
  const [error, setError] = useState("");
  const load = () => api.get<User[]>("/api/users").then(setUsers);
  useEffect(() => { load(); }, []);
  const patch = async (u: User, body: object) => {
    setError("");
    try { await api.patch(`/api/users/${u.id}`, body); load(); } catch (e) { setError((e as Error).message); }
  };
  const add = async () => {
    setError("");
    try { await api.post("/api/users", form); setForm({ email: "", name: "", role: "estimator", password: "" }); load(); }
    catch (e) { setError((e as Error).message); }
  };
  return (
    <section className="card">
      <h2>Users</h2>
      <table>
        <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Active</th><th></th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.name}</td>
              <td>
                <select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                  <option value="estimator">Estimator</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option>
                </select>
              </td>
              <td><input type="checkbox" checked={u.active} disabled={u.id === me.id} onChange={(e) => patch(u, { active: e.target.checked })} /></td>
              <td><button className="link" onClick={() => {
                const pw = window.prompt(`New password for ${u.email} (8+ characters)`);
                if (pw) patch(u, { password: pw });
              }}>Reset password</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row wrap">
        <input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          <option value="estimator">Estimator</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option>
        </select>
        <input placeholder="Password (8+)" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <button onClick={add} disabled={!form.email || form.password.length < 8}>Add user</button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function Cell({ v, onSave }: { v: string; onSave: (v: string) => void }) {
  const [val, setVal] = useState(v);
  useEffect(() => setVal(v), [v]);
  return <input className="cell" value={val} onChange={(e) => setVal(e.target.value)} onBlur={() => val !== v && onSave(val)}
    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />;
}

function AddRow({ fields, onAdd }: { fields: string[]; onAdd: (vals: string[]) => void }) {
  const [vals, setVals] = useState(fields.map(() => ""));
  return (
    <div className="row wrap">
      {fields.map((f, i) => (
        <input key={f} placeholder={f} value={vals[i]} onChange={(e) => setVals(vals.map((x, j) => (j === i ? e.target.value : x)))} />
      ))}
      <button disabled={vals.some((v) => !v)} onClick={() => { onAdd(vals); setVals(fields.map(() => "")); }}>Add</button>
    </div>
  );
}

function Benchmarks() {
  const { settings } = useApp();
  const [items, setItems] = useState<Benchmark[]>([]);
  const [form, setForm] = useState({ name: "", codes: "", min: "", max: "" });
  const [error, setError] = useState("");
  const load = () => api.get<Benchmark[]>("/api/benchmarks").then(setItems);
  useEffect(() => { load(); }, []);
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const save = async (b: Benchmark | null, body: object) => {
    setError("");
    try {
      if (b) await api.put(`/api/benchmarks/${b.id}`, { ...b, ...body });
      else await api.post("/api/benchmarks", body);
      load();
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <section className="card">
      <h2>Check-measure benchmarks</h2>
      <p className="muted small">Metres of the chosen services per fixture. Check-measure flags a job outside the band. Use Peak's figures from past jobs.</p>
      <table>
        <thead><tr><th>Name</th><th>Services</th><th>Min m/fixture</th><th>Max m/fixture</th><th>Active</th></tr></thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id}>
              <td><Cell v={b.name} onSave={(name) => save(b, { name })} /></td>
              <td><Cell v={b.service_codes.join(", ")} onSave={(v) => save(b, { service_codes: v.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean) })} /></td>
              <td><Cell v={b.min_value === null ? "" : String(b.min_value)} onSave={(v) => save(b, { min_value: num(v) })} /></td>
              <td><Cell v={b.max_value === null ? "" : String(b.max_value)} onSave={(v) => save(b, { max_value: num(v) })} /></td>
              <td><input type="checkbox" checked={b.active} onChange={(e) => save(b, { active: e.target.checked })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row wrap">
        <input placeholder="e.g. Drainage m per fixture" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input placeholder={`Services, e.g. SAN, TW (${settings.services.length} available)`} value={form.codes} onChange={(e) => setForm({ ...form, codes: e.target.value })} />
        <input className="tiny" placeholder="Min" value={form.min} onChange={(e) => setForm({ ...form, min: e.target.value })} />
        <input className="tiny" placeholder="Max" value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value })} />
        <button disabled={!form.name || !form.codes} onClick={async () => {
          await save(null, { name: form.name, service_codes: form.codes.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean),
            min_value: num(form.min), max_value: num(form.max) });
          setForm({ name: "", codes: "", min: "", max: "" });
        }}>Add</button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

type Template = { columns: { header: string; field: string }[]; group_by_stage: boolean; group_by_service: boolean; include_allowances: boolean };

function SimproTemplate() {
  const [t, setT] = useState<Template | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<{ template: Template; fields: Record<string, string> }>("/api/settings/simpro-template").then((r) => { setT(r.template); setFields(r.fields); });
  }, []);
  if (!t) return null;
  const setCol = (i: number, patch: Partial<Template["columns"][0]>) => setT({ ...t, columns: t.columns.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const move = (i: number, d: number) => {
    const cols = [...t.columns];
    const [c] = cols.splice(i, 1);
    cols.splice(Math.max(0, Math.min(cols.length, i + d)), 0, c);
    setT({ ...t, columns: cols });
  };
  const save = async () => {
    setError(""); setMsg("");
    try { await api.put("/api/settings/simpro-template", t); setMsg("Saved."); } catch (e) { setError((e as Error).message); }
  };
  return (
    <section className="card">
      <h2>Simpro CSV layout</h2>
      <p className="muted small">Match the columns to the import format your Simpro is set up for. One row per prebuild or catalogue code.</p>
      <table>
        <thead><tr><th>Column heading</th><th>Value</th><th></th></tr></thead>
        <tbody>
          {t.columns.map((c, i) => (
            <tr key={i}>
              <td><input value={c.header} onChange={(e) => setCol(i, { header: e.target.value })} /></td>
              <td>
                <select value={c.field} onChange={(e) => setCol(i, { field: e.target.value })}>
                  {Object.entries(fields).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </td>
              <td className="actions">
                <button className="link" onClick={() => move(i, -1)}>↑</button>
                <button className="link" onClick={() => move(i, 1)}>↓</button>
                <button className="link" onClick={() => setT({ ...t, columns: t.columns.filter((_, j) => j !== i) })}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row wrap">
        <button onClick={() => setT({ ...t, columns: [...t.columns, { header: "New column", field: "code" }] })}>Add column</button>
        <label className="inline"><input type="checkbox" checked={t.group_by_stage} onChange={(e) => setT({ ...t, group_by_stage: e.target.checked })} /> Separate rows per stage</label>
        <label className="inline"><input type="checkbox" checked={t.group_by_service} onChange={(e) => setT({ ...t, group_by_service: e.target.checked })} /> per service</label>
        <label className="inline"><input type="checkbox" checked={t.include_allowances} onChange={(e) => setT({ ...t, include_allowances: e.target.checked })} /> Include PC items and provisional sums</label>
        <span className="spacer" />
        <button className="primary" onClick={save}>Save layout</button>
      </div>
      {msg && <p className="ok small">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
