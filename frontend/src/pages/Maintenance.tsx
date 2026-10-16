/* Maintenance planner: assets on customers' sites that need servicing or testing, and making the service jobs for what's due. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DataTable, ErrorLine, Field, fmtDate, Modal, money, useAction, useLoad } from "../ui";

interface Asset { id: number; site_id: number; site: string; address: string; kind: string; location: string; make: string; model: string; serial: string; interval_months: number;
  last_service: string | null; next_due: string | null; service_price: number | null; overdue: boolean; active: boolean; notes: string; installed: string | null; form_template_id: number | null }

export default function Maintenance() {
  const [within, setWithin] = useState<number | "">(60);
  const { data, reload } = useLoad<{ kinds: string[]; assets: Asset[] }>(`/api/assets${within !== "" ? `?due_within=${within}` : ""}`, [within]);
  const sites = useLoad<{ id: number; name: string; address: string }[]>("/api/sites");
  const [edit, setEdit] = useState<Partial<Asset> | null>(null);
  const [sel, setSel] = useState<number[]>([]);
  const [run, error] = useAction();
  const [msg, setMsg] = useState("");
  const make = (ids: number[]) => run(async () => {
    const r = await api.post<{ jobs: { id: number; job_no: string; name: string }[] }>("/api/maintenance/generate", ids.length ? { asset_ids: ids } : { within_days: within || 30 });
    setMsg(r.jobs.length ? `Made ${r.jobs.length} job${r.jobs.length > 1 ? "s" : ""}: ${r.jobs.map((j) => j.job_no).join(", ")}` : "Nothing new to make: open service jobs already cover these."); setSel([]); reload();
  });
  const save = () => run(async () => {
    if (!edit) return;
    const body = { site_id: edit.site_id, kind: edit.kind, location: edit.location ?? "", make: edit.make ?? "", model: edit.model ?? "", serial: edit.serial ?? "",
      interval_months: edit.interval_months ?? 12, last_service: edit.last_service || null, next_due: edit.next_due || null, service_price: edit.service_price ?? null,
      notes: edit.notes ?? "", active: edit.active ?? true, installed: edit.installed || null, form_template_id: edit.form_template_id ?? null };
    if (edit.id) await api.put(`/api/assets/${edit.id}`, body); else await api.post("/api/assets", body);
    setEdit(null); reload();
  });
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Maintenance planner</h1><span className="spacer" />
        <label className="inline">Show <select value={within} onChange={(e) => setWithin(e.target.value === "" ? "" : Number(e.target.value))}>
          <option value={0}>overdue</option><option value={30}>due in 30 days</option><option value={60}>due in 60 days</option><option value={90}>due in 90 days</option><option value="">everything</option></select></label>
        <button onClick={() => setEdit({ interval_months: 12, kind: data?.kinds[0] })}>+ Asset</button>
        <button className="primary" onClick={() => make(sel)}>{sel.length ? `Make jobs for ${sel.length}` : "Make jobs for everything shown"}</button>
      </div>
      {msg && <p className="ok">{msg}</p>}<ErrorLine error={error} />
      <section className="card">
        <DataTable rows={data?.assets ?? []} rowClass={(a) => (a.overdue ? "warn-row" : "")} cols={[
          { key: "x", label: "", render: (a) => <input type="checkbox" checked={sel.includes(a.id)} onChange={() => setSel(sel.includes(a.id) ? sel.filter((i) => i !== a.id) : [...sel, a.id])} /> },
          { key: "k", label: "Asset", render: (a) => <button className="link" onClick={() => setEdit(a)}>{a.kind}</button> },
          { key: "s", label: "Site", render: (a) => <>{a.site}<div className="small muted">{a.location}</div></> },
          { key: "n", label: "Serial", hideSm: true, render: (a) => a.serial },
          { key: "l", label: "Last service", render: (a) => fmtDate(a.last_service) },
          { key: "d", label: "Next due", render: (a) => <>{fmtDate(a.next_due)}{a.overdue && <span className="badge bad">overdue</span>}</> },
          { key: "p", label: "Price", num: true, hideSm: true, render: (a) => (a.service_price ? money(a.service_price) : "") },
        ]} />
        <p className="small muted">Jobs are made one per site (the way a tech does a round), with every due asset listed. When the tech fills in the test report on the
          phone against the asset, its next due date moves on by itself. <Link to="/work?status=scheduled">Scheduled jobs ›</Link></p>
      </section>
      {edit && (
        <Modal title={edit.id ? edit.kind ?? "" : "New asset"} onClose={() => setEdit(null)}>
          <Field label="Site"><select value={edit.site_id ?? ""} onChange={(e) => setEdit({ ...edit, site_id: Number(e.target.value) })}>
            <option value="">Choose…</option>{sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name} – {s.address}</option>)}</select></Field>
          <Field label="Type"><select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{data?.kinds.map((k) => <option key={k}>{k}</option>)}</select></Field>
          <div className="settings-grid">
            {(["location", "make", "model", "serial"] as const).map((k) => <Field key={k} label={k}><input value={String(edit[k] ?? "")} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></Field>)}
            <Field label="Service every (months)"><input type="number" min={1} value={edit.interval_months} onChange={(e) => setEdit({ ...edit, interval_months: Number(e.target.value) })} /></Field>
            <Field label="Last serviced"><input type="date" value={edit.last_service ?? ""} onChange={(e) => setEdit({ ...edit, last_service: e.target.value })} /></Field>
            <Field label="Next due"><input type="date" value={edit.next_due ?? ""} onChange={(e) => setEdit({ ...edit, next_due: e.target.value })} /></Field>
            <Field label="Price per service (ex GST)"><input type="number" value={edit.service_price ?? ""} onChange={(e) => setEdit({ ...edit, service_price: e.target.value ? Number(e.target.value) : null })} /></Field>
          </div>
          <button className="primary" disabled={!edit.site_id} onClick={save}>Save</button><ErrorLine error={error} />
        </Modal>
      )}
    </main>
  );
}
