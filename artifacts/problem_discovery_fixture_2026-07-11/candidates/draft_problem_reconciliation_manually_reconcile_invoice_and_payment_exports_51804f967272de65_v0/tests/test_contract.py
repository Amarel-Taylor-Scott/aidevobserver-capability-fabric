from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_primitive", ROOT / "src" / "primitive.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateContractTest(unittest.TestCase):
    def test_positive_fixture_is_deterministic(self) -> None:
        payload = json.loads((ROOT / "fixtures" / "positive.json").read_text(encoding="utf-8"))
        first = MODULE.run(payload)
        second = MODULE.run(payload)
        self.assertIsInstance(first, dict)
        self.assertEqual(first, second)

    def test_negative_fixture_is_rejected(self) -> None:
        payload = json.loads((ROOT / "fixtures" / "negative.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            MODULE.run(payload)


if __name__ == "__main__":
    unittest.main()
