import { useEffect, useState } from "react";
import { publicApi } from "../api";
import { Badge, Err, statusTone, useAction } from "../ui";

/** Public page opened from the emailed link: /s/<token>. No login; possession of the link + the emailed code is the proof. */
export function Sign({ token }: { token: string }) {
  const [d, setD] = useState<any>(null);
  const [otp, setOtp] = useState("");
  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const [done, setDone] = useState<string>("");
  const [fatal, setFatal] = useState("");
  const { busy, error, run } = useAction();
  const load = () => publicApi(`/public/sign/${token}`).then(setD).catch((e) => setFatal(e.message));
  useEffect(() => { load(); }, []);
  if (fatal) return <div className="card login"><h2>Signing link</h2><p className="error" role="alert">{fatal}</p></div>;
  if (!d) return <p className="muted">Loading…</p>;
  const signed = d.status === "signed" || done;
  return (
    <main style={{ maxWidth: 780 }}>
      <h1>{d.title}</h1>
      <p className="muted">Signing as <strong>{d.signer_name}</strong> · document fingerprint (SHA-256) <code>{d.sha256.slice(0, 16)}…</code></p>
      <p>{d.signers.map((s: any) => <span key={s.name}><Badge tone={statusTone(s.status === "signed" ? "approved" : "draft")}>{s.name}: {s.status}</Badge>{" "}</span>)}</p>
      <textarea readOnly rows={22} value={d.text} aria-label="Document text" />
      {signed ? <div className="card"><h3>Thank you, you have signed.</h3>
          <p className="muted">{done === "all" ? "All parties have signed. The sealed copy will be available from the sender." : "You will be notified once everyone has signed."}</p></div> : (
        <form className="card form" onSubmit={(e) => { e.preventDefault(); run(async () => {
          const r = await publicApi(`/public/sign/${token}/sign`, { otp, typed_name: name, consent }); setDone(r.all_signed ? "all" : "yes"); await load(); }); }}>
          <p style={{ gridColumn: "1 / -1" }}>Step 1 — we email a one-time code to the address this link was sent to.</p>
          <div className="row" style={{ gridColumn: "1 / -1" }}>
            <button type="button" disabled={busy} onClick={() => run(async () => { await publicApi(`/public/sign/${token}/otp`, {}); setCodeSent(true); })}>
              {codeSent ? "Send a new code" : "Email me a code"}</button>
            {codeSent && <span className="muted">Code sent. Check your inbox.</span>}
          </div>
          <label>One-time code<input inputMode="numeric" maxLength={6} pattern="\d{6}" value={otp} onChange={(e) => setOtp(e.target.value)} autoComplete="one-time-code" /></label>
          <label>Type your full name as your signature<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="check" style={{ gridColumn: "1 / -1" }}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />{d.consent_text}</label>
          <Err msg={error} />
          <div className="row" style={{ gridColumn: "1 / -1" }}>
            <button className="primary" disabled={busy || !consent || otp.length !== 6 || name.trim().length < 2}>Sign document</button>
            <button type="button" disabled={busy} onClick={() => confirm("Decline to sign? The sender will be notified.") &&
              run(async () => { await publicApi(`/public/sign/${token}/decline`, {}); await load().catch(() => {}); setFatal("You declined to sign this document."); })}>Decline</button>
          </div>
        </form>)}
    </main>
  );
}
