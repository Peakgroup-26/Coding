import { FormEvent, useEffect, useState } from "react";
import { api, setToken } from "../api";
import type { User } from "../types";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(() => {
    try {
      const e = sessionStorage.getItem("sso_error") ?? "";
      sessionStorage.removeItem("sso_error");
      return e;
    } catch { return ""; }
  });
  const [sso, setSso] = useState(false);
  useEffect(() => {
    fetch("/api/auth/sso").then((r) => r.json()).then((d) => setSso(!!d.enabled)).catch(() => setSso(false));
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const r = await api.post<{ token: string; user: User }>("/api/auth/login", { email, password });
      setToken(r.token);
      onLogin(r.user);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="login">
      <div className="login-brand"><img src="/brand/lorojo-full.png" alt="lorojo – all of it. one place." /></div>
      <form onSubmit={submit} className="card">
        <h1>Sign in</h1>
        <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit">Sign in</button>
        {sso && (
          <>
            <div className="or"><span>or</span></div>
            <a className="button ms" href="/api/auth/sso/start">Sign in with Microsoft</a>
          </>
        )}
      </form>
    </div>
  );
}
