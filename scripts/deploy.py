#!/usr/bin/env python3
"""One-command deploy of the health-bridge relay to YOUR Cloudflare account (free plan is enough).

    python3 scripts/deploy.py                    # random project name, data in ~/.health-bridge
    python3 scripts/deploy.py --project my-hb    # fixed project name
    python3 scripts/deploy.py --dry-run          # show what would happen, change nothing

Authentication (pick one, before running):
  * `npx wrangler login`            (browser OAuth), or
  * export CLOUDFLARE_API_TOKEN=... and CLOUDFLARE_ACCOUNT_ID=...
    token permissions: Account > Cloudflare Pages: Edit, Account > Workers KV Storage: Edit

What it does (idempotent; re-running keeps your tokens unless --rotate):
  1. generates INGEST_TOKEN (phone, write-only) and READ_TOKEN (this machine, read+ack) -> <data-dir>/config.env (0600)
  2. creates a KV namespace and a Pages project
  3. writes worker/wrangler.toml (git-ignored) binding KV as HEALTH_KV
  4. stores both tokens as Pages *secrets* (never in the repo, never in toml)
  5. deploys, waits for /health, writes the final URL to config.env
  6. runs scripts/selftest.py
Requires: Node.js (npx) and Python 3.9+.
"""
import argparse, base64, json, os, re, secrets, shutil, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKER = os.path.join(ROOT, "worker")
sys.path.insert(0, os.path.join(ROOT, "bridge"))
import common  # noqa: E402

WRANGLER = ["npx", "--yes", "wrangler@4"]


def token():
    # 32 chars of a-z2-7: easy to type on a phone
    return base64.b32encode(secrets.token_bytes(20)).decode().lower().rstrip("=")


