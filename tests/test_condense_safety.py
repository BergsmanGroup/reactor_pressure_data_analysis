"""Condensation must not truncate an input through a file alias."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from _helpers import sha256_file
from _synthetic_run import write_synthetic_run
from data_parser import condense_log, condensed_path, is_condensed_file


class CondenseSafetyTests(unittest.TestCase):
    def test_hardlinked_destination_does_not_truncate_source(self):
        with tempfile.TemporaryDirectory(prefix="condense_alias_") as folder:
            source = write_synthetic_run(Path(folder) / "raw.json")
            destination = condensed_path(source)
            os.link(source, destination)
            before = sha256_file(source)
            condense_log(source, destination)
            self.assertEqual(sha256_file(source), before)
            self.assertTrue(is_condensed_file(destination))
            self.assertFalse(source.samefile(destination))


if __name__ == "__main__":
    unittest.main()
