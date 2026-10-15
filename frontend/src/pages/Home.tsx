import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, upload } from "../api";
import { can, useApp } from "../App";
import type { Job, SalesSettings, Sector } from "../types";
import { SECTOR_LABELS, STAGE_LABELS } from "../types";

type Kind = "hydraulic" | "civil";
const ACCEPTED = [".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".csv"];

/** Where a job is up to, in plain words. */
export function jobStage(j: Job): { text: string; tone: "busy" | "ok" | "warn" | "bad" | "plain" } {
  const a = j.autopilot;
  if (j.status === "final") return { text: "Final", tone: "ok" };
  if (!a) return { text: "Manual job", tone: "plain" };
  if (a.state === "queued" || a.state === "running") return { text: "Reading the plans…", tone: "busy" };
  if (a.state === "failed") return { text: "Stopped with an error", tone: "bad" };
  if (a.state === "interrupted") return { text: "Interrupted: run again", tone: "warn" };
  const needs = a.attention?.length ?? 0;
  if (needs) return { text: `Ready · ${needs} thing${needs === 1 ? "" : "s"} need you`, tone: "warn" };
  return { text: "Ready to review", tone: "ok" };
}

function DropZone({ kind, title, blurb, busy, onFiles }: {
  kind: Kind; title: string; blurb: string; busy: boolean; onFiles: (kind: Kind, files: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const take = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => ACCEPTED.some((ext) => f.name.toLowerCase().endsWith(ext)));
    if (files.length) onFiles(kind, files);
  };
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (!busy) take(e.dataTransfer.files); };
  return (
    <div
      className={`dropzone ${kind} ${over ? "over" : ""} ${busy ? "busy" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      onClick={() => !busy && input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
    >
      <div className="dz-icon">{kind === "civil" ? "🛣️" : "🚿"}</div>
      <h2>{title}</h2>
      <p>{blurb}</p>
      <p className="dz-hint">Drop the plans here, plus any scope, specs, acoustic reports, briefs or addenda. Or click to choose them.</p>
      <input ref={input} type="file" accept={ACCEPTED.join(",")} multiple hidden onChange={(e) => take(e.target.files)} />
    </div>
  );
}

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState<"" | Kind>("");
  const [sales, setSales] = useState<SalesSettings | null>(null);
  const [sector, setSectorState] = useState<Sector>(() => {
    try { return (localStorage.getItem("home-sector") as Sector) || "commercial"; } catch { return "commercial"; }
  });
  const setSector = (s: Sector) => { setSectorState(s); try { localStorage.setItem("home-sector", s); } catch { /* storage unavailable */ } };
  const [leadOpen, setLeadOpen] = useState(false);
  const nav = useNavigate();
  const { user } = useApp();
  const canHyd = can(user, "can_hydraulic");
  const canCiv = can(user, "can_civil");

  const load = () => api.get<Job[]>("/api/jobs").then(setJobs);
  useEffect(() => {
    api.get<SalesSettings>("/api/sales/settings").then((s) => {
      setSales(s);
      if (s.sectors.length && !s.sectors.some((x) => x.key === sector)) setSector(s.sectors[0].key);
    });
    load();
    const t = setInterval(load, 5000); // keep the "Reading…" badges current
    return () => clearInterval(t);
  }, []);

  const start = async (kind: Kind, files: File[]) => {
    setError("");
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("kind", kind);
    form.append("name", name);
    form.append("client", client);
    form.append("sector", sector);
    setProgress(0);
    try {
      const job = await upload<Job>("/api/quick-start", form, setProgress);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
    }
  };

  const shown = jobs.filter((j) => (j.sector ?? "commercial") === sector && (!kind || (j.kind ?? "hydraulic") === kind)
    && (!filter || `${j.name} ${j.client} ${j.quote_no}`.toLowerCase().includes(filter.toLowerCase())));

  return (
    <main className="page home">
      <div className="sector-tabs">
        {(sales?.sectors ?? []).map((x) => (
          <button key={x.key} className={sector === x.key ? "active" : ""} onClick={() => setSector(x.key)}>
            {x.label} <span className="count">{jobs.filter((j) => (j.sector ?? "commercial") === x.key).length}</span>
          </button>
        ))}
        <span className="spacer" />
        <button className="primary" onClick={() => setLeadOpen(!leadOpen)}>+ New lead</button>
      </div>
      {leadOpen && sales && <NewLead sector={sector} sources={sales.lead_sources} onDone={(id) => nav(`/jobs/${id}`)} onCancel={() => setLeadOpen(false)} />}
      <section className="hero">
        <h1>New {SECTOR_LABELS[sector].toLowerCase()} estimate</h1>
        <p className="muted">Drop in the full tender: plans and documents together. The app sorts the drawings from the documents, reads the scales,
          takes off the quantities, and works out what the scope, specs and reports mean for the price. You check and approve.</p>
        <div className="row wrap job-details">
          <input placeholder="Job name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="Client / consultant (optional)" value={client} onChange={(e) => setClient(e.target.value)} />
        </div>
        <div className={`dropzones ${canHyd && canCiv ? "" : "single"}`}>
          {canHyd && <DropZone kind="hydraulic" title="Hydraulic take-off" busy={progress !== null} onFiles={start}
                    blurb="Pipe runs, fixtures and fittings from hydraulic services plans." />}
          {canCiv && <DropZone kind="civil" title="Civil BOQ" busy={progress !== null} onFiles={start}
                    blurb="Bill of quantities from civil plans, priced from your previous civil jobs." />}
        </div>
        {progress !== null && (
          <div className="upload-progress">
            <div className="bar"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span>{progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Uploaded. Starting the read…"}</span>
          </div>
        )}
        {error && <p className="error big">{error}</p>}
      </section>

      <section className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>{can(user, "can_all_jobs") ? "Jobs" : "Your jobs"}</h2>
          {canHyd && canCiv && (
            <div className="tabs" style={{ margin: 0 }}>
              {([["", "All"], ["hydraulic", "Plumbing"], ["civil", "Civil"]] as const).map(([k, l]) => (
                <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>{l}</button>
              ))}
            </div>
          )}
          <span className="spacer" />
          <input placeholder="Search jobs" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <div className="job-list">
          {shown.map((j) => {
            const st = jobStage(j);
            return (
              <Link key={j.id} to={`/jobs/${j.id}`} className="job-card">
                <span className={`badge ${j.kind === "civil" ? "civil" : "hyd"}`}>{j.kind === "civil" ? "Civil" : "Hydraulic"}</span>
                <span className="job-name">{j.name}</span>
                <span className="muted small">{[j.quote_no, j.client].filter(Boolean).join(" · ")}</span>
                <span className="spacer" />
                {j.sales_stage && <span className={`stage-chip ${j.sales_stage}`}>{STAGE_LABELS[j.sales_stage]}</span>}
                {j.autopilot && <span className={`status ${st.tone}`}>{st.text}</span>}
                <span className="muted small" title="Lead came in">{(j.lead_date ?? j.created_at) ? new Date((j.lead_date ?? j.created_at)!.slice(0, 10) + "T00:00:00").toLocaleDateString("en-AU") : ""}</span>
              </Link>
            );
          })}
          {shown.length === 0 && <p className="muted">No {SECTOR_LABELS[sector].toLowerCase()} jobs yet. Drop some plans above, or add a lead.</p>}
        </div>
        <p className="small muted"><Link to="/jobs">Set up a job by hand instead</Link></p>
      </section>
    </main>
  );
}

function NewLead({ sector, sources, onDone, onCancel }: { sector: Sector; sources: string[]; onDone: (id: number) => void; onCancel: () => void }) {
  const { user } = useApp();
  const [f, setF] = useState({ name: "", client: "", contact: "", lead_source: "", address: "", due_date: "", tender_value: "",
    kind: can(user, "can_hydraulic") ? "hydraulic" : "civil" });
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const job = await api.post<Job>("/api/leads", { ...f, sector, due_date: f.due_date || null,
        tender_value: f.tender_value ? Number(f.tender_value) : null });
      onDone(job.id);
    } catch (err) { setError((err as Error).message); }
  };
  const field = (k: keyof typeof f, placeholder: string, type = "text") => (
    <input type={type} placeholder={placeholder} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} required={k === "name"} />
  );
  return (
    <form className="card lead-form" onSubmit={save}>
      <h2>New {SECTOR_LABELS[sector].toLowerCase()} lead</h2>
      <p className="small muted">For an enquiry before the plans arrive. Drop the plans on it later and it carries on from there.</p>
      <div className="row wrap">
        {field("name", "Job / site name")}
        {field("client", "Client or builder")}
        {field("contact", "Contact (name, phone, email)")}
        <input list="lead-sources" placeholder="Where did it come from?" value={f.lead_source} onChange={(e) => setF({ ...f, lead_source: e.target.value })} />
        <datalist id="lead-sources">{sources.map((s) => <option key={s} value={s} />)}</datalist>
      </div>
      <div className="row wrap">
        {field("address", "Site address")}
        <label className="inline small">Quote due {field("due_date", "", "date")}</label>
        {field("tender_value", "Rough value $ (optional)", "number")}
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {can(user, "can_hydraulic") && <option value="hydraulic">Plumbing</option>}
          {can(user, "can_civil") && <option value="civil">Civil</option>}
        </select>
        <button className="primary" type="submit">Add lead</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
