import { DragEvent, Fragment, useEffect, useRef, useState } from "react";
import { api, upload } from "../api";
import type { CivilRate, RateSet } from "../types";

const money = (n: number) => n.toLocaleString("en-AU", { style: "currency", currency: "AUD" });

export default function CivilRates() {
  const [sets, setSets] = useState<RateSet[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [rates, setRates] = useState<CivilRate[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = () => api.get<RateSet[]>("/api/civil/rate-sets").then(setSets);
  useEffect(() => { load(); }, []);

  const send = async (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    setError(""); setMsg(""); setBusy(true);
    const added: string[] = [];
    for (const f of files) {
      const form = new FormData();
      form.append("file", f);
      form.append("name", files.length === 1 ? name : "");
      try {
        const s = await upload<RateSet>("/api/civil/rate-sets", form);
        added.push(`${s.name} (${s.rates} rates)`);
      } catch (e) { setError(`${f.name}: ${(e as Error).message}`); }
    }
    if (added.length) setMsg(`Loaded ${added.join(", ")}.`);
    setName("");
    setBusy(false);
    load();
  };

  const show = async (id: number) => {
    if (open === id) { setOpen(null); return; }
    setRates(await api.get<CivilRate[]>(`/api/civil/rate-sets/${id}/rates`));
    setOpen(id);
  };
  const toggle = async (s: RateSet) => { await api.patch(`/api/civil/rate-sets/${s.id}`, { active: !s.active }); load(); };
  const remove = async (s: RateSet) => {
    if (!window.confirm(`Remove all ${s.rates} rates from "${s.name}"? Jobs already priced keep their rates.`)) return;
    await api.del(`/api/civil/rate-sets/${s.id}`);
    load();
  };
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (!busy) send(e.dataTransfer.files); };

  return (
    <main className="page">
      <h1>Previous civil job rates</h1>
      <p className="muted">
        Load the priced BOQs from your past civil jobs. New civil jobs are priced from these: each line gets the middle
        value of the matching past rates, and shows which jobs they came from.
      </p>
      <section className="card">
        <div className="row wrap">
          <input placeholder="Name for this job (optional, e.g. Smith St 2025)" value={name} onChange={(e) => setName(e.target.value)} style={{ minWidth: 320 }} />
        </div>
        <div className={`dropzone small-zone ${over ? "over" : ""} ${busy ? "busy" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
             onClick={() => !busy && input.current?.click()} role="button" tabIndex={0}>
          <h2>{busy ? "Loading…" : "Drop Excel or CSV BOQs here"}</h2>
          <p className="dz-hint">Any layout works as long as there's a header row with <b>Description</b> and <b>Rate</b> (Unit and Qty are used too). Section headings become categories.</p>
          <input ref={input} type="file" accept=".xlsx,.xlsm,.csv" multiple hidden onChange={(e) => send(e.target.files)} />
        </div>
        {error && <p className="error big">{error}</p>}
        {msg && <p className="ok big">{msg}</p>}
      </section>

      <section className="card">
        <table>
          <thead><tr><th>Job</th><th>File</th><th className="r">Rates</th><th>Loaded</th><th>Used for pricing</th><th></th></tr></thead>
          <tbody>
            {sets.map((s) => (
              <Fragment key={s.id}>
                <tr>
                  <td><button className="link" onClick={() => show(s.id)}>{open === s.id ? "▾" : "▸"} {s.name}</button></td>
                  <td className="small muted">{s.source_file}</td>
                  <td className="r">{s.rates}</td>
                  <td className="small">{new Date(s.created_at).toLocaleDateString("en-AU")}</td>
                  <td><label className="inline"><input type="checkbox" checked={s.active} onChange={() => toggle(s)} /> {s.active ? "Yes" : "No"}</label></td>
                  <td><button className="link danger" onClick={() => remove(s)}>Remove</button></td>
                </tr>
                {open === s.id && (
                  <tr>
                    <td colSpan={6}>
                      <table className="inner">
                        <thead><tr><th>Item</th><th>Section</th><th>Description</th><th>Unit</th><th className="r">Rate</th></tr></thead>
                        <tbody>
                          {rates.map((r) => (
                            <tr key={r.id}><td>{r.code}</td><td className="small muted">{r.category}</td><td>{r.description}</td><td>{r.unit}</td><td className="r">{money(r.rate)}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {sets.length === 0 && <tr><td colSpan={6} className="muted">No previous jobs loaded yet.</td></tr>}
          </tbody>
        </table>
      </section>
    </main>
  );
}
