from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PART_FILE_RE = re.compile(r"^parte_(\d+)(?:\..+)?\.txt$", flags=re.IGNORECASE)
MANIFEST_FILENAME = "parte_manifest.json"


def _canonical_path(value: str | Path) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(manifest_path: Path, payload: dict[str, Any]) -> None:
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Manifesto inválido: conteúdo inesperado.")
    return raw


def _split_lines_on_safe_boundaries(lines: list[str], parts_count: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    start = 0
    total = len(lines)

    for idx in range(parts_count):
        remaining_parts = parts_count - idx
        remaining_lines = total - start
        if idx == parts_count - 1:
            end = total
        else:
            min_tail = remaining_parts - 1  # reserve at least one line per remaining chunk
            ideal = max(1, remaining_lines // remaining_parts)
            end = min(start + ideal, total - min_tail)

            # Prefer to cut after a blank line to avoid splitting translation blocks.
            while end < total - min_tail and lines[end - 1].strip() != "":
                end += 1

        if end <= start:
            end = min(start + 1, total)
        chunks.append(lines[start:end])
        start = end
    return chunks


def _merge_text_chunks_with_boundary_guard(
    chunks: list[str],
    *,
    boundary_requires_blank_line: list[bool] | None = None,
) -> str:
    if not chunks:
        return ""
    merged = chunks[0]
    for idx, next_text in enumerate(chunks[1:]):
        requires_blank = bool(boundary_requires_blank_line[idx]) if boundary_requires_blank_line else False
        if requires_blank:
            if not merged.endswith("\n\n"):
                if merged.endswith("\n") and next_text.startswith("\n"):
                    pass
                elif merged.endswith("\n") or next_text.startswith("\n"):
                    merged += "\n"
                else:
                    merged += "\n\n"
        else:
            if not merged.endswith("\n") and not next_text.startswith("\n"):
                merged += "\n"
        merged += next_text
    return merged


def split_text_file(
    source_path: str | Path,
    output_dir: str | Path,
    parts_count: int,
    *,
    engine: str | None = None,
    target_path: str | Path | None = None,
) -> list[Path]:
    if parts_count < 2:
        raise ValueError("A divisão precisa ter pelo menos 2 partes.")
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Arquivo de origem não encontrado: {source}")

    lines = source.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    if not lines:
        raise ValueError("O TXT gerado está vazio e não pode ser dividido.")
    if parts_count > len(lines):
        raise ValueError(f"O TXT tem {len(lines)} linhas. Escolha no máximo {len(lines)} partes.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    line_chunks = _split_lines_on_safe_boundaries(lines, parts_count)
    created_files: list[Path] = []
    for idx, chunk in enumerate(line_chunks):
        out_path = out_dir / f"parte_{idx:02d}.txt"
        out_path.write_text("".join(chunk), encoding="utf-8-sig")
        created_files.append(out_path)

    manifest_payload: dict[str, Any] = {
        "version": 1,
        "engine": (engine or "").strip().lower(),
        "source_path": str(source.resolve()),
        "source_sha256": _file_sha256(source),
        "target_path": str(Path(target_path).resolve()) if target_path else "",
        "total_parts": len(created_files),
        "part_names": [p.name for p in created_files],
        "boundary_requires_blank_line": [
            "".join(chunk).endswith("\n\n") for chunk in line_chunks[:-1]
        ],
    }
    _write_manifest(out_dir / MANIFEST_FILENAME, manifest_payload)
    return created_files


def merge_parts_into_target(
    parts_dir: str | Path,
    target_path: str | Path,
    *,
    cleanup: bool = True,
    require_manifest: bool = True,
) -> tuple[list[Path], int]:
    directory = Path(parts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / MANIFEST_FILENAME
    manifest: dict[str, Any] | None = None

    if require_manifest:
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Manifesto não encontrado em: {manifest_path}. Gere as partes novamente pelo app."
            )
        manifest = _read_manifest(manifest_path)
    elif manifest_path.exists():
        manifest = _read_manifest(manifest_path)

    if manifest and str(manifest.get("target_path", "")).strip():
        expected_target = _canonical_path(str(manifest.get("target_path")))
        received_target = _canonical_path(target_path)
        if expected_target != received_target:
            raise ValueError(
                "As partes não pertencem ao TXT atual da engine. "
                "Refaça a divisão para este projeto antes de juntar."
            )

    candidates = [p for p in directory.glob("parte_*.txt") if p.is_file()]
    index_map: dict[int, list[Path]] = {}
    for path in candidates:
        match = PART_FILE_RE.match(path.name)
        if not match:
            continue
        idx = int(match.group(1))
        index_map.setdefault(idx, []).append(path)

    if not index_map:
        raise FileNotFoundError(f"Nenhum arquivo parte_*.txt foi encontrado em: {directory}")

    duplicates = {idx: paths for idx, paths in index_map.items() if len(paths) > 1}
    if duplicates:
        dup_desc = ", ".join(
            f"{idx}: {', '.join(p.name for p in sorted(paths, key=lambda x: x.name.lower()))}"
            for idx, paths in sorted(duplicates.items())
        )
        raise ValueError(f"Foram encontradas partes duplicadas para o mesmo índice ({dup_desc}).")

    if manifest:
        expected_total = int(manifest.get("total_parts", 0))
        if expected_total <= 0:
            raise ValueError("Manifesto inválido: total_parts ausente ou inválido.")
    else:
        expected_total = max(index_map.keys()) + 1

    missing = [idx for idx in range(expected_total) if idx not in index_map]
    if missing:
        missing_text = ", ".join(f"parte_{idx:02d}" for idx in missing)
        raise ValueError(f"Faltam partes para a junção: {missing_text}.")

    extras = [idx for idx in sorted(index_map.keys()) if idx >= expected_total]
    if extras:
        extras_text = ", ".join(f"parte_{idx:02d}" for idx in extras)
        raise ValueError(f"Foram encontradas partes extras inesperadas: {extras_text}.")

    ordered_parts = [index_map[idx][0] for idx in range(expected_total)]
    chunk_texts = [path.read_text(encoding="utf-8-sig") for path in ordered_parts]
    boundary_flags: list[bool] | None = None
    if manifest:
        raw_flags = manifest.get("boundary_requires_blank_line")
        if isinstance(raw_flags, list):
            parsed_flags = [bool(item) for item in raw_flags]
            if len(parsed_flags) == max(0, len(chunk_texts) - 1):
                boundary_flags = parsed_flags
    merged = _merge_text_chunks_with_boundary_guard(
        chunk_texts,
        boundary_requires_blank_line=boundary_flags,
    )

    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(merged, encoding="utf-8-sig")

    removed = 0
    if cleanup:
        for part in ordered_parts:
            try:
                part.unlink()
                removed += 1
            except OSError:
                continue
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError:
                pass
    return ordered_parts, removed
