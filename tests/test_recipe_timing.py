"""Pure timing-model tests for source-row recipe semantics."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from _baseline import PAYLOAD_FIXTURES
from _helpers import OWNER_EXAMPLE_CSV, OWNER_EXAMPLE_TOTAL_SECONDS
from convert_to_json import build_payload, estimate_process_seconds, extract_timing_table, load_table
from reactor_ui.models.recipe_timing import (
    RecipeTimingError,
    compute_run_timing,
    cycle_index,
    phase_summary,
    sequence_at,
)


class RecipeTimingTests(unittest.TestCase):
    def test_owner_example_groups_rows_and_cycles(self):
        with tempfile.TemporaryDirectory(prefix="timing_") as folder:
            source = Path(folder) / "owner.csv"
            source.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
            frame = load_table(source)
            run = compute_run_timing(extract_timing_table(frame))
        self.assertEqual([seq.cycle_count for seq in run.sequences], [1, 1, 40, 1])
        self.assertEqual([seq.row_indices for seq in run.sequences], [(0,), (1,), (2, 3, 4, 5, 6, 7), (8,)])
        self.assertEqual([seq.cycle_duration_s for seq in run.sequences], [140, 25, 2030, 140])
        self.assertEqual(run.run_duration_s, OWNER_EXAMPLE_TOTAL_SECONDS)
        summary = phase_summary(run.sequences[2])
        self.assertEqual(summary[0].name, "Total")
        self.assertEqual(summary[0].total_s, 81200)
        self.assertEqual(next(row.per_cycle_s for row in summary if row.name == "N2Dose"), 30)
        self.assertAlmostEqual(sum(row.fraction for row in summary[1:] if row.fraction is not None), 1.0)

    def test_model_and_converter_agree_on_all_baseline_fixtures(self):
        for source in PAYLOAD_FIXTURES.values():
            with self.subTest(source=source.name):
                frame = load_table(source)
                timing = compute_run_timing(extract_timing_table(frame))
                self.assertAlmostEqual(timing.run_duration_s, estimate_process_seconds(frame), places=8)

    def test_boundaries_zero_duration_and_cycle_index(self):
        rows = [
            ["2", "5", "10", "", "", "", "", "", ""],
            ["1", "7", "0", "0", "0", "0", "0", "0", "0"],
            ["1", "8", "3", "0", "0", "0", "0", "0", "0"],
        ]
        run = compute_run_timing(rows)
        self.assertEqual([seq.end_s for seq in run.sequences], [20, 20, 23])
        self.assertEqual(sequence_at(run, -1).index, 1)
        self.assertEqual(sequence_at(run, 19.999).index, 1)
        self.assertEqual(sequence_at(run, 20).index, 3)
        self.assertEqual(sequence_at(run, 23).index, 3)
        self.assertEqual(sequence_at(run, 999).index, 3)
        self.assertEqual(cycle_index(run.sequences[0], 0), 1)
        self.assertEqual(cycle_index(run.sequences[0], 10), 2)
        self.assertEqual(cycle_index(run.sequences[0], 20), 2)
        self.assertIsNone(cycle_index(run.sequences[1], 20))
        self.assertTrue(all(row.fraction is None for row in phase_summary(run.sequences[1])))
        self.assertIsNone(sequence_at(compute_run_timing([]), 0))

    def test_invalid_cells_return_structured_issues(self):
        rows = [
            ["", "0", "-1", "nan", "inf", "0", "0", "0", "0"],
            ["2.5", "5", "0", "0", "0", "0", "0", "0", "0"],
            ["-1", "5", "0", "0", "0", "0", "0", "0", "0"],
        ]
        with self.assertRaises(RecipeTimingError) as caught:
            compute_run_timing(rows)
        self.assertTrue({(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 0), (2, 0)} <= {
            (issue.row, issue.column) for issue in caught.exception.issues
        })

    def test_fractional_cycle_boundaries_use_the_calculated_boundary(self):
        run = compute_run_timing([["20", "5", "0.1", "0", "0", "0", "0", "0", "0"]])
        sequence = run.sequences[0]
        self.assertEqual(cycle_index(sequence, 10 * sequence.cycle_duration_s), 11)
        self.assertEqual(cycle_index(sequence, 3 * sequence.cycle_duration_s), 4)

    def test_large_cycle_count_does_not_expand_rows(self):
        rows = [["1000000", "5", "1", "0", "0", "0", "0", "0", "0"] for _ in range(200)]
        started = time.perf_counter()
        run = compute_run_timing(rows)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(len(run.sequences), 200)
        self.assertEqual(sum(len(seq.events) for seq in run.sequences), 200)
        self.assertEqual(run.run_duration_s, 200_000_000)

    def test_integer_cycle_text_is_not_rounded_during_export(self):
        with tempfile.TemporaryDirectory(prefix="timing_") as folder:
            source = Path(folder) / "large.csv"
            source.write_text(OWNER_EXAMPLE_CSV.replace("40,5,10", "9007199254740993,5,10"), encoding="utf-8")
            frame = load_table(source)
            rows = extract_timing_table(frame)
            self.assertEqual(rows[2][0], "9007199254740993")
            self.assertEqual(compute_run_timing(rows).sequences[2].cycle_count, 9007199254740993)
            self.assertEqual(build_payload(frame, username="test", details="raw")["recipe"][2][0], "9007199254740993")


if __name__ == "__main__":
    unittest.main()
