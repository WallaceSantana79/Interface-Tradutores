from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from translator_core.orchestrator import exportar, importar, pre_validar_importacao


class CoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"core_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "workspace"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_renpy_export_and_import(self) -> None:
        project = self.root / "renpy_game"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# "Hello [player]"\n'
            'e "Hello [player]"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        self.assertTrue(translated_path.exists())
        content = translated_path.read_text(encoding="utf-8-sig")
        translated_path.write_text(
            content.replace("Hello [PLACEHOLDER_0]", "Oi [PLACEHOLDER_0]"),
            encoding="utf-8-sig",
        )

        pre = pre_validar_importacao("renpy", project, self.workspace, translated_path)
        self.assertTrue(pre.success, pre.message)

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('"Oi [player]"', final_text)

    def test_rpgm_export_and_import(self) -> None:
        project = self.root / "rpgm_data"
        project.mkdir(parents=True)

        actors_path = project / "Actors.json"
        actors_path.write_text(
            json.dumps([None, {"name": "Hero", "description": "Welcome \\N[1]"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        self.assertTrue(translated_path.exists())
        content = translated_path.read_text(encoding="utf-8")
        content = content.replace("Hero", "Heroi")
        content = content.replace("Welcome [PLACEHOLDER_0]", "Bem-vindo [PLACEHOLDER_0]")
        translated_path.write_text(content, encoding="utf-8")

        pre = pre_validar_importacao("rpgm", project, self.workspace, translated_path)
        self.assertTrue(pre.success, pre.message)

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(actors_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[1]["name"], "Heroi")
        self.assertEqual(parsed[1]["description"], "Bem-vindo \\N[1]")

    def test_pre_validation_warns_on_count_mismatch(self) -> None:
        project = self.root / "renpy_game_warning"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# "Hello [player]"\n'
            'e "Hello [player]"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        placeholders_path = self.workspace / "renpy" / "all_placeholders.txt"
        placeholders_path.write_text("=== ARQUIVO_000 ===\n", encoding="utf-8-sig")

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        pre = pre_validar_importacao("renpy", project, self.workspace, translated_path)
        self.assertTrue(pre.success, pre.message)
        self.assertGreater(len(pre.warnings), 0)


if __name__ == "__main__":
    unittest.main()
