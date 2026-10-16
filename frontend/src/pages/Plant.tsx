/* Plant and vehicles: the register, this week's pre-starts and washes, defects, photos and service / rego due. */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fetchBlobUrl } from "../api";
import { PdfShare } from "./Share";
import { DataTable, ErrorLine, Field, fmtDate, Modal, money, num, Status, useAction, useLoad } from "../ui";

interface PlantRow { id: number; kind: string; name: string; fleet_no: string; category: string; rego: string; make: string; model: string; year: number | null; serial: string;
  assigned_user_id: number | null; assigned_to: string; hours: number | null; odometer: number | null; service_every_hours: number | null; service_every_km: number | null;
  last_service_hours: number | null; last_service_km: number | null; next_service_date: string | null; rego_expiry: string | null; insurance_expiry: string | null;
  status: string; hire_rate: number; photos_required: boolean; notes: string; due: string[]; open_defects: number;
  last_check: { kind: string; at: string; passed: boolean; by: string } | null; weekly_done: boolean | null; wash_done: boolean | null; checklist_id: number | null }
interface Detail extends PlantRow { operated_hours: number;
  checks: { id: number; kind: string; at: string; by: string; passed: boolean; hours: number | null; odometer: number | null; fuel_pct: number | null; photo_ids: Record<string, number>; answers: Record<string, unknown> | null; notes: string }[];
  defects: { id: number; kind: string; severity: string; description: string; status: string; reported_at: string; by: string; photo_ids: number[]; repair_notes: string; repair_cost: number | null; fixed_at: string | null }[] }

const STATUS_LABELS = { in_service: "In service", out_of_service: "Out of service", in_repair: "In repair", sold: "Sold" };

