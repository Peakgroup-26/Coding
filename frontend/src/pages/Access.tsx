/* Admin → Feature access: for every tab and feature, set each person (or a position preset) to Hidden, View only or Can change.
   Enforced on the server. A person follows their position unless a feature is set on them. */
import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorLine, Field, Tabs, useAction, useLoad } from "../ui";

type Level = "none" | "view" | "edit";
interface Feature { key: string; group: string; label: string; routes: string[] }
interface Position { id: number; name: string; description: string; features: Record<string, Level>; people: number }
interface Overview { user_id: number; name: string; role: string; position: string; own: string[]; access: Record<string, Level> }
interface UserAccess { user_id: number; position_id: number | null; features: Record<string, Level>; effective: Record<string, Level>; is_admin: boolean }

const LEVEL_LABEL: Record<Level, string> = { none: "Hidden", view: "View only", edit: "Can change" };
const ICON: Record<Level, string> = { none: "–", view: "👁", edit: "✓" };

function groups(fs: Feature[]) {
  const out: [string, Feature[]][] = [];
  for (const f of fs) {
    const g = out.find((x) => x[0] === f.group);
    if (g) g[1].push(f); else out.push([f.group, [f]]);
  }
  return out;
}

function LevelPick({ value, onChange, inherited, dim }: { value: Level; onChange: (l: Level) => void; inherited?: boolean; dim?: boolean }) {
  return (
    <span className={`level-pick ${inherited ? "inherited" : "own"} ${dim ? "dim" : ""}`}>
      {(["none", "view", "edit"] as Level[]).map((l) => (
        <button key={l} type="button" className={`lv-${l} ${value === l ? "on" : ""}`} onClick={() => onChange(l)}>{LEVEL_LABEL[l]}</button>
      ))}
    </span>
  );
}

