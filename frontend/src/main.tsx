import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, getKey, setKey } from "./api";
import { Admin } from "./pages/Admin";
import { Billing } from "./pages/Billing";
import { Contracts } from "./pages/Contracts";
import { Invoices } from "./pages/Invoices";
import { Reconciliations } from "./pages/Reconciliations";
import { Sign } from "./pages/Sign";
import "./styles.css";

const TABS = { invoices: "Invoices", reconciliations: "Bank reconciliation", contracts: "Contracts", billing: "Plan & usage", admin: "Admin" } as const;
type Tab = keyof typeof TABS;

function Login({ onDone }: { onDone: () => void }) {
  const [key, setK] = useState("");
  const [err, setErr] = useState(() => ({ not_invited: "Your email is not invited to any workspace. Ask an admin to invite you.",
    email_not_verified: "Your identity provider did not confirm your email address.", login_failed: "Single sign-on failed. Please try again." } as Record<string, string>)[
    new URLSearchParams(location.search).get("sso_error") ?? ""] ?? "");
  const [sso, setSso] = useState<{ sso: boolean; provider: string | null }>({ sso: false, provider: null });
  useEffect(() => { fetch("/auth/config").then((r) => r.json()).then(setSso).catch(() => {}); }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setKey(key.trim());
    try { await api("/me"); onDone(); } catch { setKey(""); setErr("That API key was not accepted."); }
  }
  return (
    <form className="card login" onSubmit={submit}>
      <h1>FinTech Suite</h1>
      {sso.sso && <><a className="primary btn" href="/auth/login">Sign in with {sso.provider}</a><p className="muted">or use an API key</p></>}
      {!sso.sso && <p className="muted">Enter your API key to continue.</p>}
      <input type="password" autoFocus placeholder="fk_…" value={key} onChange={(e) => setK(e.target.value)} aria-label="API key" />
      {err && <p className="error" role="alert">{err}</p>}
      <button className="primary" disabled={!key.trim()}>Sign in</button>
    </form>
  );
}

function App() {
  const [me, setMe] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("invoices");
  // an SSO session cookie or a stored API key both authenticate /me
  const load = () => api("/me").then(setMe).catch(() => { setKey(""); setMe(null); });
  useEffect(() => { load(); }, []);
  if (!me) return <Login onDone={load} />;
  return (
    <>
      <header>
        <strong>FinTech Suite</strong>
        <nav>{(Object.keys(TABS) as Tab[]).filter((t) => t !== "admin" || me.role === "admin").map((t) => (
          <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>{TABS[t]}</button>))}
        </nav>
        <span className="muted">{me.label} · {me.role} · {me.plan}</span>
        <button onClick={() => { setKey(""); api("/auth/logout", { method: "POST", json: {} }).catch(() => {}).finally(() => setMe(null)); }}>Sign out</button>
      </header>
      <main>
        {tab === "invoices" && <Invoices role={me.role} />}
        {tab === "reconciliations" && <Reconciliations role={me.role} />}
        {tab === "contracts" && <Contracts role={me.role} />}
        {tab === "billing" && <Billing />}
        {tab === "admin" && <Admin />}
      </main>
    </>
  );
}

const signToken = location.pathname.startsWith("/s/") ? location.pathname.slice(3) : null;
createRoot(document.getElementById("root")!).render(<StrictMode>{signToken ? <Sign token={signToken} /> : <App />}</StrictMode>);
