/* Live jobs: everything won or raised and not yet closed, with where each one is up to and how it's tracking. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { SalesSettings, Sector } from "../types";
import { DataTable, ErrorLine, Modal, money, num, pct, Status, todayIso, useAction, useLoad } from "../ui";
import { Chips } from "./Pick";

export interface WorkRow {
  id: number; job_no: string; quote_no: string; name: string; kind: string; sector: Sector; work_status: string; priority: string; customer: string;
  customer_id: number | null; site: string; address: string; order_no: string; work_type: string; description: string; billing: string;
  contract_value: number | null; start_date: string | null; finish_date: string | null; due_date: string | null; supervisor_id: number | null;
  percent_complete: number | null; retention_pct: number; contact: string; completed_at: string | null; signed_by_name: string; site_id: number | null;
  fin?: { revenue: number; cost_to_date: number; forecast_margin_pct: number | null; percent_complete: number; invoiced: number; hours_budget: number;
    hours_actual: number; over_budget: boolean; over_under_billed: number; budget_margin_pct: number | null };
}
export const WORK_LABELS: Record<string, string> = { scheduled: "Scheduled", in_progress: "In progress", on_hold: "On hold", complete: "Complete – to invoice",
  invoiced: "Invoiced", closed: "Closed" };

export default function WorkBoard() {
  const [status, setStatus] = useState("active");
  const [sector, setSector] = useState("");
  const [q, setQ] = useState("");
  const { data, reload } = useLoad<WorkRow[]>(`/api/work?status=${status}&sector=${sector}&q=${encodeURIComponent(q)}`, [status, sector, q]);
  const [adding, setAdding] = useState(false);
  const nav = useNavigate();
  return (
    <main className="page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Jobs</h1><span className="spacer" />
        <input placeholder="Search jobs" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="primary" onClick={() => setAdding(true)}>+ New job</button>
      </div>
      <div className="tabs scroll">
        {[["active", "Active"], ["scheduled", "Scheduled"], ["in_progress", "In progress"], ["on_hold", "On hold"], ["complete", "To invoice"],
          ["invoiced", "Invoiced"], ["closed", "Closed"], ["", "All"]].map(([k, l]) => (
          <button key={k} className={status === k ? "active" : ""} onClick={() => setStatus(k)}>{l}</button>))}
        <span className="spacer" />
        {[["", "All sectors"], ["residential", "Residential"], ["commercial", "Commercial"], ["maintenance", "Maintenance"]].map(([k, l]) => (
          <button key={k} className={sector === k ? "active" : ""} onClick={() => setSector(k)}>{l}</button>))}
      </div>
      <section className="card">
        <DataTable rows={data ?? []} onRow={(r) => nav(`/work/${r.id}`)} rowClass={(r) => (r.fin?.over_budget ? "warn-row" : "")} empty="No jobs here."
          cols={[
            { key: "no", label: "Job", render: (r) => <><b>{r.job_no}</b> {r.priority === "urgent" && <span className="badge bad">Urgent</span>}</> },
            { key: "name", label: "Name", render: (r) => <>{r.name}<div className="small muted">{r.customer}</div></> },
            { key: "st", label: "Status", render: (r) => <Status value={r.work_status} labels={WORK_LABELS} /> },
            { key: "pc", label: "% done", num: true, render: (r) => pct(r.fin?.percent_complete) },
            { key: "hrs", label: "Hours (act / budget)", num: true, hideSm: true, render: (r) => `${num(r.fin?.hours_actual)} / ${num(r.fin?.hours_budget)}` },
            { key: "rev", label: "Revenue", num: true, hideSm: true, render: (r) => money(r.fin?.revenue) },
            { key: "cost", label: "Cost to date", num: true, hideSm: true, render: (r) => money(r.fin?.cost_to_date) },
            { key: "m", label: "Forecast margin", num: true, render: (r) => <span className={(r.fin?.forecast_margin_pct ?? 99) < (r.fin?.budget_margin_pct ?? 0) - 0.5 ? "warn" : ""}>{pct(r.fin?.forecast_margin_pct)}</span> },
            { key: "inv", label: "Invoiced", num: true, hideSm: true, render: (r) => money(r.fin?.invoiced) },
          ]} />
      </section>
      {adding && <NewJob onClose={() => setAdding(false)} onMade={(id) => { reload(); nav(`/work/${id}`); }} />}
    </main>
  );
}

interface Cust { id: number; name: string; kind: string }

export function NewJob({ onClose, onMade, defaults }: { onClose: () => void; onMade: (id: number) => void; defaults?: Partial<Record<string, unknown>> }) {
  const sales = useLoad<SalesSettings>("/api/sales/settings");
  const [cq, setCq] = useState("");
  const custs = useLoad<Cust[]>(cq.length >= 2 ? `/api/customers?q=${encodeURIComponent(cq)}` : null, [cq]);
  const [f, setF] = useState({ sector: "maintenance", kind: "hydraulic", customer_id: null as number | null, customer_name: "", customer_kind: "maintenance",
    address: "", contact: "", work_type: "", priority: "normal", billing: "charge", contract_value: "", description: "", order_no: "",
    start_date: todayIso(), finish_date: "", name: "", ...defaults });
  const [run, error, busy] = useAction();
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const kinds = [["residential", "Residential"], ["maintenance", "Maintenance"], ["strata", "Strata / real estate"], ["builder", "Builder"],
    ["commercial", "Commercial client"], ["civil", "Civil client"], ["government", "Government"]];
  return (
    <Modal title="New job" onClose={onClose} wide>
      <div className="q-grid">
        <span className="q">Sector</span>
        <Chips options={(sales.data?.sectors ?? []).map((s) => ({ key: s.key, label: s.label }))} value={f.sector as Sector} required
               onChange={(v) => setF((x) => ({ ...x, sector: v || x.sector, work_type: "", billing: v === "maintenance" ? "charge" : "fixed" }))} />
        <span className="q">Job type</span>
        <Chips options={[{ key: "hydraulic", label: "Plumbing / gas" }, { key: "civil", label: "Civil" }]} value={f.kind as "hydraulic"} required onChange={(v) => set("kind", v || f.kind)} />
        <span className="q">Customer</span>
        <div>
          {f.customer_id ? <p><b>{f.customer_name}</b> <button className="link small" onClick={() => setF((x) => ({ ...x, customer_id: null, customer_name: "" }))}>change</button></p> : (
            <>
              <input placeholder="Search customers, or type a new one" value={cq} onChange={(e) => { setCq(e.target.value); set("customer_name", e.target.value); }} />
              <div className="pick-list small">{custs.data?.slice(0, 6).map((c) => (
                <button key={c.id} className="chip" onClick={() => setF((x) => ({ ...x, customer_id: c.id, customer_name: c.name }))}>{c.name}</button>))}</div>
              {cq && !custs.data?.some((c) => c.name.toLowerCase() === cq.toLowerCase()) && (
                <div className="small">New customer: <Chips options={kinds.map(([k, l]) => ({ key: k, label: l }))} value={f.customer_kind as "residential"} required
                                                       onChange={(v) => set("customer_kind", v || f.customer_kind)} /></div>
              )}
            </>
          )}
        </div>
        <span className="q">Site address</span><input value={f.address} onChange={(e) => set("address", e.target.value)} placeholder="Street, suburb" />
        <span className="q">Type of work</span>
        <Chips options={sales.data?.work_types[f.sector as Sector] ?? []} value={f.work_type} onChange={(v) => set("work_type", v)} />
        <span className="q">Priority</span>
        <Chips options={[{ key: "low", label: "Low" }, { key: "normal", label: "Normal" }, { key: "high", label: "High" }, { key: "urgent", label: "Urgent" }]}
               value={f.priority as "normal"} required onChange={(v) => set("priority", v || "normal")} />
        <span className="q">Billing</span>
        <Chips options={[{ key: "charge", label: "Do and charge (time & materials)" }, { key: "fixed", label: "Fixed price / quoted" }]} value={f.billing as "charge"} required
               onChange={(v) => set("billing", v || f.billing)} />
        <span className="q">{f.billing === "fixed" ? "Price (ex GST)" : "Not to exceed (optional)"}</span>
        <input type="number" min={0} value={f.contract_value} onChange={(e) => set("contract_value", e.target.value)} />
        <span className="q">What's needed</span><textarea rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} placeholder="Fault, scope, access" />
        <span className="q">Contact on site</span><input value={f.contact} onChange={(e) => set("contact", e.target.value)} placeholder="Name and phone" />
        <span className="q">Client order no.</span><input value={f.order_no} onChange={(e) => set("order_no", e.target.value)} />
        <span className="q">Dates</span>
        <div className="row wrap"><input type="date" value={f.start_date} onChange={(e) => set("start_date", e.target.value)} /> to
          <input type="date" value={f.finish_date} onChange={(e) => set("finish_date", e.target.value)} /></div>
      </div>
      <div className="row"><button className="primary" disabled={busy || (!f.customer_id && !f.customer_name)} onClick={() => run(async () => {
        const r = await api.post<{ id: number }>("/api/work", { ...f, contract_value: f.contract_value ? Number(f.contract_value) : null,
          finish_date: f.finish_date || null, start_date: f.start_date || null });
        onMade(r.id);
      })}>Create job</button><button className="link" onClick={onClose}>Cancel</button></div>
      <ErrorLine error={error} />
      <p className="small muted">It gets a job number straight away and shows in the phone app for the team to clock into.</p>
    </Modal>
  );
}
