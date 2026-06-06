from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from translator_core.renpy_prepare import (
    aplicar_force_language,
    abrir_processo_jogo,
    copiar_un_files_para_game,
    detectar_executavel_jogo,
    detectar_versao_renpy,
    executar_unren_em_pasta,
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

        with patch("platform.system", return_value="Windows"):
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

        with patch("platform.system", return_value="Windows"):
            copied = preparar_descompactador(project, source_txt, abrir_interativo=False)
        self.assertTrue(copied.exists())
        self.assertEqual(copied.name, "UnRen-forall.bat")
        self.assertIn("echo teste", copied.read_text(encoding="utf-8"))

        removed = remover_descompactador_temporario(copied)
        self.assertTrue(removed)
        self.assertFalse(copied.exists())

    def test_execute_unren_folder_windows_passes_project_argument(self) -> None:
        project = self.root / "game_unren_folder"
        project.mkdir(parents=True)
        unren_dir = self.root / "UnRen-forall-la_0.77-le_9.7.60-cu_9.7.80"
        unren_dir.mkdir(parents=True)
        script = unren_dir / "UnRen-forall.bat"
        script.write_text("@echo off\necho teste\n", encoding="utf-8")

        with patch("translator_core.renpy_prepare._is_windows", return_value=True):
            with patch("subprocess.Popen") as popen_mock:
                popen_mock.return_value = SimpleNamespace()
                executed = executar_unren_em_pasta(project, unren_dir, abrir_interativo=True)

        self.assertEqual(executed, script)
        popen_mock.assert_called_once()
        args, kwargs = popen_mock.call_args
        self.assertIn(str(project), args[0])
        self.assertIn(str(script), args[0])
        self.assertEqual(kwargs.get("cwd"), unren_dir)
        self.assertTrue(kwargs.get("shell"))

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

        with patch("platform.system", return_value="Windows"):
            detected = detectar_executavel_jogo(project)
        self.assertEqual(detected, project / "game_exe.exe")

    def test_detect_game_executable_none_when_missing(self) -> None:
        project = self.root / "game_without_exe"
        project.mkdir(parents=True)
        with patch("platform.system", return_value="Windows"):
            detected = detectar_executavel_jogo(project)
        self.assertIsNone(detected)

    def test_listar_launchers_linux_uses_renpy_sh(self) -> None:
        launchers_root = self.root / "renpy_versions_linux"
        for name in ["renpy-8.5.0-sdk", "renpy-8.5.3-sdk"]:
            folder = launchers_root / name
            folder.mkdir(parents=True)
            launcher = folder / "renpy.sh"
            launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | 0o111)

        with patch("platform.system", return_value="Linux"):
            launchers = listar_launchers(launchers_root)
        self.assertEqual(len(launchers), 2)

    def test_prepare_descompactador_linux_uses_sh(self) -> None:
        project = self.root / "game_unren_linux"
        project.mkdir(parents=True)
        source_sh = self.root / "UnRen-forall.sh"
        source_sh.write_text("#!/usr/bin/env bash\necho teste\n", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            copied = preparar_descompactador(project, source_sh, abrir_interativo=False)
        self.assertTrue(copied.exists())
        self.assertEqual(copied.name, "UnRen-forall.sh")
        self.assertTrue(os.access(copied, os.X_OK))

    def test_prepare_descompactador_linux_preserves_selected_script_name(self) -> None:
        project = self.root / "game_unren_linux_named"
        project.mkdir(parents=True)
        source_sh = self.root / "UnRen-Linux.sh"
        source_sh.write_text("#!/usr/bin/env bash\necho teste\n", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            copied = preparar_descompactador(project, source_sh, abrir_interativo=False)
        self.assertTrue(copied.exists())
        self.assertEqual(copied.name, "UnRen-Linux.sh")

    def test_prepare_descompactador_linux_preserves_command_script_name(self) -> None:
        project = self.root / "game_unren_linux_command"
        project.mkdir(parents=True)
        source_command = self.root / "UnRen-v1.0.11u.command"
        source_command.write_text("#!/usr/bin/env bash\necho teste\n", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            copied = preparar_descompactador(project, source_command, abrir_interativo=False)

        self.assertTrue(copied.exists())
        self.assertEqual(copied.name, "UnRen-v1.0.11u.command")
        self.assertTrue(os.access(copied, os.X_OK))

    def test_prepare_descompactador_linux_bat_requires_wine(self) -> None:
        project = self.root / "game_unren_linux_bat"
        project.mkdir(parents=True)
        source_bat = self.root / "UnRen-forall.bat"
        source_bat.write_text("@echo off\necho teste\n", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value=None):
                with self.assertRaises(RuntimeError):
                    preparar_descompactador(project, source_bat, abrir_interativo=True)

    def test_prepare_descompactador_linux_bat_uses_wine_cmd(self) -> None:
        project = self.root / "game_unren_linux_bat_wine"
        project.mkdir(parents=True)
        source_bat = self.root / "UnRen-forall.bat"
        source_bat.write_text("@echo off\necho teste\n", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value="/usr/bin/wine"):
                with patch("subprocess.Popen") as popen_mock:
                    popen_mock.return_value = SimpleNamespace()
                    copied = preparar_descompactador(project, source_bat, abrir_interativo=True)

        self.assertEqual(copied.name, "UnRen-forall.bat")
        popen_mock.assert_called_once()
        args, kwargs = popen_mock.call_args
        self.assertEqual(args[0], ["/usr/bin/wine", "cmd", "/c", "UnRen-forall.bat"])
        self.assertEqual(kwargs.get("cwd"), str(project))

    def test_detect_game_executable_linux_prefers_main_candidate(self) -> None:
        project = self.root / "game_linux_bin"
        project.mkdir(parents=True)
        renpy_sh = project / "renpy.sh"
        renpy_sh.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        renpy_sh.chmod(renpy_sh.stat().st_mode | 0o111)
        game_sh = project / "game_main.sh"
        game_sh.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        game_sh.chmod(game_sh.stat().st_mode | 0o111)

        with patch("platform.system", return_value="Linux"):
            detected = detectar_executavel_jogo(project)
        self.assertEqual(detected, game_sh)

    def test_detect_game_executable_linux_accepts_exe(self) -> None:
        project = self.root / "game_linux_wine"
        project.mkdir(parents=True)
        game_exe = project / "game_main.exe"
        game_exe.write_text("stub", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            detected = detectar_executavel_jogo(project)
        self.assertEqual(detected, game_exe)

    def test_abrir_processo_jogo_linux_exe_requires_wine(self) -> None:
        project = self.root / "game_linux_wine_missing"
        project.mkdir(parents=True)
        game_exe = project / "game_main.exe"
        game_exe.write_text("stub", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value=None):
                with self.assertRaises(RuntimeError):
                    abrir_processo_jogo(game_exe, project)

    def test_abrir_processo_jogo_linux_exe_uses_wine(self) -> None:
        project = self.root / "game_linux_wine_ok"
        project.mkdir(parents=True)
        game_exe = project / "game_main.exe"
        game_exe.write_text("stub", encoding="utf-8")

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value="/usr/bin/wine"):
                with patch("subprocess.Popen") as popen_mock:
                    popen_mock.return_value = SimpleNamespace()
                    abrir_processo_jogo(game_exe, project)

        popen_mock.assert_called_once()
        args, kwargs = popen_mock.call_args
        self.assertEqual(args[0], ["/usr/bin/wine", str(game_exe)])
        self.assertEqual(kwargs.get("cwd"), str(project))

    def test_abrir_processo_jogo_linux_command_uses_bash_when_not_executable(self) -> None:
        project = self.root / "game_linux_command"
        project.mkdir(parents=True)
        game_command = project / "game_main.command"
        game_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        game_command.chmod(0o644)

        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.Popen") as popen_mock:
                popen_mock.return_value = SimpleNamespace()
                abrir_processo_jogo(game_command, project)

        popen_mock.assert_called_once()
        args, kwargs = popen_mock.call_args
        self.assertEqual(args[0], ["bash", str(game_command)])
        self.assertEqual(kwargs.get("cwd"), str(project))

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
