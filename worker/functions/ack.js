import { tokenOk, json } from "../lib/auth.js";
// POST /ack {"keys":[...]} -> deletes keys the box has stored
export async function onRequest({ request, env }) {
  if (request.method !== "POST") return json({ error: "method" }, 405);
  if (!(await tokenOk(request, env.READ_TOKEN))) return json({ error: "unauthorized" }, 401);
  if (!env.HEALTH_KV) return json({ error: "storage_not_configured" }, 503);
  let b;
  try { b = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
  const keys = Array.isArray(b.keys) ? b.keys.filter((k) => typeof k === "string" && k.startsWith("r:")).slice(0, 50) : [];
  for (const k of keys) await env.HEALTH_KV.delete(k);
  return json({ ok: true, deleted: keys.length });
}
