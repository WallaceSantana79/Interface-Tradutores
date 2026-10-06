from __future__ import annotations

import json
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import TextIO

from .models import JobResult
from .utils import create_backup_snapshot, ensure_directory

TRANSLATIONS_FILENAME = "all_translations.txt"
PLACEHOLDERS_FILENAME = "all_placeholders.txt"
MAP_FILENAME = "renpy_mapa_arquivos.json"
IMPORT_LOG_FILENAME = "renpy_import_log.txt"
EXPORT_PLAN_FILENAME = "renpy_export_plan.json"
MEMORY_ENV_VAR = "INTERFACE_TRADUTORES_MEMORY_DIR"

_TECHNICAL_FILE_EXT_RE = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|bmp|ico|mp3|ogg|wav|m4a|webm|mp4|avi|mov|"
    r"json|js|css|ttf|otf|woff2?|rpa|rpy|rpyc|exe|dll)(?:$|\?)",
    flags=re.IGNORECASE,
)
_TECHNICAL_ASSET_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"(?:[A-Za-z0-9_.\-]+(?:[\\/])[A-Za-z0-9_.\-/\\ ]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico|"
    r"mp3|ogg|wav|m4a|webm|mp4|avi|mov|json|js|css|ttf|otf|woff2?|rpa|rpy|rpyc|exe|dll)(?:\?[^\s\"']*)?)"
    r"|"
    r"(?:[A-Za-z0-9_.\-]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico|mp3|ogg|wav|m4a|webm|mp4|avi|mov|"
    r"json|js|css|ttf|otf|woff2?|rpa|rpy|rpyc|exe|dll)(?:\?[^\s\"']*)?)"
    r")"
    r"(?![A-Za-z0-9_])",
    flags=re.IGNORECASE,
)


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _translation_memory_root() -> Path:
    override = os.environ.get(MEMORY_ENV_VAR, "").strip()
    if override:
        return Path(override) / "renpy"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif os.name == "posix" and os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "InterfaceTradutores" / "translation_memory" / "renpy"


def _renpy_identity_root(project_dir: str | Path) -> Path:
    project = Path(project_dir).resolve()
    if project.name.lower() == "portuguese" and project.parent.name.lower() == "tl":
        maybe_game = project.parent.parent
        if maybe_game.name.lower() == "game":
            return maybe_game.parent
    if project.name.lower() == "tl" and project.parent.name.lower() == "game":
        return project.parent.parent
    if project.name.lower() == "game":
        return project.parent
    return project


def _slugify_game_name(name: str) -> str:
    raw = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    without_version = re.sub(r"-(?:v)?\d+(?:[-.]?\d+)*(?:[a-z])?(?:-.+)?$", "", slug)
    without_suffix = re.sub(r"-(?:pc|win|windows|linux|mac|osx)$", "", without_version)
    return without_suffix.strip("-") or slug or "renpy-game"


def _memory_game_key(project_dir: str | Path) -> str:
    return _slugify_game_name(_renpy_identity_root(project_dir).name)


def _memory_path_for_project(project_dir: str | Path) -> Path:
    return _translation_memory_root() / f"{_memory_game_key(project_dir)}.json"


