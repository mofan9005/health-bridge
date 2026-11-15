import { json } from "../lib/auth.js";
export async function onRequest({ env }) {
  return json({ ok: true, storage: !!env.HEALTH_KV });
}
