"""Production entry-point and Windows launcher smoke tests."""

from __future__ import annotations

import os
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_python_entry_point_calls_qt_main_and_propagates_exit_code(self):
        with patch("reactor_ui.app.main", return_value=23) as main:
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT / "reactor_plotter.py"), run_name="__main__")
        main.assert_called_once_with()
        self.assertEqual(result.exception.code, 23)

    @unittest.skipUnless(
        os.name == "nt" and (ROOT / ".venv" / "Scripts" / "python.exe").is_file(),
        "Windows launcher smoke test requires the existing project virtual environment",
    )
    def test_windows_batch_launches_qt_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory(prefix="reactor_launcher_") as folder:
            site = Path(folder) / "sitecustomize.py"
            site.write_text(
                "from PySide6.QtCore import QTimer\n"
                "from PySide6.QtWidgets import QApplication\n"
                "_application = QApplication([])\n"
                "QTimer.singleShot(750, _application.quit)\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in (folder, env.get("PYTHONPATH", "")) if part
            )
            result = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ROOT / "run_gui.bat")],
                cwd=folder,
                env=env,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Launching Reactor Pressure Data Analyzer", result.stdout)


if __name__ == "__main__":
    unittest.main()
