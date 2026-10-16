/* Tools: every tool, who has it right now, and the hand-overs between people.
   The office keeps the register (/tools); everyone sees who has what on the phone (/field/tools), taps the
   holder's name to call them, and both sides confirm the hand-over so the register stays right. */
import { useEffect, useMemo, useState } from "react";
import { api, fetchBlobUrl, upload } from "../api";
import { level, useApp } from "../App";
import { DataTable, ErrorLine, Field, fmtDate, getLocation, Modal, money, shrinkImage, useAction, useLoad } from "../ui";

export interface Move { id: number; tool_id: number; kind: string; from_user_id: number | null; from: string; to_user_id: number | null; to: string;
  location: string; status: string; started_by: number; note: string; at: string; done_at: string | null; tool?: string }
export interface ToolRow { id: number; name: string; category: string; asset_no: string; make: string; model: string; serial: string; value: number | null;
  status: string; status_label: string; holder_id: number | null; holder: string; holder_phone: string; job_id: number | null; location: string;
  test_tag_due: string | null; test_tag_overdue: boolean; service_due: string | null; has_photo: boolean; notes: string; updated_at: string | null; pending: Move[] }
interface Board { tools: ToolRow[]; me: number; to_confirm: Move[]; waiting: Move[]; people: { user_id: number; name: string; phone: string }[]; office: boolean }

const tel = (p: string) => `tel:${p.replace(/[^\d+]/g, "")}`;
const soon = (iso: string | null) => !!iso && new Date(iso + "T00:00:00").getTime() - Date.now() < 14 * 86400000;

/** The holder's name; a tap rings them. */
export function Holder({ t }: { t: ToolRow }) {
  if (!t.holder_id) return <span className="muted">{t.location || "Yard"}</span>;
  return t.holder_phone
    ? <a className="call-link" href={tel(t.holder_phone)} onClick={(e) => e.stopPropagation()} title={`Call ${t.holder}`}>📞 {t.holder}</a>
    : <span>{t.holder} <small className="muted">(no number)</small></span>;
}

function moveText(m: Move, me: number) {
  const tool = m.tool ? `the ${m.tool}` : "it";
  if (m.kind === "request") return m.started_by === me ? `You asked ${m.from || "the yard"} for ${tool}` : `${m.to} needs ${tool}`;
  if (m.started_by === me) return m.to_user_id === me ? `You said you've got ${tool} from ${m.from || "the yard"}` : `You're handing ${tool} to ${m.to}`;
  return m.to_user_id === m.started_by ? `${m.to} says they've got ${tool} from you` : `${m.from} is handing you ${tool}`;
}

