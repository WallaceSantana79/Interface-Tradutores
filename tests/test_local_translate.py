from __future__ import annotations

import shutil
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from translator_core.local_translate import (
    LocalTranslateConfig,
    local_translated_path,
    translate_document_local,
)


class LocalTranslateTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"local_translate_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_local_translated_path_keeps_original_and_adds_suffix(self) -> None:
        result = local_translated_path(self.root / "all_translations.txt", self.root / "out")
        self.assertEqual(result, self.root / "out" / "all_translations.local_ptbr.txt")

    def test_translate_document_local_translates_all_lines_without_limit(self) -> None:
        input_path = self.root / "source.txt"
        lines = [f"Line {idx}" for idx in range(205)]
        input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def fake_translate(_config: LocalTranslateConfig, chunk: list[str]) -> list[str]:
            return [f"PT::{line}" for line in chunk]

        with patch("translator_core.local_translate._translate_chunk", side_effect=fake_translate):
            result = translate_document_local(
                LocalTranslateConfig(
                    input_path=input_path,
                    output_dir=self.root,
                    chunk_lines=50,
                )
            )

        self.assertTrue(result.success, result.message)
        output_path = self.root / "source.local_ptbr.txt"
        produced = output_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(produced), 205)
        self.assertEqual(produced[0], "PT::Line 0")
        self.assertEqual(produced[-1], "PT::Line 204")

    def test_translate_document_local_preserves_explicit_content(self) -> None:
        input_path = self.root / "adult.txt"
        input_path.write_text("You are a damn idiot.\nAdult explicit content.\n", encoding="utf-8")

        def fake_translate(_config: LocalTranslateConfig, chunk: list[str]) -> list[str]:
            return ["Seu maldito idiota.", "Conteúdo adulto explícito."]

        with patch("translator_core.local_translate._translate_chunk", side_effect=fake_translate):
            result = translate_document_local(
                LocalTranslateConfig(
                    input_path=input_path,
                    output_dir=self.root,
                    chunk_lines=10,
                )
            )

        self.assertTrue(result.success, result.message)
        output = (self.root / "adult.local_ptbr.txt").read_text(encoding="utf-8")
        self.assertIn("maldito", output)
        self.assertIn("adulto explícito", output)

    def test_translate_document_local_returns_error_when_ollama_unavailable(self) -> None:
        input_path = self.root / "source.txt"
        input_path.write_text("Hello\n", encoding="utf-8")

        with patch("translator_core.local_translate._ollama_generate", side_effect=OSError("connection refused")):
            result = translate_document_local(LocalTranslateConfig(input_path=input_path, output_dir=self.root))

        self.assertFalse(result.success)
        self.assertIn("Falha na tradução local", result.message)

    def test_translate_document_local_cancelled_by_user(self) -> None:
        input_path = self.root / "source.txt"
        input_path.write_text("a\nb\nc\nd\n", encoding="utf-8")
        cancel_event = threading.Event()

        def fake_translate(_config: LocalTranslateConfig, chunk: list[str]) -> list[str]:
            cancel_event.set()
            return [f"PT::{line}" for line in chunk]

        with patch("translator_core.local_translate._translate_chunk", side_effect=fake_translate):
            result = translate_document_local(
                LocalTranslateConfig(
                    input_path=input_path,
                    output_dir=self.root,
                    chunk_lines=2,
                    cancel_event=cancel_event,
                )
            )

        self.assertFalse(result.success)
        self.assertIn("cancelada", result.message.casefold())
        self.assertTrue(result.generated_files)

    def test_translate_document_local_splits_chunk_when_model_returns_invalid_json(self) -> None:
        input_path = self.root / "source.txt"
        lines = [f"Line {idx}" for idx in range(16)]
        input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def fake_translate(_config: LocalTranslateConfig, chunk: list[str]) -> list[str]:
            if len(chunk) > 4:
                raise ValueError("Resposta do modelo não retornou JSON de linhas.")
            return [f"PT::{line}" for line in chunk]

        with patch("translator_core.local_translate._translate_chunk", side_effect=fake_translate):
            result = translate_document_local(
                LocalTranslateConfig(
                    input_path=input_path,
                    output_dir=self.root,
                    chunk_lines=16,
                )
            )

        self.assertTrue(result.success, result.message)
        output = (self.root / "source.local_ptbr.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(output[0], "PT::Line 0")
        self.assertEqual(output[-1], "PT::Line 15")


if __name__ == "__main__":
    unittest.main()
