from __future__ import annotations

import hashlib
import json
import re
import runpy
import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric.e2e import DEMO_DESTINATION, DEMO_PRIMITIVE_ID, run_demo


PATTERN = re.compile(r"ado_pat_[0-9a-f]{16}\.[A-Za-z0-9_-]{32,128}")


def all_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(all_keys(item))
    return keys


class E2ECommandTests(unittest.TestCase):
    def test_real_stack_report_and_materialized_module_are_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            report = run_demo(workspace)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["executable_count"], 11)
            self.assertEqual(report["tool_count"], 6)
            self.assertEqual(report["matched_primitive"], DEMO_PRIMITIVE_ID)
            self.assertTrue(report["proof_passed"])
            self.assertEqual(report["execution_result"]["match_count"], 2)
            self.assertEqual(report["receipt_count"], 2)
            self.assertEqual(report["materialized"]["path"], DEMO_DESTINATION)
            self.assertRegex(report["materialized"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(report["materialized"]["reused_existing"])
            self.assertGreater(report["materialized"]["bytes_written"], 0)
            self.assertTrue(report["phases"])
            self.assertTrue(all(phase["status"] == "passed" for phase in report["phases"]))

            target = workspace / DEMO_DESTINATION
            self.assertTrue(target.is_file())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), report["materialized"]["sha256"])
            module = runpy.run_path(str(target))
            executed = module["execute"]({"text": "Use runnable@example.test"})
            self.assertEqual(executed["emails"], ["runnable@example.test"])

    def test_second_run_reuses_exact_file_and_report_contains_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first = run_demo(workspace)
            target = workspace / DEMO_DESTINATION
            first_bytes = target.read_bytes()

            second = run_demo(workspace)
            self.assertEqual(second["status"], "ok")
            self.assertTrue(second["materialized"]["reused_existing"])
            self.assertEqual(second["materialized"]["bytes_written"], 0)
            self.assertEqual(target.read_bytes(), first_bytes)
            self.assertEqual(second["materialized"]["sha256"], first["materialized"]["sha256"])
            self.assertEqual(second["receipt_count"], 2)

            serialized = json.dumps(second, sort_keys=True)
            self.assertIsNone(PATTERN.search(serialized))
            forbidden = ("password", "token", "secret", "credential", "session", "csrf")
            leaked_keys = [
                key
                for key in all_keys(second)
                if any(fragment in key.lower() for fragment in forbidden)
            ]
            self.assertEqual(leaked_keys, [])


if __name__ == "__main__":
    unittest.main()
