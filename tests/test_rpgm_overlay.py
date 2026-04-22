from __future__ import annotations

import json
import re
import shutil
import unittest
import uuid
from pathlib import Path

from translator_core.orchestrator import exportar, importar
from translator_core.rpgm_core import OVERLAY_PLUGIN_FILENAME, detectar_runtime_rpgm, instalar_overlay_rpgm


class RpgmOverlayAndRecursiveTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"overlay_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "workspace"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rpgm_recursive_generic_extraction_for_plugin_json(self) -> None:
        project = self.root / "rpgm_plugin_recursive"
        plugin_json = project / "www" / "data" / "PKD_PhoneMenu" / "ShopApp" / "settings.json"
        plugin_json.parent.mkdir(parents=True)
        plugin_json.write_text(
            json.dumps(
                {
                    "ui": {
                        "headerText": "Open Store",
                        "buttons": [
                            {"label": "Buy now"},
                            {"label": "Sell items"},
                        ],
                        "assets": {
                            "icon": "img/system/IconSet.png",
                            "portrait": "img/portraits/Hero.jpg",
                            "effect": "img/effects/Blink.gif",
                            "trailer": "movies/intro.mp4",
                        },
                    },
                    "meta": {"plugin": "PKD_PhoneMenu"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        self.assertIn("Open Store", content)
        self.assertIn("Buy now", content)
        self.assertIn("Sell items", content)
        self.assertNotIn("img/system/IconSet.png", content)
        self.assertNotIn("img/portraits/Hero.jpg", content)
        self.assertNotIn("img/effects/Blink.gif", content)
        self.assertNotIn("movies/intro.mp4", content)

        translated_path.write_text(
            content.replace("Open Store", "Abrir loja")
            .replace("Buy now", "Comprar agora")
            .replace("Sell items", "Vender itens"),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(plugin_json.read_text(encoding="utf-8"))
        self.assertEqual(parsed["ui"]["headerText"], "Abrir loja")
        self.assertEqual(parsed["ui"]["buttons"][0]["label"], "Comprar agora")
        self.assertEqual(parsed["ui"]["buttons"][1]["label"], "Vender itens")
        self.assertEqual(parsed["ui"]["assets"]["icon"], "img/system/IconSet.png")
        self.assertEqual(parsed["ui"]["assets"]["portrait"], "img/portraits/Hero.jpg")
        self.assertEqual(parsed["ui"]["assets"]["effect"], "img/effects/Blink.gif")
        self.assertEqual(parsed["ui"]["assets"]["trailer"], "movies/intro.mp4")

    def test_rpgm_aggressive_filter_skips_map_preset_style_fields(self) -> None:
        project = self.root / "rpgm_aggressive_filter"
        file_path = project / "www" / "data" / "PluginData.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(
            json.dumps(
                {
                    "mapPreset": "Debug Room",
                    "debugContainerName": "Village Container",
                    "headerText": "Main Menu",
                    "optionLabel": "Start",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        self.assertIn("Main Menu", content)
        self.assertIn("Start", content)
        self.assertNotIn("Debug Room", content)
        self.assertNotIn("Village Container", content)

    def test_rpgm_legacy_map_ambiguous_filename_generates_warning(self) -> None:
        project = self.root / "rpgm_legacy_ambiguous"
        file_a = project / "www" / "data" / "FolderA" / "config.json"
        file_b = project / "www" / "data" / "FolderB" / "config.json"
        file_a.parent.mkdir(parents=True)
        file_b.parent.mkdir(parents=True)
        file_a.write_text(json.dumps({"title": "Alpha"}, ensure_ascii=False), encoding="utf-8")
        file_b.write_text(json.dumps({"title": "Beta"}, ensure_ascii=False), encoding="utf-8")

        workspace_rpgm = self.workspace / "rpgm"
        workspace_rpgm.mkdir(parents=True)
        (workspace_rpgm / "rpgm_translations.txt").write_text(
            "=== ARQUIVO_000 ===\nTitulo traduzido\n\n",
            encoding="utf-8",
        )
        (workspace_rpgm / "rpgm_placeholders.txt").write_text(
            "=== ARQUIVO_000 ===\n\n\n",
            encoding="utf-8",
        )
        (workspace_rpgm / "rpgm_mapa_arquivos.json").write_text(
            json.dumps({"ARQUIVO_000": "config.json"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        import_result = importar(
            "rpgm",
            project,
            self.workspace,
            workspace_rpgm / "rpgm_translations.txt",
            criar_backup=False,
        )
        self.assertTrue(import_result.success, import_result.message)
        self.assertTrue(any("ambíguo" in warning for warning in import_result.warnings))

        parsed_a = json.loads(file_a.read_text(encoding="utf-8"))
        parsed_b = json.loads(file_b.read_text(encoding="utf-8"))
        self.assertEqual(parsed_a["title"], "Alpha")
        self.assertEqual(parsed_b["title"], "Beta")

    def test_overlay_installation_is_idempotent_on_mz(self) -> None:
        project = self.root / "rpgm_overlay_mz"
        js_dir = project / "www" / "js"
        plugins_dir = js_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        (js_dir / "rmmz_core.js").write_text("// mz runtime", encoding="utf-8")
        (js_dir / "plugins.js").write_text("var $plugins = [];\n", encoding="utf-8")

        self.assertEqual(detectar_runtime_rpgm(project), "mz")

        ok_first, message_first = instalar_overlay_rpgm(project)
        ok_second, message_second = instalar_overlay_rpgm(project)
        self.assertTrue(ok_first, message_first)
        self.assertTrue(ok_second, message_second)

        plugin_file = plugins_dir / OVERLAY_PLUGIN_FILENAME
        self.assertTrue(plugin_file.exists())
        plugin_source = plugin_file.read_text(encoding="utf-8")
        self.assertNotIn(".trimEnd(", plugin_source)
        self.assertNotIn(".trimStart(", plugin_source)
        self.assertIn("bindOverlayInputGuards", plugin_source)
        self.assertIn("stopPropagation", plugin_source)

        plugins_js = (js_dir / "plugins.js").read_text(encoding="utf-8")
        match = re.search(r"\$plugins\s*=\s*(\[[\s\S]*\])\s*;", plugins_js)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1) if match else "[]")
        entries = [item for item in payload if item.get("name") == "InterfaceTradutoresOverlay"]
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].get("status"))

    def test_rpgm_generic_extraction_does_not_translate_picture_names_in_events(self) -> None:
        project = self.root / "rpgm_event_picture_name"
        map_path = project / "www" / "data" / "Map001.json"
        map_path.parent.mkdir(parents=True)
        map_path.write_text(
            json.dumps(
                {
                    "events": [
                        None,
                        {
                            "pages": [
                                {
                                    "list": [
                                        {
                                            "code": 231,
                                            "parameters": [1, "Aviso Legal do PC", 0, 0, 0, 100, 100, 255, 0],
                                        },
                                        {
                                            "code": 401,
                                            "parameters": ["Linha de diálogo válida"],
                                        },
                                    ]
                                }
                            ]
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        self.assertIn("Linha de diálogo válida", content)
        self.assertNotIn("Aviso Legal do PC", content)

        translated_path.write_text(
            content.replace("Linha de diálogo válida", "Linha traduzida"),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(map_path.read_text(encoding="utf-8"))
        commands = parsed["events"][1]["pages"][0]["list"]
        self.assertEqual(commands[0]["parameters"][1], "Aviso Legal do PC")
        self.assertEqual(commands[1]["parameters"][0], "Linha traduzida")

    def test_rpgm_script_phrase_filter_skips_technical_and_keeps_user_text(self) -> None:
        project = self.root / "rpgm_script_filter"
        map_path = project / "www" / "data" / "Map001.json"
        map_path.parent.mkdir(parents=True)
        map_path.write_text(
            json.dumps(
                {
                    "events": [
                        None,
                        {
                            "pages": [
                                {
                                    "list": [
                                        {
                                            "code": 355,
                                            "parameters": [
                                                'this.mapPreset("Debug Room"); $gameMessage.add("Você quer continuar?"); this.cmd("center");'
                                            ],
                                        }
                                    ]
                                }
                            ]
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        self.assertIn("Você quer continuar?", content)
        self.assertNotIn("Debug Room", content)
        self.assertNotIn("center", content)

    def test_rpgm_generic_extraction_skips_character_name_asset_fields(self) -> None:
        project = self.root / "rpgm_actor_assets"
        actors_path = project / "data" / "Actors.json"
        actors_path.parent.mkdir(parents=True)
        actors_path.write_text(
            json.dumps(
                [
                    None,
                    {
                        "name": "Truck Driver",
                        "characterName": "!$Truck",
                        "faceName": "Actor1",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        self.assertIn("Truck Driver", content)
        self.assertNotIn("!$Truck", content)
        self.assertNotIn("Actor1", content)

        translated_path.write_text(content.replace("Truck Driver", "Motorista"), encoding="utf-8")

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(actors_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[1]["name"], "Motorista")
        self.assertEqual(parsed[1]["characterName"], "!$Truck")
        self.assertEqual(parsed[1]["faceName"], "Actor1")


if __name__ == "__main__":
    unittest.main()
