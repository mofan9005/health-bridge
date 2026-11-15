import { tokenOk, json } from "../lib/auth.js";
// GET /pull?limit=10 -> {items:[{key,received_at,body}]}   (oldest first)
export async function onRequest({ request, env }) {
  if (request.method !== "GET") return json({ error: "method" }, 405);
  if (!(await tokenOk(request, env.READ_TOKEN))) return json({ error: "unauthorized" }, 401);
  if (!env.HEALTH_KV) return json({ error: "storage_not_configured" }, 503);
  const url = new URL(request.url);
  const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "10", 10) || 10, 1), 20);
  const list = await env.HEALTH_KV.list({ prefix: "r:", limit });
  const items = [];
  for (const k of list.keys) {
    const body = await env.HEALTH_KV.get(k.name);
    if (body === null) continue;
    items.push({ key: k.name, received_at: k.metadata && k.metadata.received_at, body });
  }
  return json({ items, more: !list.list_complete });
}
