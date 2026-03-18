from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def ensure_directory(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_backup_snapshot(
    engine: str,
    project_dir: str | Path,
    workspace_dir: str | Path,
    files_to_backup: list[Path],
) -> Path:
    project = Path(project_dir).resolve()
    workspace = ensure_directory(workspace_dir).resolve()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = workspace / "backups" / f"{engine}_{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)

    for src in files_to_backup:
        rel = src.resolve().relative_to(project)
        dst = backup_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return backup_root
