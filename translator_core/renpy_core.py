from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TextIO

from .models import JobResult
from .utils import create_backup_snapshot, ensure_directory

IGNORAR_ARQUIVOS = ["common.rpy", "options.rpy", "screens.rpy"]

TRANSLATIONS_FILENAME = "all_translations.txt"
PLACEHOLDERS_FILENAME = "all_placeholders.txt"
MAP_FILENAME = "renpy_mapa_arquivos.json"
IMPORT_LOG_FILENAME = "renpy_import_log.txt"


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


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
        if not p.is_file() or p.name in IGNORAR_ARQUIVOS:
            continue
        files.append(p)

    files.sort(key=lambda p: str(p).lower())
    return files


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    pattern = r"(\[.*?\]|%[sd]|{\#.*?}|\{/?[a-zA-Z0-9_]+(?:=[^}]+)?\})"

    placeholders: list[str] = []

    def repl(match: re.Match[str]) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"[PLACEHOLDER_{idx}]"

    protegido = re.sub(pattern, repl, texto)
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
    for i, ph in enumerate(phs):
        text = text.replace(f"[PLACEHOLDER_{i}]", ph)
    return text


def corrigir_aspas(text: str) -> str:
    text = re.sub(r'(?<!\\)"', r'\\"', text)
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


def exportar_renpy(project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
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

    with translations_path.open("w", encoding="utf-8-sig") as f_txt, placeholders_path.open(
        "w", encoding="utf-8-sig"
    ) as f_ph:
        for i, (relpath, textos, placeholders) in enumerate(export_entries):
            chave_arquivo = f"ARQUIVO_{i:03d}"
            mapa_arquivos[chave_arquivo] = relpath

            f_txt.write(f"=== {chave_arquivo} ===\n")
            for idx_t, texto in enumerate(textos):
                f_txt.write(texto)
                if idx_t < len(textos) - 1:
                    f_txt.write("\n\n")
            f_txt.write("\n\n")

            f_ph.write(f"=== {chave_arquivo} ===\n")
            for phs in placeholders:
                f_ph.write("|||".join(phs) + "\n")
            f_ph.write("\n")

    with map_path.open("w", encoding="utf-8") as f_map:
        json.dump(mapa_arquivos, f_map, indent=4, ensure_ascii=False)

    return JobResult(
        success=True,
        message=f"Exportação Ren'Py concluída ({len(export_entries)} arquivos).",
        generated_files=[str(translations_path), str(placeholders_path), str(map_path)],
    )


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

    with map_path.open("r", encoding="utf-8") as f_map:
        mapa_arquivos: dict[str, str] = json.load(f_map)

    warnings: list[str] = []

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

    message = "Importação Ren'Py concluída."
    if backup_dir:
        message += f" Backup criado em: {backup_dir}"

    return JobResult(
        success=True,
        message=message,
        warnings=warnings,
        generated_files=[str(log_path)],
        log_file=str(log_path),
    )
