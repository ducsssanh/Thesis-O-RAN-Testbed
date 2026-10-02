#!/usr/bin/env python3
"""Pure helpers of scripts/k8s/staged.py; no cluster access."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/k8s"))
import staged  # noqa: E402


class Helpers(unittest.TestCase):
    def test_ric_wedged_needs_repeated_pending_delete(self):
        line = "[NEAR-RIC]: SUBSCRIPTION REQUEST DELETE RAN FUNC ID 2 RIC_REQ_ID 1047 MSG ALREADY PENDING\n"
        self.assertTrue(staged.ric_wedged(line * 2))
        self.assertFalse(staged.ric_wedged(line))
        self.assertFalse(staged.ric_wedged("[iApp]: E42 SETUP-REQUEST rx\n"))

    def test_urr_key_separates_session_epochs(self):
        old = {"seid": 8, "ur_seqn": 3}
        a = {"seid": "8", "ur_seqn": "3", "session_epoch": "20261001T120000Z"}
        b = {"seid": 8, "ur_seqn": 3, "session_epoch": "20261001T121000Z"}
        self.assertEqual(staged.urr_key(old), (8, "", 3))
        self.assertNotEqual(staged.urr_key(a), staged.urr_key(b))


if __name__ == "__main__":
    unittest.main()
