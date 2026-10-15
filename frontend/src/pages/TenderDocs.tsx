import { useCallback, useEffect, useRef, useState } from "react";
import { api, fetchBlobUrl, upload } from "../api";
import { useApp } from "../App";
import type { Requirement, RequirementList, TenderDoc } from "../types";

const DOC_TYPES: Record<string, string> = {
  scope: "Scope of works", specification: "Specification", acoustic_report: "Acoustic report", brief: "Design brief",
  addendum: "Addendum", tender_conditions: "Tender conditions", schedule_of_rates: "Schedule of rates",
  geotechnical_report: "Geotechnical report", other: "Document",
};
const ORDER = ["material_spec", "exclusion", "allowance", "rate_factor", "inclusion", "risk", "note"];
const ACCEPTED = ".pdf,.docx,.xlsx,.xlsm,.txt,.csv";

function Editor({ r, civil, categories, onSave }: {
  r: Requirement; civil: boolean; categories: string[]; onSave: (body: Partial<Requirement>) => void;
}) {
  const { settings } = useApp();
  const services = settings.services.filter((s) => s.active);
  const set = (body: Partial<Requirement>) => onSave(body);
  const serviceSelect = (
    <select value={r.service_codes[0] ?? ""} onChange={(e) => set({ service_codes: e.target.value ? [e.target.value] : [] })}>
      <option value="">{r.category === "rate_factor" ? "All services" : "Choose service"}</option>
      {services.map((s) => <option key={s.code} value={s.code}>{s.code}: {s.name}</option>)}
    </select>
  );
  const categorySelect = (
    <select value={r.civil_category} onChange={(e) => set({ civil_category: e.target.value })}>
      <option value="">{r.category === "rate_factor" ? "All BOQ lines" : "Choose category"}</option>
      {categories.map((c) => <option key={c}>{c}</option>)}
    </select>
  );
  if (r.category === "material_spec") {
    return (
      <div className="row wrap small">
        {serviceSelect}
        <input list="materials" defaultValue={r.material} placeholder="Material" onBlur={(e) => e.target.value !== r.material && set({ material: e.target.value })} />
        <datalist id="materials">{settings.materials.map((m) => <option key={m.id} value={m.name} />)}</datalist>
      </div>
    );
  }
  if (r.category === "exclusion") return <div className="row wrap small">{civil ? categorySelect : serviceSelect}</div>;
  if (r.category === "rate_factor") {
    return (
      <div className="row wrap small">
        <input className="tiny" type="number" min={0} step="0.5" defaultValue={r.percent || ""} placeholder="%"
               onBlur={(e) => Number(e.target.value) !== r.percent && set({ percent: Number(e.target.value) || 0 })} />
        <span>% on</span>
        <select value={r.applies_to || "labour"} onChange={(e) => set({ applies_to: e.target.value })}>
          <option value="labour">labour</option><option value="material">materials</option><option value="all">everything</option>
        </select>
        <span>for</span>
        {civil ? categorySelect : serviceSelect}
      </div>
    );
  }
  if (r.category === "allowance") {
    return (
      <div className="row wrap small">
        {!civil && (
          <select value={r.allowance_kind || "provisional"} onChange={(e) => set({ allowance_kind: e.target.value })}>
            <option value="provisional">Provisional sum</option><option value="pc">PC item</option>
          </select>
        )}
        <span>$</span>
        <input className="tiny" type="number" min={0} defaultValue={r.amount || ""} placeholder="amount"
               onBlur={(e) => Number(e.target.value) !== r.amount && set({ amount: Number(e.target.value) || 0 })} />
        {civil && categorySelect}
      </div>
    );
  }
  return null;
}

