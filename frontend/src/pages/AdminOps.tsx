/* Admin portal: Xero and messaging, operations settings, plant rules and form templates. */
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorLine, Field, useAction, useLoad } from "../ui";

interface XeroStatus {
  configured: boolean; status: string; organisation: string; last_sync: string | null; last_error: string; redirect_uri: string; scopes: string;
  settings: Record<string, string | boolean>; log: { at: string; errors: string[]; [k: string]: unknown }[];
}

export function Integrations() {
  const { data, reload } = useLoad<{ xero: XeroStatus }>("/api/integrations");
  const crm = useLoad<{ email_ready: boolean; sms_ready: boolean }>("/api/crm/settings");
  const [run, error, busy] = useAction();
  const [msg, setMsg] = useState("");
  const q = new URLSearchParams(window.location.search);
  const x = data?.xero;
  const [s, setS] = useState<Record<string, string | boolean>>({});
  useEffect(() => { if (x) setS(x.settings); }, [x]);
  if (!x) return null;
  const connect = () => run(async () => { const r = await api.get<{ url: string }>("/api/integrations/xero/connect"); window.location.href = r.url; });
  return (
    <div className="admin-grid">
      <section className="card">
        <h2>Xero</h2>
        {q.get("xero") === "connected" && <p className="ok">Connected to Xero.</p>}
        {q.get("xero_error") && <p className="error">Xero: {q.get("xero_error")}</p>}
        {!x.configured ? (
          <div className="small">
            <p>To connect, someone with access to the server makes a Xero app once (about 5 minutes):</p>
            <ol>
              <li>Sign in at <b>developer.xero.com</b> → My Apps → New app → <b>Web app</b>.</li>
              <li>Redirect URI: <code>{x.redirect_uri}</code></li>
              <li>Copy the Client ID and a Client secret into the server's <code>.env</code> as <code>XERO_CLIENT_ID</code> and <code>XERO_CLIENT_SECRET</code>,
                then run <code>sudo docker compose up -d</code>. Full steps: <code>deploy/XERO.md</code>.</li>
            </ol>
          </div>
        ) : (
          <>
            <p>Status: <b className={x.status === "connected" ? "ok" : x.status === "error" ? "error" : ""}>{x.status}</b>
              {x.organisation && <> · {x.organisation}</>} {x.last_sync && <span className="muted small">· last sync {new Date(x.last_sync).toLocaleString("en-AU")}</span>}</p>
            {x.last_error && <p className="error small">{x.last_error}</p>}
            <div className="row wrap">
              <button className="primary" onClick={connect} disabled={busy}>{x.status === "connected" ? "Reconnect" : "Connect to Xero"}</button>
              {x.status !== "disconnected" && <button onClick={() => run(async () => { const r = await api.post<{ errors: string[] }>("/api/integrations/xero/sync"); setMsg(r.errors.length ? r.errors.join("; ") : "Synced."); reload(); })}>Sync now</button>}
              {x.status !== "disconnected" && <button className="link" onClick={() => window.confirm("Disconnect Xero?") && run(async () => { await api.post("/api/integrations/xero/disconnect"); reload(); })}>Disconnect</button>}
            </div>
            {msg && <p className="small">{msg}</p>}
          </>
        )}
        <h3>What's kept in step</h3>
        <ul className="small">
          <li>Invoices sent here go to Xero as sales invoices (same number, job number in the reference).</li>
          <li>Payments made in Xero mark the invoice paid here.</li>
          <li>Supplier bills in Xero quoting one of our PO numbers bill that PO; bills quoting a job number become a cost on the job.</li>
          <li>Sales invoices raised in Xero with a job number count towards that job.</li>
          <li>The Xero bank balance becomes the cash flow forecast's opening balance.</li>
        </ul>
        <div className="settings-grid">
          <Field label="Sales account code"><input value={String(s.sales_account ?? "")} onChange={(e) => setS({ ...s, sales_account: e.target.value })} /></Field>
          <Field label="Retention account code" hint="blank = sales account"><input value={String(s.retention_account ?? "")} onChange={(e) => setS({ ...s, retention_account: e.target.value })} /></Field>
          <Field label="Invoices arrive in Xero as">
            <select value={String(s.invoice_status)} onChange={(e) => setS({ ...s, invoice_status: e.target.value })}>
              <option value="AUTHORISED">Approved</option><option value="SUBMITTED">Awaiting approval</option><option value="DRAFT">Draft</option>
            </select>
          </Field>
          <Field label="Tax type"><input value={String(s.tax_type ?? "")} onChange={(e) => setS({ ...s, tax_type: e.target.value })} /></Field>
        </div>
        <div className="row wrap">
          {[["push_invoices", "Send invoices"], ["pull_payments", "Bring in payments"], ["pull_bills", "Bring in supplier bills"],
            ["pull_sales", "Bring in Xero sales invoices"], ["pull_bank", "Bank balance"]].map(([k, l]) => (
            <label key={k} className="inline"><input type="checkbox" checked={!!s[k]} onChange={(e) => setS({ ...s, [k]: e.target.checked })} /> {l}</label>
          ))}
        </div>
        <button onClick={() => run(async () => { await api.put("/api/integrations/xero", s); setMsg("Saved."); reload(); })}>Save Xero settings</button>
        {x.log.length > 0 && (
          <details className="small"><summary>Recent syncs</summary>
            {x.log.map((l, i) => <div key={i}>{new Date(l.at).toLocaleString("en-AU")}: {Object.entries(l).filter(([k]) => !["at", "errors"].includes(k)).map(([k, v]) => `${k} ${v}`).join(", ")}
              {l.errors.length > 0 && <span className="error"> {l.errors.join("; ")}</span>}</div>)}
          </details>
        )}
        <ErrorLine error={error} />
      </section>
      <section className="card">
        <h2>Reece maX and other suppliers</h2>
        <p className="small">Reece only lets approved partner software connect to maX directly. Until Peak is approved, download the price file
          from maX each month (maX → Account → Price file) and load it under <b>Purchasing → Supplier prices</b>, the same as every other
          supplier's CSV or Excel price list. The app remembers each supplier's columns.</p>
        <h2>Email and text messages</h2>
        <p className="small">Used for customer follow-ups, feedback requests and reminders.</p>
        <p>Email: <b className={crm.data?.email_ready ? "ok" : "warn"}>{crm.data?.email_ready ? "ready" : "not set up"}</b> ·
          Text messages: <b className={crm.data?.sms_ready ? "ok" : "warn"}>{crm.data?.sms_ready ? "ready" : "not set up"}</b></p>
        <p className="small muted">Set <code>SMTP_HOST</code>, <code>SMTP_USER</code>, <code>SMTP_PASSWORD</code> and <code>SMTP_FROM</code> (e.g. Microsoft 365) for
          email, and <code>CLICKSEND_USERNAME</code> / <code>CLICKSEND_API_KEY</code> for texts, in the server's <code>.env</code>. Messages wait in the
          queue until they're set up.</p>
      </section>
    </div>
  );
}

