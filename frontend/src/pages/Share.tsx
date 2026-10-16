/* PDF export for ITPs, site pre-starts, SWMS, incidents, toolbox talks and plant pre-starts:
   open it, share it from the phone (Messages, WhatsApp, email, Drive…), download it, or email it from Lorojo. */
import { useState } from "react";
import { api, getToken } from "../api";
import { ErrorLine, Field, Modal, useAction } from "../ui";

export type PdfKind = "itp" | "prestart" | "plant-check" | "swms" | "incident" | "toolbox" | "form";

async function fetchPdf(kind: PdfKind, id: number): Promise<File> {
  const res = await fetch(`/api/field/pdf/${kind}/${id}`, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `${kind}-${id}.pdf`;
  return new File([await res.blob()], name, { type: "application/pdf" });
}

function saveFile(f: File) {
  const url = URL.createObjectURL(f);
  const a = document.createElement("a");
  a.href = url; a.download = f.name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** "PDF" and "Share" buttons; Share uses the phone's share sheet when it can, otherwise downloads. */
export function PdfShare({ kind, id, title, small }: { kind: PdfKind; id: number; title: string; small?: boolean }) {
  const [run, error, busy] = useAction();
  const [emailing, setEmailing] = useState(false);
  const open = () => run(async () => {
    const w = window.open("", "_blank");  // open first so the pop-up isn't blocked
    const f = await fetchPdf(kind, id);
    const url = URL.createObjectURL(f);
    if (w) w.location.href = url; else saveFile(f);
  });
  const share = () => run(async () => {
    const f = await fetchPdf(kind, id);
    const nav = navigator as Navigator & { canShare?: (d: { files: File[] }) => boolean };
    if (nav.share && nav.canShare?.({ files: [f] })) {
      try { await nav.share({ files: [f], title, text: title }); } catch (e) { if ((e as Error).name !== "AbortError") throw e; }
    } else saveFile(f);
  });
  const cls = small ? "small" : "";
  return (
    <span className="pdf-share">
      <button className={cls} onClick={open} disabled={busy}>📄 PDF</button>
      <button className={cls} onClick={share} disabled={busy}>📤 Share</button>
      <button className={cls} onClick={() => setEmailing(true)} disabled={busy}>✉️ Email</button>
      <ErrorLine error={error} />
      {emailing && <EmailPdf kind={kind} id={id} title={title} onClose={() => setEmailing(false)} />}
    </span>
  );
}

function EmailPdf({ kind, id, title, onClose }: { kind: PdfKind; id: number; title: string; onClose: () => void }) {
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState("");
  const [run, error, busy] = useAction();
  const send = () => run(async () => {
    await api.post(`/api/field/pdf/${kind}/${id}/email`, { to, message });
    setSent(`Sent to ${to}.`);
  });
  return (
    <Modal title={`Email ${title}`} onClose={onClose}>
      {sent ? <><p className="ok">{sent}</p><button onClick={onClose}>Done</button></> : (
        <div className="stack">
          <Field label="To" hint="One or more addresses, separated by commas"><input inputMode="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="builder@example.com" autoFocus /></Field>
          <Field label="Message (optional)"><textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
          <ErrorLine error={error} />
          <button className="primary" onClick={send} disabled={busy || to.trim().length < 3}>{busy ? "Sending…" : "Send with the PDF attached"}</button>
        </div>
      )}
    </Modal>
  );
}