export default function PlantPage() {
  const { plantId } = useParams();
  const nav = useNavigate();
  const { data, reload } = useLoad<{ plant: PlantRow[] }>("/api/plant");
  const [edit, setEdit] = useState<Partial<PlantRow> | null>(null);
  if (plantId) return <PlantDetail id={Number(plantId)} onEdit={setEdit} edit={edit} onSaved={() => { setEdit(null); reload(); }} />;
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Plant & vehicles</h1><span className="spacer" />
        <button className="primary" onClick={() => setEdit({ kind: "plant", status: "in_service", photos_required: true, hire_rate: 0 })}>+ Add plant or vehicle</button></div>
      <section className="card">
        <DataTable rows={data?.plant ?? []} onRow={(p) => nav(`/plant/${p.id}`)} rowClass={(p) => (p.status !== "in_service" ? "warn-row" : "")} cols={[
          { key: "n", label: "", render: (p) => <><b>{p.kind === "vehicle" ? "🚙" : p.kind === "trailer" ? "🛻" : "🚜"} {p.name}</b> <span className="small muted">{p.fleet_no} {p.rego}</span></> },
          { key: "a", label: "Driver / operator", render: (p) => p.assigned_to },
          { key: "s", label: "Status", render: (p) => <><Status value={p.status} labels={STATUS_LABELS} />{p.open_defects > 0 && <span className="badge bad">{p.open_defects} defect{p.open_defects > 1 ? "s" : ""}</span>}</> },
          { key: "c", label: "This week", render: (p) => p.kind === "vehicle"
            ? <span className="small">{p.weekly_done ? "✓ pre-start" : <span className="warn">no pre-start</span>} · {p.wash_done ? "✓ washed" : "wash due"}</span>
            : <span className="small">{p.last_check ? `${p.last_check.kind} ${fmtDate(p.last_check.at)} by ${p.last_check.by}` : "no checks yet"}</span> },
          { key: "r", label: "Reading", num: true, hideSm: true, render: (p) => (p.kind === "vehicle" ? (p.odometer ? `${num(p.odometer, 0)} km` : "") : (p.hours ? `${num(p.hours)} h` : "")) },
          { key: "d", label: "Due", render: (p) => p.due.map((d) => <span key={d} className="badge warn">{d}</span>) },
        ]} />
      </section>
      {edit && <PlantEditor p={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
    </main>
  );
}

function PlantDetail({ id, edit, onEdit, onSaved }: { id: number; edit: Partial<PlantRow> | null; onEdit: (p: Partial<PlantRow>) => void; onSaved: () => void }) {
  const { data: p, reload } = useLoad<Detail>(`/api/plant/${id}`);
  const [run, error] = useAction();
  const [photo, setPhoto] = useState("");
  if (!p) return <main className="page">Loading…</main>;
  const show = async (docId: number) => setPhoto(await fetchBlobUrl(`/api/files/${docId}`));
  return (
    <main className="page">
      <Link to="/plant" className="small">‹ Plant & vehicles</Link>
      <div className="row wrap"><h1 style={{ margin: 0 }}>{p.name}</h1><Status value={p.status} labels={STATUS_LABELS} /><span className="spacer" />
        <button onClick={() => onEdit(p)}>Edit</button></div>
      <p className="muted small">{[p.category, p.make, p.model, p.year, p.rego && `Rego ${p.rego}`, p.serial && `S/N ${p.serial}`, p.assigned_to && `Driven by ${p.assigned_to}`].filter(Boolean).join(" · ")}</p>
      <div className="tiles">
        <div className="tile"><b>{p.kind === "vehicle" ? `${num(p.odometer ?? 0, 0)} km` : `${num(p.hours ?? 0)} h`}</b><span>latest reading</span></div>
        <div className="tile"><b>{num(p.operated_hours)} h</b><span>clocked on jobs</span></div>
        {p.hire_rate > 0 && <div className="tile"><b>{money(p.hire_rate)}/h</b><span>charged to jobs</span></div>}
        {p.due.length > 0 && <div className="tile warn"><b>Due</b><span>{p.due.join(" · ")}</span></div>}
      </div>
      <div className="two-col even">
        <section className="card">
          <h2>Defects and damage</h2>
          {p.defects.length === 0 && <p className="muted small">None reported.</p>}
          {p.defects.map((d) => (
            <div key={d.id} className={`defect ${d.severity} ${d.status}`}>
              <div className="row wrap"><b>{d.kind} · {d.severity}</b><Status value={d.status} /><span className="spacer" /><small className="muted">{d.by} {new Date(d.reported_at).toLocaleString("en-AU")}</small></div>
              <p>{d.description}</p>
              <div className="row wrap">{d.photo_ids.map((pid) => <button key={pid} className="link small" onClick={() => show(pid)}>📷 photo</button>)}</div>
              {d.status !== "fixed" && d.status !== "no_action" && (
                <div className="row wrap">
                  <button className="small" onClick={() => run(async () => { await api.put(`/api/plant-defects/${d.id}`, { status: "in_repair" }); reload(); })}>In repair</button>
                  <button className="small" onClick={() => { const notes = window.prompt("What was done?") ?? ""; run(async () => { await api.put(`/api/plant-defects/${d.id}`, { status: "fixed", repair_notes: notes }); reload(); }); }}>Fixed</button>
                  <button className="link small" onClick={() => run(async () => { await api.put(`/api/plant-defects/${d.id}`, { status: "no_action" }); reload(); })}>No action needed</button>
                </div>
              )}
              {d.repair_notes && <p className="small ok">{d.repair_notes}</p>}
            </div>
          ))}
          <ErrorLine error={error} />
        </section>
        <section className="card">
          <h2>Pre-starts, photos and checks</h2>
          <DataTable rows={p.checks} cols={[
            { key: "w", label: "When", render: (c) => new Date(c.at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" }) },
            { key: "k", label: "Check", render: (c) => <>{c.kind.replace("_", " ")} {c.passed ? "✓" : <span className="error">✗ failed</span>}</> },
            { key: "b", label: "By", render: (c) => c.by },
            { key: "r", label: "Reading", hideSm: true, render: (c) => [c.hours && `${num(c.hours)} h`, c.odometer && `${num(c.odometer, 0)} km`, c.fuel_pct !== null && `fuel ${c.fuel_pct}%`].filter(Boolean).join(" · ") },
            { key: "p", label: "Photos", render: (c) => Object.entries(c.photo_ids).map(([k, v]) => <button key={k} className="link small" onClick={() => show(v)}>📷 {k}</button>) },
            { key: "pdf", label: "", render: (c) => <PdfShare kind="plant-check" id={c.id} title={`${p.name} ${c.kind.replace("_", " ")} ${fmtDate(c.at)}`} small /> },
          ]} />
        </section>
      </div>
      {photo && <Modal title="Photo" onClose={() => setPhoto("")} wide><img src={photo} alt="" style={{ maxWidth: "100%" }} /></Modal>}
      {edit && <PlantEditor p={edit} onClose={() => onSaved()} onSaved={() => { onSaved(); reload(); }} />}
    </main>
  );
}

function PlantEditor({ p, onClose, onSaved }: { p: Partial<PlantRow>; onClose: () => void; onSaved: () => void }) {
  const staff = useLoad<{ id: number; name: string }[]>("/api/staff");
  const [f, setF] = useState<Partial<PlantRow>>(p);
  const [run, error, busy] = useAction();
  const text = (k: keyof PlantRow, label: string, type = "text") => (
    <Field label={label}><input type={type} value={String(f[k] ?? "")} onChange={(e) => setF({ ...f, [k]: type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : type === "date" ? (e.target.value || null) : e.target.value })} /></Field>);
  const save = () => run(async () => {
    const keys = ["kind", "name", "fleet_no", "category", "rego", "make", "model", "year", "serial", "assigned_user_id", "hours", "odometer", "service_every_hours", "service_every_km",
      "last_service_hours", "last_service_km", "next_service_date", "rego_expiry", "insurance_expiry", "status", "hire_rate", "checklist_id", "photos_required", "notes"] as const;
    const body = Object.fromEntries(keys.map((k) => [k, f[k] ?? (k === "hire_rate" ? 0 : k === "photos_required" ? true : k === "notes" || k === "fleet_no" || k === "category" || k === "rego" || k === "make" || k === "model" || k === "serial" ? "" : null)]));
    if (p.id) await api.put(`/api/plant/${p.id}`, body); else await api.post("/api/plant", body);
    onSaved();
  });
  return (
    <Modal title={p.id ? `Edit ${p.name}` : "Add plant or vehicle"} onClose={onClose} wide>
      <div className="settings-grid">
        <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="plant">Plant / machine</option><option value="vehicle">Vehicle</option><option value="trailer">Trailer</option><option value="tool">Tool / equipment</option></select></Field>
        {text("name", "Name (e.g. 5t excavator, Hilux – Dave)")}{text("fleet_no", "Fleet no.")}{text("category", "Category (Excavator, Ute…)")}
        {text("rego", "Rego")}{text("make", "Make")}{text("model", "Model")}{text("year", "Year", "number")}{text("serial", "VIN / serial")}
        <Field label={f.kind === "vehicle" ? "Company vehicle driven by" : "Usual operator"}><select value={f.assigned_user_id ?? ""} onChange={(e) => setF({ ...f, assigned_user_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">–</option>{staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        {f.kind === "vehicle" ? text("odometer", "Odometer (km)", "number") : text("hours", "Hour meter", "number")}
        {f.kind === "vehicle" ? text("service_every_km", "Service every (km)", "number") : text("service_every_hours", "Service every (hours)", "number")}
        {f.kind === "vehicle" ? text("last_service_km", "Last service at (km)", "number") : text("last_service_hours", "Last service at (hours)", "number")}
        {text("next_service_date", "Next service date", "date")}{text("rego_expiry", "Rego expires", "date")}{text("insurance_expiry", "Insurance expires", "date")}
        {text("hire_rate", "Internal hire rate $/h (charged to jobs)", "number")}
        <Field label="Status"><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{Object.entries(STATUS_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
      </div>
      <label className="check-line"><input type="checkbox" checked={f.photos_required ?? true} onChange={(e) => setF({ ...f, photos_required: e.target.checked })} /> Photos of the machine and fuel gauge at the start and end of each day</label>
      <Field label="Notes"><textarea rows={2} value={f.notes ?? ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <button className="primary" onClick={save} disabled={busy || !f.name}>Save</button><ErrorLine error={error} />
    </Modal>
  );
}