const OPS_FIELDS: [string, string, string, "text" | "number"][] = [
  ["company_name", "Company name", "On invoices, POs and messages", "text"],
  ["google_review_url", "Google review link", "Where happy customers are sent (Google Business Profile → Ask for reviews)", "text"],
  ["job_prefix", "Job number prefix", "J → J26-0001", "text"],
  ["invoice_prefix", "Invoice number prefix", "", "text"],
  ["default_terms_days", "Payment terms (days)", "For customers with no terms set", "number"],
  ["default_cost_rate", "Default labour cost $/h", "For staff with no cost rate", "number"],
  ["default_charge_rate", "Charge-out rate $/h", "Do-and-charge jobs", "number"],
  ["charge_materials_markup_pct", "Markup % on other costs (do-and-charge)", "Bills and costs that aren't stock items", "number"],
  ["stock_markup_pct", "Stock margin %", "Materials used from stock: price-file cost plus this", "number"],
  ["civil_budget_margin_pct", "Civil budget: margin taken off BOQ %", "", "number"],
  ["overtime_weekly_hours", "Overtime after (hours / week)", "", "number"],
  ["overtime_daily_hours", "Overtime after (hours / day)", "0 = weekly only", "number"],
  ["tolerance_pct", "Dashboard tolerance %", "How far over the pro-rata forecast before it goes red", "number"],
  ["opening_bank_balance", "Bank balance (cash flow start)", "Filled by Xero when connected", "number"],
];

