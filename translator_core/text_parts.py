from __future__ import annotations

import re
from pathlib import Path

PART_FILE_RE = re.compile(r"^parte_(\d+)(?:\..+)?\.txt$", flags=re.IGNORECASE)


def split_text_file(source_path: str | Path, output_dir: str | Path, parts_count: int) -> list[Path]:
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

    base, extra = divmod(len(lines), parts_count)
    start = 0
    created_files: list[Path] = []
    for idx in range(parts_count):
        size = base + (1 if idx < extra else 0)
        chunk = lines[start : start + size]
        start += size
        out_path = out_dir / f"parte_{idx:02d}.txt"
        out_path.write_text("".join(chunk), encoding="utf-8-sig")
        created_files.append(out_path)
    return created_files


def merge_parts_into_target(parts_dir: str | Path, target_path: str | Path, *, cleanup: bool = True) -> tuple[list[Path], int]:
    directory = Path(parts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    candidates = [p for p in directory.glob("parte_*.txt") if p.is_file()]

    numbered: list[tuple[int, Path]] = []
    for path in candidates:
        match = PART_FILE_RE.match(path.name)
        if not match:
            continue
        numbered.append((int(match.group(1)), path))
    if not numbered:
        raise FileNotFoundError(f"Nenhum arquivo parte_*.txt foi encontrado em: {directory}")

    numbered.sort(key=lambda item: (item[0], item[1].name.lower()))
    ordered_parts = [path for _, path in numbered]
    merged = "".join(path.read_text(encoding="utf-8-sig") for path in ordered_parts)

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
    return ordered_parts, removed
