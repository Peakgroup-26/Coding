/* Boards (the Monday.com side): boards from templates, groups of items with typed columns, subitems, an item panel with
   updates (@mentions), files and an activity log, views (table, kanban, calendar, timeline, workload, chart), automations,
   forms and My work. */
import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, download, fetchBlobUrl, upload } from "../api";
import { addDays, ErrorLine, Field, fmtDate, Modal, money, monday, num, todayIso, useAction, useLoad } from "../ui";
import type { Person } from "./FieldMe";

interface Label { key: string; label: string; colour: string; done?: boolean }
interface Col { id: number; key: string; title: string; type: string; settings: { labels?: Label[]; options?: string[]; unit?: string }; position: number }
interface Group { id: number; title: string; colour: string; position: number }
export interface Item { id: number; group_id: number | null; parent_id: number | null; name: string; values: Record<string, any>; depends_on: number[]; position: number;
  archived: boolean; created_by: number | null; created_at: string; updated_at: string; files: number; updates: number }
interface Automation { id: number; name: string; trigger: Record<string, any>; actions: Record<string, any>[]; active: boolean; runs: number; last_run: string | null; last_error: string }
interface View { id: number; name: string; type: string; settings: Record<string, any> }
interface FormDef { id: number; token: string; title: string; intro: string; columns: string[]; group_id: number | null; public: boolean; active: boolean }
interface Board { id: number; name: string; description: string; owner_id: number | null; private: boolean; members: number[]; job_id: number | null; job: string;
  template: string; archived: boolean; columns: Col[]; groups: Group[]; items: Item[]; automations: Automation[]; views: View[]; forms: FormDef[] }
interface BoardRow { id: number; name: string; description: string; template: string; private: boolean; owner: string; items: number; updated_at: string; archived: boolean }

const TYPES: [string, string][] = [["status", "Status"], ["person", "Person"], ["date", "Date"], ["timeline", "Timeline (from–to)"], ["text", "Text"], ["long_text", "Long text"],
  ["number", "Number"], ["money", "Money"], ["dropdown", "Dropdown"], ["tags", "Tags"], ["checkbox", "Checkbox"], ["rating", "Rating"], ["progress", "Progress"],
  ["job", "Job"], ["customer", "Customer"], ["link", "Link"], ["phone", "Phone"], ["email", "Email"], ["time", "Time tracking"], ["files", "Files"]];
type ViewType = "table" | "kanban" | "calendar" | "timeline" | "workload" | "chart";
const VIEWS: [ViewType, string][] = [["table", "Table"], ["kanban", "Kanban"], ["calendar", "Calendar"], ["timeline", "Timeline"], ["workload", "Workload"], ["chart", "Chart"]];

function usePeople() {
  const { data } = useLoad<Person[]>("/api/field/me/directory");
  return data ?? [];
}
const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
const labelsOf = (c: Col): Label[] => c.settings.labels ?? [];
const mainStatus = (cols: Col[]) => cols.find((c) => c.type === "status" && labelsOf(c).some((l) => l.done)) ?? cols.find((c) => c.type === "status");
const dateOf = (c: Col | undefined, it: Item): string | null => {
  if (!c) return null;
  const v = it.values[c.key];
  return v ? (typeof v === "object" ? v.end : v) : null;
};

/* ---------- list ---------- */
export default function Boards() {
  const { data, reload } = useLoad<BoardRow[]>("/api/boards");
  const { data: templates } = useLoad<{ key: string; name: string; groups: string[]; columns: string[]; automations: string[] }[]>("/api/boards/templates");
  const [picking, setPicking] = useState(false);
  const [run, err] = useAction();
  const nav = useNavigate();
  return (
    <main className="page">
      <div className="row"><h1 style={{ margin: 0 }}>Boards</h1><span className="spacer" /><Link to="/my-work" className="button">My work</Link>
        <button className="primary" onClick={() => setPicking(true)}>+ New board</button></div>
      <div className="board-grid">
        {(data ?? []).filter((b) => !b.archived).map((b) => (
          <Link key={b.id} to={`/boards/${b.id}`} className="card board-card">
            <b>{b.private && "🔒 "}{b.name}</b><span className="muted small">{b.items} items · {b.owner}</span>
            {b.description && <span className="small">{b.description}</span>}
          </Link>
        ))}
      </div>
      {(data ?? []).some((b) => b.archived) && <details><summary className="muted">Archived boards</summary>
        {(data ?? []).filter((b) => b.archived).map((b) => <div key={b.id}><Link to={`/boards/${b.id}`}>{b.name}</Link></div>)}</details>}
      {data && data.length === 0 && <p className="muted">No boards yet. Start one from a template: office tasks, the tender pipeline, a project programme, safety reports…</p>}
      {picking && templates && (
        <Modal title="New board" onClose={() => setPicking(false)} wide>
          <div className="board-grid">
            {templates.map((t) => (
              <button key={t.key} className="card board-card tpl" onClick={() => run(async () => { const b = await api.post<Board>("/api/boards", { template: t.key }); await reload(); nav(`/boards/${b.id}`); })}>
                <b>{t.name}</b><span className="small muted">{t.columns.join(" · ")}</span>
                {t.automations.length > 0 && <span className="small">⚡ {t.automations.join("; ")}</span>}
              </button>
            ))}
          </div>
          <ErrorLine error={err} />
        </Modal>
      )}
    </main>
  );
}

/* ---------- one board ---------- */
export function BoardPage() {
  const { boardId } = useParams();
  const [sp, setSp] = useSearchParams();
  const [showArchived, setShowArchived] = useState(false);
  const { data: b, reload, set } = useLoad<Board>(`/api/boards/${boardId}?archived=${showArchived}`, [showArchived]);
  const people = usePeople();
  const [view, setView] = useState<ViewType>("table");
  const [q, setQ] = useState("");
  const [person, setPerson] = useState<number | "">("");
  const [modal, setModal] = useState<"" | "column" | "group" | "auto" | "forms" | "settings">("");
  const [run, err] = useAction();
  const nav = useNavigate();
  const openItem = Number(sp.get("item")) || null;
  if (!b) return <main className="page"><p className="muted">Loading…</p></main>;
  const pcols = b.columns.filter((c) => c.type === "person").map((c) => c.key);
  const match = (it: Item) => (!q || it.name.toLowerCase().includes(q.toLowerCase()) || Object.values(it.values).some((v) => String(v).toLowerCase().includes(q.toLowerCase())))
    && (person === "" || pcols.some((k) => (it.values[k] || []).includes(person)));
  const items = b.items.filter((i) => !i.parent_id);
  const shown = items.filter((i) => match(i) || b.items.some((s) => s.parent_id === i.id && match(s)));
  const patchItem = (id: number, body: Record<string, unknown>) => run(async () => { await api.patch(`/api/boards/items/${id}`, body); await reload(); });
  const ctx: Ctx = { b, people, patchItem, reload, open: (id) => setSp(id ? { item: String(id) } : {}), run };
  return (
    <main className="page board-page">
      <div className="row wrap">
        <Link to="/boards">‹ Boards</Link>
        <h1 style={{ margin: 0 }} contentEditable suppressContentEditableWarning className="editable"
          onBlur={(e) => { const name = e.currentTarget.textContent?.trim(); if (name && name !== b.name) run(async () => { await api.patch(`/api/boards/${b.id}`, { name }); await reload(); }); }}>{b.name}</h1>
        {b.private && <span title="Private board">🔒</span>}{b.job && <span className="muted small">{b.job}</span>}
        <span className="spacer" />
        <button onClick={() => setModal("auto")}>⚡ Automations ({b.automations.filter((a) => a.active).length})</button>
        <button onClick={() => setModal("forms")}>📝 Forms</button>
        <button onClick={() => setModal("settings")}>⚙ Board</button>
      </div>
      {b.description && <p className="muted small">{b.description}</p>}
      <div className="row wrap view-bar">
        <div className="tabs scroll">{VIEWS.map(([k, l]) => <button key={k} className={view === k ? "active" : ""} onClick={() => setView(k)}>{l}</button>)}</div>
        <span className="spacer" />
        <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 150 }} />
        <select value={person} onChange={(e) => setPerson(e.target.value ? +e.target.value : "")}><option value="">Everyone</option>
          {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select>
        {view === "table" && <><button onClick={() => setModal("group")}>+ Group</button><button onClick={() => setModal("column")}>+ Column</button></>}
        <button onClick={() => download(`/api/boards/${b.id}/export.xlsx`, `${b.name}.xlsx`)}>Excel</button>
      </div>
      <ErrorLine error={err} />
      {view === "table" && <TableView ctx={ctx} items={shown} />}
      {view === "kanban" && <KanbanView ctx={ctx} items={shown} />}
      {view === "calendar" && <CalendarView ctx={ctx} items={shown} />}
      {view === "timeline" && <TimelineView ctx={ctx} items={shown} />}
      {view === "workload" && <WorkloadView ctx={ctx} items={shown} />}
      {view === "chart" && <ChartView boardId={b.id} />}
      <label className="inline small muted"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived items</label>
      {openItem && <ItemPanel ctx={ctx} id={openItem} />}
      {modal === "column" && <ColumnModal b={b} onClose={() => setModal("")} onDone={() => { setModal(""); reload(); }} />}
      {modal === "group" && <GroupModal b={b} onClose={() => setModal("")} onDone={() => { setModal(""); reload(); }} />}
      {modal === "auto" && <AutomationsModal b={b} people={people} onClose={() => setModal("")} reload={reload} />}
      {modal === "forms" && <FormsModal b={b} onClose={() => setModal("")} reload={reload} />}
      {modal === "settings" && <SettingsModal b={b} people={people} onClose={() => setModal("")} onSaved={(nb) => { set(nb); }}
        onDeleted={() => nav("/boards")} onDuplicated={(id) => { setModal(""); nav(`/boards/${id}`); }} />}
    </main>
  );
}

