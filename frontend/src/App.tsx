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
import People, { PersonPage } from "./pages/People";
import Boards, { BoardPage, MyWork } from "./pages/Boards";
import { RateLibrary } from "./pages/Workbook";
import { BoardFormPage, Careers } from "./pages/PublicPages";

interface Ctx { user: User; settings: Settings; reloadSettings: () => Promise<void> }
const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => useContext(AppCtx)!;

/** Admins can do everything; everyone else has the permissions an admin gave them. */
export const can = (user: User, permission: keyof Permissions) => user.role === "admin" || user[permission];
/** What this person may do with a feature (Admin → Feature access): none, view or edit. */
export const level = (user: User, feature: string) => (user.role === "admin" ? "edit" : user.access?.[feature] ?? "edit");
export const sees = (user: User, feature: string) => level(user, feature) !== "none";

/** A page behind a feature: hidden = a polite stop; view only = a banner, and the server refuses changes. */
export function Gate({ f, children }: { f: string; children: JSX.Element }) {
  const { user } = useApp();
  const lv = level(user, f);
  if (lv === "none") return <main className="page"><div className="card"><h2>Not available</h2><p className="muted">You don't have access to this part of Lorojo. Ask an admin if you need it.</p></div></main>;
  return lv === "view" ? <><div className="view-only">👁 View only: you can look, but changes are turned off for you.</div>{children}</> : children;
}

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

  const onLogin = async (u: User) => {
    const full = await api.get<User>("/api/auth/me").catch(() => u);  // with what they can see
    setUser(full); await reloadSettings(); nav(full.role === "field" ? "/field" : "/");
  };
  const logout = () => { setToken(null); setUser(null); nav("/login"); };

  if (!checked) return null;
  if (window.location.pathname.startsWith("/feedback/")) {
    return <Routes><Route path="/feedback/:token" element={<FeedbackForm />} /></Routes>;
  }
  if (/^\/(careers|forms)(\/|$)/.test(window.location.pathname)) {  // public: no sign-in
    return <Routes><Route path="/careers" element={<Careers />} /><Route path="/careers/:id" element={<Careers />} /><Route path="/forms/:token" element={<BoardFormPage />} /></Routes>;
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
  const hr = can(user, "can_hr");
  const groups: { label: string; links: [string, string, boolean][] }[] = [
    { label: "Work", links: [["/my-work", "My work", true], ["/boards", "Boards", true]] },
    { label: "Estimating", links: [["/", "Tenders & quotes", true], ["/sales", "Sales", true], ["/rate-library", "Rate library", true],
      ["/civil-rates", "Civil rates", can(user, "can_past_rates") && can(user, "can_civil")],
      ["/price-books", "Price books", can(user, "can_hydraulic")], ["/rules", "Fitting rules", can(user, "can_hydraulic")],
      ["/mappings", "Price mappings", can(user, "can_hydraulic")], ["/jobs", "Jobs set up by hand", true]] },
    { label: "Operations", links: [["/work", "Jobs", ops], ["/schedule", "Schedule", ops], ["/timesheets", "Timesheets", ops],
      ["/purchasing", "Purchasing", ops], ["/plant", "Plant & vehicles", ops], ["/maintenance", "Maintenance planner", ops],
      ["/documents", "Company documents", ops], ["/field", "Phone app", true]] },
    { label: "People", links: [["/people", "Team", hr], ["/people?tab=leave", "Leave", hr], ["/people?tab=licences", "Licences & training", hr],
      ["/people?tab=hiring", "Hiring", hr], ["/people?tab=reviews", "Reviews", hr], ["/people?tab=reports", "HR reports", hr],
      ["/field/me", "Me (my leave, licences, policies)", true], ["/field/me/people", "Team directory", true]] },
    { label: "Customers", links: [["/customers", "Customers", ops], ["/crm", "Feedback & follow-ups", ops]] },
    { label: "Money", links: [["/finance", "Dashboard", fin], ["/finance?tab=wip", "WIP", fin], ["/finance?tab=cash", "Cash flow", fin],
      ["/finance?tab=budget", "Budgets", fin], ["/finance?tab=invoices", "Invoices & debtors", fin],
      ["/purchasing?tab=prices", "Supplier prices", fin], ["/reports", "Job reports", true]] },
  ];
  const FEATURE_OF: Record<string, string> = {
    "/my-work": "my_work", "/boards": "boards", "/": "tenders", "/jobs": "tenders", "/sales": "sales", "/rate-library": "rate_library",
    "/civil-rates": "civil_rates", "/price-books": "price_books", "/rules": "rules", "/mappings": "mappings", "/work": "live_jobs",
    "/schedule": "schedule", "/timesheets": "timesheets", "/purchasing": "purchasing", "/plant": "plant", "/maintenance": "maintenance",
    "/documents": "documents", "/customers": "customers", "/crm": "crm", "/finance": "finance", "/finance?tab=wip": "finance",
    "/finance?tab=cash": "finance", "/finance?tab=budget": "finance", "/finance?tab=invoices": "invoices", "/purchasing?tab=prices": "supplier_prices",
    "/reports": "reports", "/people": "hr_records", "/people?tab=leave": "hr_leave", "/people?tab=licences": "hr_licences",
    "/people?tab=hiring": "hr_hiring", "/people?tab=reviews": "hr_reviews", "/people?tab=reports": "hr_records", "/field/me": "field_me",
  };
  for (const g of groups) g.links = g.links.map(([to, label, ok]) => [to, label, ok && (!FEATURE_OF[to] || sees(user, FEATURE_OF[to]))]);
  const G = (f: string, el: JSX.Element) => <Gate f={f}>{el}</Gate>;
  return (
    <AppCtx.Provider value={{ user, settings, reloadSettings }}>
      <div className="app">
        <header className="topbar">
          <button className="burger" aria-label="Menu" onClick={() => setMenu(!menu)}>☰</button>
          <Link to="/" className="brand" aria-label="Lorojo home"><img src="/brand/lorojo-logo.png" alt="Lorojo" /></Link>
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
          {sees(user, "assistant") && <AskPeakButton />}
          <Bell />
          <Link to="/account" className="muted who">{user.name || user.email}</Link>
          <button className="link" onClick={logout}>Sign out</button>
        </header>
        <Routes>
          <Route path="/" element={sees(user, "tenders") ? G("tenders", <Home />) : <Navigate to={sees(user, "my_work") ? "/my-work" : "/field"} />} />
          <Route path="/jobs" element={G("tenders", <Jobs />)} />
          <Route path="/jobs/:jobId" element={G("tenders", <JobOverview />)} />
          <Route path="/jobs/:jobId/details" element={G("tenders", <JobPage />)} />
          <Route path="/jobs/:jobId/reports" element={G("reports", <JobReports />)} />
          <Route path="/reports" element={G("reports", <Dashboard />)} />
          <Route path="/sales" element={G("sales", <Sales />)} />
          <Route path="/civil-rates" element={G("civil_rates", <CivilRates />)} />
          <Route path="/sheets/:sheetId" element={G("tenders", <SheetViewer />)} />
          <Route path="/rules" element={G("rules", <Rules />)} />
          <Route path="/price-books" element={G("price_books", <PriceBooks />)} />
          <Route path="/mappings" element={G("mappings", <Mappings />)} />
          <Route path="/work" element={G("live_jobs", <WorkBoard />)} />
          <Route path="/work/:jobId" element={G("live_jobs", <JobHub />)} />
          <Route path="/schedule" element={G("schedule", <Schedule />)} />
          <Route path="/timesheets" element={G("timesheets", <Timesheets />)} />
          <Route path="/purchasing" element={G("purchasing", <Purchasing />)} />
          <Route path="/plant" element={G("plant", <PlantPage />)} />
          <Route path="/plant/:plantId" element={G("plant", <PlantPage />)} />
          <Route path="/maintenance" element={G("maintenance", <Maintenance />)} />
          <Route path="/documents" element={G("documents", <CompanyDocs />)} />
          <Route path="/customers" element={G("customers", <Customers />)} />
          <Route path="/customers/:customerId" element={G("customers", <CustomerPage />)} />
          <Route path="/crm" element={G("crm", <Crm />)} />
          <Route path="/finance" element={G("finance", <Finance />)} />
          <Route path="/people" element={hr ? G("hr_records", <People />) : <Navigate to="/field/me" />} />
          <Route path="/people/:userId" element={hr ? G("hr_records", <PersonPage />) : <Navigate to="/field/me" />} />
          <Route path="/boards" element={G("boards", <Boards />)} />
          <Route path="/boards/:boardId" element={G("boards", <BoardPage />)} />
          <Route path="/my-work" element={G("my_work", <MyWork />)} />
          <Route path="/rate-library" element={G("rate_library", <RateLibrary />)} />
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
