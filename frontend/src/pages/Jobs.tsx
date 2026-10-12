import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Job } from "../types";

const EMPTY = { name: "", client: "", builder: "", address: "", quote_no: "", due_date: "" };

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const nav = useNavigate();

  useEffect(() => { api.get<Job[]>("/api/jobs").then(setJobs); }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const job = await api.post<Job>("/api/jobs", { ...form, due_date: form.due_date || null });
      nav(`/jobs/${job.id}`);
    } catch (err) { setError((err as Error).message); }
  };

  const field = (k: keyof typeof EMPTY, label: string, type = "text") => (
    <label>{label}<input type={type} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} required={k === "name"} /></label>
  );

  return (
    <main className="page">
      <h1>Jobs</h1>
      <div className="two-col">
        <section className="card">
          <table>
            <thead><tr><th>Quote</th><th>Job</th><th>Client</th><th>Builder</th><th>Due</th><th>Status</th></tr></thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.quote_no}</td>
                  <td><Link to={`/jobs/${j.id}`}>{j.name}</Link></td>
                  <td>{j.client}</td><td>{j.builder}</td><td>{j.due_date ?? ""}</td><td>{j.status}</td>
                </tr>
              ))}
              {jobs.length === 0 && <tr><td colSpan={6} className="muted">No jobs yet.</td></tr>}
            </tbody>
          </table>
        </section>
        <form className="card form" onSubmit={create}>
          <h2>New job</h2>
          {field("name", "Job name")}
          {field("client", "Client")}
          {field("builder", "Builder")}
          {field("address", "Address")}
          {field("quote_no", "Quote number")}
          {field("due_date", "Due date", "date")}
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit">Create job</button>
        </form>
      </div>
    </main>
  );
}
