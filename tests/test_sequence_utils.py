"""Sequence parsing and phase-bin regression tests."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from _helpers import OWNER_EXAMPLE_CSV

import convert_to_json
from sequence_utils import PHASE_TYPES, compute_phase_bins, convert_sequence, make_cycle_seq_map


class ConvertSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="seq_test_"))
        try:
            path = tmp / "owner_example.csv"
            path.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
            df = convert_to_json.load_table(path)
            cls.recipe = convert_to_json.build_payload(df)["recipe"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        cls.seq = convert_sequence(cls.recipe)

    def test_sequences_start_at_numbered_rows(self):
        self.assertEqual(list(self.seq), ["seq1", "seq2", "seq3", "seq4"])
        self.assertEqual([s["cycles"] for s in self.seq.values()], [1, 1, 40, 1])
        self.assertEqual(
            [[valve for valve, _ in s["valve_rows"]] for s in self.seq.values()],
            [[12], [7], [5, 5, 7, 8, 8, 7], [12]],
        )

    def test_zero_cycle_cell_is_continuation(self):
        rows = [row[:] for row in self.recipe]
        rows[3][0] = "0"
        self.assertEqual(convert_sequence(rows), self.seq)

    def test_cycle_map_covers_every_nominal_cycle(self):
        mapping = make_cycle_seq_map(self.seq)
        self.assertEqual(len(mapping), 43)
        self.assertEqual(mapping[1], "seq1")
        self.assertEqual(mapping[2], "seq2")
        self.assertEqual(mapping[3], "seq3")
        self.assertEqual(mapping[42], "seq3")
        self.assertEqual(mapping[43], "seq4")

    def test_phase_bins_accumulate_nonzero_slots_serially(self):
        phased = compute_phase_bins(self.seq)
        self.assertEqual(phased["seq1"]["phase_bins"], [0.0, 10.0, 130.0, 140.0])
        self.assertEqual(phased["seq3"]["phase_bins"][-1], 2030.0)

    def test_phase_type_order_is_pinned(self):
        # Current labels. Slots 2 and 3 are known to be swapped relative to the
        # owner-confirmed order (PrePump, N2Dose, PumpDose, ...); prompt 04
        # resolves this deliberately and must update this assertion.
        self.assertEqual(PHASE_TYPES, ["prepump", "dosepump", "dosen2", "dose", "hold", "prepurge", "purge"])


if __name__ == "__main__":
    unittest.main()
