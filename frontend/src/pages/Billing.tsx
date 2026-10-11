import { useEffect, useState } from "react";
import { api } from "../api";
import { inr } from "../ui";

const LABEL: Record<string, string> = { invoices: "Invoices", reconciliations: "Reconciliations", contracts: "Contracts" };

export function Billing() {
  const [b, setB] = useState<any>(null);
  useEffect(() => { api("/billing").then(setB); }, []);
  if (!b) return <p className="muted">Loading…</p>;
  return (
    <section>
      <h2>Plan: {b.plan}</h2>
      <div className="grid">
        {Object.keys(LABEL).map((m) => {
          const limit = b.limits[m], used = b.usage[m];
          return (
            <div className="card" key={m}>
              <h3>{LABEL[m]} this month</h3>
              <p className="big">{used}{limit != null && <span className="muted"> / {limit}</span>}</p>
              {limit != null && <progress value={used} max={limit} />}
            </div>
          );
        })}
      </div>
      <h3>Available plans</h3>
      <table>
        <thead><tr><th>Plan</th><th>Price / month</th><th>Invoices</th><th>Reconciliations</th><th>Contracts</th></tr></thead>
        <tbody>{Object.entries<any>(b.plans).map(([name, p]) => (
          <tr key={name}><td>{name}{name === b.plan && " (current)"}</td><td>{inr(p.price_inr)}</td>
            <td>{p.invoices ?? "Unlimited"}</td><td>{p.reconciliations ?? "Unlimited"}</td><td>{p.contracts ?? "Unlimited"}</td></tr>))}
        </tbody>
      </table>
    </section>
  );
}
