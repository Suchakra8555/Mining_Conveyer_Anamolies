async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}
const post = <T,>(u: string, body?: unknown) =>
  j<T>(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

export const api = {
  get: <T,>(u: string) => j<T>(u),
  post,
  analyze: (form: FormData) => j<any>("/api/vision/analyze", { method: "POST", body: form }),
  file: (p: string | null) => (p ? `/api/vision/files/${p}` : ""),
};
