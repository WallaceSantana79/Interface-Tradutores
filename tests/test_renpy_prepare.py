from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from translator_core.renpy_prepare import (
    aplicar_force_language,
    copiar_un_files_para_game,
    detectar_executavel_jogo,
    detectar_versao_renpy,
    listar_launchers,
    preparar_descompactador,
    remover_un_files_de_game,
    remover_descompactador_temporario,
    selecionar_launcher_compativel,
)


class RenpyPrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"renpy_prepare_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detect_version_uses_priority_order(self) -> None:
        project = self.root / "game_version_priority"
        (project / "renpy").mkdir(parents=True)
        (project / "renpy" / "version.py").write_text(
            'version_string = "Ren\'Py 8.5.2"\n',
            encoding="utf-8",
        )
        (project / "renpy" / "__init__.py").write_text(
            'version_string = "Ren\'Py 8.3.1"\n',
            encoding="utf-8",
        )

        detected = detectar_versao_renpy(project)
        self.assertEqual(detected, "8.5.2")

    def test_detect_version_fallback_to_log(self) -> None:
        project = self.root / "game_log"
        project.mkdir(parents=True)
        (project / "log.txt").write_text(
            "Ren'Py 8.4.1.24092608 running in test mode\n",
            encoding="utf-8",
        )

        detected = detectar_versao_renpy(project)
        self.assertEqual(detected, "8.4.1")

    def test_detect_ignores_generic_init_tuple(self) -> None:
        project = self.root / "game_init_only"
        (project / "renpy").mkdir(parents=True)
        (project / "renpy" / "__init__.py").write_text(
            "version_tuple = (8, 0, 1, vc_version)\n",
            encoding="utf-8",
        )

        detected = detectar_versao_renpy(project)
        self.assertIsNone(detected)

    def test_launcher_selection_exact_and_nearest_patch(self) -> None:
        launchers_root = self.root / "renpy_versions"
        for name in ["renpy-8.5.0-sdk", "renpy-8.5.3-sdk", "renpy-7.8.0-sdk"]:
            folder = launchers_root / name
            folder.mkdir(parents=True)
            (folder / "renpy.exe").write_text("", encoding="utf-8")

        launchers = listar_launchers(launchers_root)
        self.assertEqual(len(launchers), 3)

        exact = selecionar_launcher_compativel("8.5.0", launchers)
        self.assertIsNotNone(exact)
        self.assertEqual(exact.version_tuple, (8, 5, 0))

        nearest = selecionar_launcher_compativel("8.5.2", launchers)
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest.version_tuple, (8, 5, 3))

        incompatible = selecionar_launcher_compativel("8.6.1", launchers)
        self.assertIsNone(incompatible)

    def test_prepare_and_remove_unren_temp_file(self) -> None:
        project = self.root / "game_unren"
        project.mkdir(parents=True)
        source_txt = self.root / "UnRen-forall.txt"
        source_txt.write_text("@echo off\necho teste\n", encoding="utf-8")

        copied = preparar_descompactador(project, source_txt, abrir_interativo=False)
        self.assertTrue(copied.exists())
        self.assertEqual(copied.name, "UnRen-forall.bat")
        self.assertIn("echo teste", copied.read_text(encoding="utf-8"))

        removed = remover_descompactador_temporario(copied)
        self.assertTrue(removed)
        self.assertFalse(copied.exists())

    def test_apply_force_language_to_game_folder(self) -> None:
        project = self.root / "game_force"
        (project / "game").mkdir(parents=True)
        source = self.root / "force_language.rpy"
        source.write_text('init python:\n    config.language = "portuguese"\n', encoding="utf-8")

        destination = aplicar_force_language(project, source)
        self.assertEqual(destination, project / "game" / "force_language.rpy")
        self.assertTrue(destination.exists())
        self.assertIn("config.language", destination.read_text(encoding="utf-8"))

    def test_detect_game_executable_prefers_main_candidate(self) -> None:
        project = self.root / "game_exe"
        project.mkdir(parents=True)
        (project / "renpy.exe").write_text("stub", encoding="utf-8")
        (project / "game_exe.exe").write_text("stub_main", encoding="utf-8")
        (project / "updater.exe").write_text("stub_updater", encoding="utf-8")

        detected = detectar_executavel_jogo(project)
        self.assertEqual(detected, project / "game_exe.exe")

    def test_detect_game_executable_none_when_missing(self) -> None:
        project = self.root / "game_without_exe"
        project.mkdir(parents=True)
        detected = detectar_executavel_jogo(project)
        self.assertIsNone(detected)

    def test_copy_and_remove_un_files_cycle(self) -> None:
        project = self.root / "game_un_cycle"
        game_dir = project / "game"
        game_dir.mkdir(parents=True)
        un_rpy_source = self.root / "un.rpy"
        un_rpyc_source = self.root / "un.rpyc"
        un_rpy_source.write_text("init python:\n    pass\n", encoding="utf-8")
        un_rpyc_source.write_bytes(b"\x00\x01\x02")

        copied = copiar_un_files_para_game(project, un_rpy_source, un_rpyc_source)
        self.assertEqual(len(copied), 2)
        self.assertTrue((game_dir / "un.rpy").exists())
        self.assertTrue((game_dir / "un.rpyc").exists())

        removed = remover_un_files_de_game(project)
        self.assertEqual(len(removed), 2)
        self.assertFalse((game_dir / "un.rpy").exists())
        self.assertFalse((game_dir / "un.rpyc").exists())


if __name__ == "__main__":
    unittest.main()
