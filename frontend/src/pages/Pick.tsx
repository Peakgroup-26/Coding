import { useEffect, useState } from "react";

/** Tap one: a row of buttons. Tapping the chosen one again clears it (unless required). */
export function Chips<T extends string>({ options, value, onChange, required = false }: {
  options: (T | { key: T; label: string })[]; value: T | ""; onChange: (v: T | "") => void; required?: boolean;
}) {
  return (
    <div className="chips" role="radiogroup">
      {options.map((o) => {
        const key = typeof o === "string" ? o : o.key;
        const label = typeof o === "string" ? o : o.label;
        return (
          <button type="button" key={key} role="radio" aria-checked={value === key} className={value === key ? "chip on" : "chip"}
                  onClick={() => onChange(value === key && !required ? "" : key)}>{label}</button>
        );
      })}
    </div>
  );
}

const NEW = "\u0000new";

/** A drop-down of what's been used before, with "+ New…" for anything else.
 *  `lazy` hands over a typed value only when the box is left (for fields that save as they change). */
export function PickOrNew({ options, value, onChange, placeholder, newLabel = "+ New…", emptyLabel = "Choose…", lazy = false }: {
  options: string[]; value: string; onChange: (v: string) => void; placeholder: string; newLabel?: string; emptyLabel?: string; lazy?: boolean;
}) {
  const known = !value || options.includes(value);
  const [typing, setTyping] = useState(!known);
  const [draft, setDraft] = useState(value);
  useEffect(() => { if (value && !options.includes(value)) setTyping(true); }, [value, options]);
  useEffect(() => setDraft(value), [value]);
  if (typing) {
    return (
      <span className="pick-new">
        {lazy
          ? <input autoFocus placeholder={placeholder} value={draft} onChange={(e) => setDraft(e.target.value)}
                   onBlur={() => onChange(draft.trim())} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onChange(draft.trim()); } }} />
          : <input autoFocus placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />}
        {options.length > 0 && <button type="button" className="link small" onClick={() => { setTyping(false); onChange(""); }}>pick from list</button>}
      </span>
    );
  }
  return (
    <select value={value} onChange={(e) => (e.target.value === NEW ? (setTyping(true), onChange("")) : onChange(e.target.value))}>
      <option value="">{emptyLabel}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
      <option value={NEW}>{newLabel}</option>
    </select>
  );
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const daysFromToday = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d); };

/** Quick date choices ("Today", "In a week"…) with a calendar for anything else. */
export function DateChips({ value, onChange, choices, allowNone }: {
  value: string; onChange: (v: string) => void; choices: [string, number][]; allowNone?: string;
}) {
  const preset = choices.find(([, n]) => daysFromToday(n) === value);
  const [picking, setPicking] = useState(!!value && !preset);
  return (
    <div className="chips">
      {allowNone && <button type="button" className={!value && !picking ? "chip on" : "chip"} onClick={() => { setPicking(false); onChange(""); }}>{allowNone}</button>}
      {choices.map(([label, n]) => (
        <button type="button" key={label} className={!picking && value === daysFromToday(n) ? "chip on" : "chip"}
                onClick={() => { setPicking(false); onChange(daysFromToday(n)); }}>{label}</button>
      ))}
      <button type="button" className={picking ? "chip on" : "chip"} onClick={() => setPicking(true)}>Pick a date</button>
      {picking && <input type="date" value={value} onChange={(e) => onChange(e.target.value)} />}
    </div>
  );
}
