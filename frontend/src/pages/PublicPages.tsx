/* Pages anyone can open without signing in: the careers page (job ads and applications) and board forms. */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, upload } from "../api";
import { ErrorLine, useAction, useLoad } from "../ui";

interface Opening { id: number; title: string; department: string; employment_type: string; location: string; pay: string; description: string; questions: { key: string; label: string }[] }
const TYPE: Record<string, string> = { full_time: "Full time", part_time: "Part time", casual: "Casual", apprentice: "Apprenticeship", contractor: "Contract" };

function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="public-page">
      <header className="public-top"><img src="/brand/lorojo-logo.png" alt="Lorojo" /></header>
      <main className="public-main">{children}</main>
    </div>
  );
}

export function Careers() {
  const { id } = useParams();
  const { data, error } = useLoad<{ company: string; openings: Opening[] }>("/api/public/careers");
  if (!data) return <PublicShell><p className="muted">{error || "Loading…"}</p></PublicShell>;
  const o = id ? data.openings.find((x) => x.id === +id) : null;
  if (id && !o) return <PublicShell><p>That job has closed. <Link to="/careers">See what's open</Link></p></PublicShell>;
  return (
    <PublicShell>
      {o ? <Apply o={o} company={data.company} /> : (
        <>
          <h1>Work with {data.company}</h1>
          {data.openings.length === 0 && <p className="muted">No jobs open right now. Check back soon.</p>}
          {data.openings.map((x) => (
            <Link key={x.id} to={`/careers/${x.id}`} className="card job-ad">
              <h2>{x.title}</h2><p className="muted">{[TYPE[x.employment_type], x.location, x.pay].filter(Boolean).join(" · ")}</p>
              <p>{x.description.slice(0, 220)}{x.description.length > 220 && "…"}</p><span className="button primary">Apply</span>
            </Link>
          ))}
        </>
      )}
    </PublicShell>
  );
}

function Apply({ o, company }: { o: Opening; company: string }) {
  const [f, setF] = useState({ name: "", email: "", phone: "", cover_note: "", website: "" });
  const [ans, setAns] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const [done, setDone] = useState(false);
  const [run, err, busy] = useAction();
  if (done) return <div className="card"><h2>Thanks {f.name.split(" ")[0]}!</h2><p>Your application for {o.title} is in. {company} will be in touch.</p></div>;
  return (
    <>
      <Link to="/careers">‹ All jobs</Link>
      <h1>{o.title}</h1>
      <p className="muted">{[TYPE[o.employment_type], o.location, o.pay].filter(Boolean).join(" · ")}</p>
      <p className="policy-text">{o.description}</p>
      <form className="card form" onSubmit={(e) => { e.preventDefault(); run(async () => {
        const fd = new FormData();
        Object.entries(f).forEach(([k, v]) => fd.append(k, v));
        fd.append("answers", JSON.stringify(ans));
        if (file) fd.append("resume", file);
        await upload(`/api/public/careers/${o.id}`, fd);
        setDone(true);
      }); }}>
        <h2>Apply</h2>
        <label>Your name<input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Email<input required type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label>Mobile<input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
        {o.questions.map((q) => <label key={q.key}>{q.label}<input value={ans[q.key] || ""} onChange={(e) => setAns({ ...ans, [q.key]: e.target.value })} /></label>)}
        <label>A bit about you<textarea rows={4} value={f.cover_note} onChange={(e) => setF({ ...f, cover_note: e.target.value })} /></label>
        <label>Résumé (PDF or Word, optional)<input type="file" accept=".pdf,.doc,.docx,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
        <input className="hp" tabIndex={-1} autoComplete="off" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} aria-hidden />
        <button className="primary" disabled={busy}>Send application</button>
        <ErrorLine error={err} />
      </form>
    </>
  );
}

interface FormDef { title: string; intro: string; company: string; fields: { key: string; title: string; type: string; options: string[]; labels: { key: string; label: string }[] }[] }

export function BoardFormPage() {
  const { token } = useParams();
  const { data, error } = useLoad<FormDef>(`/api/public/forms/${token}`);
  const [name, setName] = useState("");
  const [vals, setVals] = useState<Record<string, unknown>>({});
  const [done, setDone] = useState(false);
  const [run, err, busy] = useAction();
  if (!data) return <PublicShell><p className="muted">{error || "Loading…"}</p></PublicShell>;
  if (done) return <PublicShell><div className="card"><h2>Thanks!</h2><p>{data.company} has it.</p>
    <button onClick={() => { setDone(false); setName(""); setVals({}); }}>Send another</button></div></PublicShell>;
  const set = (k: string, v: unknown) => setVals({ ...vals, [k]: v });
  return (
    <PublicShell>
      <h1>{data.title}</h1>
      {data.intro && <p className="policy-text">{data.intro}</p>}
      <form className="card form" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/api/public/forms/${token}`, { name, values: vals }); setDone(true); }); }}>
        <label>What is it?<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
        {data.fields.map((f) => (
          <label key={f.key}>{f.title}
            {f.type === "long_text" ? <textarea value={(vals[f.key] as string) || ""} onChange={(e) => set(f.key, e.target.value)} />
              : f.type === "status" ? <select value={(vals[f.key] as string) || ""} onChange={(e) => set(f.key, e.target.value)}><option value="">–</option>{f.labels.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select>
              : f.type === "dropdown" ? <select value={(vals[f.key] as string) || ""} onChange={(e) => set(f.key, e.target.value)}><option value="">–</option>{f.options.map((o) => <option key={o}>{o}</option>)}</select>
              : f.type === "checkbox" ? <input type="checkbox" checked={!!vals[f.key]} onChange={(e) => set(f.key, e.target.checked)} />
              : f.type === "date" ? <input type="date" value={(vals[f.key] as string) || ""} onChange={(e) => set(f.key, e.target.value)} />
              : ["number", "money", "rating"].includes(f.type) ? <input type="number" value={(vals[f.key] as string) ?? ""} onChange={(e) => set(f.key, e.target.value === "" ? null : +e.target.value)} />
              : f.type === "tags" ? <input value={((vals[f.key] as string[]) || []).join(", ")} onChange={(e) => set(f.key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
              : <input type={f.type === "email" ? "email" : f.type === "phone" ? "tel" : "text"} value={(vals[f.key] as string) || ""} onChange={(e) => set(f.key, e.target.value)} />}
          </label>
        ))}
        <button className="primary" disabled={busy}>Send</button>
        <ErrorLine error={err} />
      </form>
    </PublicShell>
  );
}
