import { useState } from "react";

export const canWrite = (role: string) => role !== "viewer";
export const canApprove = (role: string) => role === "approver" || role === "admin";
export const inr = (n?: number | null) => (n == null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR" }));

export function Badge({ children, tone }: { children: React.ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}

export function statusTone(s: string): "ok" | "warn" | "bad" | undefined {
  if (["approved", "ready", "matched", "confirmed", "finalized"].includes(s)) return "ok";
  if (["needs_review", "suggested", "processing", "in_review", "draft", "open"].includes(s)) return "warn";
  if (["failed"].includes(s)) return "bad";
}

/** Runs an async action, exposing busy/error state for the buttons that trigger it. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true); setError("");
    try { return await fn(); } catch (e: any) { setError(e.message ?? "Something went wrong"); } finally { setBusy(false); }
  }
  return { busy, error, run, setError };
}

export function Err({ msg }: { msg: string }) {
  return msg ? <p className="error" role="alert">{msg}</p> : null;
}
