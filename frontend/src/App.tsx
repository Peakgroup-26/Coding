import { createContext, useContext, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import type { Permissions, Settings, User } from "./types";
import Login from "./pages/Login";
import Jobs from "./pages/Jobs";
import Home from "./pages/Home";
import JobOverview from "./pages/JobOverview";
import CivilRates from "./pages/CivilRates";
import JobPage from "./pages/Job";
import SheetViewer from "./pages/SheetViewer";
import AdminPortal from "./pages/AdminPortal";
import Account from "./pages/Account";
import Dashboard from "./pages/Dashboard";
import Sales from "./pages/Sales";
import JobReports from "./pages/JobReports";
import Rules from "./pages/Rules";
import PriceBooks from "./pages/PriceBooks";
import Mappings from "./pages/Mappings";
import { AskPeakButton, Bell } from "./pages/AskPeak";
import FieldApp from "./pages/FieldApp";
import FeedbackForm from "./pages/FeedbackForm";
import WorkBoard from "./pages/WorkBoard";
import JobHub from "./pages/JobHub";
import Schedule from "./pages/Schedule";
import Timesheets from "./pages/Timesheets";
import Purchasing from "./pages/Purchasing";
import PlantPage from "./pages/Plant";
import Maintenance from "./pages/Maintenance";
import CompanyDocs from "./pages/CompanyDocs";
import Customers, { CustomerPage } from "./pages/Customers";
import Crm from "./pages/Crm";
import Finance from "./pages/Finance";

interface Ctx { user: User; settings: Settings; reloadSettings: () => Promise<void> }
const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => useContext(AppCtx)!;

/** Admins can do everything; everyone else has the permissions an admin gave them. */
export const can = (user: User, permission: keyof Permissions) => user.role === "admin" || user[permission];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [checked, setChecked] = useState(false);
  const [menu, setMenu] = useState(false);
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

  const onLogin = async (u: User) => { setUser(u); await reloadSettings(); nav(u.role === "field" ? "/field" : "/"); };
  const logout = () => { setToken(null); setUser(null); nav("/login"); };

  if (!checked) return null;
  if (window.location.pathname.startsWith("/feedback/")) {
    return <Routes><Route path="/feedback/:token" element={<FeedbackForm />} /></Routes>;
  }
  if (!user || !settings) {
    return (
      <Routes>
        <Route path="*" element={<Login onLogin={onLogin} />} />
      </Routes>
    );
  }
  if (user.role === "field") {
    return (
      <AppCtx.Provider value={{ user, settings, reloadSettings }}>
        <Routes>
          <Route path="/field/*" element={<FieldApp onLogout={logout} />} />
          <Route path="*" element={<Navigate to="/field" />} />
        </Routes>
      </AppCtx.Provider>
    );
  }
  const ops = can(user, "can_ops");
  const fin = can(user, "can_finance");
  const groups: { label: string; links: [string, string, boolean][] }[] = [
    { label: "Estimating", links: [["/", "Tenders & quotes", true], ["/sales", "Sales", true],
      ["/civil-rates", "Civil rates", can(user, "can_past_rates") && can(user, "can_civil")],
      ["/price-books", "Price books", can(user, "can_hydraulic")], ["/rules", "Fitting rules", can(user, "can_hydraulic")],
      ["/mappings", "Price mappings", can(user, "can_hydraulic")], ["/jobs", "Jobs set up by hand", true]] },
    { label: "Operations", links: [["/work", "Jobs", ops], ["/schedule", "Schedule", ops], ["/timesheets", "Timesheets", ops],
      ["/purchasing", "Purchasing", ops], ["/plant", "Plant & vehicles", ops], ["/maintenance", "Maintenance planner", ops],
      ["/documents", "Company documents", ops], ["/field", "Phone app", true]] },
    { label: "Customers", links: [["/customers", "Customers", ops], ["/crm", "Feedback & follow-ups", ops]] },
    { label: "Money", links: [["/finance", "Dashboard", fin], ["/finance?tab=wip", "WIP", fin], ["/finance?tab=cash", "Cash flow", fin],
      ["/finance?tab=budget", "Budgets", fin], ["/finance?tab=invoices", "Invoices & debtors", fin],
      ["/purchasing?tab=prices", "Supplier prices", fin], ["/reports", "Job reports", true]] },
  ];
  return (
    <AppCtx.Provider value={{ user, settings, reloadSettings }}>
      <div className="app">
        <header className="topbar">
          <button className="burger" aria-label="Menu" onClick={() => setMenu(!menu)}>☰</button>
          <Link to="/" className="brand">Peak</Link>
          <nav className={menu ? "open" : ""} onClick={(e) => { if ((e.target as HTMLElement).tagName === "A") { setMenu(false); closeMenus(); } }}>
            {groups.map((g) => g.links.some((l) => l[2]) && (
              <details key={g.label} className="more">
                <summary>{g.label}</summary>
                <div className="menu">
                  {g.links.filter((l) => l[2]).map(([to, label]) => <Link key={to} to={to}>{label}</Link>)}
                </div>
              </details>
            ))}
            {user.role === "admin" && <Link to="/admin">Admin</Link>}
            <Link to="/account" className="nav-account">My account</Link>
          </nav>
          <span className="spacer" />
          <AskPeakButton />
          <Bell />
          <Link to="/account" className="muted who">{user.name || user.email}</Link>
          <button className="link" onClick={logout}>Sign out</button>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:jobId" element={<JobOverview />} />
          <Route path="/jobs/:jobId/details" element={<JobPage />} />
          <Route path="/jobs/:jobId/reports" element={<JobReports />} />
          <Route path="/reports" element={<Dashboard />} />
          <Route path="/sales" element={<Sales />} />
          <Route path="/civil-rates" element={<CivilRates />} />
          <Route path="/sheets/:sheetId" element={<SheetViewer />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/price-books" element={<PriceBooks />} />
          <Route path="/mappings" element={<Mappings />} />
          <Route path="/work" element={<WorkBoard />} />
          <Route path="/work/:jobId" element={<JobHub />} />
          <Route path="/schedule" element={<Schedule />} />
          <Route path="/timesheets" element={<Timesheets />} />
          <Route path="/purchasing" element={<Purchasing />} />
          <Route path="/plant" element={<PlantPage />} />
          <Route path="/plant/:plantId" element={<PlantPage />} />
          <Route path="/maintenance" element={<Maintenance />} />
          <Route path="/documents" element={<CompanyDocs />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/customers/:customerId" element={<CustomerPage />} />
          <Route path="/crm" element={<Crm />} />
          <Route path="/finance" element={<Finance />} />
          <Route path="/field/*" element={<FieldApp />} />
          <Route path="/admin" element={user.role === "admin" ? <AdminPortal /> : <Navigate to="/" />} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </AppCtx.Provider>
  );
}

function closeMenus() {
  document.querySelectorAll("details.more[open]").forEach((d) => d.removeAttribute("open"));
}

function sessionStorageSafe(key: string, value: string) {
  try { sessionStorage.setItem(key, value); } catch { /* storage unavailable */ }
}
