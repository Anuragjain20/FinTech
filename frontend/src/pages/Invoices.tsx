import { useCallback, useEffect, useRef, useState } from "react";
import { api, download } from "../api";
import { Badge, Err, canApprove, canWrite, inr, statusTone, useAction } from "../ui";

const FIELDS = ["supplier_name", "supplier_gstin", "buyer_gstin", "invoice_number", "invoice_date", "taxable_value", "cgst", "sgst", "igst", "total"];
const NUMERIC = new Set(["taxable_value", "cgst", "sgst", "igst", "total"]);

function Detail({ id, role, onChange }: { id: string; role: string; onChange: () => void }) {
  const [inv, setInv] = useState<any>(null);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const load = useCallback(() => api(`/invoices/${id}`).then((d) => { setInv(d); setDraft(d.invoice ?? {}); }), [id]);
  useEffect(() => { load(); }, [load]);
  // poll while the worker is still extracting
  useEffect(() => { if (inv?.status !== "processing") return; const t = setTimeout(load, 2000); return () => clearTimeout(t); }, [inv, load]);
  if (!inv) return <p className="muted">Loading…</p>;
  const editable = canWrite(role) && !["approved", "processing"].includes(inv.status);
  const errors = (inv.issues ?? []).filter((i: any) => i.severity === "error");
  const save = () => run(async () => {
    const body: Record<string, any> = { ...draft };
    for (const k of NUMERIC) body[k] = body[k] === "" || body[k] == null ? null : Number(body[k]);
    await api(`/invoices/${id}`, { method: "PUT", json: body }); await load(); onChange();
  });
  const approve = () => run(async () => { await api(`/invoices/${id}/approve`, { json: { override_reason: reason || null } }); await load(); onChange(); });
  return (
    <div className="card detail">
      <h3>Invoice <Badge tone={statusTone(inv.status)}>{inv.status}</Badge></h3>
      {inv.status === "failed" && <p className="error">{inv.error}</p>}
      {inv.filename && <button onClick={() => download(`/invoices/${id}/file`, inv.filename)}>Download original</button>}
      <div className="form">{FIELDS.map((f) => (
        <label key={f}>{f.replace("_", " ")}
          <input disabled={!editable} value={draft[f] ?? ""} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
            className={inv.confidence?.[f] != null && inv.confidence[f] < 0.8 ? "lowconf" : ""} />
        </label>))}
      </div>
      {(inv.issues ?? []).length > 0 && <ul className="issues">{inv.issues.map((i: any, n: number) => (
        <li key={n} className={i.severity}><strong>{i.code}</strong> {i.message}</li>))}</ul>}
      <Err msg={error} />
      <div className="row">
        {editable && <button onClick={save} disabled={busy}>Save &amp; re-validate</button>}
        {canApprove(role) && ["ready", "needs_review"].includes(inv.status) && <>
          {errors.length > 0 && <input placeholder="Override reason (required: blocking errors)" value={reason} onChange={(e) => setReason(e.target.value)} />}
          <button className="primary" onClick={approve} disabled={busy || (errors.length > 0 && !reason.trim())}>Approve</button></>}
      </div>
    </div>
  );
}

export function Invoices({ role }: { role: string }) {
  const [list, setList] = useState<any>({ items: [], total: 0 });
  const [filter, setFilter] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api(`/invoices${filter ? `?status=${filter}` : ""}`).then(setList), [filter]);
  useEffect(() => { load(); }, [load]);
  const upload = (files: FileList | null) => files && run(async () => {
    for (const f of Array.from(files)) { const fd = new FormData(); fd.append("file", f); const r = await api("/invoices/upload", { form: fd }); setSel(r.id); }
    await load();
  });
  return (
    <section className="split">
      <div>
        <div className="row">
          <h2>Invoices</h2>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status">
            <option value="">All</option>{["needs_review", "ready", "approved", "processing", "failed"].map((s) => <option key={s}>{s}</option>)}
          </select>
          {canWrite(role) && <><input ref={file} type="file" multiple hidden accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={(e) => upload(e.target.files)} />
            <button className="primary" disabled={busy} onClick={() => file.current?.click()}>Upload invoices</button></>}
          <button onClick={() => download("/invoices/export/csv", "invoices.csv")}>CSV</button>
          <button onClick={() => download("/invoices/export/tally", "tally-vouchers.xml")}>Tally XML</button>
        </div>
        <Err msg={error} />
        <table>
          <thead><tr><th>Invoice</th><th>Supplier</th><th>Total</th><th>Status</th></tr></thead>
          <tbody>{list.items.map((i: any) => (
            <tr key={i.id} className={i.id === sel ? "selected" : ""} onClick={() => setSel(i.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(i.id)}>
              <td>{i.invoice?.invoice_number ?? i.filename ?? i.id.slice(0, 8)}</td><td>{i.invoice?.supplier_name ?? "—"}</td>
              <td>{inr(i.invoice?.total)}</td><td><Badge tone={statusTone(i.status)}>{i.status}</Badge></td></tr>))}
            {list.items.length === 0 && <tr><td colSpan={4} className="muted">No invoices yet.</td></tr>}
          </tbody>
        </table>
        <p className="muted">{list.total} total</p>
      </div>
      {sel && <Detail key={sel} id={sel} role={role} onChange={load} />}
    </section>
  );
}
