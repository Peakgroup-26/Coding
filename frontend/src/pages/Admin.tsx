import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { User } from "../types";

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
            <thead><tr><th>Code</th><th>Name</th><th>Colour</th><th>Default stage</th><th>Order</th><th>Active</th></tr></thead>
            <tbody>
              {settings.services.map((s) => (
                <tr key={s.id}>
                  <td><Cell v={s.code} onSave={(code) => save("services", s.id, { ...s, code })} /></td>
                  <td><Cell v={s.name} onSave={(name) => save("services", s.id, { ...s, name })} /></td>
                  <td><input type="color" value={s.colour} onChange={(e) => save("services", s.id, { ...s, colour: e.target.value })} /></td>
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
            <thead><tr><th>Item</th><th>Default service</th><th>Default stage</th><th>Fixture</th><th>Active</th></tr></thead>
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
                  <td><input type="checkbox" checked={c.active} onChange={(e) => save("count-types", c.id, { ...c, active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <AddRow fields={["Item"]} onAdd={([name]) => save("count-types", null, { name })} />
        </section>

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