export default function TenderDocs({ jobId, civil, final, running, onChanged }: {
  jobId: number; civil: boolean; final: boolean; running: boolean; onChanged: () => void;
}) {
  const [docs, setDocs] = useState<TenderDoc[]>([]);
  const [list, setList] = useState<RequirementList | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showDone, setShowDone] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [d, l] = await Promise.all([
      api.get<TenderDoc[]>(`/api/jobs/${jobId}/documents`), api.get<RequirementList>(`/api/jobs/${jobId}/requirements`)]);
    setDocs(d);
    setList(l);
  }, [jobId]);
  useEffect(() => { load(); }, [load, running]);
  useEffect(() => {
    if (civil) api.get<{ categories: string[] }>(`/api/jobs/${jobId}/civil/boq`).then((b) => setCategories(b.categories));
  }, [civil, jobId]);

  const send = async (files: FileList | null) => {
    const chosen = Array.from(files ?? []);
    if (!chosen.length) return;
    const form = new FormData();
    chosen.forEach((f) => form.append("files", f));
    setError(""); setBusy(0);
    try { await upload(`/api/jobs/${jobId}/documents`, form, setBusy); onChanged(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };
  const act = async (r: Requirement, action: "accept" | "reject" | "undo") => {
    setError(""); setMsg("");
    try { await api.post(`/api/requirements/${r.id}/${action}`); await load(); onChanged(); }
    catch (e) { setError((e as Error).message); }
  };
  const save = async (r: Requirement, body: Partial<Requirement>) => {
    try { await api.patch(`/api/requirements/${r.id}`, body); await load(); }
    catch (e) { setError((e as Error).message); }
  };
  const acceptAll = async () => {
    setError("");
    const res = await api.post<{ accepted: number; waiting: number }>(`/api/jobs/${jobId}/requirements/accept-all`);
    setMsg(`Accepted ${res.accepted}.${res.waiting ? ` ${res.waiting} still need a choice from you (shown in orange).` : ""}`);
    await load();
    onChanged();
  };
  const open = async (d: TenderDoc) => {
    const url = await fetchBlobUrl(`/api/documents/${d.id}/file`);
    window.open(url, "_blank");
  };
  const remove = async (d: TenderDoc) => {
    if (!window.confirm(`Remove ${d.filename}? Anything accepted from it is undone.`)) return;
    await api.del(`/api/documents/${d.id}`);
    await load();
    onChanged();
  };

  const reqs = list?.requirements ?? [];
  const pending = reqs.filter((r) => r.status === "suggested");
  const done = reqs.filter((r) => r.status !== "suggested");
  const shown = showDone ? reqs : pending;
  const label = (c: string) => list?.labels[c] ?? c;

  return (
    <section className="card tender">
      <div className="row wrap">
        <h2 style={{ margin: 0 }}>Tender documents</h2>
        <span className="spacer" />
        <button disabled={final || running || busy !== null} onClick={() => input.current?.click()}>
          {busy !== null ? `Uploading ${Math.round(busy * 100)}%` : "+ Add scope, specs, reports…"}
        </button>
        <input ref={input} type="file" accept={ACCEPTED} multiple hidden onChange={(e) => send(e.target.files)} />
      </div>
      {docs.length === 0 && (
        <p className="muted">
          Add the scope of works, specifications, acoustic reports, design briefs, addenda and tender conditions. The AI reads them
          and lists what changes the take-off or the price (materials specified, exclusions, allowances, site conditions, risks), with the
          page each one came from.
        </p>
      )}
      {docs.length > 0 && (
        <ul className="doc-list">
          {docs.map((d) => (
            <li key={d.id}>
              <span className="badge">{DOC_TYPES[d.doc_type] ?? "Document"}</span>{" "}
              <button className="link" onClick={() => open(d)}>{d.filename}</button>
              {d.status === "queued" && <span className="muted small"> waiting to be read…</span>}
              {d.status === "failed" && <span className="error small"> couldn't be read: {d.error}</span>}
              {d.status === "read" && <span className="muted small"> {d.requirements} item{d.requirements === 1 ? "" : "s"} found</span>}
              {!final && <> <button className="link danger small" onClick={() => remove(d)}>remove</button></>}
              {d.summary && <div className="small muted">{d.summary}</div>}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}

      {reqs.length > 0 && (
        <>
          <div className="row wrap">
            <h3 style={{ margin: 0 }}>What the documents mean for this job</h3>
            <span className="spacer" />
            <label className="inline small"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show accepted and rejected ({done.length})</label>
            <button className="primary" disabled={final || !pending.length} onClick={acceptAll}>Accept all ({pending.length})</button>
          </div>
          <p className="small muted">Nothing here changes the take-off or price until you accept it. Each item quotes the document so you can check it.</p>
          {ORDER.map((cat) => {
            const items = shown.filter((r) => r.category === cat);
            if (!items.length) return null;
            return (
              <div key={cat} className="req-group">
                <h4>{label(cat)}</h4>
                {items.map((r) => (
                  <div key={r.id} className={`req ${r.status} ${r.needs ? "needs" : ""}`}>
                    <div className="req-main">
                      <b>{r.title}</b>
                      <blockquote>“{r.quote}”<span className="muted small"> ({r.document}{r.page ? `, page ${r.page}` : ""})</span></blockquote>
                      {r.status === "suggested" && !final && <Editor r={r} civil={civil} categories={categories} onSave={(b) => save(r, b)} />}
                      <div className="small">
                        {r.status === "accepted" ? <span className="ok">✓ Applied: {r.effect}</span>
                          : r.status === "rejected" ? <span className="muted">Rejected</span>
                          : r.needs ? <span className="warn">{r.needs}</span>
                          : <span className="muted">Accepting will: {r.effect}</span>}
                      </div>
                    </div>
                    {!final && (
                      <div className="req-actions">
                        {r.status === "suggested" && <button className="primary" disabled={!!r.needs} onClick={() => act(r, "accept")}>Accept</button>}
                        {r.status === "suggested" && <button onClick={() => act(r, "reject")}>Reject</button>}
                        {r.status !== "suggested" && <button onClick={() => act(r, "undo")}>Undo</button>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            );
          })}
          {!shown.length && <p className="muted small">Everything has been dealt with. Tick "show accepted" to see it.</p>}
        </>
      )}
    </section>
  );
}
