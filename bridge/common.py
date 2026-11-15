"""Shared helpers: data directory, config.env loading, timezone. Stdlib only (Python 3.9+)."""
import os
from datetime import timezone

DATA_DIR = os.path.expanduser(os.environ.get("HEALTH_BRIDGE_DIR", "~/.health-bridge"))
INBOX = os.path.join(DATA_DIR, "inbox")
CONFIG = os.path.join(DATA_DIR, "config.env")


def load_env(path=None):
    env = {}
    with open(path or CONFIG) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def day_tz(env=None):
    """Timezone used to name day files. config.env TIMEZONE=Area/City, else $HEALTH_BRIDGE_TZ, else UTC."""
    name = (env or {}).get("TIMEZONE") or os.environ.get("HEALTH_BRIDGE_TZ") or "UTC"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def write_private(path, text):
    """Write a file with mode 0600 from the start (no world-readable window)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)
