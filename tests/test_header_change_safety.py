"""Header changes are planned, backed up, and recoverable."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _synthetic_run import write_synthetic_run
from data_parser import condense_log, condensed_path, read_header
from header_text import associated_header_artifacts, parse_header_text, save_header_text
from reactor_ui.adapters.header_changes import (
    HeaderChangeFailure,
    build_header_change_plan,
    describe_header_change_plan,
    execute_header_change,
    inspect_header_artifacts,
    validate_header_change_plan,
)


class HeaderChangeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="header_safety_")
        self.root = Path(self.folder.name)
        self.source = write_synthetic_run(
            self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Data.json"
        )
        self.payload = read_header(self.source)
        self.header = self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Header.txt"
        save_header_text(self.header, self.payload)
        with self.header.open("a", encoding="utf-8") as target:
            target.write("Time Elapsed: 42\n")

    def tearDown(self):
        self.folder.cleanup()

    def plan(self, *, username="New", save_text=True, align=False, token="abc123"):
        inventory = inspect_header_artifacts(self.source, username, self.header)
        return build_header_change_plan(
            self.source,
            username,
            self.header,
            save_header_text=save_text,
            align_names=align,
            inventory=inventory,
            timestamp="20261101-123456",
            token=token,
        )

    def test_plan_is_read_only_and_lists_rewrites_and_backup_paths(self):
        before = {path: path.read_bytes() for path in (self.source, self.header)}
        plan = self.plan()
        description = describe_header_change_plan(plan)
        self.assertIn("This will overwrite", description)
        for path in before:
            self.assertIn(str(path), description)
            self.assertEqual(path.read_bytes(), before[path])
        self.assertEqual(len(plan.backups), 2)
        self.assertTrue(all(str(backup.destination) in description for backup in plan.backups))
        self.assertTrue(all(str(write.temporary) in description for write in plan.writes))
        self.assertEqual(sorted(self.root.iterdir()), sorted(before))

    def test_backups_and_atomic_writes_preserve_remaining_records(self):
        original_data = self.source.read_bytes()
        original_text = self.header.read_bytes()
        payload = copy.deepcopy(self.payload)
        payload["username"] = "Corrected"
        payload.pop("startTime")
        plan = self.plan()
        validate_header_change_plan(plan)
        result = execute_header_change(plan, payload)
        self.assertEqual(read_header(self.source)["username"], "Corrected")
        self.assertEqual(read_header(self.source)["startTime"], self.payload["startTime"])
        self.assertEqual(self.source.read_bytes().splitlines()[1:], original_data.splitlines()[1:])
        self.assertIn("Time Elapsed: 42", self.header.read_text(encoding="utf-8"))
        self.assertEqual(parse_header_text(self.header)["startTime"], self.payload["startTime"])
        backups = {entry.source: entry.destination for entry in plan.backups}
        self.assertEqual(backups[self.source].read_bytes(), original_data)
        self.assertEqual(backups[self.header].read_bytes(), original_text)
        self.assertEqual(set(result.backups), set(backups.values()))
        self.assertTrue(all(not write.temporary.exists() for write in plan.writes))

    def test_alignment_lists_and_backs_up_all_existing_associated_files(self):
        condensed = condensed_path(self.source)
        condense_log(self.source, condensed)
        artifacts = associated_header_artifacts(self.source, "New", str(self.header))
        data_text = artifacts["data_text"]["current"]
        data_text.write_text("associated data", encoding="utf-8")
        converted = self.header.with_suffix(".json")
        converted.write_text("converted header", encoding="utf-8")
        originals = {path: path.read_bytes() for path in (self.source, condensed, self.header, data_text, converted)}
        plan = self.plan(align=True)
        self.assertEqual({rename.source for rename in plan.renames}, set(originals))
        self.assertEqual({backup.source for backup in plan.backups}, set(originals))
        result = execute_header_change(plan, {**self.payload, "username": "New"})
        self.assertEqual(result.selected_path, artifacts["selected"]["expected"])
        self.assertEqual(read_header(result.selected_path)["username"], "New")
        for backup in plan.backups:
            self.assertEqual(backup.destination.read_bytes(), originals[backup.source])
        for rename in plan.renames:
            self.assertFalse(rename.source.exists())
            self.assertTrue(rename.destination.exists())

    def test_second_write_failure_reports_changed_files_and_backups(self):
        original_data = self.source.read_bytes()
        original_text = self.header.read_bytes()
        plan = self.plan()
        original_replace = os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("deliberate write failure")
            return original_replace(source, destination)

        with patch("reactor_ui.adapters.header_changes.os.replace", side_effect=fail_second):
            with self.assertRaises(HeaderChangeFailure) as raised:
                execute_header_change(plan, {**self.payload, "username": "Changed"})
        error = raised.exception
        self.assertIn("deliberate write failure", str(error))
        self.assertIn(str(self.source), str(error))
        self.assertEqual(len(error.changed), 1)
        self.assertEqual(len(error.backups), 2)
        backups = {entry.source: entry.destination for entry in plan.backups}
        self.assertEqual(backups[self.source].read_bytes(), original_data)
        self.assertEqual(backups[self.header].read_bytes(), original_text)
        self.assertEqual(self.header.read_bytes(), original_text)
        self.assertTrue(all(not write.temporary.exists() for write in plan.writes))

    def test_external_change_and_rename_collision_are_rejected(self):
        plan = self.plan()
        with self.source.open("ab") as target:
            target.write(b"\n")
        with self.assertRaises(HeaderChangeFailure) as raised:
            execute_header_change(plan, self.payload)
        self.assertIn("changed since", str(raised.exception))
        self.assertFalse(any(backup.destination.exists() for backup in plan.backups))

        expected = associated_header_artifacts(self.source, "New", str(self.header))["selected"]["expected"]
        expected.write_text("do not overwrite", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.plan(align=True)
        self.assertEqual(expected.read_text(encoding="utf-8"), "do not overwrite")
        with self.assertRaises(ValueError):
            self.plan(username="../unsafe", align=True)

    def test_header_text_can_be_created_with_no_existing_file(self):
        self.header.unlink()
        plan = self.plan()
        self.assertEqual(len(plan.backups), 1)
        self.assertIn(f"CREATE: {self.header}", describe_header_change_plan(plan))
        execute_header_change(plan, self.payload)
        self.assertTrue(self.header.is_file())

    def test_partial_backup_is_removed_and_no_original_is_modified(self):
        original = self.source.read_bytes()
        plan = self.plan(save_text=False)

        def partial_copy(source, destination, length):
            del source, length
            destination.write(b"incomplete")
            raise OSError("backup failed")

        with patch("reactor_ui.adapters.header_changes.shutil.copyfileobj", side_effect=partial_copy):
            with self.assertRaises(HeaderChangeFailure) as raised:
                execute_header_change(plan, self.payload)
        self.assertIn("backup failed", str(raised.exception))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(raised.exception.backups, ())
        self.assertFalse(plan.backups[0].destination.exists())

    def test_data_and_header_hardlinks_are_rejected(self):
        self.header.unlink()
        os.link(self.source, self.header)
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "aliases"):
            self.plan()
        self.assertEqual(self.source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
