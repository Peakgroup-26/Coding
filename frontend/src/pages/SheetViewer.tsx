import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Arrow, Circle, Group, Image as KImage, Layer, Line, Rect, Stage, Text } from "react-konva";
import type Konva from "konva";
import { api, fetchBlobUrl } from "../api";
import { useApp } from "../App";
import type { CountItem, Flag, Job, Level, Pt, Run, Service, Sheet, Totals, Viewport } from "../types";
import { SnapIndex, dist, fmtM, ortho, polyLength } from "../util";
import { TotalsTables } from "./Job";
import { AiAssist } from "./AiAssist";
import { DiffOverlay, ShortcutsHelp, type Diff } from "./RevisionCompare";

type Tool = "pan" | "calibrate" | "verify" | "trace" | "riser" | "count" | "viewport";
type ScaleTarget = { kind: "sheet" } | { kind: "viewport"; id: number };
type Selection = { kind: "run" | "count"; id: number } | null;

const TOOL_KEYS: Record<string, Tool> = { h: "pan", k: "calibrate", t: "trace", r: "riser", n: "count" };
const COMMON_DN = [15, 20, 25, 32, 40, 50, 65, 80, 90, 100, 150, 225, 300];

export default function SheetViewer() {
  const { sheetId } = useParams();
  const [searchParams] = useSearchParams();
  const [flags, setFlags] = useState<Flag[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [pin, setPin] = useState<Pt | null>(null); // a location linked to from a flag
  const [highlight, setHighlight] = useState<[number, number, number, number] | null>(null); // a line style's extent
  const [revisions, setRevisions] = useState<{ id: number; revision: string; is_current: boolean; runs: number; counts: number }[]>([]);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [compareMsg, setCompareMsg] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  useEffect(() => {
    api.get<typeof revisions>(`/api/sheets/${sheetId}/revisions`).then(setRevisions).catch(() => setRevisions([]));
  }, [sheetId]);
  const { settings } = useApp();
  const services = settings.services.filter((s) => s.active);
  const serviceById = useMemo(() => new Map(settings.services.map((s) => [s.id, s])), [settings.services]);

  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [counts, setCounts] = useState<CountItem[]>([]);
  const [levels, setLevels] = useState<Level[]>([]);
  const [totals, setTotals] = useState<Totals | null>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [snaps, setSnaps] = useState<SnapIndex | null>(null);
  const [error, setError] = useState("");

  const [tool, setTool] = useState<Tool>("pan");
  const [scaleTarget, setScaleTarget] = useState<ScaleTarget>({ kind: "sheet" });
  const [draft, setDraft] = useState<Pt[]>([]);
  const [cursor, setCursor] = useState<Pt | null>(null);
  const [snapOn, setSnapOn] = useState(true);
  const [selected, setSelected] = useState<Selection>(null);
  const [pendingDistance, setPendingDistance] = useState("");

  // Properties applied to new runs and counts
  const [serviceId, setServiceId] = useState<number>(services[0]?.id ?? 0);
  const [dn, setDn] = useState(100);
  const [material, setMaterial] = useState(settings.materials[0]?.name ?? "");
  const [levelId, setLevelId] = useState<number | null>(null);
  const [stageId, setStageId] = useState<number | null>(null); // null = service default
  const [locationTag, setLocationTag] = useState("");
  const [dropCount, setDropCount] = useState(0);
  const [dropHeight, setDropHeight] = useState(0);
  const [riserMode, setRiserMode] = useState<"manual" | "levels">("manual");
  const [riserFrom, setRiserFrom] = useState<number | null>(null);
  const [riserTo, setRiserTo] = useState<number | null>(null);
  const [countType, setCountType] = useState(
    (settings.count_types.find((c) => c.name === "WC") ?? settings.count_types[0])?.name ?? "");

  // View
  const wrapRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [spaceDown, setSpaceDown] = useState(false);
  const [shiftDown, setShiftDown] = useState(false);

  const loadSheet = useCallback(async () => {
    const s = await api.get<Sheet>(`/api/sheets/${sheetId}`);
    setSheet(s);
    return s;
  }, [sheetId]);
  const loadItems = useCallback(async (jobId: number) => {
    const [r, c, t, f, j] = await Promise.all([
      api.get<Run[]>(`/api/sheets/${sheetId}/runs`),
      api.get<CountItem[]>(`/api/sheets/${sheetId}/counts`),
      api.get<Totals>(`/api/jobs/${jobId}/totals`),
      api.get<Flag[]>(`/api/jobs/${jobId}/flags`),
      api.get<Job>(`/api/jobs/${jobId}`),
    ]);
    setRuns(r); setCounts(c); setTotals(t); setJob(j);
    setFlags(f.filter((x) => x.sheet_id === Number(sheetId) && x.status === "open"));
  }, [sheetId]);

  useEffect(() => {
    let url = "";
    (async () => {
      const s = await loadSheet();
      await loadItems(s.job_id);
      setLevels(await api.get<Level[]>(`/api/jobs/${s.job_id}/levels`));
      url = await fetchBlobUrl(`/api/sheets/${s.id}/image`);
      const im = new window.Image();
      im.onload = () => setImg(im);
      im.src = url;
      const pts = await api.get<Pt[]>(`/api/sheets/${s.id}/snap-points`);
      setSnaps(new SnapIndex(pts));
    })().catch((e) => setError(e.message));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [loadSheet, loadItems]);

  // Fit to window on first load and on resize of the container
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const fit = useCallback(() => {
    if (!sheet) return;
    const scale = Math.min(size.w / sheet.width_pt, size.h / sheet.height_pt) * 0.97;
    setView({ scale, x: (size.w - sheet.width_pt * scale) / 2, y: (size.h - sheet.height_pt * scale) / 2 });
  }, [sheet, size]);
  const fitted = useRef(false);
  useEffect(() => { if (sheet && size.w > 0 && !fitted.current) { fit(); fitted.current = true; } }, [sheet, size, fit]);

  // Links from fittings lines and check-measure flags: ?run=12, ?count=5 or ?x=..&y=..
  const linkHandled = useRef(false);
  useEffect(() => {
    if (linkHandled.current || !fitted.current || !sheet || !job) return;
    const runId = Number(searchParams.get("run")), countId = Number(searchParams.get("count"));
    const x = searchParams.get("x"), y = searchParams.get("y");
    if (runId) {
      const r = runs.find((v) => v.id === runId);
      if (r) { setSelected({ kind: "run", id: r.id }); focusOn(r.geometry[0]); }
    } else if (countId) {
      const c = counts.find((v) => v.id === countId);
      if (c) { setSelected({ kind: "count", id: c.id }); focusOn([c.x, c.y]); }
    } else if (x !== null && y !== null) {
      const p: Pt = [Number(x), Number(y)];
      setPin(p);
      focusOn(p);
    }
    linkHandled.current = true;
  });

  const sheetVerified = !!sheet?.scale_verified;
  const service = serviceById.get(serviceId);

  const err = (e: unknown) => setError((e as Error).message);
  const refresh = async () => { if (sheet) await loadItems(sheet.job_id); };

  const resetDraft = () => { setDraft([]); setPendingDistance(""); };
  const chooseTool = (t: Tool) => {
    setTool(t); resetDraft(); setError("");
    if (t === "count") {
      const ct = settings.count_types.find((c) => c.name === countType);
      if (ct?.default_service_id) setServiceId(ct.default_service_id);
    }
  };
  // Latest draft for handlers that fire between renders (double-click finishes a trace).
  const draftRef = useRef<Pt[]>([]);
  draftRef.current = draft;

  // --- pointer → sheet points ---
  const pointerPt = (): Pt | null => {
    const p = stageRef.current?.getRelativePointerPosition();
    if (!p) return null;
    let q: Pt = [p.x, p.y];
    if (shiftDown && draft.length && (tool === "trace" || tool === "calibrate" || tool === "verify")) {
      q = ortho(draft[draft.length - 1], q);
    } else if (snapOn && snaps && tool !== "pan" && tool !== "viewport") {
      const s = snaps.nearest(q, 10 / view.scale);
      if (s) q = s;
    }
    return q;
  };

  const scaleFor = (p: Pt | undefined): number | null => {
    if (!sheet || !p) return null;
    const vp = sheet.viewports.find((v) => inside(v.bbox, p));
    if (vp) return vp.scale_verified ? vp.calibrated_scale : null;
    return sheet.scale_verified ? sheet.calibrated_scale : null;
  };

  // --- actions ---
  const finishTrace = async (pts: Pt[]) => {
    const clean = pts.filter((p, i) => i === 0 || dist(p, pts[i - 1]) > 1e-6);
    if (clean.length < 2) { resetDraft(); return; }
    try {
      await api.post(`/api/sheets/${sheet!.id}/runs`, {
        service_id: serviceId, dn, material, geometry: clean, level_id: levelId, stage_id: stageId,
        location_tag: locationTag,
        vertical_mode: dropCount > 0 ? "manual" : "none", vertical_count: dropCount, vertical_height_m: dropHeight,
      });
      resetDraft();
      await refresh();
    } catch (e) { err(e); }
  };

  const placeRiser = async (p: Pt) => {
    try {
      await api.post(`/api/sheets/${sheet!.id}/runs`, {
        service_id: serviceId, dn, material, geometry: [p], level_id: levelId, stage_id: stageId, location_tag: locationTag,
        vertical_mode: riserMode, vertical_count: riserMode === "manual" ? Math.max(dropCount, 1) : 1,
        vertical_height_m: dropHeight, vertical_from_level_id: riserFrom, vertical_to_level_id: riserTo,
      });
      await refresh();
    } catch (e) { err(e); }
  };

  const placeCount = async (p: Pt) => {
    const ct = settings.count_types.find((c) => c.name === countType);
    try {
      await api.post(`/api/sheets/${sheet!.id}/counts`, {
        service_id: serviceId || ct?.default_service_id, item_type: countType, x: p[0], y: p[1],
        level_id: levelId, stage_id: stageId, location_tag: locationTag,
      });
      await refresh();
    } catch (e) { err(e); }
  };

  const applyScale = async () => {
    const known = Number(pendingDistance);
    if (!(known > 0) || draft.length !== 2) return;
    const base = scaleTarget.kind === "sheet" ? `/api/sheets/${sheet!.id}` : `/api/viewports/${scaleTarget.id}`;
    try {
      if (tool === "calibrate") {
        await api.post(`${base}/calibrate`, { method: "two_point", p1: draft[0], p2: draft[1], known_m: known });
        setTool("verify");
      } else {
        await api.post(`${base}/verify`, { p1: draft[0], p2: draft[1], known_m: known });
        setTool("pan");
      }
      resetDraft();
      await loadSheet();
    } catch (e) { err(e); }
  };

  const useStatedScale = async (ratio: number, paper: string) => {
    try {
      await api.post(`/api/sheets/${sheet!.id}/calibrate`, { method: "stated", ratio, paper: paper || null });
      await loadSheet();
      setScaleTarget({ kind: "sheet" });
      chooseTool("verify");
    } catch (e) { err(e); }
  };

  const onClick = async (e: Konva.KonvaEventObject<MouseEvent>) => {
    if (e.evt.button !== 0 || spaceDown) return;
    const p = pointerPt();
    if (!p || !sheet) return;
    setError("");
    if (tool === "pan") setSelected(null);
    else if (tool === "trace") setDraft((d) => [...d, p]);
    else if (tool === "calibrate" || tool === "verify") setDraft((d) => (d.length >= 2 ? [p] : [...d, p]));
    else if (tool === "riser") placeRiser(p);
    else if (tool === "count") placeCount(p);
    else if (tool === "viewport") {
      if (draft.length === 0) setDraft([p]);
      else {
        const name = window.prompt("Name this detail viewport", "Detail") ?? "";
        if (name) {
          try {
            const vp = await api.post<Viewport>(`/api/sheets/${sheet.id}/viewports`, { name, bbox: [draft[0][0], draft[0][1], p[0], p[1]] });
            await loadSheet();
            setScaleTarget({ kind: "viewport", id: vp.id });
            setTool("calibrate");
          } catch (e) { err(e); }
        }
        setDraft([]);
      }
    }
  };

  // Native dblclick on the container: Konva's own dblclick doesn't fire reliably on empty stage areas.
  const onDblClick = () => { if (tool === "trace") finishTrace(draftRef.current); };

  const onWheel = (e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const st = stageRef.current!;
    const pointer = st.getPointerPosition()!;
    const factor = e.evt.deltaY > 0 ? 1 / 1.15 : 1.15;
    const scale = Math.min(Math.max(view.scale * factor, 0.05), 40);
    const wx = (pointer.x - view.x) / view.scale, wy = (pointer.y - view.y) / view.scale;
    setView({ scale, x: pointer.x - wx * scale, y: pointer.y - wy * scale });
  };

  // --- keyboard (Bluebeam-style) ---
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "Shift") setShiftDown(true);
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === " ") { setSpaceDown(true); e.preventDefault(); return; }
      if (e.key === "Escape") { if (draft.length) resetDraft(); else chooseTool("pan"); return; }
      if (e.key === "Enter" && tool === "trace") { finishTrace(draft); return; }
      if (e.key === "Backspace" && draft.length) { setDraft((d) => d.slice(0, -1)); e.preventDefault(); return; }
      if (e.key === "Delete" && selected) { deleteSelected(); return; }
      if (e.key === "?") { setShowHelp((v) => !v); return; }
      if (e.key === "f") { fit(); return; }
      if (e.key === "s") { setSnapOn((v) => !v); return; }
      if (e.key === "[" || e.key === "]") {
        const i = services.findIndex((s) => s.id === serviceId);
        const n = services[(i + (e.key === "]" ? 1 : services.length - 1)) % services.length];
        if (n) setServiceId(n.id);
        return;
      }
      const t = TOOL_KEYS[e.key.toLowerCase()];
      if (t && !e.ctrlKey && !e.metaKey) {
        if (t === "calibrate") setScaleTarget({ kind: "sheet" });
        chooseTool(t);
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === " ") setSpaceDown(false);
      if (e.key === "Shift") setShiftDown(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  });

  const deleteSelected = async () => {
    if (!selected) return;
    if (!window.confirm(`Delete this ${selected.kind}?`)) return;
    try {
      await api.del(selected.kind === "run" ? `/api/runs/${selected.id}` : `/api/counts/${selected.id}`);
      setSelected(null);
      await refresh();
    } catch (e) { err(e); }
  };

  const focusOn = (p: Pt) => {
    const scale = Math.max(view.scale, 2);
    setView({ scale, x: size.w / 2 - p[0] * scale, y: size.h / 2 - p[1] * scale });
  };

  const currentIdx = revisions.findIndex((r) => r.id === Number(sheetId));
  const previousRev = currentIdx > 0 ? revisions[currentIdx - 1] : undefined;
  const toggleCompare = async () => {
    if (diff) { setDiff(null); return; }
    setCompareMsg("");
    try { setDiff(await api.get<Diff>(`/api/sheets/${sheetId}/compare`)); } catch (e) { err(e); }
  };
  const carryForward = async () => {
    try {
      const r = await api.post<{ runs: number; counts: number; skipped: number; on_changed_line_work: number }>(`/api/sheets/${sheetId}/carry-forward`, {});
      setCompareMsg(`${r.runs} run(s) and ${r.counts} count(s) carried forward as suggestions` +
        (r.on_changed_line_work ? `; ${r.on_changed_line_work} on changed line work` : "") + (r.skipped ? `; ${r.skipped} already here` : "") + ".");
      await refresh();
    } catch (e) { err(e); }
  };

  if (!sheet) return <main className="page">{error && <p className="error">{error}</p>}</main>;

  const sw = 1.5 / view.scale; // constant on-screen stroke width
  const draftLen = (() => {
    const mpp = scaleFor(draft[0]);
    if (!mpp || !draft.length) return null;
    const pts = cursor ? [...draft, cursor] : draft;
    return polyLength(pts) * mpp;
  })();
  const measuringBlocked = (tool === "trace" || tool === "riser") && !sheetVerified && !sheet.viewports.some((v) => v.scale_verified);
  const selRun = selected?.kind === "run" ? runs.find((r) => r.id === selected.id) : undefined;
  const selCount = selected?.kind === "count" ? counts.find((c) => c.id === selected.id) : undefined;
  const scaleTargetObj: Sheet | Viewport | undefined =
    scaleTarget.kind === "sheet" ? sheet : sheet.viewports.find((v) => v.id === scaleTarget.id);

  return (
    <div className="viewer">
      {showHelp && <ShortcutsHelp onClose={() => setShowHelp(false)} />}
      <div className="toolbar">
        <Link to={`/jobs/${sheet.job_id}`}>← Job</Link> <Link to={`/jobs/${sheet.job_id}/details`}>Sheets</Link>
        <b>{sheet.sheet_no || `Page ${sheet.page_no}`}</b> <span className="muted">Rev {sheet.revision || "–"} · {sheet.title}</span>
        <span className="spacer" />
        {([
          ["pan", "Pan / select (H)"], ["calibrate", "Calibrate (K)"], ["verify", "Check scale"],
          ["trace", "Trace run (T)"], ["riser", "Riser / drop (R)"], ["count", "Count (N)"], ["viewport", "Detail viewport"],
        ] as [Tool, string][]).map(([t, label]) => (
          <button key={t} className={tool === t ? "active" : ""} onClick={() => { if (t === "calibrate" || t === "verify") setScaleTarget({ kind: "sheet" }); chooseTool(t); }}>
            {label}
          </button>
        ))}
        <label className="inline"><input type="checkbox" checked={snapOn} onChange={(e) => setSnapOn(e.target.checked)} /> Snap (S)</label>
        <button onClick={fit}>Fit (F)</button>
        {revisions.length > 1 && sheet.is_current && (
          <button className={diff ? "active" : ""} onClick={toggleCompare}>
            {diff ? "Hide changes" : `Compare with Rev ${previousRev?.revision || "–"}`}
          </button>
        )}
        <button title="Keyboard shortcuts" onClick={() => setShowHelp(true)}>?</button>
      </div>

      {!sheetVerified && (
        <div className="banner bad">
          Measuring is blocked on this sheet until its scale is calibrated and checked against a second known dimension.
          {sheet.stated_scale && <> Stated scale: <b>{sheet.stated_scale}</b> on an {sheet.page_size} page.</>}
        </div>
      )}
      {sheet.calibration_data?.warning && <div className="banner warn">{sheet.calibration_data.warning}</div>}
      {job?.status === "final" && <div className="banner warn">This estimate is final and locked. A reviewer can reopen it from the job page.</div>}
      {error && <div className="banner bad">{error}</div>}

      <div className="viewer-body">
        <div className="canvas" ref={wrapRef} onDoubleClick={onDblClick} style={{ cursor: tool === "pan" || spaceDown ? "grab" : "crosshair" }}>
          <Stage
            ref={stageRef} width={size.w} height={size.h}
            scaleX={view.scale} scaleY={view.scale} x={view.x} y={view.y}
            draggable={tool === "pan" || spaceDown}
            onDragEnd={(e) => { if (e.target === stageRef.current) setView((v) => ({ ...v, x: e.target.x(), y: e.target.y() })); }}
            onWheel={onWheel}
            onClick={onClick}
            onMouseMove={() => setCursor(pointerPt())}
          >
            <Layer listening={false}>
              {img && <KImage image={img} width={sheet.width_pt} height={sheet.height_pt} />}
            </Layer>
            <Layer>
              {sheet.viewports.map((v) => (
                <Group key={v.id} listening={false}>
                  <Rect x={v.bbox[0]} y={v.bbox[1]} width={v.bbox[2] - v.bbox[0]} height={v.bbox[3] - v.bbox[1]}
                    stroke={v.scale_verified ? "#2a9d4b" : "#d08000"} strokeWidth={sw} dash={[6 / view.scale, 4 / view.scale]} />
                  <Text x={v.bbox[0] + 2 / view.scale} y={v.bbox[1] + 2 / view.scale} text={v.name} fontSize={11 / view.scale} fill="#d08000" />
                </Group>
              ))}
              {runs.map((r) => {
                const svc = serviceById.get(r.service_id);
                const isSel = selected?.kind === "run" && selected.id === r.id;
                const colour = svc?.colour ?? "#000";
                const flat = r.geometry.flat();
                const select = (e: Konva.KonvaEventObject<MouseEvent>) => { if (tool === "pan") { e.cancelBubble = true; setSelected({ kind: "run", id: r.id }); } };
                return (
                  <Group key={r.id} onClick={select} opacity={r.status === "suggested" ? 0.5 : 0.85}>
                    {r.geometry.length > 1 && (
                      <Line points={flat} stroke={colour} strokeWidth={(isSel ? 6 : 3.5) / view.scale} hitStrokeWidth={10 / view.scale}
                        lineCap="round" lineJoin="round" dash={r.status === "suggested" ? [8 / view.scale, 6 / view.scale] : undefined}
                        shadowColor={isSel ? "#ffeb3b" : undefined} shadowBlur={isSel ? 10 : 0} />
                    )}
                    {(svc?.kind === "drainage" || svc?.kind === "stormwater") && r.geometry.slice(1).map((b, i) => {
                      const a = r.geometry[i];
                      const len = dist(a, b);
                      if (len * view.scale < 30) return null;
                      const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len, mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
                      const h = 7 / view.scale;
                      return <Arrow key={i} points={[mx - ux * h, my - uy * h, mx + ux * h, my + uy * h]} fill={colour} stroke={colour}
                        strokeWidth={2 / view.scale} pointerLength={7 / view.scale} pointerWidth={7 / view.scale} listening={false} />;
                    })}
                    {r.vertical_m > 0 && (
                      <Circle x={r.geometry[0][0]} y={r.geometry[0][1]} radius={(isSel ? 8 : 6) / view.scale}
                        stroke={colour} strokeWidth={2 / view.scale} fill="#fff" />
                    )}
                  </Group>
                );
              })}
              {counts.map((c) => {
                const svc = serviceById.get(c.service_id);
                const isSel = selected?.kind === "count" && selected.id === c.id;
                return (
                  <Group key={c.id} x={c.x} y={c.y} opacity={c.status === "suggested" ? 0.5 : 1}
                    onClick={(e) => { if (tool === "pan") { e.cancelBubble = true; setSelected({ kind: "count", id: c.id }); } }}>
                    <Rect x={-5 / view.scale} y={-5 / view.scale} width={10 / view.scale} height={10 / view.scale}
                      fill={svc?.colour ?? "#000"} stroke={isSel ? "#ffeb3b" : "#fff"} strokeWidth={(isSel ? 3 : 1) / view.scale} />
                  </Group>
                );
              })}
              {flags.filter((f) => f.x !== null).map((f) => (
                <Group key={`f${f.id}`} x={f.x!} y={f.y!} listening={false}>
                  <Circle radius={11 / view.scale} stroke={f.severity === "error" ? "#c42b2b" : "#d08000"} strokeWidth={2.5 / view.scale} />
                  <Text text="!" fontSize={13 / view.scale} fontStyle="bold" fill={f.severity === "error" ? "#c42b2b" : "#d08000"}
                    x={-2.5 / view.scale} y={-6.5 / view.scale} />
                </Group>
              ))}
              {diff && <DiffOverlay diff={diff} scale={view.scale} />}
              {highlight && <Rect x={highlight[0] - 4} y={highlight[1] - 4} width={highlight[2] - highlight[0] + 8} height={highlight[3] - highlight[1] + 8}
                fill="rgba(47,111,214,0.12)" stroke="#2f6fd6" strokeWidth={2 / view.scale} listening={false} />}
              {pin && <Circle x={pin[0]} y={pin[1]} radius={18 / view.scale} stroke="#2f6fd6" strokeWidth={3 / view.scale} dash={[5 / view.scale, 4 / view.scale]} listening={false} />}
              {/* Draft geometry */}
              {draft.length > 0 && tool === "trace" && (
                <Line points={[...draft, ...(cursor ? [cursor] : [])].flat()} stroke={service?.colour ?? "#000"} strokeWidth={3 / view.scale} dash={[6 / view.scale, 4 / view.scale]} listening={false} />
              )}
              {(tool === "calibrate" || tool === "verify") && draft.length > 0 && (
                <Line points={[...draft, ...(draft.length === 1 && cursor ? [cursor] : [])].flat()} stroke="#e00" strokeWidth={sw} listening={false} />
              )}
              {tool === "viewport" && draft.length === 1 && cursor && (
                <Rect x={draft[0][0]} y={draft[0][1]} width={cursor[0] - draft[0][0]} height={cursor[1] - draft[0][1]} stroke="#d08000" strokeWidth={sw} listening={false} />
              )}
              {draft.map((p, i) => <Circle key={i} x={p[0]} y={p[1]} radius={3 / view.scale} fill="#e00" listening={false} />)}
              {cursor && tool !== "pan" && <Circle x={cursor[0]} y={cursor[1]} radius={4 / view.scale} stroke="#e00" strokeWidth={1 / view.scale} listening={false} />}
            </Layer>
          </Stage>
          {tool === "trace" && draftLen !== null && <div className="hud">{fmtM(draftLen)} m · double-click or Enter to finish · Backspace undoes a point · Shift for 45°</div>}
          {measuringBlocked && <div className="hud bad">Scale not verified — measuring blocked</div>}
        </div>

        <aside className="side">
          <ScalePanel
            sheet={sheet} tool={tool} draft={draft} target={scaleTarget} targetObj={scaleTargetObj}
            pendingDistance={pendingDistance} setPendingDistance={setPendingDistance} onApply={applyScale}
            onStart={(target, t) => { setScaleTarget(target); chooseTool(t); }}
            onStated={useStatedScale}
            onDeleteViewport={async (id) => { try { await api.del(`/api/viewports/${id}`); await loadSheet(); } catch (e) { err(e); } }}
          />

          <section>
            <h3>New items</h3>
            <div className="grid2">
              <label>Service
                <select value={serviceId} onChange={(e) => setServiceId(Number(e.target.value))}>
                  {services.map((s) => <option key={s.id} value={s.id}>{s.code} – {s.name}</option>)}
                </select>
              </label>
              <label>Stage
                <select value={stageId ?? ""} onChange={(e) => setStageId(e.target.value ? Number(e.target.value) : null)}>
                  <option value="">Service default ({settings.stages.find((s) => s.id === service?.default_stage_id)?.name ?? "none"})</option>
                  {settings.stages.filter((s) => s.active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>
              <label>DN
                <input type="number" list="dn-list" value={dn} min={1} onChange={(e) => setDn(Number(e.target.value))} />
                <datalist id="dn-list">{COMMON_DN.map((d) => <option key={d} value={d} />)}</datalist>
              </label>
              <label>Material
                <select value={material} onChange={(e) => setMaterial(e.target.value)}>
                  {settings.materials.filter((m) => m.active).map((m) => <option key={m.id}>{m.name}</option>)}
                </select>
              </label>
              <label>Level
                <select value={levelId ?? ""} onChange={(e) => setLevelId(e.target.value ? Number(e.target.value) : null)}>
                  <option value="">–</option>
                  {levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
              <label>Location<input value={locationTag} onChange={(e) => setLocationTag(e.target.value)} placeholder="e.g. Amenities L1" /></label>
            </div>
            {tool === "count" && (
              <label>Count item
                <select value={countType} onChange={(e) => {
                  setCountType(e.target.value);
                  const ct = settings.count_types.find((c) => c.name === e.target.value);
                  if (ct?.default_service_id) setServiceId(ct.default_service_id);
                }}>
                  {settings.count_types.filter((c) => c.active).map((c) => <option key={c.id}>{c.name}</option>)}
                </select>
              </label>
            )}
            {(tool === "trace" || tool === "riser") && (
              <div className="grid2">
                {tool === "riser" && (
                  <label>Height from
                    <select value={riserMode} onChange={(e) => setRiserMode(e.target.value as "manual" | "levels")}>
                      <option value="manual">Count × height</option>
                      <option value="levels">Level table</option>
                    </select>
                  </label>
                )}
                {(tool === "trace" || riserMode === "manual") ? (
                  <>
                    <label>{tool === "trace" ? "Drops on this run" : "Count"}<input type="number" min={0} value={dropCount} onChange={(e) => setDropCount(Number(e.target.value))} /></label>
                    <label>Height each (m)<input type="number" min={0} step={0.1} value={dropHeight} onChange={(e) => setDropHeight(Number(e.target.value))} /></label>
                  </>
                ) : (
                  <>
                    <label>From level<select value={riserFrom ?? ""} onChange={(e) => setRiserFrom(Number(e.target.value) || null)}>
                      <option value="">–</option>{levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
                    <label>To level<select value={riserTo ?? ""} onChange={(e) => setRiserTo(Number(e.target.value) || null)}>
                      <option value="">–</option>{levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
                  </>
                )}
              </div>
            )}
            <p className="muted small">[ and ] switch service · Space+drag pans · scroll zooms · Esc cancels</p>
          </section>

          {selRun && <RunEditor key={selRun.id} run={selRun} levels={levels} services={services} onSaved={refresh} onError={err} onDelete={deleteSelected} />}
          {selCount && <CountEditor key={selCount.id} item={selCount} services={services} onSaved={refresh} onError={err} onDelete={deleteSelected} />}

          <section>
            <h3>On this sheet</h3>
            <ul className="items">
              {runs.map((r) => {
                const svc = serviceById.get(r.service_id);
                return (
                  <li key={r.id} className={selected?.kind === "run" && selected.id === r.id ? "sel" : ""}
                    onClick={() => { setSelected({ kind: "run", id: r.id }); focusOn(r.geometry[0]); setTool("pan"); }}>
                    <span className="swatch" style={{ background: svc?.colour }} />
                    {svc?.code} DN{r.dn} {r.material}
                    <span className="spacer" />
                    {fmtM(r.length_m)}{r.vertical_m > 0 && ` + ${fmtM(r.vertical_m)}↕`} m
                    {r.status === "suggested" && <span className="warn small"> suggested</span>}
                  </li>
                );
              })}
              {counts.map((c) => (
                <li key={`c${c.id}`} className={selected?.kind === "count" && selected.id === c.id ? "sel" : ""}
                  onClick={() => { setSelected({ kind: "count", id: c.id }); focusOn([c.x, c.y]); setTool("pan"); }}>
                  <span className="swatch" style={{ background: serviceById.get(c.service_id)?.colour }} />
                  {serviceById.get(c.service_id)?.code} {c.item_type}
                  {c.status === "suggested" && <span className="warn small"> suggested</span>}
                </li>
              ))}
              {runs.length + counts.length === 0 && <li className="muted">Nothing measured yet.</li>}
            </ul>
          </section>

          {diff && (
            <section>
              <h3>Changes since Rev {diff.old_revision || "–"}</h3>
              <div className="compare-legend">
                <span className="add">━ added {Math.round(diff.added_length_pt * (sheet.calibrated_scale ?? 0) * 10) / 10 || ""}{sheet.calibrated_scale ? " m" : ""}</span>
                <span className="rem">┅ removed {Math.round(diff.removed_length_pt * (sheet.calibrated_scale ?? 0) * 10) / 10 || ""}{sheet.calibrated_scale ? " m" : ""}</span>
                <span className="muted">({diff.method === "vector" ? "line work" : "image"} compare)</span>
              </div>
              {diff.affected_runs.length > 0 && (
                <p className="warn small">{diff.affected_runs.length} run(s) and {diff.affected_counts.length} count(s) measured on Rev {diff.old_revision} sit on line work that changed.</p>
              )}
              {diff.unmeasured_new_work && <p className="warn small">New line work on this revision isn't measured yet.</p>}
              <ul className="items">
                {diff.regions.map((r, i) => (
                  <li key={i} onClick={() => focusOn([(r[0] + r[2]) / 2, (r[1] + r[3]) / 2])}>Change {i + 1}<span className="spacer" /><span className="muted small">show</span></li>
                ))}
                {diff.regions.length === 0 && <li className="muted">No changes found.</li>}
              </ul>
              {previousRev && previousRev.runs + previousRev.counts > 0 && (
                <>
                  <button className="primary" disabled={!sheet.scale_verified} onClick={carryForward}>
                    Carry {previousRev.runs} run(s) and {previousRev.counts} count(s) forward
                  </button>
                  {!sheet.scale_verified && <span className="warn small"> Verify this revision's scale first.</span>}
                  <p className="muted small">They arrive as suggestions to check; ones on changed line work are noted.</p>
                </>
              )}
              {compareMsg && <p className="ok small">{compareMsg}</p>}
            </section>
          )}

          <AiAssist sheet={sheet} runs={runs} counts={counts} selectedCount={selCount} onChanged={refresh}
            onHighlight={setHighlight} onError={err} />

          {flags.length > 0 && (
            <section>
              <h3>Open flags on this sheet</h3>
              <ul className="items">
                {flags.map((f) => (
                  <li key={f.id} onClick={() => { if (f.x !== null) { setPin([f.x, f.y!]); focusOn([f.x, f.y!]); } }}>
                    <span className={`badge ${f.severity === "error" ? "bad" : "warn"}`}>{f.severity}</span> {f.message}
                  </li>
                ))}
              </ul>
              <Link className="small" to={`/jobs/${sheet.job_id}/details`}>Resolve flags on the job's Check-measure tab</Link>
            </section>
          )}

          {totals && (
            <section>
              <h3>Job totals (confirmed)</h3>
              <TotalsTables t={totals} compact />
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function inside(b: number[], p: Pt) {
  return p[0] >= Math.min(b[0], b[2]) && p[0] <= Math.max(b[0], b[2]) && p[1] >= Math.min(b[1], b[3]) && p[1] <= Math.max(b[1], b[3]);
}

function ratioLabel(mpp: number | null) {
  if (!mpp) return "–";
  // Points → mm on the page as it is saved.
  return `1:${(mpp * 1000 / (25.4 / 72)).toFixed(1)} at this page size`;
}

function ScalePanel(props: {
  sheet: Sheet; tool: Tool; draft: Pt[]; target: ScaleTarget; targetObj?: Sheet | Viewport;
  pendingDistance: string; setPendingDistance: (v: string) => void; onApply: () => void;
  onStart: (t: ScaleTarget, tool: Tool) => void; onStated: (ratio: number, paper: string) => void;
  onDeleteViewport: (id: number) => void;
}) {
  const { sheet, tool, draft, target, targetObj } = props;
  const statedMatch = /1\s*:\s*(\d+(?:\.\d+)?)(?:\s*(?:@|AT)\s*(A[0-4]))?/i.exec(sheet.stated_scale);
  const [ratio, setRatio] = useState(statedMatch?.[1] ?? "100");
  const [paper, setPaper] = useState(statedMatch?.[2]?.toUpperCase() ?? sheet.page_size);
  const v = sheet.verification_data;
  const scaling = tool === "calibrate" || tool === "verify";
  const targetName = target.kind === "sheet" ? "sheet" : `viewport "${(targetObj as Viewport | undefined)?.name ?? ""}"`;

  return (
    <section>
      <h3>Scale</h3>
      <p className="small">
        Page {sheet.page_size} · stated {sheet.stated_scale || "none found"}<br />
        Calibrated: {ratioLabel(sheet.calibrated_scale)} {sheet.calibration_method && `(${sheet.calibration_method === "stated" ? "from stated scale" : "two-point"})`}<br />
        {sheet.scale_verified
          ? <span className="ok">Verified: check measured {v?.measured_m} m vs {v?.known_m} m ({v?.error_pct.toFixed(2)}% off)</span>
          : v ? <span className="bad">Check failed: measured {v.measured_m} m vs {v.known_m} m ({v.error_pct.toFixed(2)}% off, limit 1%)</span>
          : <span className="bad">Not verified</span>}
      </p>
      <div className="row wrap">
        <button onClick={() => props.onStart({ kind: "sheet" }, "calibrate")}>Calibrate from 2 points</button>
        <button disabled={!sheet.calibrated_scale} onClick={() => props.onStart({ kind: "sheet" }, "verify")}>Check scale</button>
      </div>
      <div className="row wrap">
        <span className="small">Use stated 1:</span>
        <input className="tiny" value={ratio} onChange={(e) => setRatio(e.target.value)} />
        <span className="small">@</span>
        <select value={paper} onChange={(e) => setPaper(e.target.value)}>
          {["A0", "A1", "A2", "A3", "A4"].map((p) => <option key={p}>{p}</option>)}
        </select>
        <button onClick={() => props.onStated(Number(ratio), paper)}>Apply</button>
      </div>
      {scaling && (
        <div className="callout">
          <b>{tool === "calibrate" ? "Calibrate" : "Check"} {targetName}:</b>{" "}
          {draft.length < 2
            ? `click two points on a dimension you know (${draft.length}/2).`
            : <>
                distance between them (m)
                <input autoFocus className="tiny" value={props.pendingDistance} onChange={(e) => props.setPendingDistance(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && props.onApply()} />
                <button className="primary" onClick={props.onApply}>{tool === "calibrate" ? "Set scale" : "Check"}</button>
              </>}
          {tool === "verify" && <div className="small muted">Use a different dimension from the one you calibrated on.</div>}
        </div>
      )}
      {sheet.viewports.length > 0 && (
        <>
          <h4>Detail viewports</h4>
          <ul className="items">
            {sheet.viewports.map((vp) => (
              <li key={vp.id}>
                {vp.name}: {vp.scale_verified ? <span className="ok">verified</span> : <span className="bad">{vp.calibrated_scale ? "not verified" : "no scale"}</span>}
                <span className="spacer" />
                <button className="link" onClick={() => props.onStart({ kind: "viewport", id: vp.id }, "calibrate")}>Calibrate</button>
                <button className="link" disabled={!vp.calibrated_scale} onClick={() => props.onStart({ kind: "viewport", id: vp.id }, "verify")}>Check</button>
                <button className="link" onClick={() => props.onDeleteViewport(vp.id)}>Delete</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function RunEditor({ run, levels, services, onSaved, onError, onDelete }: {
  run: Run; levels: Level[]; services: Service[]; onSaved: () => void; onError: (e: unknown) => void; onDelete: () => void;
}) {
  const { settings } = useApp();
  const save = async (body: Partial<Run>) => {
    try { await api.patch(`/api/runs/${run.id}`, body); onSaved(); } catch (e) { onError(e); }
  };
  return (
    <section className="editor">
      <h3>Selected run #{run.id}</h3>
      <p className="small">
        Plan {fmtM(run.length_m)} m · vertical {fmtM(run.vertical_m)} m · waste {run.waste_pct}%
        {run.viewport_id && " · measured in detail viewport"}
      </p>
      <div className="grid2">
        <label>Service<select value={run.service_id} onChange={(e) => save({ service_id: Number(e.target.value) })}>
          {services.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select></label>
        <label>Stage<select value={run.stage_id ?? ""} onChange={(e) => save({ stage_id: Number(e.target.value) || null })}>
          <option value="">–</option>{settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>DN<input type="number" defaultValue={run.dn} onBlur={(e) => Number(e.target.value) !== run.dn && save({ dn: Number(e.target.value) })} /></label>
        <label>Material<select value={run.material} onChange={(e) => save({ material: e.target.value })}>
          {settings.materials.map((m) => <option key={m.id}>{m.name}</option>)}</select></label>
        <label>Level<select value={run.level_id ?? ""} onChange={(e) => save({ level_id: Number(e.target.value) || null })}>
          <option value="">–</option>{levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label>Location<input defaultValue={run.location_tag} onBlur={(e) => e.target.value !== run.location_tag && save({ location_tag: e.target.value })} /></label>
        <label>Vertical<select value={run.vertical_mode} onChange={(e) => save({ vertical_mode: e.target.value as Run["vertical_mode"] })}>
          <option value="none">None</option><option value="manual">Count × height</option><option value="levels">Level table</option></select></label>
        {run.vertical_mode === "manual" && <>
          <label>Count<input type="number" defaultValue={run.vertical_count} onBlur={(e) => save({ vertical_count: Number(e.target.value) })} /></label>
          <label>Height (m)<input type="number" step={0.1} defaultValue={run.vertical_height_m} onBlur={(e) => save({ vertical_height_m: Number(e.target.value) })} /></label>
        </>}
        {run.vertical_mode === "levels" && <>
          <label>Count<input type="number" defaultValue={run.vertical_count} onBlur={(e) => save({ vertical_count: Number(e.target.value) })} /></label>
          <label>From<select value={run.vertical_from_level_id ?? ""} onChange={(e) => save({ vertical_from_level_id: Number(e.target.value) || null })}>
            <option value="">–</option>{levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>To<select value={run.vertical_to_level_id ?? ""} onChange={(e) => save({ vertical_to_level_id: Number(e.target.value) || null })}>
            <option value="">–</option>{levels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        </>}
        <label>Waste %<input type="number" step={0.5} defaultValue={run.waste_pct} onBlur={(e) => Number(e.target.value) !== run.waste_pct && save({ waste_pct: Number(e.target.value) })} /></label>
      </div>
      {run.note && <p className="warn small">{run.note}</p>}
      <div className="row">
        {run.status === "suggested"
          ? <button className="primary" onClick={() => save({ status: "confirmed" })}>Confirm</button>
          : <span className="ok small">Confirmed</span>}
        {run.geometry.length > 1 && (
          <button title="Drainage is drawn in the direction of flow" onClick={() => save({ geometry: [...run.geometry].reverse() })}>
            Reverse direction
          </button>
        )}
        <span className="spacer" />
        <button className="danger" onClick={onDelete}>{run.status === "suggested" ? "Reject" : "Delete (Del)"}</button>
      </div>
    </section>
  );
}

function CountEditor({ item, services, onSaved, onError, onDelete }: {
  item: CountItem; services: Service[]; onSaved: () => void; onError: (e: unknown) => void; onDelete: () => void;
}) {
  const { settings } = useApp();
  const save = async (body: Partial<CountItem>) => {
    try { await api.patch(`/api/counts/${item.id}`, body); onSaved(); } catch (e) { onError(e); }
  };
  return (
    <section className="editor">
      <h3>Selected count #{item.id}</h3>
      <div className="grid2">
        <label>Item<select value={item.item_type} onChange={(e) => save({ item_type: e.target.value })}>
          {settings.count_types.map((c) => <option key={c.id}>{c.name}</option>)}</select></label>
        <label>Service<select value={item.service_id} onChange={(e) => save({ service_id: Number(e.target.value) })}>
          {services.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select></label>
        <label>Stage<select value={item.stage_id ?? ""} onChange={(e) => save({ stage_id: Number(e.target.value) || null })}>
          <option value="">–</option>{settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Location<input defaultValue={item.location_tag} onBlur={(e) => e.target.value !== item.location_tag && save({ location_tag: e.target.value })} /></label>
      </div>
      <div className="row">
        {item.status === "suggested"
          ? <button className="primary" onClick={() => save({ status: "confirmed" })}>Confirm</button>
          : <span className="ok small">Confirmed</span>}
        <span className="spacer" />
        <button className="danger" onClick={onDelete}>{item.status === "suggested" ? "Reject" : "Delete (Del)"}</button>
      </div>
    </section>
  );
}
