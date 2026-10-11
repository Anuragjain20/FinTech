import { useCallback, useEffect, useState } from "react";
import { api, download } from "../api";
import { Badge, Err, canApprove, canWrite, statusTone, useAction } from "../ui";

function Review({ review }: { review: any }) {
  return (
    <div className="card">
      <h4>Automated screening <span className="muted">(not legal advice)</span></h4>
      {review.findings.length === 0 && review.missing_clauses.length === 0 && <p>No issues detected.</p>}
      <ul className="issues">
        {review.findings.map((f: any) => <li key={f.code} className={f.severity === "high" ? "error" : "warning"}>
          <strong>{f.severity.toUpperCase()} · {f.code}</strong> {f.message} <em>{f.suggestion}</em></li>)}
        {review.missing_clauses.map((m: any) => <li key={m.clause} className="warning">{m.message}</li>)}
      </ul>
    </div>
  );
}

function Detail({ id, role, onChange }: { id: string; role: string; onChange: () => void }) {
  const [c, setC] = useState<any>(null);
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();
  const load = useCallback(() => api(`/contracts/${id}`).then((d) => { setC(d); setText(d.text); }), [id]);
  useEffect(() => { load(); }, [load]);
  if (!c) return <p className="muted">Loading…</p>;
  const act = (path: string, body: object = {}) => run(async () => { await api(`/contracts/${id}/${path}`, { json: body }); await load(); onChange(); });
  const risky = c.review.high_risk_count > 0;
  return (
    <div>
      <h3>{c.title} <Badge tone={statusTone(c.status)}>{c.status}</Badge> <span className="muted">v{c.version}</span></h3>
      {!c.lawyer_reviewed && <p className="warn">This template has not been reviewed by a lawyer. Treat the output as a draft.</p>}
      <textarea rows={18} value={text} readOnly={c.status !== "draft" || !canWrite(role)} onChange={(e) => setText(e.target.value)} aria-label="Contract text" />
      <Err msg={error} />
      <div className="row">
        {c.status === "draft" && canWrite(role) && <>
          <button disabled={busy || text === c.text} onClick={() => run(async () => { await api(`/contracts/${id}`, { method: "PUT", json: { text } }); await load(); })}>Save new version</button>
          <button disabled={busy || text !== c.text} onClick={() => act("submit")}>Submit for review</button></>}
        {c.status === "in_review" && canApprove(role) && <>
          <button className="primary" disabled={busy} onClick={() => act("approve", { acknowledge_risks: risky && confirm("High-risk findings are present. Approve anyway?") })}>Approve</button>
          <button disabled={busy} onClick={() => act("reject")}>Return to draft</button></>}
        <button onClick={() => download(`/contracts/${id}/docx`, `${c.title}.docx`)}>Download DOCX</button>
      </div>
      <Review review={c.review} />
    </div>
  );
}

function Generator({ onDone }: { onDone: (id: string) => void }) {
  const [tpls, setTpls] = useState<any[]>([]);
  const [tpl, setTpl] = useState<any>(null);
  const [ans, setAns] = useState<Record<string, any>>({});
  const { busy, error, run } = useAction();
  useEffect(() => { api("/contracts/templates").then(setTpls); }, []);
  const pick = (id: string) => id ? api(`/contracts/templates/${id}`).then((t) => {
    setTpl(t); setAns(Object.fromEntries(t.questions.filter((q: any) => q.default != null).map((q: any) => [q.key, q.default])));
  }) : setTpl(null);
  return (
    <form className="card form" onSubmit={(e) => { e.preventDefault(); run(async () => onDone((await api("/contracts", { json: { template_id: tpl.id, answers: ans } })).id)); }}>
      <label>Template<select onChange={(e) => pick(e.target.value)} defaultValue=""><option value="">Choose…</option>
        {tpls.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      {tpl?.questions.map((q: any) => q.type === "bool"
        ? <label key={q.key} className="check"><input type="checkbox" checked={!!ans[q.key]} onChange={(e) => setAns({ ...ans, [q.key]: e.target.checked })} />{q.label}</label>
        : <label key={q.key}>{q.label}{q.required && " *"}<input required={q.required} type={q.type === "int" ? "number" : "text"} value={ans[q.key] ?? ""}
            onChange={(e) => setAns({ ...ans, [q.key]: e.target.value })} /></label>)}
      <Err msg={error} />
      {tpl && <button className="primary" disabled={busy}>Generate draft</button>}
    </form>
  );
}

export function Contracts({ role }: { role: string }) {
  const [list, setList] = useState<any>({ items: [] });
  const [sel, setSel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => api("/contracts").then(setList), []);
  useEffect(() => { load(); }, [load]);
  return (
    <section className="split">
      <div>
        <div className="row"><h2>Contracts</h2>{canWrite(role) && <button className="primary" onClick={() => { setCreating(true); setSel(null); }}>New contract</button>}</div>
        <table><thead><tr><th>Title</th><th>Status</th><th>Versions</th></tr></thead>
          <tbody>{list.items.map((c: any) => (<tr key={c.id} className={c.id === sel ? "selected" : ""} tabIndex={0}
            onClick={() => { setSel(c.id); setCreating(false); }} onKeyDown={(e) => e.key === "Enter" && setSel(c.id)}>
            <td>{c.title}</td><td><Badge tone={statusTone(c.status)}>{c.status}</Badge></td><td>{c.versions}</td></tr>))}
            {list.items.length === 0 && <tr><td colSpan={3} className="muted">No contracts yet.</td></tr>}</tbody></table>
      </div>
      <div>
        {creating && <Generator onDone={(id) => { setCreating(false); setSel(id); load(); }} />}
        {sel && <Detail key={sel} id={sel} role={role} onChange={load} />}
      </div>
    </section>
  );
}
