import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, getKey, setKey } from "./api";
import { Billing } from "./pages/Billing";
import { Contracts } from "./pages/Contracts";
import { Invoices } from "./pages/Invoices";
import { Reconciliations } from "./pages/Reconciliations";
import "./styles.css";

const TABS = { invoices: "Invoices", reconciliations: "Bank reconciliation", contracts: "Contracts", billing: "Plan & usage" } as const;
type Tab = keyof typeof TABS;

function Login({ onDone }: { onDone: () => void }) {
  const [key, setK] = useState("");
  const [err, setErr] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setKey(key.trim());
    try { await api("/me"); onDone(); } catch { setKey(""); setErr("That API key was not accepted."); }
  }
  return (
    <form className="card login" onSubmit={submit}>
      <h1>FinTech Suite</h1>
      <p className="muted">Enter your API key to continue.</p>
      <input type="password" autoFocus placeholder="fk_…" value={key} onChange={(e) => setK(e.target.value)} aria-label="API key" />
      {err && <p className="error" role="alert">{err}</p>}
      <button className="primary" disabled={!key.trim()}>Sign in</button>
    </form>
  );
}

function App() {
  const [me, setMe] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("invoices");
  const load = () => (getKey() ? api("/me").then(setMe).catch(() => { setKey(""); setMe(null); }) : undefined);
  useEffect(() => { load(); }, []);
  if (!me) return <Login onDone={load} />;
  return (
    <>
      <header>
        <strong>FinTech Suite</strong>
        <nav>{(Object.keys(TABS) as Tab[]).map((t) => (
          <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>{TABS[t]}</button>))}
        </nav>
        <span className="muted">{me.label} · {me.role} · {me.plan}</span>
        <button onClick={() => { setKey(""); setMe(null); }}>Sign out</button>
      </header>
      <main>
        {tab === "invoices" && <Invoices role={me.role} />}
        {tab === "reconciliations" && <Reconciliations role={me.role} />}
        {tab === "contracts" && <Contracts role={me.role} />}
        {tab === "billing" && <Billing />}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
