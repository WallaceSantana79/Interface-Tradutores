from __future__ import annotations

import json
import shutil
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from translator_core.orchestrator import exportar, importar, pre_validar_importacao
from translator_core.unity_core import (
    _patch_catalog_crc_for_bundle,
    clear_unity_selected_table_for_project,
    detectar_tabelas_idioma_unity,
    get_unity_selected_table_for_project,
    set_unity_selected_table_for_project,
)


class UnityCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"unity_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "workspace"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detect_unity_language_tables_with_known_and_unknown(self) -> None:
        project = self.root / "UnityTables"
        aa_dir = project / "UnityTables_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
        aa_dir.mkdir(parents=True, exist_ok=True)
        (project / "UnityTables.exe").write_text("stub", encoding="utf-8")
        (aa_dir / "localization-string-tables-english_assets_all.bundle").write_text("stub", encoding="utf-8")
        (aa_dir / "localization-string-tables-russian_assets_all.bundle").write_text("stub", encoding="utf-8")
        (aa_dir / "localization-custom_assets_all.bundle").write_text("stub", encoding="utf-8")

        candidates, warnings = detectar_tabelas_idioma_unity(project)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(any("English" in candidate.label for candidate in candidates))
        self.assertTrue(any("Russian" in candidate.label for candidate in candidates))
        self.assertTrue(any("Desconhecido" in candidate.label for candidate in candidates))
        self.assertFalse(any("inválida" in warning.lower() for warning in warnings))

    def test_selected_unity_table_is_persisted_in_core_state(self) -> None:
        project = self.root / "UnitySelectionState"
        project.mkdir(parents=True, exist_ok=True)

        set_unity_selected_table_for_project(project, "bundle::foo.bundle")
        self.assertEqual(get_unity_selected_table_for_project(project), "bundle::foo.bundle")

        clear_unity_selected_table_for_project(project)
        self.assertIsNone(get_unity_selected_table_for_project(project))

    def test_unity_export_and_import_supported_formats(self) -> None:
        project = self.root / "MyUnityGame"
        data_dir = project / "MyUnityGame_Data"
        streaming_dir = data_dir / "StreamingAssets" / "Loc"
        streaming_dir.mkdir(parents=True, exist_ok=True)
        (project / "MyUnityGame.exe").write_text("stub", encoding="utf-8")

        json_path = streaming_dir / "dialog.json"
        json_path.write_text(
            json.dumps(
                {
                    "title": "Welcome hero",
                    "imagePath": "img/characters/Hero.png",
                    "portraitPath": "img/characters/Hero.jpg",
                    "fxPath": "img/effects/Blink.gif",
                    "videoPath": "video/intro.mp4",
                    "description": "Choose your path",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        csv_path = streaming_dir / "ui.csv"
        csv_path.write_text(
            "key,text,path\nbtn_play,Play,img/ui/play.png\nbtn_quit,Quit,img/ui/quit.png\n",
            encoding="utf-8",
        )

        txt_path = streaming_dir / "tips.txt"
        txt_path.write_text("Open the map\nUse potion\n", encoding="utf-8")

        xml_path = streaming_dir / "messages.xml"
        xml_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><root><line>Hello adventurer</line></root>',
            encoding="utf-8",
        )

        yaml_path = streaming_dir / "settings.yaml"
        yaml_path.write_text(
            'title: "Main Menu"\n'
            'hint: Press Start\n'
            "assetPath: img/system/window.png\n"
            "options: [one, two]\n",
            encoding="utf-8",
        )

        export_result = exportar("unity", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)
        self.assertIn("MyUnityGame_Data", export_result.message)

        translated = self.workspace / "unity" / "unity_translations.txt"
        self.assertTrue(translated.exists())
        content = translated.read_text(encoding="utf-8")
        self.assertIn("Welcome hero", content)
        self.assertIn("Play", content)
        self.assertIn("Open the map", content)
        self.assertIn("Hello adventurer", content)
        self.assertIn("Main Menu", content)
        self.assertNotIn("img/characters/Hero.png", content)
        self.assertNotIn("img/characters/Hero.jpg", content)
        self.assertNotIn("img/effects/Blink.gif", content)
        self.assertNotIn("video/intro.mp4", content)
        self.assertNotIn("img/ui/play.png", content)

        content = content.replace("Welcome hero", "Bem-vindo heroi")
        content = content.replace("Choose your path", "Escolha seu caminho")
        content = content.replace("Play", "Jogar")
        content = content.replace("Quit", "Sair")
        content = content.replace("Open the map", "Abra o mapa")
        content = content.replace("Use potion", "Use pocao")
        content = content.replace("Hello adventurer", "Ola aventureiro")
        content = content.replace("Main Menu", "Menu Principal")
        content = content.replace("Press Start", "Pressione Iniciar")
        translated.write_text(content, encoding="utf-8")

        pre = pre_validar_importacao("unity", project, self.workspace, translated)
        self.assertTrue(pre.success, pre.message)

        import_result = importar("unity", project, self.workspace, translated, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed_json = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed_json["title"], "Bem-vindo heroi")
        self.assertEqual(parsed_json["description"], "Escolha seu caminho")
        self.assertEqual(parsed_json["imagePath"], "img/characters/Hero.png")
        self.assertEqual(parsed_json["portraitPath"], "img/characters/Hero.jpg")
        self.assertEqual(parsed_json["fxPath"], "img/effects/Blink.gif")
        self.assertEqual(parsed_json["videoPath"], "video/intro.mp4")

        csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
        self.assertIn("btn_play,Jogar,img/ui/play.png", csv_lines)
        self.assertIn("btn_quit,Sair,img/ui/quit.png", csv_lines)

        txt_lines = txt_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(txt_lines, ["Abra o mapa", "Use pocao"])

        xml_root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
        self.assertEqual(xml_root.find("line").text, "Ola aventureiro")

        yaml_content = yaml_path.read_text(encoding="utf-8")
        self.assertIn('title: "Menu Principal"', yaml_content)
        self.assertIn("hint: Pressione Iniciar", yaml_content)
        self.assertIn("options: [one, two]", yaml_content)

    def test_unity_json_multiline_roundtrip_without_translation_keeps_text(self) -> None:
        project = self.root / "UnityMultiline"
        data_dir = project / "UnityMultiline_Data" / "StreamingAssets" / "Loc"
        data_dir.mkdir(parents=True, exist_ok=True)
        (project / "UnityMultiline.exe").write_text("stub", encoding="utf-8")

        json_path = data_dir / "dialog.json"
        original = "Line one\\nLine two"
        json_path.write_text(
            json.dumps({"text": original}, ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("unity", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated = self.workspace / "unity" / "unity_translations.txt"
        pre = pre_validar_importacao("unity", project, self.workspace, translated)
        self.assertTrue(pre.success, pre.message)

        import_result = importar("unity", project, self.workspace, translated, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        after = json.loads(json_path.read_text(encoding="utf-8"))["text"]
        self.assertEqual(after, original)

    def test_unity_import_skips_item_on_count_mismatch_for_safety(self) -> None:
        project = self.root / "UnityMismatch"
        data_dir = project / "UnityMismatch_Data" / "StreamingAssets" / "Loc"
        data_dir.mkdir(parents=True, exist_ok=True)
        (project / "UnityMismatch.exe").write_text("stub", encoding="utf-8")

        json_path = data_dir / "dialog.json"
        json_path.write_text(
            json.dumps({"text": "Hello adventurer"}, ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("unity", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated = self.workspace / "unity" / "unity_translations.txt"
        content = translated.read_text(encoding="utf-8")
        content = content.replace('"Hello adventurer"\n', '"Hello adventurer"\n"EXTRA_LINE"\n')
        translated.write_text(content, encoding="utf-8")

        import_result = importar("unity", project, self.workspace, translated, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)
        self.assertTrue(any("ignorada por segurança" in warning for warning in import_result.warnings))

        parsed = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["text"], "Hello adventurer")

    def test_unity_resolve_data_dir_fallback_warns_when_multiple(self) -> None:
        project = self.root / "UnityFallback"
        project.mkdir(parents=True, exist_ok=True)
        (project / "UnityFallback.exe").write_text("stub", encoding="utf-8")

        alpha_data = project / "Alpha_Data"
        beta_data = project / "Beta_Data"
        alpha_data.mkdir(parents=True)
        beta_data.mkdir(parents=True)
        (alpha_data / "loc.txt").write_text("Alpha text\n", encoding="utf-8")
        (beta_data / "loc.txt").write_text("Beta text\n", encoding="utf-8")

        result = exportar("unity", project, self.workspace)
        self.assertTrue(result.success, result.message)
        self.assertTrue(any("múltiplas pastas *_Data" in warning for warning in result.warnings))
        self.assertIn("Alpha_Data", result.message)

    def test_unity_backup_includes_data_subfolder_files(self) -> None:
        project = self.root / "BackupUnity"
        data_dir = project / "BackupUnity_Data" / "StreamingAssets" / "Texts"
        data_dir.mkdir(parents=True, exist_ok=True)
        (project / "BackupUnity.exe").write_text("stub", encoding="utf-8")

        json_path = data_dir / "dialog.json"
        json_path.write_text(json.dumps({"text": "Hello there"}, ensure_ascii=False), encoding="utf-8")

        export_result = exportar("unity", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated = self.workspace / "unity" / "unity_translations.txt"
        translated.write_text(
            translated.read_text(encoding="utf-8").replace("Hello there", "Ola"),
            encoding="utf-8",
        )

        import_result = importar("unity", project, self.workspace, translated, criar_backup=True)
        self.assertTrue(import_result.success, import_result.message)
        self.assertIn("Backup criado em:", import_result.message)

        backup_root = self.workspace / "unity" / "backups"
        backups = sorted(backup_root.glob("unity_*"))
        self.assertTrue(backups)
        latest_backup = backups[-1]
        self.assertTrue(
            (latest_backup / "BackupUnity_Data" / "StreamingAssets" / "Texts" / "dialog.json").exists()
        )

    def test_unity_export_fails_when_no_supported_text_files(self) -> None:
        project = self.root / "NoUnityText"
        data_dir = project / "NoUnityText_Data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (project / "NoUnityText.exe").write_text("stub", encoding="utf-8")
        (data_dir / "globalgamemanagers.assets").write_text("binary", encoding="utf-8")

        result = exportar("unity", project, self.workspace)
        self.assertFalse(result.success)
        self.assertIn("Nenhum texto elegível", result.message)

    def test_unity_export_warns_when_bundle_selected_without_unitypy(self) -> None:
        project = self.root / "UnityBundleNoLib"
        data_dir = project / "UnityBundleNoLib_Data"
        aa_dir = data_dir / "StreamingAssets" / "aa" / "StandaloneWindows64"
        text_dir = data_dir / "StreamingAssets" / "Texts"
        aa_dir.mkdir(parents=True, exist_ok=True)
        text_dir.mkdir(parents=True, exist_ok=True)
        (project / "UnityBundleNoLib.exe").write_text("stub", encoding="utf-8")
        (text_dir / "dialog.txt").write_text("Hello\n", encoding="utf-8")

        bundle_name = "localization-string-tables-english_assets_all.bundle"
        (aa_dir / bundle_name).write_text("dummy bundle", encoding="utf-8")

        candidate_id = f"bundle::StreamingAssets/aa/StandaloneWindows64/{bundle_name}"
        set_unity_selected_table_for_project(project, candidate_id)
        self.addCleanup(lambda: clear_unity_selected_table_for_project(project))

        with patch("translator_core.unity_core.UnityPy", None):
            result = exportar("unity", project, self.workspace)
        self.assertTrue(result.success, result.message)
        self.assertTrue(any("UnityPy" in warning for warning in result.warnings))

    def test_patch_catalog_crc_for_bundle_updates_expected_slot(self) -> None:
        data_dir = self.root / "CatalogPatch" / "Game_Data"
        aa_dir = data_dir / "StreamingAssets" / "aa"
        aa_dir.mkdir(parents=True, exist_ok=True)
        catalog_path = aa_dir / "catalog.bin"

        bundle_name = "localization-string-tables-english_assets_all.bundle"
        old_crc = 0xF99F5E01
        new_crc = 0x3C2DBFA1

        prefix = b"header_"
        body = (
            bundle_name.encode("utf-8")
            + (b"\x00" * 60)
            + old_crc.to_bytes(4, "little")
            + b"_tail"
        )
        catalog_path.write_bytes(prefix + body)

        patched, msg = _patch_catalog_crc_for_bundle(
            data_dir,
            f"StreamingAssets/aa/StandaloneWindows64/{bundle_name}",
            new_crc,
        )
        self.assertTrue(patched, msg)
        updated = catalog_path.read_bytes()
        crc_pos = len(prefix) + len(bundle_name) + 60
        self.assertEqual(int.from_bytes(updated[crc_pos : crc_pos + 4], "little"), new_crc)


if __name__ == "__main__":
    unittest.main()
