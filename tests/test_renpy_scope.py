from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from translator_core.orchestrator import exportar, importar


class RenpyScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"renpy_scope_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "workspace"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_root_project_does_not_touch_renpy_common(self) -> None:
        project = self.root / "game_root"
        game_dir = project / "game"
        tl_dir = game_dir / "tl" / "portuguese"
        common_dir = project / "renpy" / "common"
        tl_dir.mkdir(parents=True)
        common_dir.mkdir(parents=True)

        script_path = tl_dir / "script.rpy"
        script_path.write_text('# "Hello [player]"\ne "Hello [player]"\n', encoding="utf-8-sig")

        game_script_path = game_dir / "script.rpy"
        game_script_original = '# "GAME ROOT"\ne "GAME ROOT"\n'
        game_script_path.write_text(game_script_original, encoding="utf-8-sig")

        common_path = common_dir / "00library.rpy"
        common_original = '# Copyright (the "Software")\nlabel x:\n    return\n'
        common_path.write_text(common_original, encoding="utf-8-sig")

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        translated_path.write_text(
            content.replace("Hello [PLACEHOLDER_0]", "Oi [PLACEHOLDER_0]"),
            encoding="utf-8-sig",
        )

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_script = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('"Oi [player]"', final_script)
        self.assertEqual(game_script_path.read_text(encoding="utf-8-sig"), game_script_original)
        self.assertEqual(common_path.read_text(encoding="utf-8-sig"), common_original)

    def test_duplicate_filenames_are_mapped_by_relative_path(self) -> None:
        project = self.root / "game_dupes"
        (project / "game" / "tl" / "portuguese" / "route_a").mkdir(parents=True)
        (project / "game" / "tl" / "portuguese" / "route_b").mkdir(parents=True)

        file_a = project / "game" / "tl" / "portuguese" / "route_a" / "script.rpy"
        file_b = project / "game" / "tl" / "portuguese" / "route_b" / "script.rpy"
        file_a.write_text('# "Hello A"\na "Hello A"\n', encoding="utf-8-sig")
        file_b.write_text('# "Hello B"\nb "Hello B"\n', encoding="utf-8-sig")

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        content = content.replace("Hello A", "Oi A")
        content = content.replace("Hello B", "Oi B")
        translated_path.write_text(content, encoding="utf-8-sig")

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        self.assertIn('"Oi A"', file_a.read_text(encoding="utf-8-sig"))
        self.assertIn('"Oi B"', file_b.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
