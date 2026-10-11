import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Err, useAction } from "../ui";

export function Admin() {
  const [users, setUsers] = useState<any[]>([]);
  const [docs, setDocs] = useState<any>({ private: [], shared: [] });
  const [u, setU] = useState({ email: "", role: "operator" });
  const [src, setSrc] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => { api("/users").then(setUsers); api("/legal/documents").then(setDocs); }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <section>
      <h2>Team (SSO)</h2>
      <p className="muted">Invited people can sign in with your identity provider using the same email address. Nobody is added automatically.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/users", { json: u }); setU({ ...u, email: "" }); load(); }); }}>
        <input type="email" required placeholder="name@company.com" value={u.email} onChange={(e) => setU({ ...u, email: e.target.value })} aria-label="Email" />
        <select value={u.role} onChange={(e) => setU({ ...u, role: e.target.value })} aria-label="Role">{["viewer", "operator", "approver", "admin"].map((r) => <option key={r}>{r}</option>)}</select>
        <button className="primary" disabled={busy}>Invite</button>
      </form>
      <Err msg={error} />
      <table><thead><tr><th>Email</th><th>Role</th><th>Last login</th><th /></tr></thead>
        <tbody>{users.map((x) => (<tr key={x.id}><td>{x.email}</td><td>{x.role}</td><td>{x.last_login ?? "never"}</td>
          <td>{x.active ? <button onClick={() => run(async () => { await api(`/users/${x.id}`, { method: "DELETE" }); load(); })}>Deactivate</button> : <Badge>inactive</Badge>}</td></tr>))}
          {users.length === 0 && <tr><td colSpan={4} className="muted">No invited users yet.</td></tr>}</tbody></table>

      <h2>Legal knowledge base</h2>
      <p className="muted">Your private reference material (clause playbook, precedent contracts) used to ground AI legal review. Only your organisation can see it.
        Shared public-law sources loaded by the platform: {docs.shared.length ? docs.shared.map((s: any) => `${s.source} (${s.chunks})`).join(", ") : <strong>none loaded yet</strong>}.</p>
      <div className="row">
        <input placeholder="Source name, e.g. Acme NDA playbook" value={src} onChange={(e) => setSrc(e.target.value)} aria-label="Source name" />
        <input ref={file} type="file" accept=".txt,.md,.pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f && src.trim()) run(async () => {
          const fd = new FormData(); fd.append("file", f); fd.append("source", src.trim()); await api("/legal/documents", { form: fd }); setSrc(""); load(); }); }} />
        <button disabled={busy || !src.trim()} onClick={() => file.current?.click()}>Upload document</button>
      </div>
      <table><thead><tr><th>Private source</th><th>Chunks</th><th /></tr></thead>
        <tbody>{docs.private.map((d: any) => (<tr key={d.source}><td>{d.source}</td><td>{d.chunks}</td>
          <td><button onClick={() => run(async () => { await api(`/legal/documents?source=${encodeURIComponent(d.source)}`, { method: "DELETE" }); load(); })}>Delete</button></td></tr>))}
          {docs.private.length === 0 && <tr><td colSpan={3} className="muted">Nothing uploaded.</td></tr>}</tbody></table>
    </section>
  );
}
