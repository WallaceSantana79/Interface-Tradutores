from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

import app


class DropLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"drop_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

        self.game_dir = self.root / "project"
        self.game_dir.mkdir(parents=True, exist_ok=True)
        self.sample_txt = self.root / "translated.txt"
        self.sample_txt.write_text("ok", encoding="utf-8")
        self.sample_png = self.root / "image.png"
        self.sample_png.write_text("bin", encoding="utf-8")
        self.sample_mp4 = self.root / "video.mp4"
        self.sample_mp4.write_text("bin", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_normalize_dropped_items(self) -> None:
        items = app.normalize_dropped_items([f"{{{self.game_dir}}}", str(self.sample_txt)])
        self.assertEqual(items[0], self.game_dir)
        self.assertEqual(items[1], self.sample_txt)

    def test_resolve_project_drop_prefers_directory(self) -> None:
        selected, from_file = app.resolve_project_drop_path([self.game_dir, self.sample_txt])
        self.assertEqual(selected, self.game_dir)
        self.assertFalse(from_file)

    def test_resolve_project_drop_uses_parent_when_file(self) -> None:
        selected, from_file = app.resolve_project_drop_path([self.sample_txt])
        self.assertEqual(selected, self.sample_txt.parent)
        self.assertTrue(from_file)

    def test_resolve_translated_txt_accepts_only_txt(self) -> None:
        selected = app.resolve_translated_txt_drop_path([self.sample_png, self.sample_txt])
        self.assertEqual(selected, self.sample_txt)

    def test_resolve_translated_txt_rejects_non_txt(self) -> None:
        selected = app.resolve_translated_txt_drop_path([self.sample_png, self.game_dir])
        self.assertIsNone(selected)

    def test_resolve_buzz_media_drop_path_accepts_video(self) -> None:
        selected = app.resolve_buzz_media_drop_path([self.sample_png, self.sample_txt, self.sample_mp4])
        self.assertEqual(selected, self.sample_mp4)

    def test_resolve_buzz_media_drop_path_rejects_non_media(self) -> None:
        selected = app.resolve_buzz_media_drop_path([self.sample_png, self.sample_txt, self.game_dir])
        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
