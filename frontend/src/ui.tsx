/* Shared bits for the operations pages: loading data, tabs, modals, money and dates, the microphone,
   photo capture and signatures. */
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api, fetchBlobUrl, upload } from "./api";

export function useLoad<T>(url: string | null, deps: unknown[] = []): { data: T | null; error: string; reload: () => Promise<void>; set: (t: T) => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!url) return;
    try { setData(await api.get<T>(url)); setError(""); } catch (e) { setError((e as Error).message); }
  }, [url]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload, ...deps]);
  return { data, error, reload, set: setData };
}

export const money = (v: number | null | undefined, cents = false) =>
  (v ?? 0).toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: cents ? 2 : 0, minimumFractionDigits: cents ? 2 : 0 });
export const num = (v: number | null | undefined, dp = 1) => (v ?? 0).toLocaleString("en-AU", { maximumFractionDigits: dp });
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${num(v)}%`);
export const fmtDate = (iso?: string | null) => (iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-AU") : "");
export const fmtDay = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });
export const fmtTime = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }) : "");
export const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
export const addDays = (iso: string, n: number) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
export const monday = (iso: string) => { const d = new Date(iso + "T00:00:00"); const wd = (d.getDay() + 6) % 7; return addDays(iso, -wd); };
export const hrs = (h: number | null | undefined) => `${num(h ?? 0, 2)} h`;

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs scroll">
      {tabs.map(([k, label]) => <button key={k} className={value === k ? "active" : ""} onClick={() => onChange(k)}>{label}</button>)}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{title}</h2><span className="spacer" /><button className="link" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small className="muted">{hint}</small>}</label>;
}

export function Status({ value, labels }: { value: string; labels?: Record<string, string> }) {
  return <span className={`status-chip s-${value}`}>{labels?.[value] ?? value.replace(/_/g, " ")}</span>;
}

export function ErrorLine({ error }: { error: string }) {
  return error ? <p className="error">{error}</p> : null;
}

/** Run an action and show its error. */
export function useAction(): [(fn: () => Promise<unknown>) => Promise<boolean>, string, boolean, (e: string) => void] {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setError(""); setBusy(true);
    try { await fn(); return true; } catch (e) { setError((e as Error).message); return false; } finally { setBusy(false); }
  };
  return [run, error, busy, setError];
}

/* --- microphone (browser speech recognition, Australian English) --- */
interface Recognition {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
  start: () => void; stop: () => void;
}
const SpeechRec: (new () => Recognition) | undefined =
  (window as unknown as { SpeechRecognition?: new () => Recognition }).SpeechRecognition
  ?? (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

/** Speech to text. continuous: keep listening through pauses until stop() (for dictating a whole list). */
export function useMic(onFinal: (text: string) => void, onInterim?: (text: string) => void, continuous = false) {
  const [listening, setListening] = useState(false);
  const rec = useRef<Recognition | null>(null);
  const heard = useRef("");
  const supported = !!SpeechRec;
  const start = () => {
    if (!SpeechRec || listening) return;
    const r = new SpeechRec();
    r.lang = "en-AU"; r.interimResults = true; r.continuous = continuous;
    heard.current = "";
    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) heard.current += (heard.current && continuous ? " " : "") + res[0].transcript.trim(); else interim += " " + res[0].transcript;
      }
      onInterim?.((heard.current + interim).trim());
    };
    r.onend = () => { setListening(false); if (heard.current.trim()) onFinal(heard.current.trim()); };
    r.onerror = () => setListening(false);
    rec.current = r;
    setListening(true);
    r.start();
  };
  const stop = () => rec.current?.stop();
  return { supported, listening, start, stop };
}

export function speak(words: string) {
  if (!("speechSynthesis" in window) || !words) return;
  const u = new SpeechSynthesisUtterance(words);
  u.lang = "en-AU";
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

/* --- photos and signatures --- */
/** Shrink a phone photo before upload (most are 4-12 MB). */
export async function shrinkImage(file: File, maxPx = 1800): Promise<Blob> {
  if (!file.type.startsWith("image/")) return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxPx / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
    c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise<Blob>((res) => c.toBlob((b) => res(b ?? file), "image/jpeg", 0.82));
  } catch { return file; }
}

export interface DocOut { id: number; filename: string; title: string; folder: string; mime: string; version: number; is_image: boolean; created_at: string; size: number; field_visible: boolean; job_id: number | null }

/** A big "take photo" button; uploads straight away and reports the stored document. */
export function PhotoButton({ label, jobId, done, onDone, folder = "Photos" }: { label: string; jobId?: number | null; done?: boolean; onDone: (d: DocOut) => void; folder?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const take = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true); setError("");
    try {
      const blob = await shrinkImage(f);
      setPreview(URL.createObjectURL(blob));
      const form = new FormData();
      form.append("file", new File([blob], f.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }));
      form.append("folder", folder);
      form.append("title", label);
      if (jobId) form.append("job_id", String(jobId));
      onDone(await upload<DocOut>("/api/field/upload", form));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className={`photo-btn ${done ? "done" : ""}`}>
      <button type="button" onClick={() => input.current?.click()} disabled={busy}>
        {preview ? <img src={preview} alt="" /> : <span className="cam">📷</span>}
        <span>{busy ? "Uploading…" : done ? `✓ ${label}` : label}</span>
      </button>
      <input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={(e) => take(e.target.files?.[0])} />
      {error && <small className="error">{error}</small>}
    </div>
  );
}

export function SignaturePad({ onChange }: { onChange: (dataUrl: string) => void }) {
  const c = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const pos = (e: React.PointerEvent) => {
    const r = c.current!.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.current!.width / r.width), (e.clientY - r.top) * (c.current!.height / r.height)];
  };
  const down = (e: React.PointerEvent) => { drawing.current = true; const [x, y] = pos(e); const g = c.current!.getContext("2d")!; g.beginPath(); g.moveTo(x, y); };
  const move = (e: React.PointerEvent) => {
    if (!drawing.current) return;
    const [x, y] = pos(e); const g = c.current!.getContext("2d")!;
    g.lineWidth = 3; g.lineCap = "round"; g.strokeStyle = "#161616"; g.lineTo(x, y); g.stroke();
  };
  const up = () => { if (drawing.current) { drawing.current = false; onChange(c.current!.toDataURL("image/png")); } };
  const clear = () => { const g = c.current!.getContext("2d")!; g.clearRect(0, 0, 600, 200); onChange(""); };
  return (
    <div className="sig">
      <canvas ref={c} width={600} height={200} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up} style={{ touchAction: "none" }} />
      <button type="button" className="link small" onClick={clear}>Clear</button>
    </div>
  );
}

/** Where the phone is (for clock-ins); resolves to nulls if the person says no or it takes too long. */
export function getLocation(): Promise<{ lat: number | null; lng: number | null }> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) { resolve({ lat: null, lng: null }); return; }
    const t = setTimeout(() => resolve({ lat: null, lng: null }), 8000);
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(t); resolve({ lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6) }); },
      () => { clearTimeout(t); resolve({ lat: null, lng: null }); },
      { enableHighAccuracy: true, timeout: 7000, maximumAge: 60000 });
  });
}

/** A small table that turns into stacked cards on a phone. */
export function DataTable<R>({ rows, cols, empty = "Nothing here yet.", onRow, rowClass }: {
  rows: R[]; cols: { key: string; label: string; render: (r: R) => ReactNode; num?: boolean; hideSm?: boolean }[];
  empty?: string; onRow?: (r: R) => void; rowClass?: (r: R) => string;
}) {
  return (
    <div className="dt-wrap">
      <table className="dt">
        <thead><tr>{cols.map((c) => <th key={c.key} className={`${c.num ? "n" : ""} ${c.hideSm ? "hide-sm" : ""}`}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`${onRow ? "click" : ""} ${rowClass?.(r) ?? ""}`} onClick={() => onRow?.(r)}>
              {cols.map((c) => <td key={c.key} data-label={c.label} className={`${c.num ? "n" : ""} ${c.hideSm ? "hide-sm" : ""}`}>{c.render(r)}</td>)}
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={cols.length} className="muted">{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

/** A person's photo (fetched with the sign-in token), or their initials. */
export function Avatar({ userId, name, has, small }: { userId: number; name: string; has: boolean; small?: boolean }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    if (!has) return;
    let gone = false;
    fetchBlobUrl(`/api/field/me/photo/${userId}`).then((u) => { if (!gone) setSrc(u); }).catch(() => undefined);
    return () => { gone = true; };
  }, [userId, has]);
  const initials = name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
  return <span className={`avatar ${small ? "sm" : ""}`}>{src ? <img src={src} alt="" /> : initials}</span>;
}