/* ================= the office register ================= */
export default function ToolsPage() {
  const { user } = useApp();
  const edit = level(user, "tools") === "edit";
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const { data, reload, error } = useLoad<{ tools: ToolRow[]; categories: string[]; statuses: Record<string, string> }>(
    `/api/tools?q=${encodeURIComponent(q)}&status=${status}`, [q, status]);
  const [open, setOpen] = useState<ToolRow | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  const tools = data?.tools ?? [];
  const out = tools.filter((t) => t.holder_id).length;
  const due = tools.filter((t) => soon(t.test_tag_due)).length;
  const pending = tools.flatMap((t) => t.pending.map((m) => ({ ...m, tool: t.name })));
  return (
    <main className="page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Tools</h1><span className="spacer" />
        {edit && <button onClick={() => setImporting(true)}>Import CSV</button>}
        {edit && <button className="primary" onClick={() => setOpen("new")}>+ Add a tool</button>}
      </div>
      <p className="muted small">Everyone can see who has each tool on their phone (Tools tab) and tap their name to call them. Hand-overs are confirmed by both people.</p>
      <div className="tiles">
        <div className="tile"><b>{tools.length}</b><span>tools</span></div>
        <div className="tile"><b>{out}</b><span>out with people</span></div>
        <div className="tile"><b>{tools.length - out}</b><span>in the yard / elsewhere</span></div>
        <div className={`tile ${due ? "warn" : ""}`}><b>{due}</b><span>test & tag due in 14 days</span></div>
        <div className={`tile ${pending.length ? "warn" : ""}`}><b>{pending.length}</b><span>hand-overs waiting</span></div>
      </div>
      {pending.length > 0 && (
        <section className="card">
          <h3>Waiting to be confirmed</h3>
          {pending.map((m) => (
            <div key={m.id} className="note-row">
              <span>{m.kind === "request" ? `${m.to} asked ${m.from || "the yard"} for the ${m.tool}` : `${m.tool}: ${m.from || "Yard"} → ${m.to}`} <small className="muted">{fmtDate(m.at)}</small></span>
              {edit && <span className="row">
                <button className="small" onClick={async () => { await api.post(`/api/field/tool-moves/${m.id}/confirm`); reload(); }}>Confirm</button>
                <button className="link small" onClick={async () => { await api.post(`/api/field/tool-moves/${m.id}/decline`); reload(); }}>Cancel</button>
              </span>}
            </div>
          ))}
        </section>
      )}
      <div className="row wrap">
        <input placeholder="Search name, tag no., serial, category" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          {Object.entries(data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <ErrorLine error={error} />
      <DataTable rows={tools} onRow={(t) => setOpen(t)} empty="No tools yet. Add them one at a time or import a spreadsheet."
        rowClass={(t) => (t.status === "lost" || t.test_tag_overdue ? "bad-row" : "")}
        cols={[
          { key: "name", label: "Tool", render: (t) => <><b>{t.name}</b>{(t.make || t.model) && <div className="small muted">{t.make} {t.model}</div>}</> },
          { key: "tag", label: "Tag no.", render: (t) => t.asset_no, hideSm: true },
          { key: "cat", label: "Category", render: (t) => t.category, hideSm: true },
          { key: "who", label: "Who has it", render: (t) => <Holder t={t} /> },
          { key: "status", label: "Status", render: (t) => <span className={`status-chip s-${t.status}`}>{t.status_label}</span> },
          { key: "tt", label: "Test & tag", render: (t) => t.test_tag_due ? <span className={t.test_tag_overdue ? "bad" : soon(t.test_tag_due) ? "warn" : ""}>{fmtDate(t.test_tag_due)}</span> : "" },
          { key: "value", label: "Value", num: true, render: (t) => (t.value ? money(t.value) : ""), hideSm: true },
        ]} />
      {open && <ToolModal tool={open === "new" ? null : open} categories={data?.categories ?? []} edit={edit}
        onClose={() => setOpen(null)} onSaved={() => { reload(); }} />}
      {importing && <ImportTools onClose={() => setImporting(false)} onDone={reload} />}
    </main>
  );
}

function ToolModal({ tool, categories, edit, onClose, onSaved }: { tool: ToolRow | null; categories: string[]; edit: boolean; onClose: () => void; onSaved: () => void }) {
  const staff = useLoad<{ id: number; name: string }[]>("/api/staff");
  const history = useLoad<Move[]>(tool ? `/api/tools/${tool.id}/history` : null);
  const [f, setF] = useState({ name: tool?.name ?? "", category: tool?.category ?? "", asset_no: tool?.asset_no ?? "", make: tool?.make ?? "", model: tool?.model ?? "",
    serial: tool?.serial ?? "", value: tool?.value ?? "", location: tool?.location ?? "Yard", test_tag_due: tool?.test_tag_due ?? "", service_due: tool?.service_due ?? "",
    notes: tool?.notes ?? "", status: tool?.status ?? "available" });
  const [who, setWho] = useState(String(tool?.holder_id ?? ""));
  const [photo, setPhoto] = useState("");
  const [run, error, busy] = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const save = () => run(async () => {
    const body = { ...f, value: f.value === "" ? null : Number(f.value), test_tag_due: f.test_tag_due || null, service_due: f.service_due || null,
      status: f.status === "with_person" ? undefined : f.status };
    if (tool) await api.put(`/api/tools/${tool.id}`, body); else await api.post("/api/tools", body);
    onSaved(); onClose();
  });
  const assign = () => run(async () => {
    await api.post(`/api/tools/${tool!.id}/assign`, { user_id: who ? Number(who) : null, location: who ? "" : f.location || "Yard" });
    onSaved(); history.reload();
  });
  const addPhoto = (file?: File) => file && run(async () => {
    const form = new FormData();
    form.append("file", new File([await shrinkImage(file, 1200)], "tool.jpg", { type: "image/jpeg" }));
    await upload(`/api/tools/${tool!.id}/photo`, form);
    setPhoto(await fetchBlobUrl(`/api/field/tools/${tool!.id}/photo?${Date.now()}`)); onSaved();
  });
  useEffect(() => { if (tool?.has_photo) fetchBlobUrl(`/api/field/tools/${tool.id}/photo`).then(setPhoto).catch(() => undefined); }, [tool?.id, tool?.has_photo]);
  return (
    <Modal title={tool ? tool.name : "Add a tool"} onClose={onClose} wide>
      <div className="two-col">
        <div className="stack">
          <div className="grid2">
            <Field label="Name"><input value={f.name} onChange={set("name")} disabled={!edit} autoFocus={!tool} /></Field>
            <Field label="Category"><select value={f.category} onChange={set("category")} disabled={!edit}><option value="">–</option>{categories.map((c) => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Tag / asset no."><input value={f.asset_no} onChange={set("asset_no")} disabled={!edit} /></Field>
            <Field label="Serial no."><input value={f.serial} onChange={set("serial")} disabled={!edit} /></Field>
            <Field label="Make"><input value={f.make} onChange={set("make")} disabled={!edit} /></Field>
            <Field label="Model"><input value={f.model} onChange={set("model")} disabled={!edit} /></Field>
            <Field label="Value ($)"><input type="number" value={f.value} onChange={set("value")} disabled={!edit} /></Field>
            <Field label="Kept at (when not with someone)"><input value={f.location} onChange={set("location")} disabled={!edit} /></Field>
            <Field label="Test & tag due"><input type="date" value={f.test_tag_due} onChange={set("test_tag_due")} disabled={!edit} /></Field>
            <Field label="Service due"><input type="date" value={f.service_due} onChange={set("service_due")} disabled={!edit} /></Field>
          </div>
          {tool && <Field label="Status"><select value={f.status} onChange={set("status")} disabled={!edit}>
            <option value="available">In the yard</option>{tool.holder_id && <option value="with_person">With {tool.holder}</option>}
            <option value="repair">Being repaired</option><option value="lost">Missing</option><option value="retired">Retired</option></select></Field>}
          <Field label="Notes"><textarea rows={2} value={f.notes} onChange={set("notes")} disabled={!edit} /></Field>
          <ErrorLine error={error} />
          {edit && <button className="primary" onClick={save} disabled={busy || !f.name.trim()}>Save</button>}
        </div>
        {tool && (
          <div className="stack">
            {photo && <img src={photo} alt="" className="tool-photo" />}
            {edit && <label className="btn small">📷 {tool.has_photo ? "Change photo" : "Add a photo"}<input type="file" accept="image/*" hidden onChange={(e) => addPhoto(e.target.files?.[0])} /></label>}
            <div className="card">
              <h3>Who has it</h3>
              <p><Holder t={tool} /></p>
              {edit && <div className="row wrap">
                <select value={who} onChange={(e) => setWho(e.target.value)}><option value="">Back in the yard</option>
                  {(staff.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
                <button onClick={assign} disabled={busy}>Set now</button>
              </div>}
              {edit && <p className="small muted">Use this for stocktakes and new tools. Day to day, people hand tools over on their phones.</p>}
            </div>
            <h3>History</h3>
            <div className="history">
              {(history.data ?? []).map((m) => (
                <div key={m.id} className="small">
                  <b>{fmtDate(m.at)}</b> {m.kind === "return" ? `${m.from || "?"} → ${m.location || "Yard"}` : m.kind === "request" ? `${m.to} asked for it` :
                    m.kind === "repair" ? "Reported for repair" : m.kind === "lost" ? "Reported missing" : `${m.from || m.location || "Yard"} → ${m.to || m.location || "Yard"}`}
                  {m.status !== "done" && <span className="muted"> ({m.status})</span>}{m.note && <span className="muted"> · {m.note}</span>}
                </div>
              ))}
              {history.data?.length === 0 && <p className="muted small">No moves yet.</p>}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

function ImportTools({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [run, error, busy] = useAction();
  const [msg, setMsg] = useState("");
  const go = (file?: File) => file && run(async () => {
    const form = new FormData();
    form.append("file", file);
    const r = await upload<{ added: number; updated: number }>("/api/tools/import", form);
    setMsg(`${r.added} added, ${r.updated} updated.`); onDone();
  });
  return (
    <Modal title="Import tools" onClose={onClose}>
      <p>A CSV with a header row. Columns (any order): <code>name, category, asset_no, make, model, serial, value, location, test_tag_due</code>.
        Rows with a tag no. that's already in the register update that tool.</p>
      <input type="file" accept=".csv,text/csv" onChange={(e) => go(e.target.files?.[0])} disabled={busy} />
      <ErrorLine error={error} />
      {msg && <p className="ok">{msg}</p>}
    </Modal>
  );
}

/* ================= the phone: who has what ================= */
export function FieldTools() {
  const { data, reload, error } = useLoad<Board>("/api/field/tools");
  const [q, setQ] = useState("");
  const [mine, setMine] = useState(false);
  const [giving, setGiving] = useState<ToolRow | null>(null);
  const [reporting, setReporting] = useState<ToolRow | null>(null);
  const [run, err, busy] = useAction();
  const [msg, setMsg] = useState("");
  const list = useMemo(() => (data?.tools ?? []).filter((t) => (!mine || t.holder_id === data?.me)
    && (!q || `${t.name} ${t.asset_no} ${t.category} ${t.holder}`.toLowerCase().includes(q.toLowerCase()))), [data, q, mine]);
  if (!data) return <p className="muted">{error || "Loading…"}</p>;
  const act = (path: string, body: Record<string, unknown> = {}, done = "") => run(async () => {
    const loc = path.endsWith("/take") ? await getLocation() : {};
    await api.post(path, { ...body, ...loc }); setMsg(done); await reload();
  });
  const myCount = data.tools.filter((t) => t.holder_id === data.me).length;
  return (
    <div className="stack">
      <h1>Tools</h1>
      {data.to_confirm.map((m) => (
        <div key={m.id} className="todo blocking tool-confirm">
          <span>🔁 {moveText(m, data.me)}{m.note && <small> · “{m.note}”</small>}</span>
          <span className="row">
            {m.kind === "request"
              ? <button className="primary small" onClick={() => act(`/api/field/tool-moves/${m.id}/confirm`, {}, "Done: it's down to them now.")} disabled={busy}>I've handed it over</button>
              : <button className="primary small" onClick={() => act(`/api/field/tool-moves/${m.id}/confirm`, {}, "Confirmed.")} disabled={busy}>Yes, confirm</button>}
            <button className="link small" onClick={() => act(`/api/field/tool-moves/${m.id}/decline`)} disabled={busy}>No</button>
          </span>
        </div>
      ))}
      {data.waiting.map((m) => (
        <div key={m.id} className="todo">
          <span>⏳ {moveText(m, data.me)}: waiting for them to confirm.</span>
          <button className="link small" onClick={() => act(`/api/field/tool-moves/${m.id}/decline`)} disabled={busy}>Cancel</button>
        </div>
      ))}
      {msg && <p className="ok">{msg}</p>}
      <ErrorLine error={err} />
      <div className="row">
        <input placeholder="Find a tool or a person" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
      </div>
      <div className="seg">
        <button className={!mine ? "on" : ""} onClick={() => setMine(false)}>Everyone's ({data.tools.length})</button>
        <button className={mine ? "on" : ""} onClick={() => setMine(true)}>Mine ({myCount})</button>
      </div>
      {list.length === 0 && <p className="muted">{mine ? "You don't have any tools down to you." : "No tools match."}</p>}
      {list.map((t) => {
        const mineNow = t.holder_id === data.me;
        const asked = t.pending.some((m) => m.started_by === data.me);
        const out = t.status === "repair" || t.status === "lost";
        return (
          <div key={t.id} className={`tool-card ${mineNow ? "mine" : ""}`}>
            <div className="row">
              <div style={{ flex: 1 }}>
                <b>{t.name}</b>{t.asset_no && <small className="muted"> · {t.asset_no}</small>}
                <div className="small">{mineNow ? <span className="ok">With you</span> : <Holder t={t} />}
                  {out && <span className="bad"> · {t.status_label}</span>}
                  {t.test_tag_due && <span className={t.test_tag_overdue ? "bad" : soon(t.test_tag_due) ? "warn" : "muted"}> · T&T {fmtDate(t.test_tag_due)}</span>}</div>
              </div>
              {!mineNow && t.holder_phone && <a className="btn call" href={tel(t.holder_phone)} aria-label={`Call ${t.holder}`}>📞</a>}
            </div>
            <div className="row wrap tool-actions">
              {mineNow ? <>
                <button className="small" onClick={() => setGiving(t)} disabled={busy}>Give to…</button>
                <button className="small" onClick={() => act(`/api/field/tools/${t.id}/return`, { location: t.location && t.location !== t.holder ? t.location : "Yard" }, "Back in the yard.")} disabled={busy}>Back to the yard</button>
                <button className="small link" onClick={() => setReporting(t)}>Problem?</button>
              </> : !out && <>
                {t.holder_id && !asked && <button className="small" onClick={() => act(`/api/field/tools/${t.id}/request`, {}, `${t.holder} has been told you need it. Give them a call to meet up.`)} disabled={busy}>I need it</button>}
                {asked && <span className="small muted">You've asked for it</span>}
                <button className="small" onClick={() => act(`/api/field/tools/${t.id}/take`, {}, t.holder_id ? `Sent to ${t.holder} to confirm.` : "It's down to you now.")} disabled={busy}>
                  {t.holder_id ? "I've got it now" : "I'm taking it"}</button>
              </>}
            </div>
          </div>
        );
      })}
      {giving && <GiveSheet tool={giving} people={data.people.filter((p) => p.user_id !== data.me)} onClose={() => setGiving(null)}
        onGive={(uid, note) => act(`/api/field/tools/${giving.id}/give`, { to_user_id: uid, note }, "Sent: they confirm when they've got it.").then((ok) => ok && setGiving(null))} />}
      {reporting && <ReportSheet tool={reporting} onClose={() => setReporting(null)}
        onSend={(kind, note) => act(`/api/field/tools/${reporting.id}/report`, { kind, note }, "The office has been told.").then((ok) => ok && setReporting(null))} />}
    </div>
  );
}

function GiveSheet({ tool, people, onGive, onClose }: { tool: ToolRow; people: Board["people"]; onGive: (uid: number, note: string) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [note, setNote] = useState("");
  return (
    <Modal title={`Give the ${tool.name} to…`} onClose={onClose}>
      <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <input placeholder="Note (optional), e.g. left it on the ute" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="pick-list">
        {people.filter((p) => p.name.toLowerCase().includes(q.toLowerCase())).map((p) => (
          <button key={p.user_id} className="job-tile" onClick={() => onGive(p.user_id, note)}>{p.name}</button>
        ))}
      </div>
    </Modal>
  );
}

function ReportSheet({ tool, onSend, onClose }: { tool: ToolRow; onSend: (kind: "repair" | "lost", note: string) => void; onClose: () => void }) {
  const [note, setNote] = useState("");
  return (
    <Modal title={tool.name} onClose={onClose}>
      <textarea rows={3} placeholder="What's wrong?" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button onClick={() => onSend("repair", note)}>🔧 Needs repair</button>
        <button className="danger" onClick={() => onSend("lost", note)}>❓ It's missing</button>
      </div>
    </Modal>
  );
}
