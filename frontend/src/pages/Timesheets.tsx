/* Timesheets: everyone's week, with what needs checking flagged; approve, fix, export for payroll; leave requests. */
import { Fragment, useState } from "react";
import { api, download } from "../api";
import { addDays, DataTable, ErrorLine, Field, fmtDate, fmtDay, hrs, Modal, monday, num, Status, Tabs, todayIso, useAction, useLoad } from "../ui";

interface Entry { id: number; user_id: number; job_id: number | null; job_no: string; job: string; task: string; local_day: string; start_local: string; end_local: string | null;
  hours: number; break_minutes: number; status: string; notes: string; source: string; flags: string[]; start_lat: number | null; start_lng: number | null; edited_reason: string }
interface Person { user_id: number; name: string; trade: string; entries: Entry[]; days: Record<string, number>; total: number; ordinary: number; overtime: number;
  leave_hours: number; open: number; submitted: number; approved: number; flags: number }

export default function Timesheets() {
  const [tab, setTab] = useState<"week" | "leave">(() => (new URLSearchParams(window.location.search).get("tab") === "leave" ? "leave" : "week"));
  const [start, setStart] = useState(monday(todayIso()));
  const { data, reload } = useLoad<{ start: string; days: string[]; people: Person[] }>(`/api/timesheets?start=${start}`, [start]);
  const jobs = useLoad<{ id: number; job_no: string; name: string }[]>("/api/work?status=");
  const [open, setOpen] = useState<number | null>(null);
  const [edit, setEdit] = useState<(Partial<Entry> & { day?: string; start?: string; end?: string; reason?: string }) | null>(null);
  const [run, error] = useAction();
  const save = () => run(async () => {
    if (!edit) return;
    const body = { user_id: edit.user_id, job_id: edit.job_id || null, task: edit.task ?? "", day: edit.day, start: edit.start, end: edit.end,
      break_minutes: edit.break_minutes ?? 0, notes: edit.notes ?? "", reason: edit.reason ?? "" };
    if (edit.id) await api.put(`/api/timesheets/entries/${edit.id}`, body); else await api.post("/api/timesheets/entries", body);
    setEdit(null); reload();
  });
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Timesheets</h1><span className="spacer" />
        <Tabs tabs={[["week", "Week"], ["leave", "Leave requests"]]} value={tab} onChange={setTab} /></div>
      {tab === "leave" ? <Leave /> : (
        <>
          <div className="row wrap">
            <button onClick={() => setStart(addDays(start, -7))}>‹</button><b>Week of {fmtDay(start)}</b><button onClick={() => setStart(addDays(start, 7))}>›</button>
            <span className="spacer" />
            <button onClick={() => download(`/api/timesheets/payroll.csv?start=${start}`, "timesheets.csv")}>Payroll export (approved)</button>
          </div>
          <section className="card">
            <div className="dt-wrap"><table className="dt">
              <thead><tr><th>Person</th>{data?.days.map((d) => <th key={d} className="n">{fmtDay(d).split(" ")[0]}</th>)}<th className="n">Total</th><th className="n">OT</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {data?.people.map((p) => (
                  <Fragment key={p.user_id}>
                    <tr className="click" onClick={() => setOpen(open === p.user_id ? null : p.user_id)}>
                      <td><b>{p.name}</b> <span className="small muted">{p.trade}</span>{p.flags > 0 && <span className="badge warn">{p.flags} to check</span>}</td>
                      {data.days.map((d) => <td key={d} className="n">{p.days[d] ? num(p.days[d], 2) : ""}</td>)}
                      <td className="n"><b>{num(p.total, 2)}</b></td><td className="n">{p.overtime ? num(p.overtime, 2) : ""}</td>
                      <td className="small">{p.approved ? `${p.approved} approved ` : ""}{p.submitted ? `${p.submitted} submitted ` : ""}{p.open ? `${p.open} open` : ""}</td>
                      <td onClick={(e) => e.stopPropagation()}>{(p.submitted + p.open) > 0 && <button className="small" onClick={() => run(async () => { await api.post("/api/timesheets/approve", { user_id: p.user_id, start }); reload(); })}>Approve week</button>}</td>
                    </tr>
                    {open === p.user_id && (
                      <tr><td colSpan={(data.days.length ?? 7) + 5}>
                        <DataTable rows={p.entries} cols={[
                          { key: "d", label: "Day", render: (e) => fmtDay(e.local_day) },
                          { key: "t", label: "Time", render: (e) => `${e.start_local}–${e.end_local ?? "now"}${e.break_minutes ? ` (${e.break_minutes} min break)` : ""}` },
                          { key: "j", label: "Job", render: (e) => `${e.job_no} ${e.job}`.trim() || "No job" },
                          { key: "k", label: "Task", hideSm: true, render: (e) => e.task },
                          { key: "h", label: "Hours", num: true, render: (e) => num(e.hours, 2) },
                          { key: "s", label: "", render: (e) => <><Status value={e.status} />{e.flags.map((f) => <span key={f} className="badge warn" title={e.edited_reason}>{f}</span>)}
                            {e.start_lat !== null && <a className="small" href={`https://maps.google.com/?q=${e.start_lat},${e.start_lng}`} target="_blank" rel="noreferrer"> 📍</a>}</> },
                          { key: "x", label: "", render: (e) => <button className="link small" onClick={() => setEdit({ ...e, day: e.local_day, start: e.start_local, end: e.end_local ?? "" })}>edit</button> },
                        ]} />
                        <button className="small" onClick={() => setEdit({ user_id: p.user_id, day: start, start: "07:00", end: "15:30", break_minutes: 30 })}>+ Add time for {p.name.split(" ")[0]}</button>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table></div>
            <p className="small muted">Click a person to see and fix their entries. Approving freezes each entry's cost rate for job costing. Flags: long shifts, time added by hand, edited, clocked in with no location.</p>
          </section>
          <ErrorLine error={error} />
        </>
      )}
      {edit && (
        <Modal title={edit.id ? "Fix time" : "Add time"} onClose={() => setEdit(null)}>
          <Field label="Job"><select value={edit.job_id ?? ""} onChange={(e) => setEdit({ ...edit, job_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">No job</option>{jobs.data?.map((j) => <option key={j.id} value={j.id}>{j.job_no} {j.name}</option>)}</select></Field>
          <div className="row wrap"><input type="date" value={edit.day} onChange={(e) => setEdit({ ...edit, day: e.target.value })} />
            <input type="time" value={edit.start} onChange={(e) => setEdit({ ...edit, start: e.target.value })} /> to <input type="time" value={edit.end} onChange={(e) => setEdit({ ...edit, end: e.target.value })} />
            <label className="inline small">Break <input type="number" style={{ width: 60 }} value={edit.break_minutes ?? 0} onChange={(e) => setEdit({ ...edit, break_minutes: Number(e.target.value) })} /> min</label></div>
          <Field label="Task"><input value={edit.task ?? ""} onChange={(e) => setEdit({ ...edit, task: e.target.value })} /></Field>
          <Field label="Why (kept with the entry)"><input value={edit.reason ?? ""} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} placeholder="e.g. forgot to clock off" /></Field>
          <div className="row"><button className="primary" onClick={save}>Save</button>
            {edit.id && <button onClick={() => window.confirm("Delete this time?") && run(async () => { await api.del(`/api/timesheets/entries/${edit.id}`); setEdit(null); reload(); })}>Delete</button>}</div>
          <ErrorLine error={error} />
        </Modal>
      )}
      <p className="small muted">{hrs(data?.people.reduce((s, p) => s + p.total, 0))} clocked this week.</p>
    </main>
  );
}

function Leave() {
  const { data, reload } = useLoad<{ id: number; name: string; kind: string; start_date: string; end_date: string; hours: number | null; notes: string; status: string }[]>("/api/time-off");
  const [run, error] = useAction();
  return (
    <section className="card">
      <DataTable rows={data ?? []} cols={[
        { key: "n", label: "Who", render: (r) => r.name },
        { key: "k", label: "Type", render: (r) => r.kind },
        { key: "d", label: "When", render: (r) => `${fmtDate(r.start_date)} – ${fmtDate(r.end_date)}` },
        { key: "x", label: "Notes", hideSm: true, render: (r) => r.notes },
        { key: "s", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "a", label: "", render: (r) => r.status === "requested" && <span className="row tight">
          <button className="small" onClick={() => run(async () => { await api.put(`/api/time-off/${r.id}`, { status: "approved" }); reload(); })}>Approve</button>
          <button className="small" onClick={() => run(async () => { await api.put(`/api/time-off/${r.id}`, { status: "declined" }); reload(); })}>Decline</button></span> },
      ]} />
      <ErrorLine error={error} />
    </section>
  );
}
