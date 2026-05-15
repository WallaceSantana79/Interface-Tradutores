from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_VERSION_RE = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
_LAUNCHER_DIR_RE = re.compile(r"^renpy-(\d+\.\d+(?:\.\d+)?)-sdk$", re.IGNORECASE)


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_non_windows_executable(path: Path) -> bool:
    return path.suffix.lower() in {".sh", ".command", ".exe"} or os.access(path, os.X_OK)


def _is_game_launch_candidate(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if _is_windows():
        return path.suffix.lower() == ".exe"
    return _is_non_windows_executable(path)


def _open_script_in_linux_terminal(script_path: Path, cwd: Path) -> bool:
    command = (
        f"cd {shlex.quote(str(cwd))} && "
        f"chmod +x {shlex.quote(script_path.name)} && "
        f"./{shlex.quote(script_path.name)}; "
        'echo ""; read -n 1 -s -r -p "Pressione qualquer tecla para fechar..."'
    )

    terminal_commands: list[list[str]] = []
    x_term = shutil.which("x-terminal-emulator")
    if x_term:
        terminal_commands.append([x_term, "-e", "bash", "-lc", command])

    gnome_term = shutil.which("gnome-terminal")
    if gnome_term:
        terminal_commands.append([gnome_term, "--", "bash", "-lc", command])

    for term in ["konsole", "xfce4-terminal", "mate-terminal", "lxterminal", "xterm", "tilix", "alacritty", "kitty"]:
        term_path = shutil.which(term)
        if term_path:
            terminal_commands.append([term_path, "-e", "bash", "-lc", command])

    for terminal_cmd in terminal_commands:
        try:
            subprocess.Popen(terminal_cmd, cwd=str(cwd))
            return True
        except Exception:
            continue
    return False


@dataclass(frozen=True)
class LauncherCandidate:
    version: str
    version_tuple: tuple[int, int, int]
    exe_path: Path


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(value)
    if not match:
        return None

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch") or 0)

    if major < 6 or major > 9:
        return None

    return (major, minor, patch)


def _version_tuple_to_text(version_tuple: tuple[int, int, int], *, keep_patch: bool) -> str:
    if keep_patch:
        return f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
    return f"{version_tuple[0]}.{version_tuple[1]}"


def _extract_from_version_py(content: str) -> str | None:
    for name in ["version_string", "version"]:
        match = re.search(rf"{name}\s*=\s*(?P<q>[\"'])(?P<value>.*?)(?P=q)", content)
        if not match:
            continue
        parsed = _parse_version(match.group("value"))
        if parsed is None:
            continue
        keep_patch = bool(re.search(r"\d+\.\d+\.\d+", match.group("value")))
        return _version_tuple_to_text(parsed, keep_patch=keep_patch)

    # Exemplo: version = "Ren'Py 8.5.2.250926"
    for pattern in [
        r"version\s*=\s*[\"']Ren'Py\s+(\d+\.\d+(?:\.\d+)?)",
    ]:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_version(match.group(1))
        if parsed is None:
            continue
        keep_patch = bool(re.search(r"\d+\.\d+\.\d+", match.group(1)))
        return _version_tuple_to_text(parsed, keep_patch=keep_patch)

    # Exemplo: version_tuple = (8, 5, 2, ...)
    tuple_match = re.search(r"version_tuple\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", content)
    if tuple_match:
        parsed = (int(tuple_match.group(1)), int(tuple_match.group(2)), int(tuple_match.group(3)))
        if _parse_version(f"{parsed[0]}.{parsed[1]}.{parsed[2]}"):
            return _version_tuple_to_text(parsed, keep_patch=True)

    return None


def _extract_from_log(content: str) -> str | None:
    # Exemplo: "Ren'Py 8.5.2.25092608"
    for match in re.finditer(r"Ren'Py\s+(\d+\.\d+(?:\.\d+)?)", content, flags=re.IGNORECASE):
        parsed = _parse_version(match.group(1))
        if parsed is None:
            continue
        keep_patch = bool(re.search(r"\d+\.\d+\.\d+", match.group(1)))
        return _version_tuple_to_text(parsed, keep_patch=keep_patch)
    return None


def _extract_from_init_py(content: str) -> str | None:
    # __init__.py costuma trazer valores base (ex.: 8.0.1) que nem sempre refletem o jogo.
    # Aqui aceitamos apenas formas explícitas de version_string para reduzir falso positivo.
    patterns = [
        r"renpy\.version_string\s*=\s*(?P<q>[\"'])(?P<value>.*?)(?P=q)",
        r"version_string\s*=\s*(?P<q>[\"'])(?P<value>.*?)(?P=q)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if not match:
            continue

        parsed = _parse_version(match.group("value"))
        if parsed is None:
            continue

        raw = match.group("value")
        keep_patch = bool(re.search(r"\d+\.\d+\.\d+", raw))
        return _version_tuple_to_text(parsed, keep_patch=keep_patch)

    return None


def detectar_versao_renpy(project_dir: str | Path) -> str | None:
    project = Path(project_dir)
    scan_order: list[tuple[Path, str]] = [
        (project / "renpy" / "version.py", "version_py"),
        (project / "log.txt", "log"),
        (project / "renpy" / "__init__.py", "init_py"),
    ]

    for candidate, source in scan_order:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue

        if source == "version_py":
            found = _extract_from_version_py(content)
        elif source == "log":
            found = _extract_from_log(content)
        else:
            found = _extract_from_init_py(content)

        if found:
            return found

    return None


def listar_launchers(launchers_root: str | Path) -> list[LauncherCandidate]:
    root = Path(launchers_root)
    if not root.exists() or not root.is_dir():
        return []

    candidates: list[LauncherCandidate] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = _LAUNCHER_DIR_RE.match(child.name)
        if not match:
            continue

        version_raw = match.group(1)
        version_tuple = _parse_version(version_raw)
        if version_tuple is None:
            continue

        launcher_names = ["renpy.exe"] if _is_windows() else ["renpy.sh", "renpy.command", "renpy", "renpy.exe"]
        exe_path = next((child / name for name in launcher_names if _is_game_launch_candidate(child / name)), None)
        if exe_path is None:
            continue

        keep_patch = bool(re.search(r"\d+\.\d+\.\d+", version_raw))
        version_text = _version_tuple_to_text(version_tuple, keep_patch=keep_patch)
        candidates.append(
            LauncherCandidate(version=version_text, version_tuple=version_tuple, exe_path=exe_path)
        )

    candidates.sort(key=lambda item: item.version_tuple, reverse=True)
    return candidates


def selecionar_launcher_compativel(
    versao_jogo: str | None,
    launchers: list[LauncherCandidate],
) -> LauncherCandidate | None:
    if not versao_jogo:
        return None

    game_tuple = _parse_version(versao_jogo)
    if game_tuple is None:
        return None

    exact = [item for item in launchers if item.version_tuple == game_tuple]
    if exact:
        return exact[0]

    same_major_minor = [
        item
        for item in launchers
        if item.version_tuple[0] == game_tuple[0] and item.version_tuple[1] == game_tuple[1]
    ]
    if not same_major_minor:
        return None

    same_major_minor.sort(
        key=lambda item: (abs(item.version_tuple[2] - game_tuple[2]), -item.version_tuple[2])
    )
    return same_major_minor[0]


def preparar_descompactador(
    project_dir: str | Path,
    source_bat_or_txt: str | Path,
    *,
    abrir_interativo: bool = True,
) -> Path:
    project = Path(project_dir)
    source = Path(source_bat_or_txt)

    if not project.exists() or not project.is_dir():
        raise FileNotFoundError(f"Pasta de projeto inválida: {project}")
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Arquivo do descompactador não encontrado: {source}")

    if _is_windows():
        destination_name = "UnRen-forall.bat"
    else:
        if source.suffix.lower() == ".txt":
            destination_name = "UnRen-forall.sh"
        else:
            destination_name = source.name
    destination = project / destination_name
    if source.resolve() == destination.resolve():
        pass
    elif source.suffix.lower() == ".txt":
        content = source.read_text(encoding="utf-8-sig", errors="ignore")
        destination.write_text(content, encoding="utf-8")
    else:
        shutil.copy2(source, destination)

    if not _is_windows():
        destination.chmod(destination.stat().st_mode | 0o111)

    if abrir_interativo:
        if _is_windows():
            command = f'start "UnRen" /D "{project}" "{destination}"'
            subprocess.Popen(command, cwd=project, shell=True)
        else:
            if destination.suffix.lower() == ".bat":
                wine_bin = shutil.which("wine")
                if not wine_bin:
                    raise RuntimeError(
                        "Wine não encontrado. Para rodar UnRen .bat no Linux, instale o Wine "
                        "(ex.: sudo apt install wine64)."
                    )
                subprocess.Popen([wine_bin, "cmd", "/c", destination.name], cwd=str(project))
            else:
                opened = _open_script_in_linux_terminal(destination, project)
                if not opened:
                    subprocess.Popen(["bash", str(destination)], cwd=str(project))

    return destination


def remover_descompactador_temporario(bat_path: str | Path) -> bool:
    target = Path(bat_path)
    if not target.exists():
        return False
    target.unlink()
    return True


def aplicar_force_language(project_dir: str | Path, force_language_src: str | Path) -> Path:
    project = Path(project_dir)
    source = Path(force_language_src)

    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Arquivo force_language inválido: {source}")

    game_dir = project / "game"
    if not game_dir.exists() or not game_dir.is_dir():
        raise FileNotFoundError(f"Pasta game não encontrada em: {game_dir}")

    destination = game_dir / "force_language.rpy"
    shutil.copy2(source, destination)
    return destination


def detectar_executavel_jogo(project_dir: str | Path) -> Path | None:
    project = Path(project_dir)
    if not project.exists() or not project.is_dir():
        return None

    candidates = [p for p in project.iterdir() if _is_game_launch_candidate(p)]
    if not candidates:
        return None

    project_name = project.name.lower()
    ignored_tokens = ("renpy", "unins", "crashpad", "updater")

    def score(path: Path) -> tuple[int, int]:
        stem = path.stem.lower()
        points = 0

        if stem == project_name:
            points += 120
        if project_name and project_name in stem:
            points += 40
        if not any(token in stem for token in ignored_tokens):
            points += 25
        if path.name.lower() in {"renpy.exe", "renpy.sh", "renpy"}:
            points -= 100

        size = path.stat().st_size if path.exists() else 0
        return (points, size)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def abrir_processo_jogo(exe_path: str | Path, project_dir: str | Path) -> subprocess.Popen[bytes]:
    exe = Path(exe_path)
    project = Path(project_dir)
    if not exe.exists() or not exe.is_file():
        raise FileNotFoundError(f"Executável do jogo não encontrado: {exe}")
    if not project.exists() or not project.is_dir():
        raise FileNotFoundError(f"Pasta de projeto inválida: {project}")

    if not _is_windows():
        if exe.suffix.lower() == ".exe":
            wine_bin = shutil.which("wine")
            if not wine_bin:
                raise RuntimeError(
                    "Wine não encontrado. Instale o Wine para abrir executáveis .exe no Linux."
                )
            return subprocess.Popen([wine_bin, str(exe)], cwd=str(project))
        if exe.suffix.lower() == ".command":
            return subprocess.Popen(["bash", str(exe)], cwd=str(project))
        if exe.suffix.lower() == ".sh" and not os.access(exe, os.X_OK):
            return subprocess.Popen(["bash", str(exe)], cwd=str(project))
    return subprocess.Popen([str(exe)], cwd=str(project))


def _game_dir(project_dir: str | Path) -> Path:
    project = Path(project_dir)
    game = project / "game"
    if not game.exists() or not game.is_dir():
        raise FileNotFoundError(f"Pasta game não encontrada em: {game}")
    return game


def copiar_un_files_para_game(
    project_dir: str | Path,
    un_rpy_source: str | Path,
    un_rpyc_source: str | Path,
) -> list[Path]:
    game = _game_dir(project_dir)
    src_rpy = Path(un_rpy_source)
    src_rpyc = Path(un_rpyc_source)

    if not src_rpy.exists() or not src_rpy.is_file():
        raise FileNotFoundError(f"Arquivo un.rpy não encontrado: {src_rpy}")
    if not src_rpyc.exists() or not src_rpyc.is_file():
        raise FileNotFoundError(f"Arquivo un.rpyc não encontrado: {src_rpyc}")

    dst_rpy = game / "un.rpy"
    dst_rpyc = game / "un.rpyc"
    shutil.copy2(src_rpy, dst_rpy)
    shutil.copy2(src_rpyc, dst_rpyc)
    return [dst_rpy, dst_rpyc]


def remover_un_files_de_game(project_dir: str | Path) -> list[Path]:
    game = _game_dir(project_dir)
    targets = [game / "un.rpy", game / "un.rpyc"]
    removed: list[Path] = []

    for target in targets:
        if target.exists():
            target.unlink()
            removed.append(target)

    return removed


def processo_ativo(proc: subprocess.Popen[bytes] | None) -> bool:
    return proc is not None and proc.poll() is None


