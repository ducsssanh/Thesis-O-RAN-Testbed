#!/usr/bin/env python3
"""Regression tests for fresh real URR selection when fixtures are also stored."""
import datetime as dt
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/k8s"))
import staged  # noqa: E402


class FreshRealUrrTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)

    def test_ignores_newer_fixture_and_selects_recent_real_report(self):
        reports = [
            {"ur_seqn": 7, "ul_bytes": 0, "dl_bytes": 500, "observed_at": "2026-09-29T11:58:00Z"},
            {"ur_seqn": 999999999, "ul_bytes": 100, "dl_bytes": 100, "observed_at": "2026-09-29T11:59:30Z"},
        ]
        result = staged.fresh_real_urr(reports, self.now)
        self.assertEqual(result["ur_seqn"], 7)

    def test_rejects_stale_real_report(self):
        reports = [{"ur_seqn": 7, "dl_bytes": 500, "observed_at": "2026-09-29T11:54:59Z"}]
        self.assertIsNone(staged.fresh_real_urr(reports, self.now))

    def test_rejects_zero_volume_and_malformed_records(self):
        reports = [
            {"ur_seqn": 8, "ul_bytes": 0, "dl_bytes": 0, "observed_at": "2026-09-29T11:59:00Z"},
            {"ur_seqn": 9, "dl_bytes": 100},
        ]
        self.assertIsNone(staged.fresh_real_urr(reports, self.now))


if __name__ == "__main__":
    unittest.main()