def run(args, dry, input_text=None, check=True, quiet=False):
    shown = " ".join(args)
    if dry:
        print("[dry-run] " + shown + ("   (stdin: <secret>)" if input_text else ""))
        return subprocess.CompletedProcess(args, 0, "", "")
    if not quiet:
        print("$ " + shown)
    p = subprocess.run(args, cwd=WORKER, input=input_text, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"command failed ({p.returncode}): {shown}\n{(p.stdout + p.stderr).strip()[-1500:]}")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="Pages project name (default: health-bridge-<random>)")
    ap.add_argument("--data-dir", help="where config.env and inbox/ live (default ~/.health-bridge)")
    ap.add_argument("--timezone", default=None, help="IANA tz used to name day files, e.g. Europe/Berlin (default: keep or UTC)")
    ap.add_argument("--rotate", action="store_true", help="generate new tokens (the phone shortcut must be updated)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-selftest", action="store_true")
    a = ap.parse_args()

    if a.data_dir:
        os.environ["HEALTH_BRIDGE_DIR"] = os.path.expanduser(a.data_dir)
        common.DATA_DIR = os.environ["HEALTH_BRIDGE_DIR"]
        common.INBOX = os.path.join(common.DATA_DIR, "inbox")
        common.CONFIG = os.path.join(common.DATA_DIR, "config.env")
    if not shutil.which("npx"):
        sys.exit("Node.js (npx) is required: https://nodejs.org")

    old = common.load_env() if os.path.exists(common.CONFIG) else {}
    project = a.project or old.get("PAGES_PROJECT") or "health-bridge-" + secrets.token_hex(3)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,56}", project):
        sys.exit("project name: lowercase letters, digits, dashes")
    ingest = token() if (a.rotate or not old.get("INGEST_TOKEN")) else old["INGEST_TOKEN"]
    read = token() if (a.rotate or not old.get("READ_TOKEN")) else old["READ_TOKEN"]
    tz = a.timezone or old.get("TIMEZONE") or "UTC"
    base_url = old.get("HEALTH_BRIDGE_URL") if old.get("PAGES_PROJECT") == project else f"https://{project}.pages.dev"
    dry = a.dry_run

    def write_config(url):
        text = (f"# health-bridge config - SECRET, keep mode 0600, never commit\n"
                f"HEALTH_BRIDGE_URL={url}\nPAGES_PROJECT={project}\nTIMEZONE={tz}\n"
                f"INGEST_TOKEN={ingest}\nREAD_TOKEN={read}\n")
        if dry:
            print(f"[dry-run] would write {common.CONFIG} (0600) with new/kept tokens")
            return
        os.makedirs(common.DATA_DIR, mode=0o700, exist_ok=True)
        os.makedirs(common.INBOX, mode=0o700, exist_ok=True)
        os.chmod(common.DATA_DIR, 0o700); os.chmod(common.INBOX, 0o700)
        common.write_private(common.CONFIG, text)

    print(f"project: {project}\ndata dir: {common.DATA_DIR}")
    write_config(base_url)

    if not dry:
        who = run(WRANGLER + ["whoami"], dry, check=False, quiet=True)
        if who.returncode != 0 or "not authenticated" in (who.stdout + who.stderr).lower():
            sys.exit("Not logged in to Cloudflare. Run `npx wrangler login` or export "
                     "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID, then re-run.")

    # 1. KV namespace (reuse if it exists)
    kv_title = f"{project}-inbox"
    run(WRANGLER + ["kv", "namespace", "create", kv_title], dry, check=False)
    kv_id = "<kv-namespace-id>"
    if not dry:
        lst = run(WRANGLER + ["kv", "namespace", "list"], dry, quiet=True)
        try:
            kv_id = next(n["id"] for n in json.loads(lst.stdout[lst.stdout.index("["):]) if n["title"] == kv_title)
        except Exception:
            sys.exit("Could not find/create the KV namespace. Check the token has 'Workers KV Storage: Edit'.")

    # 2. generated wrangler.toml (git-ignored; has the KV id)
    toml = (f'name = "{project}"\npages_build_output_dir = "public"\ncompatibility_date = "2026-01-01"\n\n'
            f'[[kv_namespaces]]\nbinding = "HEALTH_KV"\nid = "{kv_id}"\n')
    if dry:
        print("[dry-run] would write worker/wrangler.toml:\n" + toml)
    else:
        with open(os.path.join(WORKER, "wrangler.toml"), "w") as f:
            f.write(toml)

    # 3. Pages project + secrets + deploy
    run(WRANGLER + ["pages", "project", "create", project, "--production-branch", "main"], dry, check=False)
    run(WRANGLER + ["pages", "secret", "put", "INGEST_TOKEN", "--project-name", project], dry, input_text=ingest)
    run(WRANGLER + ["pages", "secret", "put", "READ_TOKEN", "--project-name", project], dry, input_text=read)
    out = run(WRANGLER + ["pages", "deploy", "public", "--project-name", project, "--branch", "main",
                          "--commit-dirty=true"], dry)
    url = base_url
    m = re.search(r"https://[a-z0-9]+\.([a-z0-9-]+\.pages\.dev)", out.stdout + out.stderr)
    if m:
        url = "https://" + m.group(1)  # real production hostname (Cloudflare may add a suffix)
    write_config(url)

    if dry:
        print("[dry-run] done; nothing was changed.")
        return 0

    print(f"deployed: {url}\nwaiting for /health ...")
    ok = False
    for _ in range(20):
        try:
            r = urllib.request.Request(url + "/health", headers={"User-Agent": "health-bridge-deploy/1"})
            body = json.load(urllib.request.urlopen(r, timeout=15))
            if body.get("ok") and body.get("storage"):
                ok = True
                break
        except Exception:
            pass
        time.sleep(3)
    if not ok:
        sys.exit("Deployed, but /health did not report storage=true. Re-run this script, or check the KV binding in the dashboard.")
    print("relay is up.")
    if not a.skip_selftest:
        rc = subprocess.call([sys.executable, os.path.join(HERE, "selftest.py")], env={**os.environ, "HEALTH_BRIDGE_DIR": common.DATA_DIR})
        if rc:
            return rc
    print(f"\nIngest URL for the phone:  {url}/ingest\nIngest token: see INGEST_TOKEN in {common.CONFIG} (do not paste it in chats)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
