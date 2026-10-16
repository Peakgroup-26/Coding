/* Every vehicle on one map, live from Geotab: where it is, who's driving, moving or parked, and its plant record. */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api";
import { level, useApp } from "../App";
import { ErrorLine, Modal, useAction, useLoad } from "../ui";

export interface Vehicle { id: string; name: string; rego: string; vin: string; lat: number | null; lng: number | null; speed: number | null; bearing: number | null;
  driving: boolean; communicating: boolean; at: string | null; driver: string; plant_id: number | null; plant: string; kind: string;
  assigned_to: string; assigned_phone: string; plant_status: string }
interface Live { connected: boolean; vehicles: Vehicle[]; message?: string; updated?: number }

const ago = (iso: string | null) => {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
};
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export default function Vehicles() {
  const { user } = useApp();
  const [data, setData] = useState<Live | null>(null);
  const [error, setError] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [linking, setLinking] = useState(false);
  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const markers = useRef<Record<string, L.Marker>>({});
  const fitted = useRef(false);

  const load = async (fresh = false) => {
    try { setData(await api.get<Live>(`/api/vehicles/live${fresh ? "?fresh=true" : ""}`)); setError(""); } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { load(); const t = setInterval(() => load(), 30000); return () => clearInterval(t); }, []);

  useEffect(() => {
    if (!mapEl.current || map.current) return;
    map.current = L.map(mapEl.current, { zoomControl: true }).setView([-26.65, 153.07], 10);  // Sunshine Coast until the vehicles load
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => { map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    if (!map.current || !layer.current || !data) return;
    layer.current.clearLayers();
    markers.current = {};
    const pts: L.LatLngExpression[] = [];
    for (const v of data.vehicles) {
      if (v.lat === null || v.lng === null) continue;
      const cls = !v.communicating ? "off" : v.driving ? "moving" : "parked";
      const icon = L.divIcon({ className: "veh-pin-wrap", iconSize: [0, 0],
        html: `<div class="veh-pin ${cls}"><span class="dot">${v.kind === "plant" || v.kind === "machine" ? "🚜" : "🚚"}</span><span class="lbl">${esc(v.plant || v.name)}</span></div>` });
      const m = L.marker([v.lat, v.lng], { icon }).addTo(layer.current)
        .bindPopup(`<b>${esc(v.plant || v.name)}</b>${v.rego ? ` · ${esc(v.rego)}` : ""}<br/>${v.driving ? `Moving ${Math.round(v.speed ?? 0)} km/h` : "Parked"}`
          + `${v.driver ? `<br/>Driver: ${esc(v.driver)}` : ""}${v.assigned_to ? `<br/>Assigned to: ${esc(v.assigned_to)}` : ""}<br/><small>${ago(v.at)}</small>`
          + `<br/><a href="https://maps.google.com/?q=${v.lat},${v.lng}" target="_blank" rel="noreferrer">Open in Google Maps</a>`);
      m.on("click", () => setSel(v.id));
      markers.current[v.id] = m;
      pts.push([v.lat, v.lng]);
    }
    if (!fitted.current && pts.length) { map.current.fitBounds(L.latLngBounds(pts).pad(0.15), { maxZoom: 14 }); fitted.current = true; }
  }, [data]);

  const focus = (v: Vehicle) => {
    setSel(v.id);
    const m = markers.current[v.id];
    if (m && map.current) { map.current.setView(m.getLatLng(), Math.max(map.current.getZoom(), 14)); m.openPopup(); }
  };
  const list = (data?.vehicles ?? []).filter((v) => !q || `${v.name} ${v.rego} ${v.driver} ${v.plant} ${v.assigned_to}`.toLowerCase().includes(q.toLowerCase()));
  const moving = (data?.vehicles ?? []).filter((v) => v.driving).length;
  return (
    <main className="page vehicles-page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Vehicles</h1>
        {data?.connected && <span className="muted small">{data.vehicles.length} vehicles · {moving} moving · updates every 30 seconds</span>}
        <span className="spacer" />
        <button onClick={() => load(true)}>↻ Refresh</button>
        {level(user, "vehicles_map") === "edit" && <button onClick={() => setLinking(true)}>Link to plant records</button>}
      </div>
      <ErrorLine error={error} />
      {data && !data.connected && <div className="card warn-card"><b>Geotab</b><p>{data.message}</p></div>}
      <div className="veh-layout">
        <div ref={mapEl} className="veh-map" />
        <aside className="veh-list">
          <input placeholder="Find a vehicle, rego or driver" value={q} onChange={(e) => setQ(e.target.value)} />
          {list.map((v) => (
            <button key={v.id} className={`veh-row ${sel === v.id ? "on" : ""}`} onClick={() => focus(v)}>
              <span className={`veh-state ${!v.communicating ? "off" : v.driving ? "moving" : "parked"}`} />
              <span className="grow">
                <b>{v.plant || v.name}</b> <small className="muted">{v.rego}</small>
                <small className="block">{v.driving ? `Moving · ${Math.round(v.speed ?? 0)} km/h` : !v.communicating ? "Not reporting" : "Parked"}
                  {v.driver && ` · ${v.driver}`} · {ago(v.at)}</small>
                {v.assigned_to && <small className="block">Assigned to {v.assigned_phone
                  ? <a href={`tel:${v.assigned_phone.replace(/[^\d+]/g, "")}`} onClick={(e) => e.stopPropagation()}>📞 {v.assigned_to}</a> : v.assigned_to}</small>}
                {v.plant_id ? <Link to={`/plant/${v.plant_id}`} className="small" onClick={(e) => e.stopPropagation()}>Plant record ›</Link>
                  : <small className="muted block">Not linked to a plant record</small>}
              </span>
            </button>
          ))}
          {data?.connected && list.length === 0 && <p className="muted small">No vehicles match.</p>}
        </aside>
      </div>
      {linking && <LinkPlant vehicles={data?.vehicles ?? []} onClose={() => setLinking(false)} onDone={() => load(true)} />}
    </main>
  );
}

function LinkPlant({ vehicles, onClose, onDone }: { vehicles: Vehicle[]; onClose: () => void; onDone: () => void }) {
  const { data: plant, reload } = useLoad<{ id: number; name: string; rego: string; kind: string; geotab_id: string }[]>("/api/vehicles/plant");
  const [run, error] = useAction();
  const save = (pid: number, gid: string) => run(async () => { await api.put(`/api/vehicles/link/${pid}`, { geotab_id: gid }); await reload(); onDone(); });
  const auto = Object.fromEntries(vehicles.filter((v) => v.plant_id).map((v) => [v.plant_id, v.id]));
  return (
    <Modal title="Link Geotab vehicles to plant records" onClose={onClose} wide>
      <p className="small muted">Vehicles are matched by rego, VIN or name automatically. Pick one here when they don't match.</p>
      <ErrorLine error={error} />
      <table className="dt">
        <thead><tr><th>Plant record</th><th>Rego</th><th>Geotab vehicle</th></tr></thead>
        <tbody>
          {(plant ?? []).map((p) => (
            <tr key={p.id}>
              <td>{p.name}</td><td>{p.rego}</td>
              <td><select value={p.geotab_id || auto[p.id] || ""} onChange={(e) => save(p.id, e.target.value)}>
                <option value="">Not linked</option>
                {vehicles.map((v) => <option key={v.id} value={v.id}>{v.name}{v.rego ? ` (${v.rego})` : ""}</option>)}
              </select>{!p.geotab_id && auto[p.id] && <small className="muted"> matched</small>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}
