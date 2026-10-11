import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Err, canWrite, useAction } from "../ui";

const tone = (s: string) => (s === "high" ? "bad" : s === "medium" ? "warn" : undefined);

export function LegalReview({ contractId, role }: { contractId: string; role: string }) {
  const [rid, setRid] = useState<string | null>(null);
  const [r, setR] = useState<any>(null);
  const { busy, error, run } = useAction();
  // open the most recent review for this contract, if any
  useEffect(() => { api(`/contracts/${contractId}/legal-reviews`).then((l: any[]) => l.length && setRid(l[l.length - 1].id)).catch(() => {}); }, [contractId]);
  useEffect(() => {
    if (!rid) return;
    let stop = false;
    const tick = async () => { const d = await api(`/legal/reviews/${rid}`); if (stop) return; setR(d); if (d.status === "processing") setTimeout(tick, 2000); };
    tick().catch(() => {});
    return () => { stop = true; };
  }, [rid]);
  const res = r?.result;
  return (
    <div className="card">
      <h4>AI legal review <span className="muted">(grounded in cited sources)</span></h4>
      {canWrite(role) && <button disabled={busy || r?.status === "processing"} onClick={() => run(async () => { setR(null); setRid((await api(`/contracts/${contractId}/legal-review`, { json: {} })).id); })}>
        {r?.status === "processing" ? "Reviewing…" : res ? "Run again" : "Run legal review"}</button>}
      <Err msg={error || (r?.status === "failed" ? r.error : "")} />
      {res && <>
        {res.notes.map((n: string) => <p key={n} className="warn">{n}</p>)}
        <p className="muted">{res.issue_count} cited issue(s) · mode: {res.mode.replace("_", " ")}{res.dropped_ungrounded > 0 && ` · ${res.dropped_ungrounded} uncited finding(s) discarded`}</p>
        {res.clauses.map((c: any) => (
          <details key={c.number} open={c.issues.length > 0 || c.rule_findings.length > 0}>
            <summary><strong>{c.number}. {c.title || "Clause"}</strong>{" "}
              {c.issues.length > 0 && <Badge tone="bad">{c.issues.length} issue{c.issues.length > 1 ? "s" : ""}</Badge>}{" "}
              {c.rule_findings.length > 0 && <Badge tone="warn">{c.rule_findings.length} rule flag{c.rule_findings.length > 1 ? "s" : ""}</Badge>}</summary>
            {c.rule_findings.map((f: any) => <p key={f.code} className="warn"><strong>{f.severity.toUpperCase()} {f.code}</strong> {f.message}</p>)}
            {c.issues.map((i: any, n: number) => (
              <blockquote key={n}><p><Badge tone={tone(i.severity)}>{i.severity}</Badge> {i.issue}</p>
                {i.suggestion && <p className="muted">Suggestion: {i.suggestion}</p>}
                {i.citations.map((q: any) => <p key={q.id} className="muted"><em>{q.source}{q.section ? `, s.${q.section}` : ""}:</em> “{q.quote}”</p>)}</blockquote>))}
            {c.issues.length === 0 && c.provisions.length > 0 && <p className="muted">Relevant provisions: {c.provisions.map((p: any) => `${p.source}${p.section ? ` s.${p.section}` : ""}`).join("; ")}</p>}
          </details>))}
        <p className="muted">{res.disclaimer}</p></>}
    </div>
  );
}
