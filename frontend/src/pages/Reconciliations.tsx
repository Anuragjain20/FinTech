import { useCallback, useEffect, useState } from "react";
import { api, download } from "../api";
import { Badge, Err, canApprove, canWrite, inr, statusTone, useAction } from "../ui";

function View({ id, role }: { id: string; role: string }) {
  const [v, setV] = useState<any>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api(`/reconciliations/${id}`).then(setV), [id]);
  useEffect(() => { load(); }, [load]);
  if (!v) return <p className="muted">Loading…</p>;
  const act = (path: string, body?: object) => run(async () => setV({ ...(await api(`/reconciliations/${id}/${path}`, { json: body ?? {} })) }));
  const s = v.summary;
  const open = v.status !== "finalized" && canWrite(role);
  return (
    <div>
      <h3>{v.name} <Badge tone={statusTone(v.status)}>{v.status}</Badge></h3>
      <div className="grid">
        <div className="card"><h4>Matched</h4><p className="big">{s.matched}</p></div>
        <div className="card"><h4>Suggestions to confirm</h4><p className="big">{s.suggested_pending}</p></div>
        <div className="card"><h4>Unmatched (bank / books)</h4><p className="big">{s.unmatched_bank} / {s.unmatched_book}</p></div>
        {s.unexplained_difference != null && <div className="card"><h4>Unexplained difference</h4>
          <p className={`big ${s.unexplained_difference === 0 ? "okc" : "badc"}`}>{inr(s.unexplained_difference)}</p></div>}
      </div>
      <Err msg={error} />
      <div className="row">
        <button onClick={() => download(`/reconciliations/${id}/report.xlsx`, `brs-${id}.xlsx`)}>Download Excel report</button>
        {canApprove(role) && v.status !== "finalized" && <button className="primary" disabled={busy || s.suggested_pending > 0} onClick={() => act("finalize")}>Finalize</button>}
      </div>
      <h4>Matches</h4>
      <table><thead><tr><th>Bank</th><th>Books</th><th>Rule</th><th>Confidence</th><th>Status</th><th /></tr></thead>
        <tbody>{v.matches.map((m: any) => (
          <tr key={m.bank_id + m.book_id}><td>{m.bank_id}</td><td>{m.book_id}</td><td>{m.rule}</td><td>{Math.round(m.confidence * 100)}%</td>
            <td><Badge tone={statusTone(m.status)}>{m.status}</Badge></td>
            <td>{open && m.status === "suggested" && <>
              <button disabled={busy} onClick={() => act("confirm", { bank_id: m.bank_id, book_id: m.book_id })}>Confirm</button>
              <button disabled={busy} onClick={() => act("reject", { bank_id: m.bank_id, book_id: m.book_id })}>Reject</button></>}</td></tr>))}
        </tbody></table>
      {(["unmatched_bank", "unmatched_book"] as const).map((k) => (
        <div key={k}><h4>{k === "unmatched_bank" ? "On bank statement only" : "In books only"}</h4>
          <table><thead><tr><th>ID</th><th>Date</th><th>Description</th><th>Amount</th><th>Likely reason</th></tr></thead>
            <tbody>{v[k].map((t: any) => (<tr key={t.id}><td>{t.id}</td><td>{t.date}</td><td>{t.description}</td><td>{inr(t.amount)}</td>
              <td><Badge tone={t.category === "unexplained" ? "bad" : "warn"}>{t.category}</Badge> {t.explanation}</td></tr>))}
              {v[k].length === 0 && <tr><td colSpan={5} className="muted">None</td></tr>}</tbody></table></div>))}
    </div>
  );
}

export function Reconciliations({ role }: { role: string }) {
  const [list, setList] = useState<any>({ items: [] });
  const [sel, setSel] = useState<string | null>(null);
  const [form, setForm] = useState<{ bank?: File; book?: File; name: string; bb: string; kb: string }>({ name: "", bb: "", kb: "" });
  const { busy, error, run } = useAction();
  const load = useCallback(() => api("/reconciliations").then(setList), []);
  useEffect(() => { load(); }, [load]);
  const create = (e: React.FormEvent) => { e.preventDefault(); run(async () => {
    const fd = new FormData();
    fd.append("bank_file", form.bank!); fd.append("book_file", form.book!); fd.append("name", form.name || "Reconciliation");
    if (form.bb) fd.append("bank_closing_balance", form.bb);
    if (form.kb) fd.append("book_closing_balance", form.kb);
    const r = await api("/reconciliations", { form: fd }); await load(); setSel(r.id);
  }); };
  return (
    <section>
      <h2>Bank reconciliation</h2>
      {canWrite(role) && <form className="card form" onSubmit={create}>
        <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="HDFC – April 2025" /></label>
        <label>Bank statement (CSV / XLSX / PDF)<input type="file" accept=".csv,.xlsx,.xlsm,.pdf" onChange={(e) => setForm({ ...form, bank: e.target.files?.[0] })} /></label>
        <label>Books / ledger export (CSV / XLSX)<input type="file" accept=".csv,.xlsx,.xlsm,.pdf" onChange={(e) => setForm({ ...form, book: e.target.files?.[0] })} /></label>
        <label>Closing balance per bank<input inputMode="decimal" value={form.bb} onChange={(e) => setForm({ ...form, bb: e.target.value })} /></label>
        <label>Closing balance per books<input inputMode="decimal" value={form.kb} onChange={(e) => setForm({ ...form, kb: e.target.value })} /></label>
        <button className="primary" disabled={busy || !form.bank || !form.book}>Reconcile</button>
      </form>}
      <Err msg={error} />
      <div className="row">{list.items.map((r: any) => (
        <button key={r.id} className={r.id === sel ? "tab active" : "tab"} onClick={() => setSel(r.id)}>{r.name} · {r.status}</button>))}</div>
      {sel && <View key={sel} id={sel} role={role} />}
    </section>
  );
}
