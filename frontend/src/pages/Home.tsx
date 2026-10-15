import { DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, upload } from "../api";
import { can, useApp } from "../App";
import type { Job } from "../types";

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
  const nav = useNavigate();
  const { user } = useApp();
  const canHyd = can(user, "can_hydraulic");
  const canCiv = can(user, "can_civil");

  const load = () => api.get<Job[]>("/api/jobs").then(setJobs);
  useEffect(() => {
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

  const shown = jobs.filter((j) => (!kind || (j.kind ?? "hydraulic") === kind)
    && (!filter || `${j.name} ${j.client} ${j.quote_no}`.toLowerCase().includes(filter.toLowerCase())));

  return (
    <main className="page home">
      <section className="hero">
        <h1>Start a new estimate</h1>
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
                <span className="muted small">{[j.client, j.quote_no].filter(Boolean).join(" · ")}</span>
                <span className="spacer" />
                <span className={`status ${st.tone}`}>{st.text}</span>
                <span className="muted small">{j.created_at ? new Date(j.created_at).toLocaleDateString("en-AU") : ""}</span>
              </Link>
            );
          })}
          {shown.length === 0 && <p className="muted">No jobs yet. Drop some plans above to start one.</p>}
        </div>
        <p className="small muted"><Link to="/jobs">Set up a job by hand instead</Link></p>
      </section>
    </main>
  );
}
