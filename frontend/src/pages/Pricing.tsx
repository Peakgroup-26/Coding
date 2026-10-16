import { useCallback, useEffect, useState } from "react";
import { api, download } from "../api";
import { useApp } from "../App";
import type { Allowance, Mapping, Prebuild, PriceBook, PriceItem, Pricing, PricingJob, PricingLine } from "../types";
import { fmtMoney } from "../util";

export function PricingTab({ jobId, locked, onJobChange }: { jobId: number; locked: boolean; onJobChange: () => void }) {
  const [job, setJob] = useState<PricingJob | null>(null);
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [p, setP] = useState<Pricing | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    const [j, b] = await Promise.all([api.get<PricingJob>(`/api/jobs/${jobId}`), api.get<PriceBook[]>("/api/price-books")]);
    setJob(j); setBooks(b);
    try { setP(await api.get<Pricing>(`/api/jobs/${jobId}/pricing`)); } catch (e) { setError((e as Error).message); }
  }, [jobId]);
  useEffect(() => { load(); }, [load]);
  if (!job) return null;

  const s = p?.summary;
  return (
    <>
      <PricingSettings job={job} books={books} locked={locked} onSaved={() => { load(); onJobChange(); }} />
      {error && <p className="error">{error}</p>}
      {p && p.price_book && !p.price_book.locked && (
        <p className="warn">Price book "{p.price_book.label}" is still a draft. Lock it on the Price books page before sign-off.</p>
      )}
      {p && (p.unmapped.length > 0 || p.missing_codes.length > 0) && (
        <section className="card attention">
          <h2>Not priced yet</h2>
          <p className="small">These block sign-off and the Simpro export. Map each one to a prebuild or catalogue item; the mapping is reused on every job.</p>
          {p.missing_codes.length > 0 && <p className="bad small">Mapped codes not in this price book: {p.missing_codes.join(", ")}</p>}
          <table>
            <thead><tr><th>Take-off item</th><th>Service</th><th>Stage</th><th className="r">Qty</th><th>Map to</th></tr></thead>
            <tbody>
              {p.unmapped.map((u, i) => (
                <tr key={i}>
                  <td>{u.kind === "pipe" ? `${u.description} pipe` : u.description} <span className="muted small">({u.kind})</span></td>
                  <td>{u.service_code}</td><td>{u.stage}</td><td className="r">{u.qty} {u.uom}</td>
                  <td><QuickMap line={u} bookId={p.price_book?.id ?? null} disabled={locked} onMapped={load} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {s && (
        <section className="card">
          <div className="row wrap">
            <h2>Estimate</h2>
            <span className="muted">on {p!.price_book ? p!.price_book.label : "the workbook rates (no price book)"} · margins as {p!.margin_basis}</span>
            <span className="spacer" />
            <button onClick={() => download(`/api/jobs/${jobId}/simpro.csv`, "simpro.csv").catch((e) => setError(e.message))}
              disabled={!!(p!.unmapped.length || p!.missing_codes.length)}>Simpro CSV</button>
          </div>
          <div className="stats">
            <Stat label="Materials" v={fmtMoney(s.material_cost)} />
            <Stat label={`Labour (${s.labour_hours} h)`} v={fmtMoney(s.labour_cost)} />
            <Stat label="PC items & provisional sums" v={fmtMoney(s.allowances_cost)} />
            <Stat label="Cost" v={fmtMoney(s.cost)} />
            <Stat label="Margin" v={fmtMoney(s.margin)} />
            <Stat label="Total ex GST" v={fmtMoney(s.sell_ex_gst)} strong />
            <Stat label="GST" v={fmtMoney(s.gst)} />
            <Stat label="Total inc GST" v={fmtMoney(s.sell_inc_gst)} strong />
          </div>
          {!!s.loadings?.length && (
            <p className="small">
              Includes {fmtMoney(s.loading_cost ?? 0)} of loadings from the tender documents:{" "}
              {s.loadings.map((l) => `${l.label} +${l.percent}% ${l.applies_to}${l.service_codes.length ? ` (${l.service_codes.join(", ")})` : ""}`).join("; ")}.
            </p>
          )}
          {s.reference_total_ex_gst !== undefined && (
            <p className={Math.abs(s.reference_variance_pct ?? 0) <= 1 ? "ok" : "warn"}>
              Known estimate {fmtMoney(s.reference_total_ex_gst)} ex GST: this pricing is {s.reference_variance_pct}% {(s.reference_variance_pct ?? 0) >= 0 ? "above" : "below"} it.
            </p>
          )}
          <div className="two-col even">
            <table className="r-cols">
              <thead><tr><th>Stage</th><th>Hours</th><th>Cost</th><th>Sell ex GST</th></tr></thead>
              <tbody>{s.by_stage.map((r) => <tr key={r.stage}><td>{r.stage}</td><td>{r.labour_hours ?? 0}</td><td>{fmtMoney(r.cost)}</td><td>{fmtMoney(r.sell)}</td></tr>)}</tbody>
            </table>
            <table className="r-cols">
              <thead><tr><th>Service</th><th>Hours</th><th>Cost</th><th>Sell ex GST</th></tr></thead>
              <tbody>{s.by_service.map((r) => <tr key={r.service_code}><td>{r.service_code}</td><td>{r.labour_hours ?? 0}</td><td>{fmtMoney(r.cost)}</td><td>{fmtMoney(r.sell)}</td></tr>)}</tbody>
            </table>
          </div>
          <h3>Lines</h3>
          <table className="r-cols-5">
            <thead><tr><th>Stage</th><th>Svc</th><th>Take-off item</th><th>Priced as</th><th>Qty</th><th>Material</th><th>Labour</th><th>Cost</th><th>Margin</th><th>Sell</th></tr></thead>
            <tbody>
              {p!.lines.map((l, i) => (
                <tr key={i}>
                  <td>{l.stage}</td><td>{l.service_code}</td>
                  <td>{l.kind === "pipe" ? `${l.description} pipe` : l.description}</td>
                  <td className="small">{l.target_code} <span className="muted">{l.target_description}</span>{l.missing?.length ? <span className="bad"> missing {l.missing.join(", ")}</span> : null}</td>
                  <td>{round(l.target_qty ?? l.qty)} {l.factor === 1 ? l.uom : ""}</td>
                  <td>{fmtMoney(l.material_cost)}</td><td>{fmtMoney(l.labour_cost)}<div className="muted small">{l.labour_hours} h</div></td>
                  <td>{fmtMoney(l.cost)}</td><td>{l.margin_pct}%</td><td><b>{fmtMoney(l.sell)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {p && !p.price_book && <p className="muted">Choose a price book above to price this job.</p>}

      <Allowances jobId={jobId} locked={locked} rows={p?.allowances ?? []} onChange={load} />
      <GoldenCompare jobId={jobId} />
    </>
  );
}

const round = (n: number) => Math.round(n * 1000) / 1000;

function Stat({ label, v, strong }: { label: string; v: string; strong?: boolean }) {
  return <div className={strong ? "stat strong" : "stat"}><div className="muted small">{label}</div><div>{v}</div></div>;
}

function PricingSettings({ job, books, locked, onSaved }: { job: PricingJob; books: PriceBook[]; locked: boolean; onSaved: () => void }) {
  const { settings } = useApp();
  const [f, setF] = useState(() => ({
    price_book_version_id: job.price_book_version_id, margin_basis: job.margin_basis, default_margin_pct: job.default_margin_pct,
    service_margins: { ...(job.service_margins ?? {}) } as Record<string, number | null>,
    stage_margins: { ...(job.stage_margins ?? {}) } as Record<string, number | null>,
    gst_pct: job.gst_pct, reference_total_ex_gst: job.reference_total_ex_gst,
  }));
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const save = async () => {
    setError("");
    try { await api.put(`/api/jobs/${job.id}/pricing-settings`, f); onSaved(); } catch (e) { setError((e as Error).message); }
  };
  const pct = (v: string) => (v.trim() === "" ? null : Number(v));
  return (
    <section className="card">
      <div className="row wrap">
        <label>Price book
          <select disabled={locked} value={f.price_book_version_id ?? ""} onChange={(e) => setF({ ...f, price_book_version_id: Number(e.target.value) || null })}>
            <option value="">Not priced</option>
            {books.map((b) => <option key={b.id} value={b.id}>{b.label}{b.locked ? "" : " (draft)"}</option>)}
          </select>
        </label>
        <label>Margins as
          <select disabled={locked} value={f.margin_basis} onChange={(e) => setF({ ...f, margin_basis: e.target.value as "markup" | "margin" })}>
            <option value="markup">Markup on cost</option>
            <option value="margin">Margin on sell</option>
          </select>
        </label>
        <label>Default %<input className="tiny" type="number" disabled={locked} value={f.default_margin_pct} onChange={(e) => setF({ ...f, default_margin_pct: Number(e.target.value) })} /></label>
        <label>GST %<input className="tiny" type="number" disabled={locked} value={f.gst_pct} onChange={(e) => setF({ ...f, gst_pct: Number(e.target.value) })} /></label>
        <label>Known estimate ex GST
          <input className="small-input" type="number" disabled={locked} placeholder="for comparison" value={f.reference_total_ex_gst ?? ""}
            onChange={(e) => setF({ ...f, reference_total_ex_gst: pct(e.target.value) })} />
        </label>
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide" : "Service and stage margins"}</button>
        <span className="spacer" />
        <button className="primary" disabled={locked} onClick={save}>Save pricing settings</button>
      </div>
      <p className="muted small">Markup: sell = cost × (1 + %). Margin: sell = cost ÷ (1 − %). A stage margin overrides a service margin, which overrides the default.</p>
      {open && (
        <div className="two-col even">
          <div>
            <h3>By service</h3>
            <div className="grid-pct">
              {settings.services.map((s) => (
                <label key={s.id} className="inline">{s.code}
                  <input className="tiny" type="number" disabled={locked} placeholder="default" value={f.service_margins[s.code] ?? ""}
                    onChange={(e) => setF({ ...f, service_margins: { ...f.service_margins, [s.code]: pct(e.target.value) } })} />
                </label>
              ))}
            </div>
          </div>
          <div>
            <h3>By stage</h3>
            <div className="grid-pct">
              {settings.stages.map((s) => (
                <label key={s.id} className="inline">{s.name}
                  <input className="tiny" type="number" disabled={locked} placeholder="–" value={f.stage_margins[s.name] ?? ""}
                    onChange={(e) => setF({ ...f, stage_margins: { ...f.stage_margins, [s.name]: pct(e.target.value) } })} />
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function QuickMap({ line, bookId, disabled, onMapped }: { line: PricingLine; bookId: number | null; disabled: boolean; onMapped: () => void }) {
  const [kind, setKind] = useState<"prebuild" | "item">(line.kind === "fitting" ? "item" : "prebuild");
  const [code, setCode] = useState("");
  const [factor, setFactor] = useState("1");
  const [anyService, setAnyService] = useState(false);
  const [options, setOptions] = useState<{ code: string; description: string }[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!bookId || code.length < 1) { setOptions([]); return; }
    const t = setTimeout(() => {
      api.get<(Prebuild | PriceItem)[]>(`/api/price-books/${bookId}/${kind === "prebuild" ? "prebuilds" : "items"}?search=${encodeURIComponent(code)}&limit=20`)
        .then((r) => setOptions(r.map((x) => ({ code: x.code, description: x.description }))));
    }, 200);
    return () => clearTimeout(t);
  }, [bookId, kind, code]);
  const save = async () => {
    setError("");
    const body = {
      source_kind: line.kind, service_code: anyService ? "" : line.service_code, target_kind: kind, target_code: code.trim(),
      factor: Number(factor) || 1, material: line.material, dn: line.dn, item_type: line.item_type,
      description: line.kind === "fitting" ? line.description : "",
    };
    try { await api.post<Mapping>("/api/mappings", body); onMapped(); } catch (e) { setError((e as Error).message); }
  };
  const listId = `opts-${line.kind}-${line.description}-${line.service_code}-${line.stage}`.replace(/\W/g, "");
  return (
    <div className="row wrap tight">
      <select disabled={disabled} value={kind} onChange={(e) => setKind(e.target.value as "prebuild" | "item")}>
        <option value="prebuild">Prebuild</option><option value="item">Catalogue item</option>
      </select>
      <input disabled={disabled} list={listId} placeholder="Code" value={code} onChange={(e) => setCode(e.target.value)} />
      <datalist id={listId}>{options.map((o) => <option key={o.code} value={o.code}>{o.description}</option>)}</datalist>
      <label className="inline small" title="Target quantity per take-off unit">×<input className="tiny" disabled={disabled} value={factor} onChange={(e) => setFactor(e.target.value)} /></label>
      <label className="inline small"><input type="checkbox" checked={anyService} onChange={(e) => setAnyService(e.target.checked)} />any service</label>
      <button disabled={disabled || !code.trim()} onClick={save}>Map</button>
      {error && <span className="error small">{error}</span>}
    </div>
  );
}

function Allowances({ jobId, locked, rows, onChange }: { jobId: number; locked: boolean; rows: Allowance[]; onChange: () => void }) {
  const { settings } = useApp();
  const [f, setF] = useState({ kind: "pc", description: "", amount: "", stage_id: "", apply_margin: true });
  const [error, setError] = useState("");
  const add = async () => {
    setError("");
    try {
      await api.post(`/api/jobs/${jobId}/allowances`, { kind: f.kind, description: f.description, amount: Number(f.amount || 0),
        stage_id: f.stage_id ? Number(f.stage_id) : null, apply_margin: f.apply_margin });
      setF({ ...f, description: "", amount: "" });
      onChange();
    } catch (e) { setError((e as Error).message); }
  };
  const del = async (a: Allowance) => {
    try { await api.del(`/api/allowances/${a.id}`); onChange(); } catch (e) { setError((e as Error).message); }
  };
  const label = { pc: "PC item", provisional: "Provisional sum", exclusion: "Exclusion" };
  return (
    <section className="card">
      <h2>PC items, provisional sums and exclusions</h2>
      <table className="r-cols-4">
        <thead><tr><th>Type</th><th>Description</th><th>Stage</th><th>Amount</th><th>Sell</th><th></th></tr></thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{label[a.kind]}</td><td>{a.description}</td><td>{a.kind !== "exclusion" ? a.stage : ""}</td>
              <td>{a.kind !== "exclusion" ? fmtMoney(a.amount) : ""}</td>
              <td>{a.kind !== "exclusion" ? <>{fmtMoney(a.sell)} <span className="muted small">{a.apply_margin ? `+${a.margin_pct}%` : "no margin"}</span></> : ""}</td>
              <td>{!locked && <button className="link" onClick={() => del(a)}>Delete</button>}</td>
            </tr>
          ))}
          {!locked && (
            <tr>
              <td>
                <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                  <option value="pc">PC item</option><option value="provisional">Provisional sum</option><option value="exclusion">Exclusion</option>
                </select>
              </td>
              <td><input placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></td>
              <td>
                {f.kind !== "exclusion" && (
                  <select value={f.stage_id} onChange={(e) => setF({ ...f, stage_id: e.target.value })}>
                    <option value="">–</option>
                    {settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                )}
              </td>
              <td>{f.kind !== "exclusion" && <input className="small-input" type="number" placeholder="$ ex GST" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />}</td>
              <td>{f.kind !== "exclusion" && <label className="inline small"><input type="checkbox" checked={f.apply_margin} onChange={(e) => setF({ ...f, apply_margin: e.target.checked })} /> add margin</label>}</td>
              <td><button disabled={!f.description || (f.kind !== "exclusion" && !(Number(f.amount) > 0))} onClick={add}>Add</button></td>
            </tr>
          )}
        </tbody>
      </table>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

type Golden = {
  has_reference: boolean;
  services: { service_code: string; reference_m: number; takeoff_m: number; variance_pct: number | null }[];
  detail: { service_code: string; dn: number | null; material: string; reference_m: number; takeoff_m: number; variance_pct: number | null }[];
  price?: { reference_total_ex_gst: number; priced_ex_gst: number; variance_pct: number | null };
};

function GoldenCompare({ jobId }: { jobId: number }) {
  const [g, setG] = useState<Golden | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.get<Golden>(`/api/jobs/${jobId}/golden-report`).then(setG), [jobId]);
  useEffect(() => { load(); }, [load]);
  const upload = async (files: FileList | null) => {
    if (!files?.[0]) return;
    const fd = new FormData();
    fd.append("file", files[0]);
    try { await api.post(`/api/jobs/${jobId}/reference`, fd); load(); } catch (e) { setError((e as Error).message); }
  };
  const v = (x: number | null) => (x === null ? "–" : `${x > 0 ? "+" : ""}${x}%`);
  return (
    <section className="card">
      <div className="row wrap">
        <h2>Compare with a completed job</h2>
        <span className="spacer" />
        <label className="upload">
          <input type="file" accept=".csv,.xlsx" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
          <span className="button">Upload known quantities</span>
        </label>
      </div>
      <p className="muted small">For the golden-job test: upload Peak's final take-off for this job as CSV or Excel with columns service, dn, material, qty (metres). dn and material can be blank to compare a whole service.</p>
      {error && <p className="error">{error}</p>}
      {g?.has_reference && (
        <div className="two-col even">
          <table className="r-cols">
            <thead><tr><th>Service</th><th>Known (m)</th><th>Take-off (m)</th><th>Variance</th></tr></thead>
            <tbody>{g.services.map((s) => <tr key={s.service_code}><td>{s.service_code}</td><td>{s.reference_m}</td><td>{s.takeoff_m}</td><td className={Math.abs(s.variance_pct ?? 100) > 5 ? "warn" : ""}>{v(s.variance_pct)}</td></tr>)}</tbody>
          </table>
          {g.detail.length > 0 && (
            <table className="r-cols">
              <thead><tr><th>Line</th><th>Known (m)</th><th>Take-off (m)</th><th>Variance</th></tr></thead>
              <tbody>{g.detail.map((d, i) => <tr key={i}><td>{d.service_code} {d.material} {d.dn ? `DN${d.dn}` : ""}</td><td>{d.reference_m}</td><td>{d.takeoff_m}</td><td>{v(d.variance_pct)}</td></tr>)}</tbody>
            </table>
          )}
        </div>
      )}
      {g?.price && <p>Price: known {fmtMoney(g.price.reference_total_ex_gst)} vs {fmtMoney(g.price.priced_ex_gst)} ex GST ({v(g.price.variance_pct)}).</p>}
    </section>
  );
}