def _source_hash(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _load_translation_memory(project_dir: str | Path) -> dict:
    path = _memory_path_for_project(project_dir)
    if not path.exists() or not path.is_file():
        return {
            "schema_version": 1,
            "game_key": _memory_game_key(project_dir),
            "entries": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema_version": 1,
            "game_key": _memory_game_key(project_dir),
            "entries": {},
        }
    if not isinstance(data, dict):
        data = {}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    data["schema_version"] = 1
    data["game_key"] = str(data.get("game_key") or _memory_game_key(project_dir))
    data["entries"] = entries
    return data


def _save_translation_memory(project_dir: str | Path, memory: dict) -> Path:
    path = _memory_path_for_project(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _memory_entry_for_source(memory: dict, source_text: str) -> dict | None:
    entry = memory.get("entries", {}).get(_source_hash(source_text))
    if not isinstance(entry, dict):
        return None
    if entry.get("source") != source_text:
        return None
    translation = entry.get("translation")
    if not isinstance(translation, str):
        return None
    return entry


def _remove_export_plan(workspace: Path) -> None:
    plan_path = workspace / EXPORT_PLAN_FILENAME
    try:
        if plan_path.exists():
            plan_path.unlink()
    except OSError:
        pass


def _load_export_plan(workspace: Path) -> dict | None:
    plan_path = workspace / EXPORT_PLAN_FILENAME
    if not plan_path.exists() or not plan_path.is_file():
        return None
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return None
    return data


def resolve_renpy_portuguese_dir(project_dir: str | Path) -> Path | None:
    project = Path(project_dir)
    candidates = [
        project / "game" / "tl" / "portuguese",
        project / "tl" / "portuguese",
        project / "portuguese" if project.name.lower() == "tl" else None,
    ]

    if project.name.lower() == "portuguese" and project.parent.name.lower() == "tl":
        candidates.append(project)

    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_dir():
            return candidate

    return None


def _collect_renpy_files(project: Path) -> list[Path]:
    # O fluxo Ren'Py deve trabalhar somente em game/tl/portuguese (ou equivalente se o
    # usuário selecionar game/ ou tl/ diretamente), sem alterar game/*.rpy nem renpy/common.
    tl_portuguese_dir = resolve_renpy_portuguese_dir(project)
    if not tl_portuguese_dir:
        return []

    files: list[Path] = []
    for p in tl_portuguese_dir.rglob("*.rpy"):
        if not p.is_file():
            continue
        files.append(p)

    files.sort(key=lambda p: str(p).lower())
    return files


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    placeholders: list[str] = []

    def store_placeholder(raw: str) -> str:
        idx = len(placeholders)
        placeholders.append(raw)
        return f"[PLACEHOLDER_{idx}]"

    def repl_technical(match: re.Match[str]) -> str:
        token = match.group(1)
        if not token:
            return match.group(0)
        lower = token.lower()
        if not _TECHNICAL_FILE_EXT_RE.search(lower):
            return match.group(0)
        if "/" not in token and "\\" not in token and len(token) < 5:
            return match.group(0)
        return store_placeholder(token)

    # Primeiro protege referências técnicas de assets para evitar "traduções" de caminhos.
    protegido = re.sub(_TECHNICAL_ASSET_REF_RE, repl_technical, texto)

    pattern = r"(\[(?!PLACEHOLDER_\d+\])[^\]]*?\]|%[sd]|{\#.*?}|\{/?[a-zA-Z0-9_]+(?:=[^}]+)?\})"

    def repl_default(match: re.Match[str]) -> str:
        return store_placeholder(match.group(0))

    protegido = re.sub(pattern, repl_default, protegido)
    return protegido, placeholders


def extract_all_quoted_text(s: str) -> list[str]:
    return re.findall(r'"((?:\\.|[^"\\])*)"', s)


def extrair_textos(caminho: Path) -> tuple[list[str], list[list[str]]]:
    textos: list[str] = []
    placeholders_list: list[list[str]] = []

    with caminho.open("r", encoding="utf-8-sig") as f:
        linhas = f.readlines()

    for linha in linhas:
        stripped = linha.lstrip()

        if stripped.startswith("#") and re.match(r"#\s*voice\b", stripped):
            textos.append("")
            placeholders_list.append([])
            continue

        if stripped.startswith("#") and '"' in stripped:
            matches = extract_all_quoted_text(linha)
            for quoted in matches:
                protegido, phs = proteger_placeholders(quoted)
                textos.append(protegido)
                placeholders_list.append(phs)
            continue

        if stripped.startswith("old ") and '"' in stripped:
            matches = extract_all_quoted_text(linha)
            for quoted in matches:
                protegido, phs = proteger_placeholders(quoted)
                textos.append(protegido)
                placeholders_list.append(phs)
            continue

    return textos, placeholders_list


def carregar_traducoes_global(nome_txt: str | Path) -> dict[str, list[str]]:
    with Path(nome_txt).open("r", encoding="utf-8-sig") as f:
        content = f.read()
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    partes = [sec for sec in content.split("=== ") if sec.strip()]
    mapa: dict[str, list[str]] = {}
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        blocos = body.split("\n\n")
        while len(blocos) > 0 and blocos[-1].strip() == "":
            blocos.pop()
        mapa[filename] = blocos
    return mapa


def carregar_placeholders_global(nome_ph: str | Path) -> dict[str, list[list[str]]]:
    with Path(nome_ph).open("r", encoding="utf-8-sig") as f:
        content = f.read()
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    partes = [sec for sec in content.split("=== ") if sec.strip()]
    mapa: dict[str, list[list[str]]] = {}
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()

        linhas = body.split("\n")
        if len(linhas) > 0 and linhas[-1] == "":
            linhas.pop()

        lista_phs: list[list[str]] = []
        for linha in linhas:
            l = linha.strip()
            if l == "" or l == "NONE":
                lista_phs.append([])
            else:
                lista_phs.append(l.split("|||"))
        mapa[filename] = lista_phs
    return mapa


def restaurar_placeholders(text: str, phs: list[str]) -> str:
    # Some Ren'Py text tags can contain a protected technical asset, producing
    # nested placeholders such as [PLACEHOLDER_1] -> "{image=[PLACEHOLDER_0]}".
    for _ in range(len(phs) + 1):
        before = text
        for i in range(len(phs) - 1, -1, -1):
            text = text.replace(f"[PLACEHOLDER_{i}]", phs[i])
        if text == before or "[PLACEHOLDER_" not in text:
            break
    return text


def _escape_renpy_inner_quotes(text: str) -> str:
    escaped: list[str] = []
    for index, char in enumerate(text):
        if char != '"':
            escaped.append(char)
            continue

        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            slash_count += 1
            cursor -= 1

        if slash_count % 2 == 0:
            escaped.append("\\")
        escaped.append(char)

    return "".join(escaped)


def corrigir_aspas(text: str) -> str:
    text = _escape_renpy_inner_quotes(text)
    text = re.sub(r'\\"(\[.*?\])\\"', r"'\1'", text)
    return text


def reintegrar(path: Path, traducoes: list[str], ph_map: list[list[str]], log: TextIO) -> None:
    name = path.name
    with path.open("r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    new_lines: list[str] = []
    idx = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith("#") and re.match(r"#\s*voice\b", stripped):
            new_lines.append(line)
            if idx < len(traducoes):
                idx += 1
            i += 1
            continue

        if stripped.startswith("voice ") and '"' in line:
            new_lines.append(line)
            i += 1
            continue

        if stripped.startswith("#") and '"' in stripped:
            matches = re.findall(r'"((?:\\.|[^"\\])*)"', stripped)
            qtd = len(matches)

            if qtd == 0:
                new_lines.append(line)
                i += 1
                continue

            if qtd >= 2:
                new_lines.append(line)
                j = i + 1
                while j < len(lines) and (
                    lines[j].strip().startswith("voice ")
                    or lines[j].lstrip().startswith("# voice")
                ):
                    new_lines.append(lines[j])
                    j += 1

                indent = re.match(r"^(\s*)", lines[j]).group(1) if j < len(lines) else ""

                if idx + qtd <= len(traducoes):
                    tr_segments = []
                    for k in range(qtd):
                        tr = traducoes[idx + k]
                        tags = ph_map[idx + k] if idx + k < len(ph_map) else []
                        tr = restaurar_placeholders(tr, tags)
                        tr = corrigir_aspas(tr)
                        if "[PLACEHOLDER_" in tr:
                            log.write(f"[FALHA DE TAG] {name} | Multi | idx {idx + k}\n")
                        tr_segments.append(tr)

                    out = indent + " ".join(f'"{seg}"' for seg in tr_segments) + "\n"
                    new_lines.append(out)
                    log.write(f"[OK] {name} - multi-quote idx {idx}..{idx + qtd - 1}\n")
                    idx += qtd
                else:
                    if j < len(lines):
                        new_lines.append(lines[j])

                i = j + 1
                continue

            m_pure = re.match(r'^\s*#\s*"(?P<orig>.*)"', stripped)
            if m_pure:
                new_lines.append(line)
                if idx < len(traducoes):
                    next_line = lines[i + 1] if i + 1 < len(lines) else ""
                    indent = re.match(r"^(\s*)", next_line).group(1) if next_line else ""
                    tr = traducoes[idx]
                    tags = ph_map[idx] if idx < len(ph_map) else []
                    tr = restaurar_placeholders(tr, tags)
                    tr = corrigir_aspas(tr)
                    if "[PLACEHOLDER_" in tr:
                        log.write(f"[FALHA DE TAG] {name} | Fala Pura | idx {idx}\n")
                    new_lines.append(f'{indent}"{tr}"\n')
                    log.write(f"[OK] {name} - fala pura idx {idx}\n")
                    idx += 1
                    i += 2
                    continue
                i += 1
                continue

            m_cmd = re.match(r'^\s*#\s*(?P<cmd>[^"]+?)\s*".*"', stripped)
            if m_cmd:
                cmd = m_cmd.group("cmd").strip()
                new_lines.append(line)

                if idx < len(traducoes):
                    j = i + 1
                    while j < len(lines) and (
                        lines[j].strip().startswith("voice ")
                        or lines[j].lstrip().startswith("# voice")
                    ):
                        new_lines.append(lines[j])
                        j += 1

                    if j < len(lines):
                        next_line = lines[j]
                        indent = re.match(r"^(\s*)", next_line).group(1)
                        tr = traducoes[idx]
                        tags = ph_map[idx] if idx < len(ph_map) else []
                        tr = restaurar_placeholders(tr, tags)
                        tr = corrigir_aspas(tr)

                        if "[PLACEHOLDER_" in tr:
                            log.write(f"[FALHA DE TAG] {name} | Cmd | idx {idx}\n")

                        next_strip = next_line.strip()
                        if next_strip.startswith('"'):
                            new_lines.append(f'{indent}{cmd} "{tr}"\n')
                        else:
                            mc = re.match(
                                r'^(?P<ind>\s*)(?P<cmd2>[^"]+?)\s*".*?"(?P<suf>.*)$',
                                next_line,
                            )
                            if mc and mc.group("cmd2").strip() == cmd:
                                ind2 = mc.group("ind")
                                suf = mc.group("suf")
                                new_lines.append(f'{ind2}{cmd} "{tr}"{suf}\n')
                            else:
                                new_lines.append(f'{indent}{cmd} "{tr}"\n')

                        log.write(f"[OK] {name} - cmd idx {idx}\n")
                        idx += 1
                        i = j + 1
                        continue

            if idx + qtd <= len(traducoes):
                idx += qtd
            new_lines.append(line)
            i += 1
            continue

        oldm = re.match(r'^(?P<ind>\s*)old\s*".*"', line)
        if oldm and idx < len(traducoes):
            matches = re.findall(r'"((?:\\.|[^"\\])*)"', line)
            qtd = len(matches) if matches else 1

            new_lines.append(line)
            tr = traducoes[idx]
            tags = ph_map[idx] if idx < len(ph_map) else []
            tr = restaurar_placeholders(tr, tags)
            tr = corrigir_aspas(tr)

            if "[PLACEHOLDER_" in tr:
                log.write(f"[FALHA DE TAG] {name} | Old | idx {idx}\n")

            if i + 1 < len(lines) and re.match(r'^\s*new\s*".*"', lines[i + 1]):
                ind2 = re.match(r"^(\s*)", lines[i + 1]).group(1)
                new_lines.append(f'{ind2}new "{tr}"\n')
                i += 2
            else:
                ind2 = oldm.group("ind") + "    "
                new_lines.append(f'{ind2}new "{tr}"\n')
                i += 1

            log.write(f"[OK] {name} - old/new idx {idx}\n")
            idx += qtd
            continue

        new_lines.append(line)
        i += 1

    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    with path.open("w", encoding="utf-8-sig") as f:
        f.writelines(new_lines)


def exportar_renpy(
    project_dir: str | Path,
    workspace_dir: str | Path,
    *,
    use_translation_memory: bool = True,
) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)

    arquivos_rpy = _collect_renpy_files(project)

    if not arquivos_rpy:
        return JobResult(
            success=False,
            message="Nenhum arquivo .rpy encontrado na pasta selecionada.",
        )

    export_entries: list[tuple[str, list[str], list[list[str]]]] = []

    for caminho in arquivos_rpy:
        textos, phs_list = extrair_textos(caminho)
        if textos:
            relpath = caminho.relative_to(project).as_posix()
            export_entries.append((relpath, textos, phs_list))

    mapa_arquivos: dict[str, str] = {}
    translations_path = workspace / TRANSLATIONS_FILENAME
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME
    plan_path = workspace / EXPORT_PLAN_FILENAME
    memory = _load_translation_memory(project) if use_translation_memory else None
    total_texts = sum(
        sum(1 for texto in textos if texto != "")
        for _relpath, textos, _placeholders in export_entries
    )
    reused_count = 0
    new_count = 0
    plan_files: list[dict] = []

    with translations_path.open("w", encoding="utf-8-sig") as f_txt, placeholders_path.open(
        "w", encoding="utf-8-sig"
    ) as f_ph:
        for i, (relpath, textos, placeholders) in enumerate(export_entries):
            chave_arquivo = f"ARQUIVO_{i:03d}"
            mapa_arquivos[chave_arquivo] = relpath
            visible_texts: list[str] = []
            visible_placeholders: list[list[str]] = []
            plan_items: list[dict] = []

            for idx_t, texto in enumerate(textos):
                phs = placeholders[idx_t]
                # A comment such as "# voice" occupies a reintegration slot but is not dialogue.
                if texto == "":
                    plan_items.append(
                        {
                            "status": "skip",
                            "source": "",
                            "placeholders": phs,
                        }
                    )
                    continue
                hash_value = _source_hash(texto)
                memory_entry = _memory_entry_for_source(memory, texto) if memory else None
                if memory_entry is not None:
                    reused_count += 1
                    plan_items.append(
                        {
                            "status": "memory",
                            "source": texto,
                            "hash": hash_value,
                            "translation": memory_entry["translation"],
                            "placeholders": phs,
                        }
                    )
                    continue

                new_count += 1
                visible_texts.append(texto)
                visible_placeholders.append(phs)
                plan_items.append(
                    {
                        "status": "new",
                        "source": texto,
                        "hash": hash_value,
                        "new_index": len(visible_texts) - 1,
                        "placeholders": phs,
                    }
                )

            plan_files.append({"key": chave_arquivo, "relpath": relpath, "items": plan_items})
            output_texts = visible_texts if use_translation_memory else textos
            output_placeholders = visible_placeholders if use_translation_memory else placeholders

            f_txt.write(f"=== {chave_arquivo} ===\n")
            for idx_t, texto in enumerate(output_texts):
                f_txt.write(texto)
                if idx_t < len(output_texts) - 1:
                    f_txt.write("\n\n")
            f_txt.write("\n\n")

            f_ph.write(f"=== {chave_arquivo} ===\n")
            for phs in output_placeholders:
                f_ph.write("|||".join(phs) + "\n")
            f_ph.write("\n")

    with map_path.open("w", encoding="utf-8") as f_map:
        json.dump(mapa_arquivos, f_map, indent=4, ensure_ascii=False)

    generated_files = [str(translations_path), str(placeholders_path), str(map_path)]
    warnings: list[str] = []
    if use_translation_memory:
        plan = {
            "schema_version": 1,
            "game_key": _memory_game_key(project),
            "memory_path": str(_memory_path_for_project(project)),
            "total_texts": total_texts,
            "reused_count": reused_count,
            "new_count": new_count,
            "created_at": _utc_now_iso(),
            "files": plan_files,
        }
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        generated_files.append(str(plan_path))
        warnings.append(
            f"Memória Ren'Py: {total_texts} fala(s), {reused_count} reaproveitada(s), {new_count} nova(s)."
        )
    else:
        _remove_export_plan(workspace)

    return JobResult(
        success=True,
        message=f"Exportação Ren'Py concluída ({len(export_entries)} arquivos).",
        warnings=warnings,
        generated_files=generated_files,
    )


def expected_new_counts_from_plan(workspace_dir: str | Path) -> dict[str, int] | None:
    plan = _load_export_plan(Path(workspace_dir))
    if plan is None:
        return None
    counts: dict[str, int] = {}
    for file_entry in plan.get("files", []):
        if not isinstance(file_entry, dict):
            continue
        key = str(file_entry.get("key") or "")
        items = file_entry.get("items")
        if not key or not isinstance(items, list):
            continue
        counts[key] = sum(1 for item in items if isinstance(item, dict) and item.get("status") == "new")
    return counts


def _build_full_translations_from_plan(
    plan: dict,
    t_map: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[list[str]]], list[str]]:
    full_translations: dict[str, list[str]] = {}
    full_placeholders: dict[str, list[list[str]]] = {}
    warnings: list[str] = []

    for file_entry in plan.get("files", []):
        if not isinstance(file_entry, dict):
            continue
        key = str(file_entry.get("key") or "")
        items = file_entry.get("items")
        if not key or not isinstance(items, list):
            continue

        new_translations = t_map.get(key, [])
        new_cursor = 0
        full_translations[key] = []
        full_placeholders[key] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            placeholders = item.get("placeholders")
            if not isinstance(placeholders, list):
                placeholders = []
            clean_placeholders = [str(ph) for ph in placeholders]
            status = item.get("status")

            if status == "skip":
                translation = str(item.get("source") or "")
            elif status == "memory":
                translation = item.get("translation")
                if not isinstance(translation, str):
                    translation = str(item.get("source") or "")
                    warnings.append(f"Chave {key}: item reaproveitado sem tradução; usando texto original.")
            else:
                if new_cursor >= len(new_translations):
                    translation = str(item.get("source") or "")
                    warnings.append(f"Chave {key}: tradução nova ausente no índice {new_cursor}; usando texto original.")
                else:
                    translation = new_translations[new_cursor]
                new_cursor += 1

            full_translations[key].append(translation)
            full_placeholders[key].append(clean_placeholders)

        if new_cursor < len(new_translations):
            warnings.append(
                f"Chave {key}: {len(new_translations) - new_cursor} tradução(ões) extra(s) ignorada(s)."
            )

    return full_translations, full_placeholders, warnings


def _update_translation_memory_from_import(
    project: Path,
    plan: dict,
    full_translations: dict[str, list[str]],
) -> Path:
    memory = _load_translation_memory(project)
    entries = memory.setdefault("entries", {})
    now = _utc_now_iso()

    for file_entry in plan.get("files", []):
        if not isinstance(file_entry, dict):
            continue
        key = str(file_entry.get("key") or "")
        relpath = str(file_entry.get("relpath") or "")
        items = file_entry.get("items")
        translations = full_translations.get(key, [])
        if not key or not isinstance(items, list):
            continue

        for idx, item in enumerate(items):
            if not isinstance(item, dict) or idx >= len(translations):
                continue
            source = str(item.get("source") or "")
            if not source:
                continue
            entry_hash = _source_hash(source)
            previous = entries.get(entry_hash)
            if not isinstance(previous, dict):
                previous = {}
            created_at = str(previous.get("created_at") or now)
            raw_use_count = previous.get("use_count")
            use_count = raw_use_count if isinstance(raw_use_count, int) else 0
            placeholders = item.get("placeholders")
            if not isinstance(placeholders, list):
                placeholders = []
            entries[entry_hash] = {
                "source": source,
                "translation": translations[idx],
                "placeholders": [str(ph) for ph in placeholders],
                "last_relpath": relpath,
                "use_count": use_count + 1,
                "created_at": created_at,
                "updated_at": now,
            }

    memory["game_key"] = _memory_game_key(project)
    memory["updated_at"] = now
    return _save_translation_memory(project, memory)


def importar_renpy(
    project_dir: str | Path,
    workspace_dir: str | Path,
    translated_txt_path: str | Path,
    criar_backup: bool = False,
) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)
    translated_path = Path(translated_txt_path)
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME
    log_path = workspace / IMPORT_LOG_FILENAME

    if not translated_path.exists():
        return JobResult(success=False, message=f"Arquivo traduzido não encontrado: {translated_path}")
    if not placeholders_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {placeholders_path}")
    if not map_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {map_path}")

    t_map = carregar_traducoes_global(translated_path)
    p_map = carregar_placeholders_global(placeholders_path)
    plan = _load_export_plan(workspace)
    plan_warnings: list[str] = []
    if plan is not None:
        if plan.get("game_key") != _memory_game_key(project):
            return JobResult(
                success=False,
                message=(
                    "O plano de memória Ren'Py não pertence ao projeto selecionado. "
                    "Execute uma nova exportação antes de importar."
                ),
            )
        t_map, p_map, plan_warnings = _build_full_translations_from_plan(plan, t_map)

    with map_path.open("r", encoding="utf-8") as f_map:
        mapa_arquivos: dict[str, str] = json.load(f_map)

    warnings: list[str] = list(plan_warnings)

    targets: list[Path] = []
    key_to_target: dict[str, Path] = {}
    for chave, relpath in mapa_arquivos.items():
        full = (project / relpath).resolve()
        if full.exists() and full.is_file():
            targets.append(full)
            key_to_target[chave] = full
        else:
            warnings.append(f"Arquivo mapeado não encontrado no projeto: {relpath}")

    backup_dir: Path | None = None
    if criar_backup and targets:
        backup_dir = create_backup_snapshot("renpy", project, workspace, targets)

    with log_path.open("w", encoding="utf-8") as log:
        for chave, full in key_to_target.items():
            if chave not in t_map:
                aviso = f"{full} não foi processado (sem traduções para a chave {chave})."
                warnings.append(aviso)
                log.write(f"[AVISO] {aviso}\n")
                continue

            if chave not in p_map:
                aviso = f"{full} não encontrou mapa de placeholders."
                warnings.append(aviso)
                log.write(f"[ERRO GRAVE] {aviso}\n")
                p_tags: list[list[str]] = []
            else:
                p_tags = p_map[chave]
                if len(t_map[chave]) != len(p_tags):
                    alerta = (
                        f"{full}: {len(t_map[chave])} traduções vs {len(p_tags)} placeholders."
                    )
                    warnings.append(alerta)
                    log.write(f"[ALERTA DE DESVIO] {alerta}\n")

            reintegrar(full, t_map[chave], p_tags, log)

    memory_path: Path | None = None
    if plan is not None:
        try:
            memory_path = _update_translation_memory_from_import(project, plan, t_map)
        except OSError as exc:
            warnings.append(f"Não foi possível atualizar a memória Ren'Py: {exc}")

    message = "Importação Ren'Py concluída."
    if backup_dir:
        message += f" Backup criado em: {backup_dir}"
    if memory_path:
        message += f" Memória atualizada em: {memory_path}"

    return JobResult(
        success=True,
        message=message,
        warnings=warnings,
        generated_files=[str(log_path)],
        log_file=str(log_path),
    )
