"""Read Apple Health daily exports from <data-dir>/inbox/ and normalize them.

    import sys; sys.path.insert(0, "path/to/health-bridge/bridge")
    from reader import load_day, refresh
    d = load_day("2026-11-15")   # or load_day() for the newest day; None if there is no file
    d["metrics"]["steps"]["sum"]  # None when n == 0

Tolerant by design: accepts the simple export (vo2max / steps / active_energy only) and the full one,
missing keys, empty strings, numbers or {"t","v","unit"} dicts instead of text lines, thousands
separators, Chinese/English sleep stage names, kJ vs kcal, SpO2 as 0-1 or percent. Stdlib only.
"""
import glob, json, os, re, subprocess, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

METRICS = ("vo2max", "hrv", "resting_hr", "respiratory_rate", "steps", "active_energy", "spo2")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")

# lower-cased substring -> canonical stage (order matters: first hit wins)
_STAGE = [
    ("core", "core"), ("核心", "core"), ("light", "core"),
    ("deep", "deep"), ("深度", "deep"),
    ("rem", "rem"), ("快速动眼", "rem"), ("快速眼动", "rem"),
    ("awake", "awake"), ("清醒", "awake"),
    ("in bed", "inbed"), ("inbed", "inbed"), ("在床", "inbed"),
    ("asleep", "asleep_unspec"), ("睡眠", "asleep_unspec"), ("unspecified", "asleep_unspec"), ("未指定", "asleep_unspec"),
]


def refresh():
    """Run pull.py (idempotent). Returns its one-line summary; never raises."""
    try:
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pull.py")],
                           capture_output=True, text=True, timeout=90)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return "pull failed: %r" % e


def _entries(v):
    """Flatten a metric field into [(number, unit_or_None)]."""
    out = []
    if v is None:
        return out
    if isinstance(v, bool):
        return out
    if isinstance(v, (int, float)):
        return [(float(v), None)]
    if isinstance(v, dict):
        x = v.get("v", v.get("value"))
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return [(float(x), v.get("unit"))]
        return _entries(x) if x is not None else []
    if isinstance(v, (list, tuple)):
        for x in v:
            out += _entries(x)
        return out
    for line in str(v).replace("\r", "\n").split("\n"):
        line = line.strip()
        m = _NUM.search(line)
        if m:
            try:
                out.append((float(m.group(0).replace(",", "")), line[m.end():].strip() or None))
            except ValueError:
                pass
    return out


def _parse_vals(v, name):
    vals, unit = [], None
    for x, u in _entries(v):
        if name == "active_energy" and u and u.lower() in ("kj", "千焦", "千焦耳"):
            x, u = x / 4.184, "kcal"
        if name == "spo2" and x <= 1.5:
            x, u = x * 100, "%"
        vals.append(x)
        unit = unit or u
    return vals, unit


def _stats(vals, unit):
    if not vals:
        return {"n": 0, "avg": None, "min": None, "max": None, "sum": None, "last": None, "unit": unit}
    return {"n": len(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals),
            "sum": sum(vals), "last": vals[-1], "unit": unit}


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except Exception:
        return None


def _sleep_lines(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [l for x in v for l in _sleep_lines(x)]
    return [l.strip() for l in str(v).replace("\r", "\n").split("\n") if l.strip()]


def _parse_sleep(v):
    segs = []
    for l in _sleep_lines(v):
        parts = [p.strip() for p in l.split("|")]
        if len(parts) < 3:
            continue
        name = parts[0].lower()
        stage = next((c for k, c in _STAGE if k in name), None)
        a, b = _dt(parts[1]), _dt(parts[2])
        try:
            if stage and a and b and b > a:
                segs.append({"stage": stage, "start": parts[1], "end": parts[2],
                             "minutes": (b - a).total_seconds() / 60,
                             "source": parts[3] if len(parts) > 3 else None, "_a": a, "_b": b})
        except TypeError:  # naive vs aware mix
            continue
    return segs


def parse(raw):
    """Raw export dict -> normalized dict (see docs/SCHEMA.md)."""
    if not isinstance(raw, dict):
        raw = {}
    out = {"exported_at": raw.get("exported_at"), "tz": raw.get("tz"), "window_hours": raw.get("window_hours"),
           "locked_or_empty": bool(raw.get("locked_or_empty")), "metrics": {}, "sleep": None}
    m = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    for k in METRICS:
        vals, unit = _parse_vals(raw.get(k, m.get(k)), k)
        out["metrics"][k] = _stats(vals, unit)
    segs = _parse_sleep(raw.get("sleep"))
    if segs:
        by_src = {}
        for s in segs:
            if s["stage"] in ("core", "deep", "rem", "asleep_unspec"):
                by_src[s["source"]] = by_src.get(s["source"], 0) + s["minutes"]
        src = max(by_src, key=by_src.get) if by_src else segs[0]["source"]
        use = [s for s in segs if s["source"] == src]  # one source only: iPhone + Watch can double count
        stages = {k: 0.0 for k in ("core", "deep", "rem", "awake", "inbed", "asleep_unspec")}
        for s in use:
            stages[s["stage"]] += s["minutes"]
        asleep = [s for s in use if s["stage"] in ("core", "deep", "rem", "asleep_unspec")]
        out["sleep"] = {
            "source": src,
            "stages_min": {k: round(v, 1) for k, v in stages.items()},
            "asleep_min": round(stages["core"] + stages["deep"] + stages["rem"] + stages["asleep_unspec"], 1),
            "start": min(asleep, key=lambda s: s["_a"])["start"] if asleep else None,
            "end": max(asleep, key=lambda s: s["_b"])["end"] if asleep else None,
            "segments": [{k: v for k, v in s.items() if not k.startswith("_")} for s in use],
            "other_sources": sorted({s["source"] for s in segs if s["source"] and s["source"] != src}),
        }
    out["has_data"] = bool(out["sleep"]) or any(v["n"] for v in out["metrics"].values())
    return out


def load_day(date=None, refresh_first=False):
    """date 'YYYY-MM-DD' (day of export in your configured timezone) or None for the newest day."""
    if refresh_first:
        refresh()
    if date is None:
        files = sorted(glob.glob(os.path.join(common.INBOX, "????-??-??.json")))
        if not files:
            return None
        path = files[-1]
    else:
        path = os.path.join(common.INBOX, f"{date}.json")
        if not os.path.exists(path):
            return None
    with open(path) as f:
        d = parse(json.load(f))
    d["date"] = os.path.basename(path)[:-5]
    return d


if __name__ == "__main__":
    d = load_day(next((a for a in sys.argv[1:] if not a.startswith("-")), None), refresh_first="--refresh" in sys.argv)
    print(json.dumps(d, ensure_ascii=False, indent=1) if d else "no data")
