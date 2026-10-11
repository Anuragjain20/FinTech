export class ApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : detail?.message ?? `HTTP ${status}`);
  }
}

const KEY = "fintech.apiKey";
export const getKey = () => sessionStorage.getItem(KEY) ?? "";
export const setKey = (k: string) => (k ? sessionStorage.setItem(KEY, k) : sessionStorage.removeItem(KEY));

async function parse(r: Response) {
  const ct = r.headers.get("content-type") ?? "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, body?.detail ?? body);
  return body;
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "fetch" };
  if (getKey()) headers["X-API-Key"] = getKey();  // otherwise the SSO session cookie authenticates the request
  let body: BodyInit | undefined;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  if (opts.form) body = opts.form;
  return parse(await fetch(path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body }));
}

/** Authenticated download (API keys travel in a header, so plain links won't work). */
export async function download(path: string, filename: string) {
  const r = await fetch(path, { headers: getKey() ? { "X-API-Key": getKey() } : {} });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** Unauthenticated calls for the public signing page (the link token is the credential). */
export async function publicApi<T = any>(path: string, json?: unknown): Promise<T> {
  return parse(await fetch(path, { method: json === undefined ? "GET" : "POST",
    headers: json === undefined ? {} : { "Content-Type": "application/json" }, body: json === undefined ? undefined : JSON.stringify(json) }));
}
