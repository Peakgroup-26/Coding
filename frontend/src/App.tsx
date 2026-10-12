import { createContext, useContext, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import type { Settings, User } from "./types";
import Login from "./pages/Login";
import Jobs from "./pages/Jobs";
import JobPage from "./pages/Job";
import SheetViewer from "./pages/SheetViewer";
import Admin from "./pages/Admin";

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
            <Link to="/">Jobs</Link>
            {user.role === "admin" && <Link to="/admin">Admin</Link>}
          </nav>
          <span className="spacer" />
          <span className="muted">{user.name || user.email} · {user.role}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </header>
        <Routes>
          <Route path="/" element={<Jobs />} />
          <Route path="/jobs/:jobId" element={<JobPage />} />
          <Route path="/sheets/:sheetId" element={<SheetViewer />} />
          <Route path="/admin" element={user.role === "admin" ? <Admin /> : <Navigate to="/" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </AppCtx.Provider>
  );
}
