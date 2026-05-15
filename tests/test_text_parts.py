from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from translator_core.text_parts import (
    MANIFEST_FILENAME,
    merge_parts_into_target,
    split_text_file,
)


class TextPartsTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / ".tmp_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"text_parts_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_split_creates_expected_parts_and_manifest(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\nc\nd\n", encoding="utf-8-sig")
        out_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"

        parts = split_text_file(source, out_dir, 3, engine="renpy", target_path=target)

        self.assertEqual([p.name for p in parts], ["parte_00.txt", "parte_01.txt", "parte_02.txt"])
        self.assertEqual(parts[0].read_text(encoding="utf-8-sig"), "a\nb\n")
        self.assertEqual(parts[1].read_text(encoding="utf-8-sig"), "c\n")
        self.assertEqual(parts[2].read_text(encoding="utf-8-sig"), "d\n")
        self.assertTrue((out_dir / MANIFEST_FILENAME).exists())

    def test_merge_joins_variants_and_cleans_up(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target)
        (parts_dir / "parte_00.txt").rename(parts_dir / "parte_00.en.pt.txt")

        ordered, removed = merge_parts_into_target(parts_dir, target, cleanup=True)

        self.assertEqual([p.name for p in ordered], ["parte_00.en.pt.txt", "parte_01.txt"])
        self.assertEqual(removed, 2)
        self.assertEqual(target.read_text(encoding="utf-8-sig"), "a\nb\n")
        self.assertFalse((parts_dir / "parte_00.en.pt.txt").exists())
        self.assertFalse((parts_dir / "parte_01.txt").exists())
        self.assertFalse((parts_dir / MANIFEST_FILENAME).exists())

    def test_merge_fails_when_part_is_missing(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\nc\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 3, engine="renpy", target_path=target)
        (parts_dir / "parte_01.txt").unlink()

        with self.assertRaisesRegex(ValueError, "Faltam partes"):
            merge_parts_into_target(parts_dir, target, cleanup=True)

    def test_merge_fails_when_part_index_is_duplicated(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target)
        shutil.copy2(parts_dir / "parte_00.txt", parts_dir / "parte_00.en.pt.txt")

        with self.assertRaisesRegex(ValueError, "duplicadas"):
            merge_parts_into_target(parts_dir, target, cleanup=True)

    def test_merge_fails_when_manifest_target_mismatches(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target_ok = self.root / "workspace" / "renpy" / "all_translations.txt"
        target_wrong = self.root / "workspace" / "unity" / "unity_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target_ok)

        with self.assertRaisesRegex(ValueError, "não pertencem"):
            merge_parts_into_target(parts_dir, target_wrong, cleanup=True)

    def test_merge_can_keep_parts_when_cleanup_disabled(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target)

        _, removed = merge_parts_into_target(parts_dir, target, cleanup=False)

        self.assertEqual(removed, 0)
        self.assertTrue((parts_dir / "parte_00.txt").exists())
        self.assertTrue((parts_dir / "parte_01.txt").exists())
        self.assertTrue((parts_dir / MANIFEST_FILENAME).exists())

    def test_merge_propagates_permission_error_when_target_write_fails(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("a\nb\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target)

        original_write_text = Path.write_text

        def _patched_write_text(self: Path, data: str, *args, **kwargs):
            if self == target:
                raise PermissionError("sem permissão")
            return original_write_text(self, data, *args, **kwargs)

        with patch("pathlib.Path.write_text", new=_patched_write_text):
            with self.assertRaises(PermissionError):
                merge_parts_into_target(parts_dir, target, cleanup=True)

    def test_merge_recovers_blank_separator_when_previous_part_loses_trailing_newline(self) -> None:
        source = self.root / "all_translations.txt"
        source.write_text("=== game/script.rpy ===\nlinha 1\n\nlinha 2\n\nlinha 3\n", encoding="utf-8-sig")
        parts_dir = self.root / "downloads"
        target = self.root / "workspace" / "renpy" / "all_translations.txt"
        split_text_file(source, parts_dir, 2, engine="renpy", target_path=target)

        first = parts_dir / "parte_00.txt"
        first.write_text(first.read_text(encoding="utf-8-sig").rstrip("\n"), encoding="utf-8-sig")

        merge_parts_into_target(parts_dir, target, cleanup=True)
        merged = target.read_text(encoding="utf-8-sig")
        self.assertIn("linha 2\n\nlinha 3", merged)


if __name__ == "__main__":
    unittest.main()
