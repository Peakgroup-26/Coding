/* The schedule board: people down the side, days across. Click a cell to book someone onto a job; drag a booking to move it.
   Changes stay unpublished (dashed) until "Publish", then they show on each person's phone. */
import { DragEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { addDays, ErrorLine, Field, fmtDay, Modal, monday, todayIso, useAction, useLoad } from "../ui";

interface Person { id: number; name: string; trade: string; colour: string; role: string }
interface Entry { id: number; user_id: number; job_id: number | null; job_no: string; job: string; address: string; day: string; start: string; end: string; kind: string; notes: string; published: boolean; priority: string }
interface Board { start: string; days: number; people: Person[]; entries: Entry[]; leave: { user_id: number; kind: string; start_date: string; end_date: string; status: string }[]; unpublished: number }
interface Live { name: string; job_no: string; job: string; since: string; on_break: boolean; start_lat: number | null; start_lng: number | null }

export default function Schedule() {
  const [start, setStart] = useState(monday(todayIso()));
  const { data, reload } = useLoad<Board>(`/api/schedule?start=${start}&days=7`, [start]);
  const live = useLoad<Live[]>("/api/timesheets/live");
  const jobs = useLoad<{ id: number; job_no: string; name: string; customer: string }[]>("/api/work");
  const [edit, setEdit] = useState<Partial<Entry> | null>(null);
  const [run, error] = useAction();
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const onDrop = (e: DragEvent, user_id: number, day: string) => {
    e.preventDefault();
    const id = Number(e.dataTransfer.getData("text/plain"));
    const en = data?.entries.find((x) => x.id === id);
    if (!en || (en.user_id === user_id && en.day === day)) return;
    run(async () => { await api.put(`/api/schedule/${id}`, { ...en, user_id, day }); reload(); });
  };
  const save = () => run(async () => {
    if (!edit) return;
    const body = { user_id: edit.user_id, job_id: edit.job_id || null, day: edit.day, start: edit.start, end: edit.end, kind: edit.kind ?? "work", notes: edit.notes ?? "" };
    if (edit.id) await api.put(`/api/schedule/${edit.id}`, body); else await api.post("/api/schedule", body);
    setEdit(null); reload();
  });
  const onLeave = (uid: number, d: string) => data?.leave.find((l) => l.user_id === uid && l.start_date <= d && l.end_date >= d);
  return (
    <main className="page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Schedule</h1>
        <button onClick={() => setStart(addDays(start, -7))}>‹</button><b>{fmtDay(start)} – {fmtDay(addDays(start, 6))}</b><button onClick={() => setStart(addDays(start, 7))}>›</button>
        <button className="link" onClick={() => setStart(monday(todayIso()))}>This week</button>
        <span className="spacer" />
        <button onClick={() => run(async () => { const r = await api.post<{ copied: number }>("/api/schedule/copy-week", { from_start: addDays(start, -7), to_start: start }); reload(); window.alert(`Copied ${r.copied} bookings from last week`); })}>Copy last week</button>
        <button className="primary" disabled={!data?.unpublished} onClick={() => run(async () => { await api.post("/api/schedule/publish", { start, days: 7 }); reload(); })}>
          Publish{data?.unpublished ? ` (${data.unpublished})` : ""}</button>
      </div>
      <ErrorLine error={error} />
      <div className="sched-wrap">
        <table className="sched">
          <thead><tr><th>Person</th>{days.map((d) => <th key={d} className={d === todayIso() ? "today" : ""}>{fmtDay(d)}</th>)}</tr></thead>
          <tbody>
            {data?.people.map((p) => (
              <tr key={p.id}>
                <th><b>{p.name}</b><div className="small muted">{p.trade}</div></th>
                {days.map((d) => {
                  const lv = onLeave(p.id, d);
                  return (
                    <td key={d} className={d === todayIso() ? "today" : ""} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, p.id, d)}
                        onClick={(e) => { if (e.target === e.currentTarget) setEdit({ user_id: p.id, day: d, start: "07:00", end: "15:30", kind: "work" }); }}>
                      {lv && <div className={`booking leave ${lv.status}`}>{lv.kind} leave{lv.status === "requested" ? "?" : ""}</div>}
                      {data.entries.filter((e) => e.user_id === p.id && e.day === d).map((e) => (
                        <div key={e.id} className={`booking ${e.published ? "" : "draft"} ${e.priority === "urgent" ? "urgent" : ""} k-${e.kind}`} draggable
                             onDragStart={(ev) => ev.dataTransfer.setData("text/plain", String(e.id))} onClick={() => setEdit(e)} title={e.address}>
                          <b>{e.start}–{e.end}</b> {e.job_no || e.kind}<span>{e.job}</span>
                        </div>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
            {data && data.people.length === 0 && <tr><td colSpan={8} className="muted">Set people's trade (plumber, apprentice...) or the "On the tools" role in Admin → People to put them on the board.</td></tr>}
          </tbody>
        </table>
      </div>
      <section className="card">
        <h2>On the clock now</h2>
        {live.data?.length === 0 && <p className="muted small">Nobody's clocked in.</p>}
        <div className="live-grid">{live.data?.map((l, i) => (
          <div key={i} className="live">{l.on_break ? "☕" : "🟢"} <b>{l.name}</b> since {l.since}<span>{l.job_no} {l.job || "No job"}</span>
            {l.start_lat !== null && <a className="small" href={`https://maps.google.com/?q=${l.start_lat},${l.start_lng}`} target="_blank" rel="noreferrer">clocked in here 📍</a>}</div>))}</div>
      </section>
      {edit && (
        <Modal title={edit.id ? "Booking" : "Book someone in"} onClose={() => setEdit(null)}>
          <Field label="Person"><select value={edit.user_id} onChange={(e) => setEdit({ ...edit, user_id: Number(e.target.value) })}>
            {data?.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Job"><select value={edit.job_id ?? ""} onChange={(e) => setEdit({ ...edit, job_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">No job</option>{jobs.data?.map((j) => <option key={j.id} value={j.id}>{j.job_no} {j.name} – {j.customer}</option>)}</select></Field>
          <div className="row wrap">
            <input type="date" value={edit.day} onChange={(e) => setEdit({ ...edit, day: e.target.value })} />
            <input type="time" value={edit.start} onChange={(e) => setEdit({ ...edit, start: e.target.value })} /> to
            <input type="time" value={edit.end} onChange={(e) => setEdit({ ...edit, end: e.target.value })} />
            <select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{["work", "training", "leave", "other"].map((k) => <option key={k}>{k}</option>)}</select>
          </div>
          <Field label="Notes for them"><textarea rows={2} value={edit.notes ?? ""} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></Field>
          <div className="row"><button className="primary" onClick={save}>Save</button>
            {edit.id && <button onClick={() => run(async () => { await api.del(`/api/schedule/${edit.id}`); setEdit(null); reload(); })}>Remove</button>}
            {edit.job_id && <Link to={`/work/${edit.job_id}`} className="small">Open job ›</Link>}</div>
          <ErrorLine error={error} />
        </Modal>
      )}
    </main>
  );
}
