#!/usr/bin/env python3
"""End-to-end self-test against your deployed relay.

1. a wrong token is rejected (401)
2. a sample export is accepted with the ingest token (200)
3. the ingest token cannot read (/pull -> 401)
4. pull.py stores it as inbox/<day>.json with mode 0600 (dir 0700), then the test file is removed

Uses a throwaway export dated 2000-01-01 so it never touches real days.
Usage: python3 scripts/selftest.py   (needs a finished scripts/deploy.py run)
"""
import json, os, stat, subprocess, sys, urllib.request, urllib.error
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bridge"))
import common  # noqa: E402

env = common.load_env()
URL = env["HEALTH_BRIDGE_URL"].rstrip("/")


def req(method, path, token, body=None):
    r = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                        "User-Agent": "health-bridge-selftest/1"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    return ok


def main():
    ok = True
    with open(os.path.join(HERE, "..", "examples", "sample_export_full.json")) as f:
        sample = json.load(f)
    sample["exported_at"] = "2000-01-01T12:00:00Z"
    ok &= check("wrong token rejected (401)", req("POST", "/ingest", "wrong-token", sample)[0] == 401)
    st, _ = req("POST", "/ingest", env["INGEST_TOKEN"], sample)
    ok &= check(f"ingest accepted (200, got {st})", st == 200)
    ok &= check("ingest token cannot read (401)", req("GET", "/pull", env["INGEST_TOKEN"])[0] == 401)
    if st == 200:
        out = subprocess.run([sys.executable, os.path.join(HERE, "..", "bridge", "pull.py")], capture_output=True, text=True)
        print(out.stdout.strip() or out.stderr.strip())
        day = datetime.fromisoformat("2000-01-01T12:00:00+00:00").astimezone(common.day_tz(env)).strftime("%Y-%m-%d")
        p = os.path.join(common.INBOX, day + ".json")
        exists = os.path.exists(p)
        ok &= check("pulled into inbox/<day>.json", exists)
        if exists:
            ok &= check("file mode 0600", stat.S_IMODE(os.stat(p).st_mode) == 0o600)
            ok &= check("inbox dir mode 0700", stat.S_IMODE(os.stat(common.INBOX).st_mode) == 0o700)
            os.remove(p)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
