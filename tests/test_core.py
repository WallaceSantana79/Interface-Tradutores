from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from translator_core.orchestrator import exportar, importar, pre_validar_importacao


class CoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"core_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "workspace"
        self.env_patcher = patch.dict(
            os.environ,
            {"INTERFACE_TRADUTORES_MEMORY_DIR": str(self.root / "translation_memory")},
        )
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()
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

    def test_renpy_translation_memory_exports_only_new_lines_and_imports_full_script(self) -> None:
        memory_root = self.root / "translation_memory"
        with patch.dict(os.environ, {"INTERFACE_TRADUTORES_MEMORY_DIR": str(memory_root)}):
            project_v04 = self.root / "Memory Game v0.4 pc"
            tl_v04 = project_v04 / "game" / "tl" / "portuguese"
            tl_v04.mkdir(parents=True)
            script_v04 = tl_v04 / "script.rpy"
            script_v04.write_text(
                '# e "Hello [player]"\n'
                'e "Hello [player]"\n'
                '# e "Good night"\n'
                'e "Good night"\n',
                encoding="utf-8-sig",
            )

            export_result = exportar("renpy", project_v04, self.workspace)
            self.assertTrue(export_result.success, export_result.message)
            translated_path = self.workspace / "renpy" / "all_translations.txt"
            content = translated_path.read_text(encoding="utf-8-sig")
            translated_path.write_text(
                content.replace("Hello [PLACEHOLDER_0]", "Olá [PLACEHOLDER_0]").replace(
                    "Good night", "Boa noite"
                ),
                encoding="utf-8-sig",
            )
            import_result = importar("renpy", project_v04, self.workspace, translated_path, criar_backup=False)
            self.assertTrue(import_result.success, import_result.message)

            project_v05 = self.root / "Memory Game v0.5 pc"
            tl_v05 = project_v05 / "game" / "tl" / "portuguese"
            tl_v05.mkdir(parents=True)
            script_v05 = tl_v05 / "script.rpy"
            script_v05.write_text(
                '# e "Hello [player]"\n'
                'e "Hello [player]"\n'
                '# e "New middle line"\n'
                'e "New middle line"\n'
                '# e "Good night"\n'
                'e "Good night"\n',
                encoding="utf-8-sig",
            )

            export_result = exportar("renpy", project_v05, self.workspace)
            self.assertTrue(export_result.success, export_result.message)
            exported = translated_path.read_text(encoding="utf-8-sig")
            self.assertIn("New middle line", exported)
            self.assertNotIn("Hello [PLACEHOLDER_0]", exported)
            self.assertNotIn("Good night", exported)

            translated_path.write_text(
                exported.replace("New middle line", "Nova fala no meio"),
                encoding="utf-8-sig",
            )
            pre = pre_validar_importacao("renpy", project_v05, self.workspace, translated_path)
            self.assertTrue(pre.success, pre.message)

            import_result = importar("renpy", project_v05, self.workspace, translated_path, criar_backup=False)
            self.assertTrue(import_result.success, import_result.message)
            final_text = script_v05.read_text(encoding="utf-8-sig")
            self.assertIn('e "Olá [player]"', final_text)
            self.assertIn('e "Nova fala no meio"', final_text)
            self.assertIn('e "Boa noite"', final_text)

            memory_path = memory_root / "renpy" / "memory-game.json"
            memory = json.loads(memory_path.read_text(encoding="utf-8"))
            entry = next(entry for entry in memory["entries"].values() if entry["source"] == "Good night")
            self.assertEqual(entry["translation"], "Boa noite")
            self.assertIn("last_relpath", entry)
            self.assertGreaterEqual(entry["use_count"], 2)
            self.assertIn("created_at", entry)
            self.assertIn("updated_at", entry)

    def test_renpy_translation_memory_all_reused_allows_empty_translation_txt(self) -> None:
        memory_root = self.root / "translation_memory_all_reused"
        with patch.dict(os.environ, {"INTERFACE_TRADUTORES_MEMORY_DIR": str(memory_root)}):
            project = self.root / "All Reused Game"
            tl_dir = project / "game" / "tl" / "portuguese"
            tl_dir.mkdir(parents=True)
            script_path = tl_dir / "script.rpy"
            script_path.write_text('# e "Repeat me"\ne "Repeat me"\n', encoding="utf-8-sig")

            export_result = exportar("renpy", project, self.workspace)
            self.assertTrue(export_result.success, export_result.message)
            translated_path = self.workspace / "renpy" / "all_translations.txt"
            translated_path.write_text(
                translated_path.read_text(encoding="utf-8-sig").replace("Repeat me", "Repita comigo"),
                encoding="utf-8-sig",
            )
            import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
            self.assertTrue(import_result.success, import_result.message)

            script_path.write_text('# e "Repeat me"\ne "Repeat me"\n', encoding="utf-8-sig")
            export_result = exportar("renpy", project, self.workspace)
            self.assertTrue(export_result.success, export_result.message)
            exported = translated_path.read_text(encoding="utf-8-sig")
            self.assertIn("=== ARQUIVO_000 ===", exported)
            self.assertNotIn("Repeat me", exported)

            pre = pre_validar_importacao("renpy", project, self.workspace, translated_path)
            self.assertTrue(pre.success, pre.message)
            import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
            self.assertTrue(import_result.success, import_result.message)
            self.assertIn('e "Repita comigo"', script_path.read_text(encoding="utf-8-sig"))

    def test_renpy_export_can_disable_translation_memory(self) -> None:
        memory_root = self.root / "translation_memory_disabled"
        with patch.dict(os.environ, {"INTERFACE_TRADUTORES_MEMORY_DIR": str(memory_root)}):
            project = self.root / "Memory Disabled Game"
            tl_dir = project / "game" / "tl" / "portuguese"
            tl_dir.mkdir(parents=True)
            script_path = tl_dir / "script.rpy"
            script_path.write_text('# e "No cache"\ne "No cache"\n', encoding="utf-8-sig")

            export_result = exportar("renpy", project, self.workspace, use_translation_memory=False)
            self.assertTrue(export_result.success, export_result.message)
            exported = (self.workspace / "renpy" / "all_translations.txt").read_text(encoding="utf-8-sig")
            self.assertIn("No cache", exported)
            self.assertFalse((self.workspace / "renpy" / "renpy_export_plan.json").exists())

            translated_path = self.workspace / "renpy" / "all_translations.txt"
            translated_path.write_text(exported.replace("No cache", "Sem memoria"), encoding="utf-8-sig")
            import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
            self.assertTrue(import_result.success, import_result.message)
            self.assertIn('e "Sem memoria"', script_path.read_text(encoding="utf-8-sig"))

    def test_renpy_rejects_memory_plan_from_another_game(self) -> None:
        first_project = self.root / "First Game"
        first_tl_dir = first_project / "game" / "tl" / "portuguese"
        first_tl_dir.mkdir(parents=True)
        (first_tl_dir / "script.rpy").write_text('# e "First"\ne "First"\n', encoding="utf-8-sig")
        self.assertTrue(exportar("renpy", first_project, self.workspace).success)

        second_project = self.root / "Second Game"
        second_tl_dir = second_project / "game" / "tl" / "portuguese"
        second_tl_dir.mkdir(parents=True)
        (second_tl_dir / "script.rpy").write_text('# e "Second"\ne "Second"\n', encoding="utf-8-sig")

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        import_result = importar("renpy", second_project, self.workspace, translated_path, criar_backup=False)
        self.assertFalse(import_result.success)
        self.assertIn("não pertence ao projeto", import_result.message)

    def test_renpy_voice_comments_do_not_create_new_translation_entries(self) -> None:
        project = self.root / "renpy_voice_comments"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# voice "audio/line.ogg"\n'
            '# e "Already translated"\n'
            'voice "audio/line.ogg"\n'
            'e "Already translated"\n',
            encoding="utf-8-sig",
        )

        first_export = exportar("renpy", project, self.workspace)
        self.assertTrue(first_export.success, first_export.message)
        translated_path = self.workspace / "renpy" / "all_translations.txt"
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8-sig").replace("Already translated", "Ja traduzida"),
            encoding="utf-8-sig",
        )
        self.assertTrue(importar("renpy", project, self.workspace, translated_path, criar_backup=False).success)

        script_path.write_text(
            '# voice "audio/line.ogg"\n'
            '# e "Already translated"\n'
            'voice "audio/line.ogg"\n'
            'e "Already translated"\n',
            encoding="utf-8-sig",
        )
        second_export = exportar("renpy", project, self.workspace)
        self.assertTrue(second_export.success, second_export.message)
        self.assertIn("0 nova(s)", second_export.warnings[0])
        self.assertEqual(
            (self.workspace / "renpy" / "all_translations.txt").read_text(encoding="utf-8-sig"),
            "=== ARQUIVO_000 ===\n\n\n",
        )

    def test_renpy_preserves_technical_asset_paths_inside_translated_line(self) -> None:
        project = self.root / "renpy_assets_in_line"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# "Look images/photos/photo.png now"\n'
            'e "Look images/photos/photo.png now"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        self.assertNotIn("images/photos/photo.png", content)
        translated_path.write_text(
            content.replace("Look [PLACEHOLDER_0] now", "Olhe [PLACEHOLDER_0] agora"),
            encoding="utf-8-sig",
        )

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('"Olhe images/photos/photo.png agora"', final_text)
        self.assertNotIn("imagens/fotos/foto", final_text)

    def test_renpy_preserves_pure_technical_media_refs(self) -> None:
        project = self.root / "renpy_media_refs"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# "Play intro.mp4 and sprite.gif"\n'
            'e "Play intro.mp4 and sprite.gif"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        self.assertNotIn("intro.mp4", content)
        self.assertNotIn("sprite.gif", content)
        translated_path.write_text(
            content.replace(
                "Play [PLACEHOLDER_0] and [PLACEHOLDER_1]",
                "Reproduza [PLACEHOLDER_0] e [PLACEHOLDER_1]",
            ),
            encoding="utf-8-sig",
        )

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('"Reproduza intro.mp4 e sprite.gif"', final_text)

    def test_renpy_restores_nested_image_tag_placeholders(self) -> None:
        project = self.root / "renpy_image_tag"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# oc_nvl "{image=gymlateralsmall.webp}"\n'
            'oc_nvl "{image=gymlateralsmall.webp}"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        self.assertIn("[PLACEHOLDER_", content)
        translated_path.write_text(content, encoding="utf-8-sig")

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('oc_nvl "{image=gymlateralsmall.webp}"', final_text)
        self.assertNotIn("[PLACEHOLDER_", final_text)

    def test_renpy_import_escapes_inner_double_quotes(self) -> None:
        project = self.root / "renpy_inner_quotes"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# mcm "Why people can\'t live without this \\"fucking\\" part though..."\n'
            'mcm "Why people can\'t live without this \\"fucking\\" part though..."\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        translated_path.write_text(
            content.replace(
                'Why people can\'t live without this \\"fucking\\" part though...',
                'Mas por que as pessoas não conseguem viver sem essa parte do "maldito" mesmo...',
            ),
            encoding="utf-8-sig",
        )

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('mcm "Mas por que as pessoas não conseguem viver sem essa parte do \\"maldito\\" mesmo..."', final_text)

    def test_renpy_import_fixes_even_backslashes_before_quotes(self) -> None:
        project = self.root / "renpy_even_slashes_quotes"
        tl_dir = project / "game" / "tl" / "portuguese"
        tl_dir.mkdir(parents=True)
        script_path = tl_dir / "script.rpy"
        script_path.write_text(
            '# mcm "Original line"\n'
            'mcm "Original line"\n',
            encoding="utf-8-sig",
        )

        export_result = exportar("renpy", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "renpy" / "all_translations.txt"
        content = translated_path.read_text(encoding="utf-8-sig")
        translated_path.write_text(
            content.replace("Original line", 'Texto com \\\\"aspas suspeitas\\\\" aqui'),
            encoding="utf-8-sig",
        )

        import_result = importar("renpy", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        final_text = script_path.read_text(encoding="utf-8-sig")
        self.assertIn('mcm "Texto com \\\\\\"aspas suspeitas\\\\\\" aqui"', final_text)

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

    def test_rpgm_preserves_wait_escape_codes(self) -> None:
        project = self.root / "rpgm_wait_codes"
        project.mkdir(parents=True)

        map_path = project / "Map001.json"
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
                                            "code": 401,
                                            "parameters": ["Sim\\_ eu também gosto..."],
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
        self.assertIn("Sim[PLACEHOLDER_0] eu também gosto...", content)
        translated_path.write_text(
            content.replace(
                "Sim[PLACEHOLDER_0] eu também gosto...",
                "Sim[PLACEHOLDER_0] eu também curto...",
            ),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(map_path.read_text(encoding="utf-8"))
        final_line = parsed["events"][1]["pages"][0]["list"][0]["parameters"][0]
        self.assertEqual(final_line, "Sim\\_ eu também curto...")

    def test_rpgm_accepts_project_root_with_www_data(self) -> None:
        project = self.root / "rpgm_root_www"
        data_dir = project / "www" / "data"
        data_dir.mkdir(parents=True)

        actors_path = data_dir / "Actors.json"
        actors_path.write_text(
            json.dumps([None, {"name": "Mage", "description": "Arcane"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)
        self.assertIn("www/data", export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace("Arcane", "Arcano"),
            encoding="utf-8",
        )

        pre = pre_validar_importacao("rpgm", project, self.workspace, translated_path)
        self.assertTrue(pre.success, pre.message)

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)
        self.assertIn("www/data", import_result.message)

        parsed = json.loads(actors_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[1]["description"], "Arcano")

    def test_rpgm_accepts_project_root_with_data(self) -> None:
        project = self.root / "rpgm_root_data"
        data_dir = project / "data"
        data_dir.mkdir(parents=True)

        actors_path = data_dir / "Actors.json"
        actors_path.write_text(
            json.dumps([None, {"name": "Knight", "description": "Shield"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)
        self.assertIn("data", export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace("Shield", "Escudo"),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(actors_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[1]["description"], "Escudo")

    def test_rpgm_processes_subfolders_and_stores_relative_paths(self) -> None:
        project = self.root / "rpgm_subfolders"
        data_dir = project / "www" / "data" / "PKD_PhoneMenu"
        data_dir.mkdir(parents=True)

        config_path = data_dir / "config.json"
        config_path.write_text(
            json.dumps([{"name": "Phone", "description": "Call mom"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        map_path = self.workspace / "rpgm" / "rpgm_mapa_arquivos.json"
        mapped = json.loads(map_path.read_text(encoding="utf-8"))
        self.assertIn("PKD_PhoneMenu/config.json", set(mapped.values()))

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace("Call mom", "Ligar para a mae"),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[0]["description"], "Ligar para a mae")

    def test_rpgm_duplicate_filenames_in_subfolders_do_not_collide(self) -> None:
        project = self.root / "rpgm_duplicate_names"
        folder_a = project / "www" / "data" / "FolderA"
        folder_b = project / "www" / "data" / "FolderB"
        folder_a.mkdir(parents=True)
        folder_b.mkdir(parents=True)

        config_a = folder_a / "config.json"
        config_b = folder_b / "config.json"
        config_a.write_text(
            json.dumps([{"name": "Alpha", "description": "Call A"}], ensure_ascii=False),
            encoding="utf-8",
        )
        config_b.write_text(
            json.dumps([{"name": "Beta", "description": "Call B"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        map_path = self.workspace / "rpgm" / "rpgm_mapa_arquivos.json"
        mapped = json.loads(map_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(mapped.values()),
            {"FolderA/config.json", "FolderB/config.json"},
        )

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        content = translated_path.read_text(encoding="utf-8")
        content = content.replace("Call A", "Chamar A")
        content = content.replace("Call B", "Chamar B")
        translated_path.write_text(content, encoding="utf-8")

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed_a = json.loads(config_a.read_text(encoding="utf-8"))
        parsed_b = json.loads(config_b.read_text(encoding="utf-8"))
        self.assertEqual(parsed_a[0]["description"], "Chamar A")
        self.assertEqual(parsed_b[0]["description"], "Chamar B")

    def test_rpgm_import_accepts_simple_filename_map_in_resolved_data_dir(self) -> None:
        project = self.root / "rpgm_legacy_map"
        data_dir = project / "data"
        data_dir.mkdir(parents=True)

        actors_path = data_dir / "Actors.json"
        actors_path.write_text(
            json.dumps([None, {"name": "Rogue"}], ensure_ascii=False),
            encoding="utf-8",
        )

        workspace_rpgm = self.workspace / "rpgm"
        workspace_rpgm.mkdir(parents=True)
        (workspace_rpgm / "rpgm_translations.txt").write_text(
            "=== ARQUIVO_000 ===\nLadino\n\n",
            encoding="utf-8",
        )
        (workspace_rpgm / "rpgm_placeholders.txt").write_text(
            "=== ARQUIVO_000 ===\n\n\n",
            encoding="utf-8",
        )
        (workspace_rpgm / "rpgm_mapa_arquivos.json").write_text(
            json.dumps({"ARQUIVO_000": "Actors.json"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        pre = pre_validar_importacao("rpgm", project, self.workspace, workspace_rpgm / "rpgm_translations.txt")
        self.assertTrue(pre.success, pre.message)

        import_result = importar(
            "rpgm",
            project,
            self.workspace,
            workspace_rpgm / "rpgm_translations.txt",
            criar_backup=False,
        )
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(actors_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[1]["name"], "Ladino")

    def test_rpgm_import_accepts_simple_filename_map_when_file_is_in_subfolder(self) -> None:
        project = self.root / "rpgm_legacy_subfolder"
        data_subdir = project / "www" / "data" / "PKD_PhoneMenu"
        data_subdir.mkdir(parents=True)

        config_path = data_subdir / "config.json"
        config_path.write_text(
            json.dumps([{"name": "Phone"}], ensure_ascii=False),
            encoding="utf-8",
        )

        workspace_rpgm = self.workspace / "rpgm"
        workspace_rpgm.mkdir(parents=True)
        (workspace_rpgm / "rpgm_translations.txt").write_text(
            "=== ARQUIVO_000 ===\nTelefone\n\n",
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

        parsed = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed[0]["name"], "Telefone")

    def test_rpgm_backup_includes_subfolder_files(self) -> None:
        project = self.root / "rpgm_backup_subfolder"
        config_path = project / "www" / "data" / "PKD_PhoneMenu" / "config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps([{"description": "Call mom"}], ensure_ascii=False),
            encoding="utf-8",
        )

        export_result = exportar("rpgm", project, self.workspace)
        self.assertTrue(export_result.success, export_result.message)

        translated_path = self.workspace / "rpgm" / "rpgm_translations.txt"
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace("Call mom", "Ligar para a mae"),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=True)
        self.assertTrue(import_result.success, import_result.message)
        self.assertIn("Backup criado em:", import_result.message)

        backup_root = self.workspace / "rpgm" / "backups"
        backups = sorted(backup_root.glob("rpgm_*"))
        self.assertTrue(backups)
        latest_backup = backups[-1]
        self.assertTrue((latest_backup / "www" / "data" / "PKD_PhoneMenu" / "config.json").exists())

    def test_rpgm_wraps_long_dialogue_text_on_import(self) -> None:
        project = self.root / "rpgm_wrap_dialogue"
        project.mkdir(parents=True)

        map_path = project / "Map001.json"
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
                                            "code": 401,
                                            "parameters": [
                                                "This is a small line to be replaced"
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
        long_text = (
            "Harry Alistair, esta sera uma frase de traducao bem maior que a original para "
            "forcar quebra automatica no importador do RPGM."
        )
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace(
                "This is a small line to be replaced",
                long_text,
            ),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(map_path.read_text(encoding="utf-8"))
        final_line = parsed["events"][1]["pages"][0]["list"][0]["parameters"][0]
        self.assertIn("\n", final_line)
        self.assertIn("Harry Alistair", final_line)

    def test_rpgm_does_not_over_wrap_medium_dialogue_text(self) -> None:
        project = self.root / "rpgm_no_over_wrap"
        project.mkdir(parents=True)

        map_path = project / "Map001.json"
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
                                            "code": 401,
                                            "parameters": ["Small placeholder line"],
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
        medium_text = "Voce ja nos disse isso antes. Leah e eu ja perdemos a conta de quantas vezes."
        translated_path.write_text(
            translated_path.read_text(encoding="utf-8").replace("Small placeholder line", medium_text),
            encoding="utf-8",
        )

        import_result = importar("rpgm", project, self.workspace, translated_path, criar_backup=False)
        self.assertTrue(import_result.success, import_result.message)

        parsed = json.loads(map_path.read_text(encoding="utf-8"))
        final_line = parsed["events"][1]["pages"][0]["list"][0]["parameters"][0]
        self.assertNotIn("\n", final_line)
        self.assertEqual(final_line, medium_text)

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