interface Ctx { b: Board; people: Person[]; patchItem: (id: number, body: Record<string, unknown>) => void; reload: () => Promise<void>;
  open: (id: number | null) => void; run: (fn: () => Promise<unknown>) => Promise<boolean> }

/* ---------- table ---------- */
function TableView({ ctx, items }: { ctx: Ctx; items: Item[] }) {
  const { b } = ctx;
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [sel, setSel] = useState<number[]>([]);
  const cols = b.columns;
  const groups = [...b.groups].sort((a, c) => a.position - c.position || a.id - c.id);
  const ungrouped = items.filter((i) => !i.group_id || !b.groups.some((g) => g.id === i.group_id));
  return (
    <div className="board-table-wrap">
      {sel.length > 0 && <BulkBar ctx={ctx} ids={sel} onDone={() => setSel([])} />}
      {[...groups, ...(ungrouped.length ? [{ id: 0, title: "No group", colour: "#c4c4c4", position: 999 }] : [])].map((g) => {
        const gi = (g.id ? items.filter((i) => i.group_id === g.id) : ungrouped).sort((a, c) => a.position - c.position);
        return (
          <section key={g.id} className="board-group" style={{ ["--gc" as string]: g.colour }}>
            <div className="group-head">
              <button className="link" onClick={() => setCollapsed({ ...collapsed, [g.id]: !collapsed[g.id] })}>{collapsed[g.id] ? "▸" : "▾"}</button>
              {g.id ? <b contentEditable suppressContentEditableWarning className="editable" onBlur={(e) => {
                const t = e.currentTarget.textContent?.trim();
                if (t && t !== g.title) ctx.run(async () => { await api.patch(`/api/boards/groups/${g.id}`, { title: t }); await ctx.reload(); });
              }}>{g.title}</b> : <b>{g.title}</b>}
              <span className="muted small">{gi.length} item{gi.length === 1 ? "" : "s"}</span>
              {g.id > 0 && gi.length === 0 && <button className="link small danger" onClick={() => ctx.run(async () => { await api.del(`/api/boards/groups/${g.id}`); await ctx.reload(); })}>Delete group</button>}
            </div>
            {!collapsed[g.id] && (
              <div className="dt-wrap">
                <table className="board-table">
                  <thead><tr><th className="chk" /><th className="name-col">Item</th>{cols.map((c) => <th key={c.key}><ColHead ctx={ctx} c={c} /></th>)}</tr></thead>
                  <tbody>
                    {gi.map((it) => (
                      <Fragment key={it.id}>
                        <ItemRow ctx={ctx} it={it} cols={cols} sel={sel.includes(it.id)} onSel={(v) => setSel(v ? [...sel, it.id] : sel.filter((x) => x !== it.id))}
                          subs={b.items.filter((s) => s.parent_id === it.id).length} expanded={!!expanded[it.id]} onExpand={() => setExpanded({ ...expanded, [it.id]: !expanded[it.id] })} />
                        {expanded[it.id] && b.items.filter((s) => s.parent_id === it.id).map((s) => (
                          <ItemRow key={s.id} ctx={ctx} it={s} cols={cols} sub sel={sel.includes(s.id)} onSel={(v) => setSel(v ? [...sel, s.id] : sel.filter((x) => x !== s.id))} />
                        ))}
                        {expanded[it.id] && <AddRow ctx={ctx} groupId={null} parentId={it.id} span={cols.length + 2} placeholder="+ Add subitem" />}
                      </Fragment>
                    ))}
                    <AddRow ctx={ctx} groupId={g.id || null} span={cols.length + 2} placeholder="+ Add item" />
                    <SummaryRow cols={cols} items={gi} />
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function ColHead({ ctx, c }: { ctx: Ctx; c: Col }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="col-head">
      <button className="link" onClick={() => setOpen(!open)} title={TYPES.find((t) => t[0] === c.type)?.[1]}>{c.title}</button>
      {open && <ColumnEditor ctx={ctx} c={c} onClose={() => setOpen(false)} />}
    </span>
  );
}

function ColumnEditor({ ctx, c, onClose }: { ctx: Ctx; c: Col; onClose: () => void }) {
  const [title, setTitle] = useState(c.title);
  const [labels, setLabels] = useState<Label[]>(labelsOf(c));
  const [options, setOptions] = useState((c.settings.options ?? []).join("\n"));
  const save = () => ctx.run(async () => {
    const settings = c.type === "status" ? { ...c.settings, labels } : ["dropdown", "tags"].includes(c.type) ? { ...c.settings, options: options.split("\n").map((s) => s.trim()).filter(Boolean) } : c.settings;
    await api.patch(`/api/boards/columns/${c.id}`, { title, settings }); await ctx.reload(); onClose();
  });
  return (
    <Modal title={`Column: ${c.title}`} onClose={onClose}>
      <div className="form">
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        {c.type === "status" && (
          <>
            <h3>Labels</h3>
            {labels.map((l, i) => (
              <div key={i} className="row">
                <input type="color" value={l.colour} onChange={(e) => setLabels(labels.map((x, j) => (j === i ? { ...x, colour: e.target.value } : x)))} />
                <input value={l.label} onChange={(e) => setLabels(labels.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                <label className="inline small"><input type="checkbox" checked={!!l.done} onChange={(e) => setLabels(labels.map((x, j) => (j === i ? { ...x, done: e.target.checked } : x)))} /> means done</label>
                <button className="link danger" onClick={() => setLabels(labels.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <button className="link" onClick={() => setLabels([...labels, { key: `l${Date.now().toString(36)}`, label: "New label", colour: "#ffb27a" }])}>+ Label</button>
          </>
        )}
        {["dropdown", "tags"].includes(c.type) && <Field label="Options (one per line)"><textarea rows={6} value={options} onChange={(e) => setOptions(e.target.value)} /></Field>}
        <div className="row"><button className="primary" onClick={save}>Save</button><span className="spacer" />
          <button className="danger" onClick={() => { if (confirm(`Delete the ${c.title} column and its values?`)) ctx.run(async () => { await api.del(`/api/boards/columns/${c.id}`); await ctx.reload(); onClose(); }); }}>Delete column</button></div>
      </div>
    </Modal>
  );
}

function ItemRow({ ctx, it, cols, sub, sel, onSel, subs, expanded, onExpand }: { ctx: Ctx; it: Item; cols: Col[]; sub?: boolean; sel: boolean; onSel: (v: boolean) => void;
  subs?: number; expanded?: boolean; onExpand?: () => void }) {
  return (
    <tr className={`${sub ? "subitem" : ""} ${it.archived ? "archived" : ""}`}>
      <td className="chk"><input type="checkbox" checked={sel} onChange={(e) => onSel(e.target.checked)} /></td>
      <td className="name-col">
        <div className="name-cell">
          {!sub && <button className="link small" onClick={onExpand} title="Subitems">{expanded ? "▾" : "▸"}{subs ? <small>{subs}</small> : null}</button>}
          <input className="cell-input" defaultValue={it.name} key={it.name} onBlur={(e) => { if (e.target.value.trim() && e.target.value !== it.name) ctx.patchItem(it.id, { name: e.target.value }); }} />
          <button className="link small open" onClick={() => ctx.open(it.id)} title="Open">💬{it.updates > 0 && <small>{it.updates}</small>}</button>
        </div>
      </td>
      {cols.map((c) => <td key={c.key} className={`cell t-${c.type}`}><Cell ctx={ctx} c={c} it={it} /></td>)}
    </tr>
  );
}

function AddRow({ ctx, groupId, parentId, span, placeholder }: { ctx: Ctx; groupId: number | null; parentId?: number; span: number; placeholder: string }) {
  const [name, setName] = useState("");
  const add = () => { if (name.trim()) ctx.run(async () => { await api.post(`/api/boards/${ctx.b.id}/items`, { name, group_id: groupId, parent_id: parentId ?? null }); setName(""); await ctx.reload(); }); };
  return <tr className={`add-row ${parentId ? "subitem" : ""}`}><td /><td colSpan={span - 1}><input className="cell-input" placeholder={placeholder} value={name} onChange={(e) => setName(e.target.value)}
    onKeyDown={(e) => { if (e.key === "Enter") add(); }} onBlur={add} /></td></tr>;
}

function SummaryRow({ cols, items }: { cols: Col[]; items: Item[] }) {
  if (!items.length) return null;
  return (
    <tr className="summary-row"><td /><td />
      {cols.map((c) => {
        if (c.type === "status") {
          const labs = labelsOf(c);
          return <td key={c.key}><div className="status-dist">{labs.map((l) => { const n = items.filter((i) => i.values[c.key] === l.key).length;
            return n ? <span key={l.key} style={{ flex: n, background: l.colour }} title={`${l.label}: ${n}`} /> : null; })}
            {items.some((i) => !i.values[c.key]) && <span style={{ flex: items.filter((i) => !i.values[c.key]).length, background: "#e7e2dd" }} />}</div></td>;
        }
        if (c.type === "number" || c.type === "money") {
          const t = items.reduce((s, i) => s + (Number(i.values[c.key]) || 0), 0);
          return <td key={c.key} className="n"><b>{c.type === "money" ? money(t) : num(t, 2)}</b></td>;
        }
        if (c.type === "time") return <td key={c.key} className="n"><b>{num(items.reduce((s, i) => s + (i.values[c.key]?.seconds || 0), 0) / 3600, 1)} h</b></td>;
        return <td key={c.key} />;
      })}
    </tr>
  );
}

/* ---------- cells ---------- */
function Cell({ ctx, c, it }: { ctx: Ctx; c: Col; it: Item }) {
  const v = it.values[c.key];
  const set = (val: unknown) => ctx.patchItem(it.id, { values: { [c.key]: val } });
  switch (c.type) {
    case "status": return <StatusPick c={c} value={v} onPick={set} />;
    case "person": return <PersonPick people={ctx.people} value={v || []} onPick={set} />;
    case "date": return <input type="date" className={`cell-input ${v && v < todayIso() && !isDone(ctx.b, it) ? "overdue" : ""}`} value={v || ""} onChange={(e) => set(e.target.value || null)} />;
    case "timeline": return <span className="tl-cell"><input type="date" className="cell-input" value={v?.start || ""} onChange={(e) => e.target.value && set({ start: e.target.value, end: v?.end && v.end >= e.target.value ? v.end : e.target.value })} />
      <input type="date" className="cell-input" value={v?.end || ""} onChange={(e) => e.target.value && set({ start: v?.start && v.start <= e.target.value ? v.start : e.target.value, end: e.target.value })} /></span>;
    case "number": case "money": return <input type="number" step="any" className="cell-input n" defaultValue={v ?? ""} key={String(v)} onBlur={(e) => { const n = e.target.value === "" ? null : +e.target.value; if (n !== (v ?? null)) set(n); }} />;
    case "checkbox": return <input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />;
    case "rating": return <span className="stars">{[1, 2, 3, 4, 5].map((n) => <button key={n} className={`link star ${v >= n ? "on" : ""}`} onClick={() => set(v === n ? null : n)}>★</button>)}</span>;
    case "progress": return <div className="bar" title={`${v ?? 0}%`}><div style={{ width: `${v ?? 0}%` }} /></div>;
    case "dropdown": return <select className="cell-input" value={v || ""} onChange={(e) => set(e.target.value || null)}><option value="" />{(c.settings.options ?? []).map((o) => <option key={o}>{o}</option>)}</select>;
    case "tags": return <TagsCell c={c} value={v || []} onSet={set} />;
    case "link": return v?.url ? <a href={v.url} target="_blank" rel="noreferrer" className="small">{v.text || v.url.replace(/^https?:\/\//, "").slice(0, 28)}</a>
      : <input className="cell-input" placeholder="https://" onBlur={(e) => e.target.value && set({ url: e.target.value })} />;
    case "job": return <JobCell value={v} onSet={set} />;
    case "customer": return <CustomerCell value={v} onSet={set} />;
    case "time": return <TimerCell ctx={ctx} c={c} it={it} />;
    case "files": return <button className="link small" onClick={() => ctx.open(it.id)}>📎 {it.files || ""}</button>;
    case "long_text": return <button className="link small cell-text" onClick={() => ctx.open(it.id)}>{v ? String(v).split("\n")[0].slice(0, 40) : "…"}</button>;
    default: return <input className="cell-input" type={c.type === "email" ? "email" : c.type === "phone" ? "tel" : "text"} defaultValue={v ?? ""} key={String(v)}
      onBlur={(e) => { if (e.target.value !== (v ?? "")) set(e.target.value || null); }} />;
  }
}

function isDone(b: Board, it: Item) {
  const sc = mainStatus(b.columns);
  return !!sc && labelsOf(sc).some((l) => l.done && l.key === it.values[sc.key]);
}

function Pop({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    setTimeout(() => document.addEventListener("click", h), 0);
    return () => document.removeEventListener("click", h);
  }, [open, onClose]);
  return open ? <div ref={ref} className="pop">{children}</div> : null;
}

function StatusPick({ c, value, onPick }: { c: Col; value: string | undefined; onPick: (v: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const l = labelsOf(c).find((x) => x.key === value);
  return (
    <span className="pop-wrap">
      <button className="status-pill" style={{ background: l?.colour ?? "#e7e2dd", color: l ? "#fff" : "var(--muted)" }} onClick={() => setOpen(!open)}>{l?.label ?? "–"}</button>
      <Pop open={open} onClose={() => setOpen(false)}>
        {labelsOf(c).map((x) => <button key={x.key} className="status-pill" style={{ background: x.colour, color: "#fff" }} onClick={() => { onPick(x.key); setOpen(false); }}>{x.label}</button>)}
        <button className="link small" onClick={() => { onPick(null); setOpen(false); }}>Clear</button>
      </Pop>
    </span>
  );
}

function PersonPick({ people, value, onPick }: { people: Person[]; value: number[]; onPick: (v: number[] | null) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const names = Object.fromEntries(people.map((p) => [p.user_id, p.name]));
  return (
    <span className="pop-wrap">
      <button className="people-cell" onClick={() => setOpen(!open)}>
        {value.length ? value.slice(0, 3).map((id) => <span key={id} className="avatar sm" title={names[id]}>{initials(names[id] ?? "?")}</span>) : <span className="muted">+</span>}
        {value.length > 3 && <small>+{value.length - 3}</small>}
      </button>
      <Pop open={open} onClose={() => setOpen(false)}>
        <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <div className="pop-list">{people.filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase())).map((p) => (
          <label key={p.user_id} className="inline small"><input type="checkbox" checked={value.includes(p.user_id)}
            onChange={(e) => { const nv = e.target.checked ? [...value, p.user_id] : value.filter((x) => x !== p.user_id); onPick(nv.length ? nv : null); }} /> {p.name}</label>))}</div>
      </Pop>
    </span>
  );
}

function TagsCell({ c, value, onSet }: { c: Col; value: string[]; onSet: (v: string[] | null) => void }) {
  const [open, setOpen] = useState(false);
  const opts = Array.from(new Set([...(c.settings.options ?? []), ...value]));
  return (
    <span className="pop-wrap">
      <button className="link small tags" onClick={() => setOpen(!open)}>{value.length ? value.map((t) => <span key={t} className="tag">{t}</span>) : "+"}</button>
      <Pop open={open} onClose={() => setOpen(false)}>
        {opts.map((o) => <label key={o} className="inline small"><input type="checkbox" checked={value.includes(o)}
          onChange={(e) => { const nv = e.target.checked ? [...value, o] : value.filter((x) => x !== o); onSet(nv.length ? nv : null); }} /> {o}</label>)}
        <input placeholder="New tag + Enter" onKeyDown={(e) => { if (e.key === "Enter" && e.currentTarget.value.trim()) { onSet([...value, e.currentTarget.value.trim()]); e.currentTarget.value = ""; } }} />
      </Pop>
    </span>
  );
}

let jobsCache: Promise<{ id: number; job_no: string; name: string }[]> | null = null;
let custCache: Promise<{ id: number; name: string }[]> | null = null;
function JobCell({ value, onSet }: { value: number | undefined; onSet: (v: number | null) => void }) {
  const [jobs, setJobs] = useState<{ id: number; job_no: string; name: string }[]>([]);
  useEffect(() => { (jobsCache ??= api.get<{ id: number; job_no: string; name: string }[]>("/api/work?status=").catch(() => [])).then(setJobs); }, []);
  const j = jobs.find((x) => x.id === value);
  return <select className="cell-input" value={value ?? ""} onChange={(e) => onSet(e.target.value ? +e.target.value : null)}>
    <option value="">{value && !j ? `Job ${value}` : ""}</option>{jobs.map((x) => <option key={x.id} value={x.id}>{x.job_no} {x.name}</option>)}</select>;
}
function CustomerCell({ value, onSet }: { value: number | undefined; onSet: (v: number | null) => void }) {
  const [cs, setCs] = useState<{ id: number; name: string }[]>([]);
  useEffect(() => { (custCache ??= api.get<{ id: number; name: string }[]>("/api/customers").catch(() => [])).then(setCs); }, []);
  return <select className="cell-input" value={value ?? ""} onChange={(e) => onSet(e.target.value ? +e.target.value : null)}><option value="" />
    {cs.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>;
}

function TimerCell({ ctx, c, it }: { ctx: Ctx; c: Col; it: Item }) {
  const v = it.values[c.key] || { seconds: 0, running_since: null };
  const [, tick] = useState(0);
  useEffect(() => { if (!v.running_since) return; const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, [v.running_since]);
  const secs = (v.seconds || 0) + (v.running_since ? (Date.now() - new Date(v.running_since).getTime()) / 1000 : 0);
  const fmt = `${Math.floor(secs / 3600)}:${String(Math.floor((secs % 3600) / 60)).padStart(2, "0")}${v.running_since ? `:${String(Math.floor(secs % 60)).padStart(2, "0")}` : ""}`;
  return <span className="timer"><button className="link" onClick={() => ctx.run(async () => { await api.post(`/api/boards/items/${it.id}/timer`, { column: c.key, start: !v.running_since }); await ctx.reload(); })}>
    {v.running_since ? "⏸" : "▶"}</button><span className={v.running_since ? "running" : ""}>{fmt}</span></span>;
}

function BulkBar({ ctx, ids, onDone }: { ctx: Ctx; ids: number[]; onDone: () => void }) {
  const sc = mainStatus(ctx.b.columns);
  const go = (body: Record<string, unknown>) => ctx.run(async () => { await api.post(`/api/boards/${ctx.b.id}/bulk`, { item_ids: ids, ...body }); onDone(); await ctx.reload(); });
  return (
    <div className="bulk-bar">
      <b>{ids.length} selected</b>
      {sc && <select defaultValue="" onChange={(e) => e.target.value && go({ values: { [sc.key]: e.target.value } })}><option value="">Set {sc.title}…</option>{labelsOf(sc).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select>}
      <select defaultValue="" onChange={(e) => e.target.value && go({ group_id: +e.target.value })}><option value="">Move to…</option>{ctx.b.groups.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select>
      <button onClick={() => go({ archive: true })}>Archive</button>
      <button className="danger" onClick={() => confirm(`Delete ${ids.length} items?`) && go({ delete: true })}>Delete</button>
      <button className="link" onClick={onDone}>Cancel</button>
    </div>
  );
}

/* ---------- kanban ---------- */
function KanbanView({ ctx, items }: { ctx: Ctx; items: Item[] }) {
  const statusCols = ctx.b.columns.filter((c) => c.type === "status");
  const [key, setKey] = useState(mainStatus(ctx.b.columns)?.key ?? "");
  const c = statusCols.find((x) => x.key === key);
  if (!c) return <p className="muted">Add a Status column to see a kanban.</p>;
  const lanes = [...labelsOf(c), { key: "", label: "Blank", colour: "#c4c4c4" }];
  return (
    <>
      {statusCols.length > 1 && <div className="row small">By <select value={key} onChange={(e) => setKey(e.target.value)}>{statusCols.map((x) => <option key={x.key} value={x.key}>{x.title}</option>)}</select></div>}
      <div className="kanban">
        {lanes.map((l) => {
          const li = items.filter((i) => (i.values[c.key] || "") === l.key);
          if (!l.key && !li.length) return null;
          return (
            <div key={l.key} className="lane" onDragOver={(e) => e.preventDefault()} onDrop={(e) => ctx.patchItem(+e.dataTransfer.getData("text/plain"), { values: { [c.key]: l.key || null } })}>
              <h3 style={{ background: l.colour }}>{l.label} <span>{li.length}</span></h3>
              {li.map((i) => <ItemCard key={i.id} ctx={ctx} it={i} />)}
            </div>
          );
        })}
      </div>
    </>
  );
}

function ItemCard({ ctx, it }: { ctx: Ctx; it: Item }) {
  const names = Object.fromEntries(ctx.people.map((p) => [p.user_id, p.name]));
  const ppl = ctx.b.columns.filter((c) => c.type === "person").flatMap((c) => it.values[c.key] || []);
  const d = dateOf(ctx.b.columns.find((c) => c.type === "date" || c.type === "timeline"), it);
  const g = ctx.b.groups.find((x) => x.id === it.group_id);
  return (
    <div className="kcard" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(it.id))} onClick={() => ctx.open(it.id)} style={{ borderLeftColor: g?.colour }}>
      <b>{it.name}</b>
      <div className="row small" style={{ margin: "4px 0 0" }}>{ppl.slice(0, 3).map((id: number) => <span key={id} className="avatar sm" title={names[id]}>{initials(names[id] ?? "?")}</span>)}
        <span className="spacer" />{d && <span className={d < todayIso() && !isDone(ctx.b, it) ? "bad" : "muted"}>{fmtDate(d)}</span>}{it.updates > 0 && <span>💬{it.updates}</span>}</div>
    </div>
  );
}

/* ---------- calendar ---------- */
function CalendarView({ ctx, items }: { ctx: Ctx; items: Item[] }) {
  const dcols = ctx.b.columns.filter((c) => c.type === "date" || c.type === "timeline");
  const [key, setKey] = useState(dcols[0]?.key ?? "");
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const c = dcols.find((x) => x.key === key);
  if (!c) return <p className="muted">Add a Date or Timeline column to see a calendar.</p>;
  const first = `${month}-01`;
  const start = monday(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const onDay = (d: string) => items.filter((i) => {
    const v = i.values[c.key];
    if (!v) return false;
    return typeof v === "object" ? v.start <= d && d <= v.end : v === d;
  });
  const shift = (n: number) => { const [y, m] = month.split("-").map(Number); const dt = new Date(y, m - 1 + n, 1); setMonth(`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`); };
  return (
    <>
      <div className="row"><button onClick={() => shift(-1)}>‹</button><b>{new Date(first + "T00:00:00").toLocaleDateString("en-AU", { month: "long", year: "numeric" })}</b>
        <button onClick={() => shift(1)}>›</button><button className="link" onClick={() => setMonth(todayIso().slice(0, 7))}>Today</button><span className="spacer" />
        {dcols.length > 1 && <select value={key} onChange={(e) => setKey(e.target.value)}>{dcols.map((x) => <option key={x.key} value={x.key}>{x.title}</option>)}</select>}</div>
      <div className="cal-grid">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="cal-h">{d}</div>)}
        {days.map((d) => (
          <div key={d} className={`cal-day ${d.slice(0, 7) !== month ? "other" : ""} ${d === todayIso() ? "today" : ""}`} onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { const id = +e.dataTransfer.getData("text/plain"); const it = items.find((x) => x.id === id); if (!it) return;
              const v = it.values[c.key];
              if (c.type === "timeline" && v) { const len = (new Date(v.end).getTime() - new Date(v.start).getTime()) / 86400000; ctx.patchItem(id, { values: { [c.key]: { start: d, end: addDays(d, len) } } }); }
              else ctx.patchItem(id, { values: { [c.key]: c.type === "timeline" ? { start: d, end: d } : d } }); }}>
            <span className="cal-n">{+d.slice(8)}</span>
            {onDay(d).slice(0, 4).map((i) => <div key={i.id} className="cal-item" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(i.id))}
              onClick={() => ctx.open(i.id)} style={{ background: ctx.b.groups.find((g) => g.id === i.group_id)?.colour }}>{i.name}</div>)}
            {onDay(d).length > 4 && <small className="muted">+{onDay(d).length - 4} more</small>}
          </div>
        ))}
      </div>
    </>
  );
}

/* ---------- timeline (Gantt) ---------- */
function TimelineView({ ctx, items }: { ctx: Ctx; items: Item[] }) {
  const tcols = ctx.b.columns.filter((c) => c.type === "timeline" || c.type === "date");
  const [key, setKey] = useState((tcols.find((c) => c.type === "timeline") ?? tcols[0])?.key ?? "");
  const c = tcols.find((x) => x.key === key);
  const rows = useMemo(() => !c ? [] : items.flatMap((i) => [i, ...ctx.b.items.filter((s) => s.parent_id === i.id)]).map((i) => {
    const v = i.values[c.key];
    return v ? { it: i, start: typeof v === "object" ? v.start : v, end: typeof v === "object" ? v.end : v } : null;
  }).filter(Boolean).sort((p, q) => (p!.start < q!.start ? -1 : p!.start > q!.start ? 1 : 0)) as { it: Item; start: string; end: string }[], [items, c, ctx.b.items]);
  if (!c) return <p className="muted">Add a Timeline column to see a Gantt chart.</p>;
  if (!rows.length) return <p className="muted">No items have dates in {c.title} yet.</p>;
  const min = monday(rows.reduce((m, r) => (r.start < m ? r.start : m), rows[0].start));
  const max = rows.reduce((m, r) => (r.end > m ? r.end : m), rows[0].end);
  const days = Math.max(14, Math.round((new Date(max).getTime() - new Date(min).getTime()) / 86400000) + 8);
  const W = 22;
  const x = (d: string) => Math.round((new Date(d).getTime() - new Date(min).getTime()) / 86400000) * W;
  const weeks = Array.from({ length: Math.ceil(days / 7) }, (_, i) => addDays(min, i * 7));
  const idx = Object.fromEntries(rows.map((r, i) => [r.it.id, i]));
  const sc = mainStatus(ctx.b.columns);
  return (
    <>
      {tcols.length > 1 && <div className="row small">From <select value={key} onChange={(e) => setKey(e.target.value)}>{tcols.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}</select></div>}
      <div className="gantt">
        <div className="gantt-names">
          <div className="gantt-h" />
          {rows.map((r) => <div key={r.it.id} className={`gantt-name ${r.it.parent_id ? "sub" : ""}`} onClick={() => ctx.open(r.it.id)}>{r.it.name}</div>)}
        </div>
        <div className="gantt-body">
          <div className="gantt-h" style={{ width: days * W }}>{weeks.map((w) => <span key={w} style={{ left: x(w), width: 7 * W }}>{fmtDate(w).slice(0, 5)}</span>)}</div>
          <div className="gantt-rows" style={{ width: days * W, height: rows.length * 30 }}>
            {todayIso() >= min && todayIso() <= addDays(min, days) && <div className="gantt-today" style={{ left: x(todayIso()) }} />}
            <svg className="gantt-deps" width={days * W} height={rows.length * 30}>
              {rows.flatMap((r, i) => (r.it.depends_on || []).filter((d) => d in idx).map((d) => {
                const from = rows[idx[d]];
                const x1 = x(from.end) + W, y1 = idx[d] * 30 + 15, x2 = x(r.start), y2 = i * 30 + 15;
                return <path key={`${d}-${r.it.id}`} d={`M${x1},${y1} H${x1 + 6} V${y2} H${x2}`} fill="none" stroke={x1 > x2 ? "#c42b2b" : "#6f6a66"} markerEnd="url(#arr)" />;
              }))}
              <defs><marker id="arr" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#6f6a66" /></marker></defs>
            </svg>
            {rows.map((r, i) => {
              const lab = sc ? labelsOf(sc).find((l) => l.key === r.it.values[sc.key]) : undefined;
              return <div key={r.it.id} className="gantt-bar" title={`${r.it.name}: ${fmtDate(r.start)} – ${fmtDate(r.end)}`} onClick={() => ctx.open(r.it.id)}
                style={{ top: i * 30 + 5, left: x(r.start), width: Math.max(W, x(r.end) - x(r.start) + W), background: lab?.colour ?? ctx.b.groups.find((g) => g.id === (r.it.group_id ?? ctx.b.items.find((p) => p.id === r.it.parent_id)?.group_id))?.colour ?? "#ff6a13" }}>
                {r.it.name}</div>;
            })}
          </div>
        </div>
      </div>
      <p className="small muted">Open an item to set what it waits for; a red arrow means it starts before the thing it depends on finishes.</p>
    </>
  );
}

/* ---------- workload ---------- */
function WorkloadView({ ctx, items }: { ctx: Ctx; items: Item[] }) {
  const pcol = ctx.b.columns.find((c) => c.type === "person");
  const dcol = ctx.b.columns.find((c) => c.type === "timeline") ?? ctx.b.columns.find((c) => c.type === "date");
  if (!pcol || !dcol) return <p className="muted">Workload needs a Person column and a Date or Timeline column.</p>;
  const start = monday(todayIso());
  const weeks = Array.from({ length: 8 }, (_, i) => addDays(start, i * 7));
  const open = items.filter((i) => !isDone(ctx.b, i));
  const ids = Array.from(new Set(open.flatMap((i) => i.values[pcol.key] || []))) as number[];
  const names = Object.fromEntries(ctx.people.map((p) => [p.user_id, p.name]));
  const count = (uid: number, w: string) => open.filter((i) => {
    if (!(i.values[pcol.key] || []).includes(uid)) return false;
    const v = i.values[dcol.key];
    if (!v) return false;
    const s = typeof v === "object" ? v.start : v, e = typeof v === "object" ? v.end : v;
    return s <= addDays(w, 6) && e >= w;
  }).length;
  return (
    <div className="dt-wrap">
      <table className="dt workload">
        <thead><tr><th>Person</th>{weeks.map((w) => <th key={w} className="n">{fmtDate(w).slice(0, 5)}</th>)}<th className="n">No date</th></tr></thead>
        <tbody>{ids.map((uid) => (
          <tr key={uid}><td>{names[uid] ?? uid}</td>{weeks.map((w) => { const n = count(uid, w); return <td key={w} className={`n load-${Math.min(n, 6)}`}>{n || ""}</td>; })}
            <td className="n muted">{open.filter((i) => (i.values[pcol.key] || []).includes(uid) && !i.values[dcol.key]).length || ""}</td></tr>))}</tbody>
      </table>
      <p className="small muted">Open items per person per week (from {pcol.title} and {dcol.title}). Darker = busier.</p>
    </div>
  );
}

/* ---------- chart ---------- */
function ChartView({ boardId }: { boardId: number }) {
  const { data: s } = useLoad<{ items: number; done: number; overdue: number; status: { column: string; title: string; labels: Label[]; counts: Record<string, number> }[];
    numbers: { column: string; title: string; type: string; total: number; by_group: Record<string, number> }[];
    people: { column: string; title: string; rows: { user_id: number; name: string; open: number; done: number }[] }[] }>(`/api/boards/${boardId}/summary`);
  if (!s) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{s.items}</b><span>Items</span></div>
        <div className="tile ok"><b>{s.done}</b><span>Done</span></div>
        <div className={`tile ${s.overdue ? "warn" : ""}`}><b>{s.overdue}</b><span>Overdue</span></div>
        {s.numbers.map((n) => <div key={n.column} className="tile"><b>{n.type === "money" ? money(n.total) : num(n.total, 1)}</b><span>{n.title} total</span></div>)}
      </div>
      <div className="two-col">
        {s.status.map((st) => {
          const max = Math.max(1, ...Object.values(st.counts));
          return (
            <section key={st.column} className="card"><h2>{st.title}</h2>
              {[...st.labels, { key: "_blank", label: "Blank", colour: "#d9d2cc" }].map((l) => st.counts[l.key] ? (
                <div key={l.key} className="hbar"><span>{l.label}</span><div><i style={{ width: `${(100 * st.counts[l.key]) / max}%`, background: l.colour }} /></div><b>{st.counts[l.key]}</b></div>) : null)}
            </section>
          );
        })}
        {s.people.map((p) => (
          <section key={p.column} className="card"><h2>{p.title}</h2>
            {p.rows.map((r) => <div key={r.user_id} className="hbar"><span>{r.name}</span><div><i style={{ width: `${(100 * r.open) / Math.max(1, ...p.rows.map((x) => x.open + x.done))}%`, background: "#ff6a13" }} />
              <i style={{ width: `${(100 * r.done) / Math.max(1, ...p.rows.map((x) => x.open + x.done))}%`, background: "#ffb27a" }} /></div><b>{r.open} open · {r.done} done</b></div>)}
          </section>
        ))}
        {s.numbers.map((n) => (
          <section key={n.column} className="card"><h2>{n.title} by group</h2>
            {Object.entries(n.by_group).map(([g, v]) => <div key={g} className="hbar"><span>{g}</span><div><i style={{ width: `${(100 * v) / Math.max(1, ...Object.values(n.by_group))}%`, background: "#0e0e0e" }} /></div>
              <b>{n.type === "money" ? money(v) : num(v, 1)}</b></div>)}
          </section>
        ))}
      </div>
    </>
  );
}

/* ---------- the item panel ---------- */
interface ItemDetail { id: number; board_id: number; name: string; group_id: number | null; parent_id: number | null; values: Record<string, any>; depends_on: number[]; archived: boolean;
  subitems: Item[]; updates: { id: number; user_id: number | null; by: string; body: string; mentions: number[]; reply_to: number | null; likes: number; at: string }[];
  file_list: { id: number; filename: string; mime: string; size: number; by: string; is_image: boolean; at: string }[];
  activity: { by: string; what: string; old: string; new: string; at: string }[] }

function ItemPanel({ ctx, id }: { ctx: Ctx; id: number }) {
  const { data: it, reload } = useLoad<ItemDetail>(`/api/boards/items/${id}`, [id, ctx.b]);
  const [tab, setTab] = useState<"updates" | "files" | "activity">("updates");
  const [text, setText] = useState("");
  const [mentions, setMentions] = useState<number[]>([]);
  const [reply, setReply] = useState<number | null>(null);
  const [run, err, busy] = useAction();
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  const nav = useNavigate();
  useEffect(() => {
    (it?.file_list ?? []).filter((f) => f.is_image && !thumbs[f.id]).forEach((f) => fetchBlobUrl(`/api/boards/files/${f.id}`).then((u) => setThumbs((t) => ({ ...t, [f.id]: u }))).catch(() => undefined));
  }, [it?.file_list]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!it) return null;
  if (it.board_id !== ctx.b.id) { nav(`/boards/${it.board_id}?item=${it.id}`, { replace: true }); return null; }
  const at = text.match(/@(\w*)$/);
  const suggestions = at ? ctx.people.filter((p) => p.name.toLowerCase().startsWith(at[1].toLowerCase())).slice(0, 5) : [];
  const both = async () => { await reload(); await ctx.reload(); };
  const fake: Item = { ...it, position: 0, created_by: null, created_at: "", updated_at: "", files: it.file_list.length, updates: it.updates.length };
  const others = ctx.b.items.filter((x) => x.id !== it.id);
  return (
    <div className="side-panel-back" onClick={() => ctx.open(null)}>
      <aside className="side-panel" onClick={(e) => e.stopPropagation()}>
        <div className="row"><input className="title-input" defaultValue={it.name} key={it.name} onBlur={(e) => e.target.value.trim() && e.target.value !== it.name && run(async () => { await api.patch(`/api/boards/items/${it.id}`, { name: e.target.value }); await both(); })} />
          <button className="link" onClick={() => ctx.open(null)}>✕</button></div>
        <div className="kv item-kv">
          {ctx.b.columns.map((c) => (
            <Fragment key={c.key}><span>{c.title}</span><div className={`cell t-${c.type}`}>
              {c.type === "long_text" ? <textarea defaultValue={it.values[c.key] ?? ""} onBlur={(e) => run(async () => { await api.patch(`/api/boards/items/${it.id}`, { values: { [c.key]: e.target.value || null } }); await both(); })} />
                : <Cell ctx={{ ...ctx, patchItem: (iid, body) => run(async () => { await api.patch(`/api/boards/items/${iid}`, body); await both(); }) }} c={c} it={fake} />}
            </div></Fragment>
          ))}
          <span>Waits for</span>
          <select multiple value={(it.depends_on || []).map(String)} onChange={(e) => run(async () => {
            await api.patch(`/api/boards/items/${it.id}`, { depends_on: Array.from(e.target.selectedOptions).map((o) => +o.value) }); await both(); })} style={{ minHeight: 60 }}>
            {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
        </div>
        {!it.parent_id && (
          <>
            <h3>Subitems</h3>
            {it.subitems.map((s) => {
              const sc = mainStatus(ctx.b.columns);
              return <div key={s.id} className="row small"><span style={{ flex: 1 }}>{s.name}</span>{sc && <StatusPick c={sc} value={s.values[sc.key]}
                onPick={(v) => run(async () => { await api.patch(`/api/boards/items/${s.id}`, { values: { [sc.key]: v } }); await both(); })} />}</div>;
            })}
            <input placeholder="+ Add subitem and press Enter" onKeyDown={(e) => { const v = e.currentTarget.value.trim(); if (e.key === "Enter" && v) { const el = e.currentTarget;
              run(async () => { await api.post(`/api/boards/${ctx.b.id}/items`, { name: v, parent_id: it.id }); el.value = ""; await both(); }); } }} />
          </>
        )}
        <div className="tabs">{(["updates", "files", "activity"] as const).map((t) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
          {t === "updates" ? `Updates (${it.updates.length})` : t === "files" ? `Files (${it.file_list.length})` : "Activity"}</button>)}</div>
        {tab === "updates" && (
          <>
            {reply && <p className="small muted">Replying… <button className="link small" onClick={() => setReply(null)}>cancel</button></p>}
            <textarea placeholder="Write an update. Type @ to mention someone." value={text} onChange={(e) => setText(e.target.value)} />
            {suggestions.length > 0 && <div className="chips">{suggestions.map((p) => <button key={p.user_id} className="chip" onClick={() => {
              setText(text.replace(/@\w*$/, `@${p.name.split(" ")[0]} `)); setMentions([...mentions, p.user_id]); }}>@{p.name}</button>)}</div>}
            <button className="primary" disabled={busy || !text.trim()} onClick={() => run(async () => {
              await api.post(`/api/boards/items/${it.id}/updates`, { body: text, mentions, reply_to: reply }); setText(""); setMentions([]); setReply(null); await both(); })}>Post update</button>
            {it.updates.filter((u) => !u.reply_to).map((u) => (
              <div key={u.id} className="update">
                <div className="row small"><b>{u.by}</b><span className="muted">{new Date(u.at).toLocaleString("en-AU")}</span><span className="spacer" />
                  <button className="link small" onClick={() => run(async () => { await api.post(`/api/boards/updates/${u.id}/like`); await reload(); })}>👍 {u.likes || ""}</button>
                  <button className="link small" onClick={() => setReply(u.id)}>Reply</button></div>
                <p>{u.body}</p>
                {it.updates.filter((r) => r.reply_to === u.id).reverse().map((r) => <div key={r.id} className="update reply"><b className="small">{r.by}</b> <span className="small">{r.body}</span></div>)}
              </div>
            ))}
          </>
        )}
        {tab === "files" && (
          <>
            <label className="button">{busy ? "Uploading…" : "+ Add files"}<input type="file" multiple hidden onChange={(e) => {
              const files = Array.from(e.target.files || []);
              run(async () => { const fd = new FormData(); files.forEach((f) => fd.append("files", f)); await upload(`/api/boards/items/${it.id}/files`, fd); await both(); });
            }} /></label>
            <div className="photo-grid">{it.file_list.map((f) => (
              <div key={f.id} className="file-tile">
                {f.is_image && thumbs[f.id] ? <img src={thumbs[f.id]} alt={f.filename} onClick={() => window.open(thumbs[f.id])} />
                  : <button className="link" onClick={async () => window.open(await fetchBlobUrl(`/api/boards/files/${f.id}`))}>📄 {f.filename}</button>}
                <small className="muted">{f.by} · {fmtDate(f.at)}</small>
                <button className="link small danger" onClick={() => run(async () => { await api.del(`/api/boards/files/${f.id}`); await both(); })}>✕</button>
              </div>))}</div>
          </>
        )}
        {tab === "activity" && it.activity.map((a, i) => (
          <div key={i} className="small activity"><span className="muted">{new Date(a.at).toLocaleString("en-AU")}</span> <b>{a.by}</b> {a.what}{a.old || a.new ? `: ${a.old || "–"} → ${a.new || "–"}` : ""}</div>))}
        <div className="row" style={{ marginTop: 16 }}>
          <button onClick={() => run(async () => { await api.patch(`/api/boards/items/${it.id}`, { archived: !it.archived }); await both(); ctx.open(null); })}>{it.archived ? "Restore" : "Archive"}</button>
          <button className="danger" onClick={() => confirm("Delete this item for good?") && run(async () => { await api.del(`/api/boards/items/${it.id}`); await ctx.reload(); ctx.open(null); })}>Delete</button>
        </div>
        <ErrorLine error={err} />
      </aside>
    </div>
  );
}

/* ---------- modals ---------- */
function ColumnModal({ b, onClose, onDone }: { b: Board; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ title: "", type: "status", options: "" });
  const [run, err, busy] = useAction();
  return (
    <Modal title="Add a column" onClose={onClose}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => {
        await api.post(`/api/boards/${b.id}/columns`, { title: f.title, type: f.type, settings: ["dropdown", "tags"].includes(f.type) ? { options: f.options.split("\n").map((s) => s.trim()).filter(Boolean) } : {} });
        onDone();
      }); }}>
        <div className="type-grid">{TYPES.map(([k, l]) => <button type="button" key={k} className={`chip ${f.type === k ? "on" : ""}`} onClick={() => setF({ ...f, type: k, title: f.title || l.split(" (")[0] })}>{l}</button>)}</div>
        <Field label="Title"><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        {["dropdown", "tags"].includes(f.type) && <Field label="Options (one per line)"><textarea value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} /></Field>}
        <button className="primary" disabled={busy}>Add</button>
        <ErrorLine error={err} />
      </form>
    </Modal>
  );
}

function GroupModal({ b, onClose, onDone }: { b: Board; onClose: () => void; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [run, err, busy] = useAction();
  return (
    <Modal title="Add a group" onClose={onClose}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/api/boards/${b.id}/groups`, { title }); onDone(); }); }}>
        <input required autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Next month" />
        <button className="primary" disabled={busy}>Add</button><ErrorLine error={err} />
      </form>
    </Modal>
  );
}

const TRIGGER_TEXT: Record<string, string> = { item_created: "an item is created", status_change: "a status changes to…", column_change: "a column changes",
  person_assigned: "someone is assigned", date_arrives: "a date arrives", recurring: "every…", subitems_done: "all subitems are done", update_posted: "an update is posted" };
const ACTION_TEXT: Record<string, string> = { notify: "notify", email: "send an email", set_value: "set a column", move_group: "move it to a group",
  create_item: "create an item", create_subitems: "add subitems", set_date_today: "set a date to today", assign: "assign people", archive: "archive it" };

function describe(b: Board, a: Automation) {
  const col = (k?: string) => b.columns.find((c) => c.key === k)?.title ?? k;
  const t = a.trigger;
  let when = TRIGGER_TEXT[t.type] ?? t.type;
  if (t.type === "status_change") when = `${col(t.column)} changes to ${labelsOf(b.columns.find((c) => c.key === t.column)!)?.find((l) => l.key === t.to)?.label ?? "anything"}`;
  if (t.type === "column_change") when = `${col(t.column)} changes`;
  if (t.type === "date_arrives") when = `${t.offset_days ? `${Math.abs(t.offset_days)} day${Math.abs(t.offset_days) > 1 ? "s" : ""} ${t.offset_days < 0 ? "before" : "after"}` : "on"} ${col(t.column)}`;
  if (t.type === "recurring") when = t.every === "week" ? `every ${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][t.weekday ?? 0]}` : t.every === "month" ? `on day ${t.day ?? 1} of each month` : "every weekday";
  const then = a.actions.map((x) => {
    if (x.type === "notify") return `notify ${x.to?.startsWith("column:") ? col(x.to.slice(7)) : x.to}`;
    if (x.type === "move_group") return `move to ${b.groups.find((g) => g.id === x.group_id)?.title ?? "a group"}`;
    if (x.type === "set_value") return `set ${col(x.column)}`;
    return ACTION_TEXT[x.type] ?? x.type;
  }).join(", then ");
  return `When ${when}, ${then}`;
}

function AutomationsModal({ b, people, onClose, reload }: { b: Board; people: Person[]; onClose: () => void; reload: () => Promise<void> }) {
  const status = b.columns.filter((c) => c.type === "status");
  const dates = b.columns.filter((c) => c.type === "date" || c.type === "timeline");
  const persons = b.columns.filter((c) => c.type === "person");
  const [t, setT] = useState<Record<string, any>>({ type: "status_change", column: status[0]?.key, to: labelsOf(status[0] ?? ({} as Col))[0]?.key });
  const [acts, setActs] = useState<Record<string, any>[]>([{ type: "notify", to: persons[0] ? `column:${persons[0].key}` : "owner", text: "{item}: {column:" + (status[0]?.key ?? "status") + "}" }]);
  const [run, err, busy] = useAction();
  const setA = (i: number, v: Record<string, any>) => setActs(acts.map((a, j) => (j === i ? { ...a, ...v } : a)));
  return (
    <Modal title="Automations" onClose={onClose} wide>
      {b.automations.map((a) => (
        <div key={a.id} className="auto-row">
          <label className="inline"><input type="checkbox" checked={a.active} onChange={() => run(async () => { await api.put(`/api/boards/automations/${a.id}`, { ...a, active: !a.active }); await reload(); })} />
            <span><b>{a.name || "Automation"}</b><br /><small>{describe(b, a)}</small></span></label>
          <span className="spacer" /><small className="muted">ran {a.runs}×{a.last_error && <span className="bad"> · {a.last_error}</span>}</small>
          <button className="link danger" onClick={() => run(async () => { await api.del(`/api/boards/automations/${a.id}`); await reload(); })}>✕</button>
        </div>
      ))}
      <h3>New automation</h3>
      <div className="recipe">
        <span>When</span>
        <select value={t.type} onChange={(e) => setT({ type: e.target.value, column: e.target.value === "date_arrives" ? dates[0]?.key : e.target.value === "status_change" ? status[0]?.key : e.target.value === "person_assigned" ? persons[0]?.key : b.columns[0]?.key })}>
          {Object.entries(TRIGGER_TEXT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        {t.type === "status_change" && <><select value={t.column} onChange={(e) => setT({ ...t, column: e.target.value })}>{status.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>
          <select value={t.to} onChange={(e) => setT({ ...t, to: e.target.value })}><option value="*">anything</option>{labelsOf(status.find((c) => c.key === t.column) ?? status[0] ?? ({ settings: {} } as Col)).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select></>}
        {t.type === "column_change" && <select value={t.column} onChange={(e) => setT({ ...t, column: e.target.value })}>{b.columns.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>}
        {t.type === "person_assigned" && <select value={t.column} onChange={(e) => setT({ ...t, column: e.target.value })}>{persons.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>}
        {t.type === "date_arrives" && <><input type="number" style={{ width: 60 }} value={-(t.offset_days || 0)} onChange={(e) => setT({ ...t, offset_days: -(+e.target.value) })} /> <span>days before</span>
          <select value={t.column} onChange={(e) => setT({ ...t, column: e.target.value })}>{dates.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select></>}
        {t.type === "recurring" && <><select value={t.every || "week"} onChange={(e) => setT({ ...t, every: e.target.value })}><option value="day">weekday</option><option value="week">week on</option><option value="month">month on day</option></select>
          {(t.every || "week") === "week" && <select value={t.weekday ?? 0} onChange={(e) => setT({ ...t, weekday: +e.target.value })}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => <option key={d} value={i}>{d}</option>)}</select>}
          {t.every === "month" && <input type="number" min={1} max={28} style={{ width: 60 }} value={t.day ?? 1} onChange={(e) => setT({ ...t, day: +e.target.value })} />}</>}
      </div>
      {acts.map((a, i) => (
        <div key={i} className="recipe">
          <span>{i === 0 ? "then" : "and"}</span>
          <select value={a.type} onChange={(e) => setA(i, { type: e.target.value })}>{Object.entries(ACTION_TEXT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {(a.type === "notify" || a.type === "email") && <select value={a.to} onChange={(e) => setA(i, { to: e.target.value })}>
            <option value="owner">the board owner</option><option value="creator">whoever made the item</option><option value="subscribers">everyone on the item</option>
            {a.type === "notify" && persons.map((c) => <option key={c.key} value={`column:${c.key}`}>the {c.title}</option>)}
            {a.type === "email" && b.columns.filter((c) => c.type === "email").map((c) => <option key={c.key} value={`column:${c.key}`}>the {c.title} address</option>)}</select>}
          {(a.type === "notify" || a.type === "email") && <input placeholder="Message: {item}, {board}, {column:key}" value={a.text || ""} onChange={(e) => setA(i, { text: e.target.value })} style={{ flex: 1 }} />}
          {a.type === "set_value" && <><select value={a.column || ""} onChange={(e) => setA(i, { column: e.target.value, value: undefined })}><option value="">column…</option>{status.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>
            {a.column && <select value={a.value || ""} onChange={(e) => setA(i, { value: e.target.value })}><option value="" />{labelsOf(status.find((c) => c.key === a.column)!).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select>}</>}
          {a.type === "move_group" && <select value={a.group_id || ""} onChange={(e) => setA(i, { group_id: +e.target.value })}><option value="">group…</option>{b.groups.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select>}
          {a.type === "set_date_today" && <select value={a.column || ""} onChange={(e) => setA(i, { column: e.target.value })}><option value="">column…</option>{dates.filter((c) => c.type === "date").map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>}
          {a.type === "assign" && <><select value={a.column || ""} onChange={(e) => setA(i, { column: e.target.value })}><option value="">column…</option>{persons.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}</select>
            <select multiple value={(a.user_ids || []).map(String)} onChange={(e) => setA(i, { user_ids: Array.from(e.target.selectedOptions).map((o) => +o.value) })}>{people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select></>}
          {a.type === "create_item" && <><input placeholder="Item name ({item}, {date})" value={a.name || ""} onChange={(e) => setA(i, { name: e.target.value })} />
            <select value={a.group_id || ""} onChange={(e) => setA(i, { group_id: e.target.value ? +e.target.value : undefined })}><option value="">first group</option>{b.groups.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select></>}
          {a.type === "create_subitems" && <input placeholder="Subitems, comma separated" value={(a.names || []).join(", ")} onChange={(e) => setA(i, { names: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} style={{ flex: 1 }} />}
          {acts.length > 1 && <button className="link danger" onClick={() => setActs(acts.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      <div className="row">
        <button className="link" onClick={() => setActs([...acts, { type: "notify", to: "owner", text: "{item}" }])}>+ another action</button><span className="spacer" />
        <button className="primary" disabled={busy} onClick={() => run(async () => {
          await api.post(`/api/boards/${b.id}/automations`, { name: "", trigger: t, actions: acts }); await reload();
        })}>Add automation</button>
      </div>
      <ErrorLine error={err} />
    </Modal>
  );
}

function FormsModal({ b, onClose, reload }: { b: Board; onClose: () => void; reload: () => Promise<void> }) {
  const [f, setF] = useState({ title: `${b.name} request`, intro: "", columns: b.columns.filter((c) => !["person", "status", "files", "time", "progress"].includes(c.type)).map((c) => c.key), group_id: "" });
  const [run, err, busy] = useAction();
  const [copied, setCopied] = useState("");
  return (
    <Modal title="Forms" onClose={onClose} wide>
      <p className="small muted">A form makes a new item on this board. Share the link with customers, subbies or the team; no sign-in needed.</p>
      {b.forms.map((x) => {
        const url = `${window.location.origin}/forms/${x.token}`;
        return (
          <div key={x.id} className="row wrap">
            <b>{x.title}</b><a href={url} target="_blank" rel="noreferrer" className="small">{url}</a>
            <button className="small" onClick={() => { navigator.clipboard?.writeText(url); setCopied(x.token); }}>{copied === x.token ? "Copied" : "Copy link"}</button>
            <label className="inline small"><input type="checkbox" checked={x.active} onChange={() => run(async () => { await api.put(`/api/boards/forms/${x.id}`, { ...x, active: !x.active }); await reload(); })} /> Open</label>
            <button className="link danger" onClick={() => run(async () => { await api.del(`/api/boards/forms/${x.id}`); await reload(); })}>✕</button>
          </div>
        );
      })}
      <h3>New form</h3>
      <div className="form">
        <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <textarea placeholder="Words at the top of the form" value={f.intro} onChange={(e) => setF({ ...f, intro: e.target.value })} />
        <div className="chips">{b.columns.filter((c) => !["person", "files", "time", "progress", "job", "customer", "timeline"].includes(c.type)).map((c) => (
          <button key={c.key} className={`chip ${f.columns.includes(c.key) ? "on" : ""}`} onClick={() => setF({ ...f, columns: f.columns.includes(c.key) ? f.columns.filter((k) => k !== c.key) : [...f.columns, c.key] })}>{c.title}</button>))}</div>
        <select value={f.group_id} onChange={(e) => setF({ ...f, group_id: e.target.value })}><option value="">Into the first group</option>{b.groups.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select>
        <button className="primary" disabled={busy} onClick={() => run(async () => { await api.post(`/api/boards/${b.id}/forms`, { ...f, group_id: f.group_id ? +f.group_id : null }); await reload(); })}>Make the form</button>
      </div>
      <ErrorLine error={err} />
    </Modal>
  );
}

function SettingsModal({ b, people, onClose, onSaved, onDeleted, onDuplicated }: { b: Board; people: Person[]; onClose: () => void; onSaved: (b: Board) => void;
  onDeleted: () => void; onDuplicated: (id: number) => void }) {
  const [f, setF] = useState({ description: b.description, private: b.private, members: b.members });
  const [run, err, busy] = useAction();
  return (
    <Modal title="Board settings" onClose={onClose}>
      <div className="form">
        <Field label="Description"><textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <label className="inline"><input type="checkbox" checked={f.private} onChange={(e) => setF({ ...f, private: e.target.checked })} /> Private: only members can see it</label>
        <Field label="Members"><div className="chips">{people.map((p) => (
          <button key={p.user_id} className={`chip ${f.members.includes(p.user_id) ? "on" : ""}`} onClick={() => setF({ ...f, members: f.members.includes(p.user_id) ? f.members.filter((x) => x !== p.user_id) : [...f.members, p.user_id] })}>{p.name}</button>))}</div></Field>
        <p className="small muted">Members on the phone app see the board's items they're assigned to in their Today tab.</p>
        <button className="primary" disabled={busy} onClick={() => run(async () => { onSaved(await api.patch<Board>(`/api/boards/${b.id}`, f)); onClose(); })}>Save</button>
        <div className="row wrap">
          <button onClick={() => run(async () => onDuplicated((await api.post<{ id: number }>(`/api/boards/${b.id}/duplicate`, { with_items: true })).id))}>Duplicate with items</button>
          <button onClick={() => run(async () => onDuplicated((await api.post<{ id: number }>(`/api/boards/${b.id}/duplicate`, { with_items: false })).id))}>Duplicate as a template</button>
          <button onClick={() => run(async () => { onSaved(await api.patch<Board>(`/api/boards/${b.id}`, { archived: !b.archived })); onClose(); })}>{b.archived ? "Restore board" : "Archive board"}</button>
          <button className="danger" onClick={() => confirm(`Delete ${b.name} and everything on it?`) && run(async () => { await api.del(`/api/boards/${b.id}`); onDeleted(); })}>Delete</button>
        </div>
        <ErrorLine error={err} />
      </div>
    </Modal>
  );
}

/* ---------- My work ---------- */
interface WorkItem { board_id: number; board: string; item_id: number; name: string; group: string; due: string | null; bucket: string; status_column: string | null;
  status: string | null; status_label: string; labels: Label[] }
export function MyWork() {
  const { data, reload } = useLoad<{ items: WorkItem[]; tasks: { id: number; title: string; due: string | null; done: boolean; overdue: boolean; person: string; user_id: number }[];
    policies: { id: number; title: string }[]; reviews: { id: number; cycle: string; as: string; person: string; due: string | null }[]; surveys: { id: number; title: string }[];
    announcements: { id: number; title: string; body: string; pinned: boolean }[] }>("/api/my-work");
  const [run, err] = useAction();
  if (!data) return <main className="page"><p className="muted">Loading…</p></main>;
  const buckets = ["overdue", "today", "this week", "next week", "later", "no date"];
  return (
    <main className="page">
      <h1>My work</h1>
      {data.announcements.slice(0, 3).map((a) => <div key={a.id} className={`news ${a.pinned ? "pinned" : ""}`}><b>{a.title}</b>{a.body && <p>{a.body}</p>}</div>)}
      {(data.policies.length + data.reviews.length + data.surveys.length + data.tasks.length) > 0 && (
        <section className="card">
          <h2>People</h2>
          {data.policies.map((p) => <p key={`p${p.id}`}>✍️ <Link to={`/field/me/policy/${p.id}`}>Read and sign: {p.title}</Link></p>)}
          {data.reviews.map((r) => <p key={`r${r.id}`}>⭐ <Link to={`/field/me/review/${r.id}`}>{r.as === "self" ? `${r.cycle}: your side` : `Review ${r.person}`}</Link>{r.due && <small className="muted"> due {fmtDate(r.due)}</small>}</p>)}
          {data.surveys.map((s) => <p key={`s${s.id}`}>💬 <Link to={`/field/me/survey/${s.id}`}>{s.title}</Link></p>)}
          {data.tasks.map((t) => <label key={t.id} className={`inline task-row ${t.overdue ? "bad" : ""}`}><input type="checkbox" checked={t.done}
            onChange={() => run(async () => { await api.put(`/api/field/me/tasks/${t.id}`, { done: !t.done }); await reload(); })} />
            <span>{t.title} <small className="muted">· {t.person}{t.due && ` · ${fmtDate(t.due)}`}</small></span></label>)}
        </section>
      )}
      {buckets.map((bk) => {
        const its = data.items.filter((i) => i.bucket === bk);
        if (!its.length) return null;
        return (
          <section key={bk} className="card">
            <h2 className={bk === "overdue" ? "bad" : ""}>{bk[0].toUpperCase() + bk.slice(1)} ({its.length})</h2>
            {its.map((i) => (
              <div key={i.item_id} className="row wrap my-item">
                <Link to={`/boards/${i.board_id}?item=${i.item_id}`}><b>{i.name}</b></Link>
                <span className="muted small">{i.board} · {i.group}</span><span className="spacer" />
                {i.due && <span className="small">{fmtDate(i.due)}</span>}
                {i.status_column && <select value={i.status ?? ""} style={{ background: i.labels.find((l) => l.key === i.status)?.colour, color: i.status ? "#fff" : undefined }}
                  onChange={(e) => run(async () => { await api.patch(`/api/boards/items/${i.item_id}`, { values: { [i.status_column!]: e.target.value || null } }); await reload(); })}>
                  <option value="">–</option>{i.labels.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select>}
              </div>
            ))}
          </section>
        );
      })}
      {data.items.length === 0 && <p className="muted">Nothing assigned to you on the boards. 🎉</p>}
      <ErrorLine error={err} />
    </main>
  );
}
