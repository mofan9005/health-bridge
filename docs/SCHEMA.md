# Export format (schema 1) / 导出格式

## 1. What the iPhone sends (stored as `inbox/YYYY-MM-DD.json`)

All fields are optional. Every metric is a **text field with one sample per line** (that is what a
"Find Health Samples" result becomes when placed in a text/JSON field).

Simple export (3 Find actions):

```json
{
  "vo2max": "42.8 mL/min·kg",
  "steps": "412 count\n1,208 count\n96 count",
  "active_energy": "35.2 kcal\n88.0 kcal"
}
```

Full export (adds metadata, more metrics, sleep):

```json
{
  "schema": 1,
  "exported_at": "2026-01-15T08:30:04+08:00",
  "tz": "Asia/Shanghai",
  "window_hours": 24,
  "device": "iPhone",
  "vo2max": "42.8 mL/min·kg",
  "hrv": "48.2 ms\n55.1 ms",
  "resting_hr": "54 count/min",
  "respiratory_rate": "14.2 count/min\n14.8 count/min",
  "steps": "412 count\n1,208 count",
  "active_energy": "35.2 kcal\n88.0 kcal",
  "spo2": "0.97\n0.96",
  "sleep": "Core|2026-01-14T23:22:00+08:00|2026-01-15T00:40:00+08:00|Apple Watch\nDeep|..."
}
```

- Empty string / missing key = no samples in the window (parsed as `n = 0`, stats `null`).
- `sleep` lines are `stage|start|end|source`; stage names in English or Chinese (Core/核心, Deep/深度, REM/快速动眼, Awake/清醒, In Bed/在床).
- Day file name = day of `exported_at` (or, if absent, of the time the relay received it) in the timezone from `config.env` (`TIMEZONE`, default UTC).
- Several exports on one day: the one **with data** wins over an empty one (e.g. a locked-phone run); between two with data, the later wins.
- The server adds `"_meta": {"received_at": ...}` when saving. Unparseable payloads are kept as `inbox/.bad-*.txt`.

## 2. Normalized output of `bridge/reader.py` (`load_day`)

```python
{
 "date": "2026-01-15", "exported_at": "...", "tz": "...", "window_hours": 24,
 "locked_or_empty": False, "has_data": True,
 "metrics": {  # vo2max hrv resting_hr respiratory_rate steps active_energy spo2
   "hrv": {"n": 4, "avg": 51.1, "min": 39.8, "max": 61.4, "sum": 204.5, "last": 39.8, "unit": "ms"},
 },            # n == 0 -> avg/min/max/sum/last are None
 "sleep": None or {
   "source": "Apple Watch",
   "stages_min": {"core": 270.0, "deep": 85.0, "rem": 85.0, "awake": 8.0, "inbed": 465.0, "asleep_unspec": 0.0},
   "asleep_min": 440.0, "start": "...", "end": "...",
   "segments": [{"stage", "start", "end", "minutes", "source"}],
   "other_sources": []     # other sources for the same night are dropped (iPhone + Watch double count)
 }
}
```

Use `sum` for steps / active energy, `avg` for hrv / resting_hr / respiratory_rate / spo2, `last` for vo2max.
kJ is converted to kcal, SpO2 fractions (0-1) to percent. The parser also accepts numbers, lists and
`{"t","v","unit"}` dicts in metric fields.

**Caveat:** samples come from *all* sources. Steps and active energy are often recorded by both iPhone and
Watch (and third-party apps), so sums can double count. Filter by *Source* in the Find action.

## 3. Python example

```python
import sys; sys.path.insert(0, "/path/to/health-bridge/bridge")
from reader import load_day, refresh

print(refresh())                  # optional: pull new data from the relay first (idempotent)
d = load_day()                    # newest day; load_day("2026-01-15") for a specific one; None if missing
if d and d["has_data"]:
    print(d["metrics"]["steps"]["sum"], d["metrics"]["vo2max"]["last"])
```
CLI: `python3 bridge/reader.py [YYYY-MM-DD] [--refresh]`
