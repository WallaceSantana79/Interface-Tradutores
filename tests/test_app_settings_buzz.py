from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import app


class AppBuzzSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"app_buzz_settings_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.root / "settings.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_settings_contains_buzz_keys(self) -> None:
        defaults = app._default_settings()
        self.assertEqual(defaults["buzz_model_type"], "fasterwhisper")
        self.assertEqual(defaults["buzz_model_size"], "large-v3-turbo")
        self.assertEqual(defaults["buzz_task"], "transcribe")
        self.assertEqual(defaults["buzz_language"], "Detectar idioma (auto)")
        self.assertFalse(defaults["buzz_word_timestamps"])
        self.assertEqual(defaults["buzz_output_formats"], ["srt"])
        self.assertTrue(defaults["buzz_output_same_dir"])

    def test_load_app_settings_reads_buzz_preferences(self) -> None:
        payload = {
            "buzz_model_type": "whispercpp",
            "buzz_model_size": "large-v3",
            "buzz_task": "translate",
            "buzz_language": "pt",
            "buzz_word_timestamps": True,
            "buzz_extract_speech": True,
            "buzz_output_formats": ["srt", "txt"],
            "buzz_output_same_dir": False,
            "buzz_output_directory": str(self.root),
        }
        self.settings_path.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(app, "SETTINGS_PATH", self.settings_path):
            loaded = app.load_app_settings()

        self.assertEqual(loaded["buzz_model_type"], "whispercpp")
        self.assertEqual(loaded["buzz_model_size"], "large-v3")
        self.assertEqual(loaded["buzz_task"], "translate")
        self.assertEqual(loaded["buzz_language"], "pt")
        self.assertTrue(loaded["buzz_word_timestamps"])
        self.assertTrue(loaded["buzz_extract_speech"])
        self.assertEqual(loaded["buzz_output_formats"], ["srt", "txt"])
        self.assertFalse(loaded["buzz_output_same_dir"])
        self.assertEqual(loaded["buzz_output_directory"], str(self.root))


if __name__ == "__main__":
    unittest.main()
