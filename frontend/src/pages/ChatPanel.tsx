import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMsg } from "../types";

/* The browser's built-in speech recognition (Chrome, Edge, Safari). Not in every TypeScript lib, so typed loosely. */
interface Recognition {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
  start: () => void; stop: () => void;
}
const SpeechRec: (new () => Recognition) | undefined =
  (window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }).SpeechRecognition
  ?? (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

const STARTERS = {
  hydraulic: ["What still needs doing on this job?", "Change all the sanitary drainage to DN150", "Count every FW tag as a floor waste",
    "Approve everything on the first plan"],
  civil: ["What still needs doing on this job?", "Which lines don't have a rate yet?", "Add 120 m of kerb and channel type B",
    "Approve all the stormwater lines"],
};

function loadPref(key: string): boolean {
  try { return localStorage.getItem(key) === "1"; } catch { return false; }
}
function savePref(key: string, on: boolean) {
  try { localStorage.setItem(key, on ? "1" : "0"); } catch { /* storage unavailable */ }
}

export default function ChatPanel({ jobId, kind, onChanged }: { jobId: number; kind: "hydraulic" | "civil"; onChanged: () => void }) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(() => loadPref("chat-speak"));
  const [handsFree, setHandsFree] = useState(() => loadPref("chat-handsfree"));
  const rec = useRef<Recognition | null>(null);
  const heard = useRef("");
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const r = await api.get<{ enabled: boolean; messages: ChatMsg[] }>(`/api/jobs/${jobId}/chat`);
    setEnabled(r.enabled);
    setMsgs(r.messages);
  }, [jobId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);

  const say = (words: string) => {
    if (!speak || !("speechSynthesis" in window) || !words) return;
    const u = new SpeechSynthesisUtterance(words);
    u.lang = "en-AU";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  };

  const send = async (message: string) => {
    const t = message.trim();
    if (!t || busy) return;
    setError("");
    setText("");
    setBusy(true);
    setMsgs((m) => [...m, { id: -Date.now(), role: "user", text: t, actions: [], user: "You" }]);
    try {
      const r = await api.post<{ messages: ChatMsg[]; changed: boolean }>(`/api/jobs/${jobId}/chat`, { text: t });
      await load();
      const reply = r.messages.filter((m) => m.role === "assistant" && m.text).map((m) => m.text).join(" ");
      say(reply);
      if (r.changed) onChanged();
    } catch (e) {
      setError((e as Error).message);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => { e.preventDefault(); send(text); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); }
  };

  const toggleMic = () => {
    if (!SpeechRec) return;
    if (listening) { rec.current?.stop(); return; }
    const r = new SpeechRec();
    r.lang = "en-AU";
    r.interimResults = true;
    r.continuous = false;
    heard.current = "";
    r.onresult = (e) => {
      let finalText = "", interim = "";
      for (let i = 0; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interim += res[0].transcript;
      }
      heard.current = finalText;
      setText((finalText + " " + interim).trim());
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed") setError("The browser blocked the microphone. Allow it in the address bar, then try again.");
      else if (e.error !== "no-speech" && e.error !== "aborted") setError(`Microphone: ${e.error}`);
    };
    r.onend = () => {
      setListening(false);
      if (handsFree && heard.current.trim()) send(heard.current);
    };
    rec.current = r;
    window.speechSynthesis?.cancel();
    r.start();
    setListening(true);
  };

  const fresh = async () => {
    if (!window.confirm("Start a new conversation? The AI keeps its memories; this chat is archived.")) return;
    await api.post(`/api/jobs/${jobId}/chat/new`);
    load();
  };

  return (
    <aside className="chat">
      <div className="chat-head">
        <b>Ask the AI</b>
        <span className="spacer" />
        <button className="link small" onClick={fresh} disabled={busy || !msgs.length}>New chat</button>
      </div>
      <div className="chat-body">
        {!enabled && <p className="warn small">The AI isn't switched on for this server yet (it needs the API key), so the chat can't answer.</p>}
        {enabled && msgs.length === 0 && (
          <div className="chat-empty">
            <p className="muted small">Tell it what to do on this job, by typing or with the microphone. It makes the change, shows you
              what it did, and remembers your preferences for next time.</p>
            {STARTERS[kind].map((s) => <button key={s} className="chip-btn" onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.role === "user" && m.user && <div className="who">{m.user}</div>}
            {m.text && <div className="bubble">{m.text}</div>}
            {m.actions.length > 0 && (
              <ul className="did">{m.actions.map((a, i) => <li key={i}>✓ {a.summary}</li>)}</ul>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing"><span /><span /><span /></div></div>}
        {error && <p className="error small">{error}</p>}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={submit}>
        <textarea rows={2} value={text} placeholder={listening ? "Listening…" : "Type or press the microphone"}
                  onChange={(e) => setText(e.target.value)} onKeyDown={onKey} disabled={!enabled} />
        <div className="row">
          {SpeechRec ? (
            <button type="button" className={`mic ${listening ? "on" : ""}`} onClick={toggleMic} disabled={!enabled || busy}
                    title={listening ? "Stop listening" : "Talk to it"} aria-label="Microphone">🎤</button>
          ) : (
            <span className="small muted" title="Use Chrome, Edge or Safari for the microphone">No mic in this browser</span>
          )}
          <label className="inline small" title="Send as soon as you stop talking">
            <input type="checkbox" checked={handsFree} onChange={(e) => { setHandsFree(e.target.checked); savePref("chat-handsfree", e.target.checked); }} /> hands-free
          </label>
          <label className="inline small" title="Read the replies out loud">
            <input type="checkbox" checked={speak} onChange={(e) => { setSpeak(e.target.checked); savePref("chat-speak", e.target.checked); }} /> read aloud
          </label>
          <span className="spacer" />
          <button className="primary" type="submit" disabled={!enabled || busy || !text.trim()}>Send</button>
        </div>
      </form>
    </aside>
  );
}
