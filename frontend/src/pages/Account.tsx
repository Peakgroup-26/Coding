import { FormEvent, useState } from "react";
import { api } from "../api";
import { can, useApp } from "../App";
import type { Permissions } from "../types";

const LABELS: Record<keyof Permissions, string> = {
  can_hydraulic: "Plumbing jobs", can_civil: "Civil jobs", can_all_jobs: "Everyone's jobs and previous tenders",
  can_past_rates: "Previous civil job rates", can_pricing: "Change price books, mappings and rules",
  can_ops: "Live jobs, scheduling, purchasing, customers", can_finance: "Finance: WIP, budgets, cash flow, invoices",
};

export default function Account() {
  const { user } = useApp();
  const [form, setForm] = useState({ current_password: "", new_password: "", again: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(""); setError("");
    if (form.new_password !== form.again) { setError("The new passwords don't match"); return; }
    try {
      await api.post("/api/auth/password", { current_password: form.current_password, new_password: form.new_password });
      setMsg("Password changed.");
      setForm({ current_password: "", new_password: "", again: "" });
    } catch (err) { setError((err as Error).message); }
  };

  return (
    <main className="page">
      <h1>My account</h1>
      <div className="two-col">
        <section className="card">
          <h2>{user.name || user.email}</h2>
          <p className="muted">{user.email} · {user.role}</p>
          <h3>What you can see</h3>
          <ul className="perm-list">
            {(Object.keys(LABELS) as (keyof Permissions)[]).map((k) => (
              <li key={k} className={can(user, k) ? "ok" : "muted"}>{can(user, k) ? "✓" : "✗"} {LABELS[k]}</li>
            ))}
          </ul>
          <p className="small muted">An admin can change these in the admin portal.</p>
        </section>
        <form className="card form" onSubmit={submit}>
          <h2>Change password</h2>
          <label>Current password<input type="password" value={form.current_password} required
                 onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
          <label>New password (8+ characters)<input type="password" value={form.new_password} minLength={8} required
                 onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
          <label>New password again<input type="password" value={form.again} minLength={8} required
                 onChange={(e) => setForm({ ...form, again: e.target.value })} /></label>
          {error && <p className="error">{error}</p>}
          {msg && <p className="ok">{msg}</p>}
          <button className="primary" type="submit">Change password</button>
        </form>
      </div>
    </main>
  );
}
