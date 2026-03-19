from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class WorkspacePathTests(unittest.TestCase):
    def test_workspace_root_development_mode(self) -> None:
        expected = app.APP_DIR / "workspace"
        self.assertEqual(app.resolve_workspace_root(frozen=False), expected)

    def test_workspace_root_frozen_windows(self) -> None:
        fake_local_app_data = r"C:\Users\Tester\AppData\Local"
        with patch("platform.system", return_value="Windows"):
            with patch.dict(os.environ, {"LOCALAPPDATA": fake_local_app_data}, clear=False):
                root = app.resolve_workspace_root(frozen=True)
        expected = Path(fake_local_app_data) / "InterfaceTradutores" / "workspace"
        self.assertEqual(root, expected)


if __name__ == "__main__":
    unittest.main()
