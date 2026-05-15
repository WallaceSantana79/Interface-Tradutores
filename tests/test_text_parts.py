from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from translator_core.text_parts import merge_parts_into_target, split_text_file


class TextPartsTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"text_parts_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_split_creates_expected_parts(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\nc\nd\n", encoding="utf-8-sig")
        out_dir = self.root / "downloads"

        parts = split_text_file(source, out_dir, 3)

        self.assertEqual([p.name for p in parts], ["parte_00.txt", "parte_01.txt", "parte_02.txt"])
        self.assertEqual(parts[0].read_text(encoding="utf-8-sig"), "a\nb\n")
        self.assertEqual(parts[1].read_text(encoding="utf-8-sig"), "c\n")
        self.assertEqual(parts[2].read_text(encoding="utf-8-sig"), "d\n")

    def test_merge_joins_variants_and_cleans_up(self) -> None:
        parts_dir = self.root / "downloads"
        parts_dir.mkdir(parents=True, exist_ok=True)
        (parts_dir / "parte_00.en.pt.txt").write_text("a\n", encoding="utf-8-sig")
        (parts_dir / "parte_01.txt").write_text("b\n", encoding="utf-8-sig")
        target = self.root / "workspace" / "renpy" / "all_translations.txt"

        ordered, removed = merge_parts_into_target(parts_dir, target, cleanup=True)

        self.assertEqual([p.name for p in ordered], ["parte_00.en.pt.txt", "parte_01.txt"])
        self.assertEqual(removed, 2)
        self.assertEqual(target.read_text(encoding="utf-8-sig"), "a\nb\n")
        self.assertFalse((parts_dir / "parte_00.en.pt.txt").exists())
        self.assertFalse((parts_dir / "parte_01.txt").exists())


if __name__ == "__main__":
    unittest.main()
