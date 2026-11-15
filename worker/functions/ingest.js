import { tokenOk, json } from "../lib/auth.js";
const MAX = 512 * 1024;
const TTL = 30 * 24 * 3600;
export async function onRequest({ request, env }) {
  if (request.method !== "POST" && request.method !== "PUT") return json({ error: "method" }, 405);
  if (!(await tokenOk(request, env.INGEST_TOKEN))) return json({ error: "unauthorized" }, 401);
  if (!env.HEALTH_KV) return json({ error: "storage_not_configured" }, 503);
  const text = await request.text();
  if (text.length > MAX) return json({ error: "too_large" }, 413);
  let obj;
  try { obj = JSON.parse(text); } catch { return json({ error: "invalid_json" }, 400); }
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return json({ error: "expected_object" }, 400);
  const now = new Date();
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z"); // 20261115T003001Z
  const key = `r:${stamp}:${crypto.randomUUID().slice(0, 8)}`;
  await env.HEALTH_KV.put(key, text, { expirationTtl: TTL, metadata: { received_at: now.toISOString() } });
  return json({ ok: true, key, bytes: text.length });
}
