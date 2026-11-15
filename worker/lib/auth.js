const enc = new TextEncoder();
async function sha(s) { return new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(s))); }
export async function tokenOk(request, expected) {
  if (!expected) return false;
  const h = request.headers.get("Authorization") || "";
  const m = /^Bearer\s+(\S+)\s*$/i.exec(h);
  if (!m) return false;
  const [a, b] = await Promise.all([sha(m[1]), sha(expected)]);
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}
export function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