export function OpsSettings() {
  const { data, reload } = useLoad<Record<string, unknown>>("/api/ops-settings");
  const plant = useLoad<{ settings: Record<string, boolean | number> }>("/api/plant");
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [pform, setP] = useState<Record<string, boolean | number>>({});
  const [run, error] = useAction();
  const [msg, setMsg] = useState("");
  const [groupsTxt, setGroupsTxt] = useState("");
  useEffect(() => { if (data) { setForm(data); setGroupsTxt(groupText(data.markup_by_group)); } }, [data]);
  useEffect(() => { if (plant.data) setP(plant.data.settings); }, [plant.data]);
  if (!data) return null;
  return (
    <div className="admin-grid">
      <section className="card">
        <h2>Operations settings</h2>
        <div className="settings-grid">
          {OPS_FIELDS.map(([k, label, hint, type]) => (
            <Field key={k} label={label} hint={hint}>
              <input type={type} value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: type === "number" ? Number(e.target.value) : e.target.value })} />
            </Field>
          ))}
        </div>
        <Field label="Margin by product group (one per line: group = %)" hint="Groups as they're named in the supplier price files, e.g. Hot water = 15">
          <textarea rows={4} value={groupsTxt} onChange={(e) => setGroupsTxt(e.target.value)} />
        </Field>
        <button className="primary" onClick={() => run(async () => {
          const body = { ...Object.fromEntries(OPS_FIELDS.map(([k]) => [k, form[k]])), markup_by_group: parseGroups(groupsTxt) };
          await api.put("/api/ops-settings", body); setMsg("Saved."); reload();
        })}>Save</button> {msg && <span className="ok small">{msg}</span>}
        <ErrorLine error={error} />
      </section>
      <section className="card">
        <h2>Plant and vehicle rules</h2>
        {[["weekly_vehicle_prestart", "Company vehicle: no clocking in each week until the weekly pre-start is done"],
          ["plant_photos", "Machines: photos of the machine and fuel gauge at the start and end of each day"],
          ["wash_monthly", "Monthly wash reminder with photos of the outside and inside"]].map(([k, l]) => (
          <label key={k} className="check-line"><input type="checkbox" checked={!!pform[k]} onChange={(e) => setP({ ...pform, [k]: e.target.checked })} /> {l}</label>
        ))}
        <Field label="Block clocking in if the wash isn't done by day" hint="0 = reminder only">
          <input type="number" min={0} max={28} value={Number(pform.wash_block_after_days ?? 0)} onChange={(e) => setP({ ...pform, wash_block_after_days: Number(e.target.value) })} />
        </Field>
        <button onClick={() => run(async () => { await api.put("/api/plant-settings", pform); setMsg("Saved."); plant.reload(); })}>Save plant rules</button>
        <FormTemplates />
      </section>
    </div>
  );
}

interface Tpl { id: number; name: string; kind: string; active: boolean; fields: { key: string; label: string; type: string; options?: string[]; required?: boolean }[] }

function FormTemplates() {
  const { data, reload } = useLoad<Tpl[]>("/api/form-templates");
  const [edit, setEdit] = useState<{ id?: number; name: string; kind: string; text: string } | null>(null);
  const [run, error] = useAction();
  const toText = (t: Tpl) => t.fields.map((f) => `${f.label} | ${f.type}${f.options?.length ? " | " + f.options.join(", ") : ""}${f.required ? " | required" : ""}`).join("\n");
  const save = () => run(async () => {
    if (!edit) return;
    const fields = edit.text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [label, type = "yesno", opts = "", req = ""] = l.split("|").map((x) => x.trim());
      return { label, type, options: opts && opts !== "required" ? opts.split(",").map((o) => o.trim()) : [], required: opts === "required" || req === "required" };
    });
    const body = { name: edit.name, kind: edit.kind, fields, active: true };
    if (edit.id) await api.put(`/api/forms/templates/${edit.id}`, body); else await api.post("/api/forms/templates", body);
    setEdit(null); reload();
  });
  return (
    <>
      <h2 style={{ marginTop: 20 }}>Forms and checklists</h2>
      <p className="small muted">Pre-starts, SWMS, test reports and completion checklists the team fill in on their phones.</p>
      <ul className="plain">
        {data?.map((t) => <li key={t.id}><button className="link" onClick={() => setEdit({ id: t.id, name: t.name, kind: t.kind, text: toText(t) })}>{t.name}</button> <span className="muted small">{t.kind} · {t.fields.length} questions</span></li>)}
      </ul>
      <button onClick={() => setEdit({ name: "", kind: "checklist", text: "Area is safe to work | yesno\nNotes | text\nSignature | signature" })}>+ New form</button>
      {edit && (
        <div className="card" style={{ marginTop: 10 }}>
          <div className="row wrap">
            <input placeholder="Form name" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            <select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>
              {["checklist", "prestart", "swms", "inspection", "test", "completion"].map((k) => <option key={k}>{k}</option>)}
            </select>
          </div>
          <p className="small muted">One question per line: <code>Question | type | options | required</code>. Types: yesno, check, text, number, choice, signature, photo, heading.</p>
          <textarea rows={8} style={{ width: "100%" }} value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} />
          <div className="row"><button className="primary" onClick={save}>Save form</button><button className="link" onClick={() => setEdit(null)}>Cancel</button></div>
          <ErrorLine error={error} />
        </div>
      )}
    </>
  );
}

function groupText(v: unknown): string {
  return Object.entries((v as Record<string, number>) ?? {}).map(([k, n]) => `${k} = ${n}`).join("\n");
}
function parseGroups(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  text.split("\n").forEach((line) => {
    const m = /^(.+?)\s*[=:]\s*([\d.]+)\s*%?\s*$/.exec(line.trim());
    if (m) out[m[1].trim()] = Number(m[2]);
  });
  return out;
}