function Matrix({ feats, value, base, onChange, onReset }: { feats: Feature[]; value: Record<string, Level>; base?: Record<string, Level>;
  onChange: (key: string, l: Level) => void; onReset?: (key: string) => void }) {
  const setGroup = (fs: Feature[], l: Level) => fs.forEach((f) => onChange(f.key, l));
  return (
    <div className="access-matrix">
      {groups(feats).map(([g, fs]) => (
        <section key={g} className="card">
          <div className="row wrap"><h2 style={{ margin: 0 }}>{g}</h2><span className="spacer" />
            <span className="small muted">Whole section:</span>
            {(["none", "view", "edit"] as Level[]).map((l) => <button key={l} className="small" onClick={() => setGroup(fs, l)}>{LEVEL_LABEL[l]}</button>)}</div>
          {fs.map((f) => {
            const own = base ? f.key in value : true;
            const v = (own ? value[f.key] : base?.[f.key]) ?? "edit";
            return (
              <div key={f.key} className="access-row">
                <span className="access-label">{f.label}{base && !own && <small className="muted"> (from position)</small>}</span>
                <LevelPick value={v} inherited={!!base && !own} onChange={(l) => onChange(f.key, l)} />
                {base && own && onReset && <button className="link small" onClick={() => onReset(f.key)} title="Follow the position again">↺ position</button>}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}

export default function AccessAdmin() {
  const [tab, setTab] = useState<"person" | "positions" | "overview">("person");
  const { data: cat } = useLoad<{ features: Feature[] }>("/api/features");
  const { data: positions, reload: reloadPos } = useLoad<Position[]>("/api/positions");
  const { data: people, reload: reloadPeople } = useLoad<Overview[]>("/api/access/overview");
  if (!cat || !positions || !people) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="muted small">Choose what each person sees and can change, tab by tab. <b>Hidden</b> takes it off their menu and phone; <b>View only</b> lets them look
        but not change anything; <b>Can change</b> is full use. Give people a position (Estimator, Supervisor, Plumber…) and adjust anyone individually on top.
        It's checked by the server on every request. Admins always have everything; the Finance, People and job-type ticks on the People tab still apply too.</p>
      <Tabs value={tab} onChange={setTab} tabs={[["person", "By person"], ["positions", "Positions (presets)"], ["overview", "Who sees what"]]} />
      {tab === "person" && <ByPerson feats={cat.features} positions={positions} people={people} onSaved={() => { reloadPeople(); reloadPos(); }} />}
      {tab === "positions" && <Positions feats={cat.features} positions={positions} onSaved={() => { reloadPos(); reloadPeople(); }} />}
      {tab === "overview" && <OverviewGrid feats={cat.features} people={people} />}
    </>
  );
}

function ByPerson({ feats, positions, people, onSaved }: { feats: Feature[]; positions: Position[]; people: Overview[]; onSaved: () => void }) {
  const [sel, setSel] = useState<number | null>(people.find((p) => p.role !== "admin")?.user_id ?? null);
  const [q, setQ] = useState("");
  const { data: acc, set } = useLoad<UserAccess>(sel ? `/api/users/${sel}/access` : null, [sel]);
  const [draft, setDraft] = useState<{ position_id: number | null; features: Record<string, Level> } | null>(null);
  const [saved, setSaved] = useState(false);
  const [run, err, busy] = useAction();
  useEffect(() => { setDraft(null); setSaved(false); }, [sel]);
  const d = draft ?? (acc ? { position_id: acc.position_id, features: acc.features } : null);
  const pos = positions.find((p) => p.id === d?.position_id);
  const person = people.find((p) => p.user_id === sel);
  const shown = people.filter((p) => !q || `${p.name} ${p.position}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="access-layout">
      <aside className="card access-people">
        <input placeholder="Find a person" value={q} onChange={(e) => setQ(e.target.value)} />
        {shown.map((p) => (
          <button key={p.user_id} className={`person-pick ${sel === p.user_id ? "on" : ""}`} onClick={() => setSel(p.user_id)}>
            <b>{p.name}</b><small>{p.role === "admin" ? "Admin: everything" : p.position || "No position"}{p.own.length ? ` · ${p.own.length} own` : ""}</small>
          </button>
        ))}
      </aside>
      <div>
        {person && acc && d && (
          acc.is_admin ? <div className="card"><h2>{person.name}</h2><p>Admins see and change everything. Change their role on the People tab to limit them.</p></div> : (
            <>
              <div className="card">
                <div className="row wrap">
                  <h2 style={{ margin: 0 }}>{person.name}</h2><span className="spacer" />
                  <Field label="Position"><select value={d.position_id ?? ""} onChange={(e) => { setDraft({ ...d, position_id: e.target.value ? +e.target.value : null }); setSaved(false); }}>
                    <option value="">None (everything, as before)</option>{positions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
                  <button onClick={() => { setDraft({ ...d, features: {} }); setSaved(false); }} disabled={!Object.keys(d.features).length}>Clear their own changes</button>
                  <button className="primary" disabled={busy || !draft} onClick={() => run(async () => {
                    set(await api.put<UserAccess>(`/api/users/${person.user_id}/access`, d)); setDraft(null); setSaved(true); onSaved();
                  })}>Save</button>
                  {saved && <span className="ok">Saved</span>}
                </div>
                {pos && <p className="small muted">{pos.description}. Greyed choices come from the {pos.name} position; pick one to set it just for {person.name.split(" ")[0]}.</p>}
                <ErrorLine error={err} />
              </div>
              <Matrix feats={feats} value={d.features} base={pos ? pos.features : Object.fromEntries(feats.map((f) => [f.key, "edit" as Level]))}
                onChange={(k, l) => { setDraft({ ...d, features: { ...d.features, [k]: l } }); setSaved(false); }}
                onReset={(k) => { const f = { ...d.features }; delete f[k]; setDraft({ ...d, features: f }); setSaved(false); }} />
            </>
          )
        )}
      </div>
    </div>
  );
}

function Positions({ feats, positions, onSaved }: { feats: Feature[]; positions: Position[]; onSaved: () => void }) {
  const [sel, setSel] = useState<number | "new">(positions[0]?.id ?? "new");
  const cur = sel === "new" ? null : positions.find((p) => p.id === sel) ?? null;
  const [f, setF] = useState<{ name: string; description: string; features: Record<string, Level> } | null>(null);
  const [saved, setSaved] = useState(false);
  const [run, err, busy] = useAction();
  useEffect(() => { setF(null); setSaved(false); }, [sel]);
  const d = f ?? { name: cur?.name ?? "", description: cur?.description ?? "", features: cur?.features ?? Object.fromEntries(feats.map((x) => [x.key, "none" as Level])) };
  return (
    <div className="access-layout">
      <aside className="card access-people">
        {positions.map((p) => (
          <button key={p.id} className={`person-pick ${sel === p.id ? "on" : ""}`} onClick={() => setSel(p.id)}><b>{p.name}</b><small>{p.people} {p.people === 1 ? "person" : "people"}</small></button>
        ))}
        <button className={`person-pick ${sel === "new" ? "on" : ""}`} onClick={() => setSel("new")}><b>+ New position</b></button>
      </aside>
      <div>
        <div className="card">
          <div className="row wrap">
            <Field label="Position"><input value={d.name} onChange={(e) => { setF({ ...d, name: e.target.value }); setSaved(false); }} placeholder="e.g. Maintenance coordinator" /></Field>
            <Field label="What it's for"><input value={d.description} onChange={(e) => { setF({ ...d, description: e.target.value }); setSaved(false); }} style={{ minWidth: 300 }} /></Field>
            <span className="spacer" />
            <button className="primary" disabled={busy || !d.name} onClick={() => run(async () => {
              const r = cur ? await api.put<Position>(`/api/positions/${cur.id}`, d) : await api.post<Position>("/api/positions", d);
              setF(null); setSaved(true); onSaved(); setSel(r.id);
            })}>{cur ? "Save" : "Add position"}</button>
            {cur && <button className="danger" onClick={() => confirm(`Delete ${cur.name}? ${cur.people} people will go back to everything.`) && run(async () => { await api.del(`/api/positions/${cur.id}`); onSaved(); setSel("new"); })}>Delete</button>}
            {saved && <span className="ok">Saved{cur?.people ? `: ${cur.people} people updated` : ""}</span>}
          </div>
          <ErrorLine error={err} />
        </div>
        <Matrix feats={feats} value={d.features} onChange={(k, l) => { setF({ ...d, features: { ...d.features, [k]: l } }); setSaved(false); }} />
      </div>
    </div>
  );
}

function OverviewGrid({ feats, people }: { feats: Feature[]; people: Overview[] }) {
  const gs = groups(feats);
  return (
    <div className="card dt-wrap">
      <table className="access-grid">
        <thead>
          <tr><th rowSpan={2} className="person-col">Person</th>{gs.map(([g, fs]) => <th key={g} colSpan={fs.length} className="grp">{g}</th>)}</tr>
          <tr>{gs.map(([g, fs]) => <Fragment key={g}>{fs.map((f) => <th key={f.key} className="vert" title={f.label}><span>{f.label.split(/[:(,]/)[0]}</span></th>)}</Fragment>)}</tr>
        </thead>
        <tbody>{people.map((p) => (
          <tr key={p.user_id}><td className="person-col"><b>{p.name}</b><div className="small muted">{p.role === "admin" ? "Admin" : p.position || "No position"}</div></td>
            {feats.map((f) => <td key={f.key} className={`lv-${p.access[f.key]} ${p.own.includes(f.key) ? "own" : ""}`} title={`${f.label}: ${LEVEL_LABEL[p.access[f.key]]}${p.own.includes(f.key) ? " (set on them)" : ""}`}>
              {ICON[p.access[f.key]]}</td>)}</tr>))}</tbody>
      </table>
      <p className="small muted">✓ can change · 👁 view only · – hidden. An orange box means it's set on that person rather than coming from their position.</p>
    </div>
  );
}
