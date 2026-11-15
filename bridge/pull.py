#!/usr/bin/env python3
"""Pull Apple Health exports from the Cloudflare relay into <data-dir>/inbox/YYYY-MM-DD.json.

Idempotent; safe to run repeatedly (flock-guarded). Typical use: cron / launchd / systemd timer, or
call it right before you build a report.

    python3 bridge/pull.py            # prints a one-line summary
Exit codes: 0 ok (even if nothing new), 2 config / network / auth error. Stdlib only.
"""
import fcntl, json, os, sys, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

FLAT_KEYS = ("vo2max", "hrv", "resting_hr", "respiratory_rate", "steps", "active_energy", "spo2")


def call(url, token, data=None):
    req = urllib.request.Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        method="GET" if data is None else "POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "health-bridge-pull/1"},  # Cloudflare rejects the default Python UA
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _nonempty(v):
    if isinstance(v, (list, tuple)):
        return any(_nonempty(x) for x in v)
    if isinstance(v, dict):
        return any(_nonempty(x) for x in v.values())
    return bool(str(v if v is not None else "").strip())


def has_data(o):
    """True if the export carries any sample. Works for the simple (3 keys) and full schemas."""
    if o.get("locked_or_empty"):
        return False
    if any(_nonempty(o.get(k)) for k in FLAT_KEYS) or _nonempty(o.get("sleep")):
        return True
    m = o.get("metrics")
    return isinstance(m, dict) and any(_nonempty(m.get(k)) for k in m)


def _utc_key(obj):
    ts = parse_ts(obj.get("exported_at") or "") or parse_ts((obj.get("_meta") or {}).get("received_at") or "")
    if ts is None:
        return "0000"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def save(obj, received_at, tz):
    obj.setdefault("_meta", {})["received_at"] = received_at
    ts = parse_ts(obj.get("exported_at") or "") or parse_ts(received_at or "") or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    date = ts.astimezone(tz).strftime("%Y-%m-%d")
    path = os.path.join(common.INBOX, date + ".json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                old = json.load(f)
            if has_data(old) and not has_data(obj):
                return date, "kept-existing (new one empty/locked)"
            if has_data(old) == has_data(obj) and _utc_key(old) >= _utc_key(obj):
                return date, "kept-existing (older export)"
        except Exception:
            pass
    fd, tmp = tempfile.mkstemp(dir=common.INBOX, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return date, "written"


def main():
    os.umask(0o077)
    os.makedirs(common.INBOX, mode=0o700, exist_ok=True)
    os.chmod(common.INBOX, 0o700)
    lock = open(os.path.join(common.DATA_DIR, ".pull.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        env = common.load_env()
        url, tok = env["HEALTH_BRIDGE_URL"].rstrip("/"), env["READ_TOKEN"]
    except Exception as e:
        print("config error:", e)
        return 2
    tz = common.day_tz(env)
    results, total = [], 0
    try:
        for _ in range(20):  # at most 400 items per run
            r = call(url + "/pull?limit=20", tok)
            items = r.get("items", [])
            if not items:
                break
            ack = []
            for it in items:
                try:
                    obj = json.loads(it["body"])
                    if not isinstance(obj, dict):
                        raise ValueError("not an object")
                    results.append(save(obj, it.get("received_at"), tz))
                except Exception:
                    # park unparseable payloads instead of losing them, then ack
                    p = os.path.join(common.INBOX, ".bad-" + it["key"].replace(":", "_") + ".txt")
                    common.write_private(p, it.get("body", ""))
                    results.append((it["key"], "bad-json parked"))
                ack.append(it["key"])
            call(url + "/ack", tok, {"keys": ack})
            total += len(items)
            if not r.get("more"):
                break
    except urllib.error.HTTPError as e:
        print("http error", e.code, e.read()[:200])
        return 2
    except Exception as e:
        print("error:", repr(e))
        return 2
    print(f"pulled {total} item(s): " + ("; ".join(f"{d} {s}" for d, s in results) or "nothing new"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
