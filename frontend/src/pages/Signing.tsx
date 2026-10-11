import { useCallback, useEffect, useState } from "react";
import { api, download } from "../api";
import { Badge, Err, canApprove, statusTone, useAction } from "../ui";

export function SigningPanel({ id, status, role, onChange }: { id: string; status: string; role: string; onChange: () => void }) {
  const [s, setS] = useState<any>(null);
  const [rows, setRows] = useState([{ name: "", email: "" }]);
  const [seal, setSeal] = useState<any>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api(`/contracts/${id}/signing`).then(setS).catch(() => setS(null)), [id]);
  useEffect(() => { load(); }, [load, status]);
  const show = status === "approved" || s;
  if (!show) return null;
  const upd = (i: number, k: "name" | "email", v: string) => setRows(rows.map((r, n) => (n === i ? { ...r, [k]: v } : r)));
  return (
    <div className="card">
      <h4>Electronic signature</h4>
      {status === "approved" && canApprove(role) && (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => { await api(`/contracts/${id}/signing`, { json: { signers: rows } }); await load(); onChange(); }); }}>
          <p className="muted">Each signer gets a private link, then a one-time code by email. The document is frozen once sent.</p>
          {rows.map((r, i) => (
            <div className="row" key={i}>
              <input required placeholder="Full name" value={r.name} onChange={(e) => upd(i, "name", e.target.value)} aria-label={`Signer ${i + 1} name`} />
              <input required type="email" placeholder="Email" value={r.email} onChange={(e) => upd(i, "email", e.target.value)} aria-label={`Signer ${i + 1} email`} />
              {rows.length > 1 && <button type="button" onClick={() => setRows(rows.filter((_, n) => n !== i))}>Remove</button>}
            </div>))}
          <div className="row"><button type="button" disabled={rows.length >= 10} onClick={() => setRows([...rows, { name: "", email: "" }])}>Add signer</button>
            <button className="primary" disabled={busy}>Send for signature</button></div>
        </form>)}
      <Err msg={error} />
      {s && <>
        <p>Request status: <Badge tone={statusTone(s.status === "completed" ? "approved" : s.status === "pending" ? "draft" : "failed")}>{s.status}</Badge>
          <span className="muted"> · fingerprint <code>{s.sha256.slice(0, 16)}…</code></span></p>
        <table><thead><tr><th>Signer</th><th>Status</th><th>Signed at (UTC)</th></tr></thead>
          <tbody>{s.signers.map((x: any) => (<tr key={x.email}><td>{x.name} <span className="muted">{x.email}</span></td>
            <td><Badge tone={x.status === "signed" ? "ok" : "warn"}>{x.status}</Badge></td><td>{x.signed_at ?? "—"}</td></tr>))}</tbody></table>
        <div className="row">
          {s.status === "pending" && canApprove(role) && <button disabled={busy} onClick={() => run(async () => { await api(`/signing/${s.id}/cancel`, { json: {} }); await load(); onChange(); })}>Cancel request</button>}
          {s.status === "completed" && <>
            <button className="primary" onClick={() => download(`/contracts/${id}/signed.pdf`, `${id}-signed.pdf`)}>Download signed PDF</button>
            <button onClick={() => run(async () => setSeal(await api(`/contracts/${id}/signed.pdf/verify`)))}>Verify seal</button>
            {seal && <Badge tone={seal.intact && seal.valid ? "ok" : "bad"}>{seal.intact && seal.valid ? "Seal intact: not altered since signing" : "Seal broken: document altered"}</Badge>}</>}
        </div>
        <p className="muted">Electronic signature with audit trail (email link, one-time code, typed name, time, IP). Not Aadhaar eSign / DSC; confirm suitability and stamping with your lawyer.</p></>}
    </div>
  );
}
