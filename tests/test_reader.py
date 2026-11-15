import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))
import reader, pull  # noqa: E402

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def load(name):
    with open(os.path.join(EX, name)) as f:
        return json.load(f)


class ReaderTests(unittest.TestCase):
    def test_simple_export(self):
        d = reader.parse(load("sample_export_simple.json"))
        self.assertTrue(d["has_data"])
        self.assertEqual(d["metrics"]["steps"]["sum"], 5066.0)
        self.assertEqual(d["metrics"]["vo2max"]["last"], 42.8)
        self.assertAlmostEqual(d["metrics"]["active_energy"]["sum"], 135.7)
        self.assertEqual(d["metrics"]["hrv"]["n"], 0)
        self.assertIsNone(d["metrics"]["hrv"]["avg"])
        self.assertIsNone(d["sleep"])

    def test_full_export(self):
        d = reader.parse(load("sample_export_full.json"))
        self.assertEqual(d["sleep"]["asleep_min"], 440.0)
        self.assertEqual(d["sleep"]["stages_min"]["deep"], 85.0)
        self.assertAlmostEqual(d["metrics"]["spo2"]["avg"], 97.0)
        self.assertEqual(d["metrics"]["hrv"]["n"], 4)

    def test_empty_and_garbage(self):
        for raw in ({}, None, [], {"steps": ""}, {"steps": None, "sleep": ""}, {"hrv": "n/a"}, {"sleep": "x|y"}):
            d = reader.parse(raw)
            self.assertFalse(d["has_data"])

    def test_alt_value_shapes(self):
        d = reader.parse({"steps": [100, 200.5], "hrv": [{"t": "x", "v": 40, "unit": "ms"}, {"v": 60}],
                          "active_energy": "418.4 kJ", "spo2": "98 %"})
        self.assertEqual(d["metrics"]["steps"]["sum"], 300.5)
        self.assertEqual(d["metrics"]["hrv"]["avg"], 50)
        self.assertAlmostEqual(d["metrics"]["active_energy"]["sum"], 100.0)
        self.assertEqual(d["metrics"]["spo2"]["avg"], 98)

    def test_sleep_names_en_zh_and_sources(self):
        raw = {"sleep": "\n".join([
            "Core|2026-01-02T00:00:00+00:00|2026-01-02T01:00:00+00:00|Watch",
            "REM|2026-01-02T01:00:00+00:00|2026-01-02T01:30:00+00:00|Watch",
            "深度|2026-01-02T01:30:00+00:00|2026-01-02T02:00:00+00:00|Watch",
            "Core|2026-01-02T00:00:00+00:00|2026-01-02T00:20:00+00:00|iPhone"])}
        s = reader.parse(raw)["sleep"]
        self.assertEqual(s["source"], "Watch")
        self.assertEqual(s["asleep_min"], 120.0)
        self.assertEqual(s["other_sources"], ["iPhone"])

    def test_has_data_prefers_real_over_empty(self):
        self.assertFalse(pull.has_data({"steps": "", "sleep": ""}))
        self.assertTrue(pull.has_data({"vo2max": "40 mL/min·kg"}))
        self.assertFalse(pull.has_data({"steps": "1 count", "locked_or_empty": True}))


class SaveTests(unittest.TestCase):
    def test_save_dedup_and_modes(self):
        import stat
        from datetime import timezone
        with tempfile.TemporaryDirectory() as t:
            pull.common.INBOX = os.path.join(t, "inbox")
            os.makedirs(pull.common.INBOX, mode=0o700)
            good = {"steps": "10 count", "exported_at": "2026-03-01T08:00:00+00:00"}
            empty = {"steps": "", "exported_at": "2026-03-01T09:00:00+00:00"}
            self.assertEqual(pull.save(dict(good), None, timezone.utc)[1], "written")
            self.assertIn("kept-existing", pull.save(dict(empty), None, timezone.utc)[1])
            p = os.path.join(pull.common.INBOX, "2026-03-01.json")
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            # simple export without exported_at: date comes from received_at
            d, _ = pull.save({"steps": "5 count"}, "2026-03-02T01:00:00Z", timezone.utc)
            self.assertEqual(d, "2026-03-02")


if __name__ == "__main__":
    unittest.main()
