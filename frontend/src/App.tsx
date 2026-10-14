import { createContext, useContext, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import type { Settings, User } from "./types";
import Login from "./pages/Login";
import Jobs from "./pages/Jobs";
import Home from "./pages/Home";
import JobOverview from "./pages/JobOverview";
import CivilRates from "./pages/CivilRates";
import JobPage from "./pages/Job";
import SheetViewer from "./pages/SheetViewer";
import Admin from "./pages/Admin";
import Rules from "./pages/Rules";
import PriceBooks from "./pages/PriceBooks";
import Mappings from "./pages/Mappings";

interface Ctx { user: User; settings: Settings; reloadSettings: () => Promise<void> }
const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => useContext(AppCtx)!;

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [checked, setChecked] = useState(false);
  const nav = useNavigate();

  const reloadSettings = async () => setSettings(await api.get<Settings>("/api/settings"));

  useEffect(() => {
    // Back from Microsoft sign-on: the token (or an error) arrives in the URL fragment.
    const hash = new URLSearchParams(window.location.hash.slice(1));
    if (hash.get("token")) setToken(hash.get("token"));
    if (hash.has("token") || hash.has("sso_error")) {
      if (hash.get("sso_error")) sessionStorageSafe("sso_error", hash.get("sso_error")!);
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (!getToken()) { setChecked(true); return; }
    api.get<User>("/api/auth/me")
      .then(async (u) => { setUser(u); await reloadSettings(); })
      .catch(() => setToken(null))
      .finally(() => setChecked(true));
  }, []);

  const onLogin = async (u: User) => { setUser(u); await reloadSettings(); nav("/"); };
  const logout = () => { setToken(null); setUser(null); nav("/login"); };

  if (!checked) return null;
  if (!user || !settings) {
    return (
      <Routes>
        <Route path="*" element={<Login onLogin={onLogin} />} />
      </Routes>
    );
  }
  return (
    <AppCtx.Provider value={{ user, settings, reloadSettings }}>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">Peak Take-off</Link>
          <nav>
            <Link to="/">Home</Link>
            <Link to="/civil-rates">Civil rates</Link>
            <Link to="/price-books">Price books</Link>
            <details className="more">
              <summary>More</summary>
              <div className="menu" onClick={(e) => (e.currentTarget.parentElement as HTMLDetailsElement).open = false}>
                <Link to="/rules">Fitting rules</Link>
                <Link to="/mappings">Price mappings</Link>
                <Link to="/jobs">Jobs (set up by hand)</Link>
                {user.role === "admin" && <Link to="/admin">Admin settings</Link>}
              </div>
            </details>
          </nav>
          <span className="spacer" />
          <span className="muted">{user.name || user.email} · {user.role}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:jobId" element={<JobOverview />} />
          <Route path="/jobs/:jobId/details" element={<JobPage />} />
          <Route path="/civil-rates" element={<CivilRates />} />
          <Route path="/sheets/:sheetId" element={<SheetViewer />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/price-books" element={<PriceBooks />} />
          <Route path="/mappings" element={<Mappings />} />
          <Route path="/admin" element={user.role === "admin" ? <Admin /> : <Navigate to="/" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </AppCtx.Provider>
  );
}

function sessionStorageSafe(key: string, value: string) {
  try { sessionStorage.setItem(key, value); } catch { /* storage unavailable */ }
}
