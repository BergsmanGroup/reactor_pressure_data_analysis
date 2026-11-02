"""End-to-end pipeline baseline on a temporary copy of the DID000141 condensed run.

Only an already-condensed run is tracked in the repository; a raw NDJSON
fixture is not available, so raw-input condensation is not yet covered.
"""

from __future__ import annotations

import math
import shutil
import tempfile
import unittest
from pathlib import Path

from _helpers import load_golden, sha256_file
from _baseline import PIPELINE_GOLDEN, did141_condensed_source, run_did141_pipeline


def _assert_close(test: unittest.TestCase, actual, expected, path="root"):
    if isinstance(expected, dict):
        test.assertIsInstance(actual, dict, path)
        test.assertEqual(set(actual), set(expected), path)
        for key in expected:
            _assert_close(test, actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        test.assertIsInstance(actual, list, path)
        test.assertEqual(len(actual), len(expected), path)
        for idx, (a, e) in enumerate(zip(actual, expected)):
            _assert_close(test, a, e, f"{path}[{idx}]")
    elif isinstance(expected, float) or isinstance(actual, float):
        test.assertTrue(math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6), f"{path}: {actual} != {expected}")
    elif isinstance(expected, str) and isinstance(actual, str):
        try:
            a, e = float(actual), float(expected)
        except ValueError:
            test.assertEqual(actual, expected, path)
        else:
            test.assertTrue(math.isclose(a, e, rel_tol=1e-6, abs_tol=1e-6), f"{path}: {actual} != {expected}")
    else:
        test.assertEqual(actual, expected, path)


class PipelineBaselineTests(unittest.TestCase):
    def test_did141_outputs_match_baseline_and_source_is_untouched(self):
        source = did141_condensed_source()
        before = sha256_file(source)
        work = Path(tempfile.mkdtemp(prefix="pipeline_test_"))
        try:
            summary = run_did141_pipeline(work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(sha256_file(source), before)
        _assert_close(self, summary, load_golden(PIPELINE_GOLDEN))


if __name__ == "__main__":
    unittest.main()
