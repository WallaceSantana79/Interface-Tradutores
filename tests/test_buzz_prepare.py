from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from translator_core.buzz_prepare import (
    BUZZ_FLATPAK_APP_ID,
    BuzzRunConfig,
    detectar_buzz,
    montar_comando_buzz,
    normalize_buzz_language,
)


class BuzzPrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"buzz_prepare_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.media = self.root / "clip.mp4"
        self.media.write_text("stub", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detectar_buzz_missing_flatpak(self) -> None:
        with patch("shutil.which", return_value=None):
            result = detectar_buzz()
        self.assertFalse(result.available)
        self.assertIn("Flatpak", result.message)

    def test_montar_comando_buzz_success(self) -> None:
        config = BuzzRunConfig(
            input_path=self.media,
            model_type="fasterwhisper",
            model_size="large-v3-turbo",
            task="transcribe",
            language="english",
            word_timestamps=True,
            extract_speech=True,
            output_formats=("srt", "txt"),
            output_directory=self.root,
            hide_gui=True,
        )
        with patch("shutil.which", return_value="/usr/bin/flatpak"):
            with patch("subprocess.run") as run_mock:
                run_mock.return_value.returncode = 0
                command = montar_comando_buzz(config)

        self.assertEqual(command[:4], ["/usr/bin/flatpak", "run", "--command=buzz", BUZZ_FLATPAK_APP_ID])
        self.assertIn("--model-type", command)
        self.assertIn("fasterwhisper", command)
        self.assertIn("--model-size", command)
        self.assertIn("large-v3-turbo", command)
        self.assertIn("--task", command)
        self.assertIn("transcribe", command)
        self.assertIn("--language", command)
        self.assertIn("en", command)
        self.assertIn("--word-timestamps", command)
        self.assertIn("--extract-speech", command)
        self.assertIn("--srt", command)
        self.assertIn("--txt", command)
        self.assertIn("--hide-gui", command)

    def test_montar_comando_rejects_invalid_model(self) -> None:
        config = BuzzRunConfig(
            input_path=self.media,
            model_type="invalid",
            model_size="large-v3-turbo",
            task="transcribe",
            output_formats=("srt",),
        )
        with patch("shutil.which", return_value="/usr/bin/flatpak"):
            with patch("subprocess.run") as run_mock:
                run_mock.return_value.returncode = 0
                with self.assertRaises(ValueError):
                    montar_comando_buzz(config)

    def test_montar_comando_requires_buzz_available(self) -> None:
        config = BuzzRunConfig(input_path=self.media)
        with patch("shutil.which", return_value="/usr/bin/flatpak"):
            with patch("subprocess.run") as run_mock:
                run_mock.return_value.returncode = 1
                with self.assertRaises(ValueError):
                    montar_comando_buzz(config)

    def test_normalize_language_alias_and_auto(self) -> None:
        self.assertEqual(normalize_buzz_language("english"), "en")
        self.assertEqual(normalize_buzz_language("Detectar idioma (auto)"), "")
        self.assertEqual(normalize_buzz_language("Português (pt)"), "pt")


if __name__ == "__main__":
    unittest.main()
