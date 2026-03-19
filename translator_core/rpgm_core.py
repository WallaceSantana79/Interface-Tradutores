from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TextIO

from .models import JobResult
from .utils import create_backup_snapshot, ensure_directory

IGNORAR_ARQUIVOS = ["System.json", "Tilesets.json", "Animations.json"]

TRANSLATIONS_FILENAME = "rpgm_translations.txt"
PLACEHOLDERS_FILENAME = "rpgm_placeholders.txt"
MAP_FILENAME = "rpgm_mapa_arquivos.json"
IMPORT_LOG_FILENAME = "rpgm_import_log.txt"
RPGM_DIALOGUE_WRAP_LIMIT = 78


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


def _iter_rpgm_json_files(data_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in data_dir.rglob("*.json")
            if path.is_file() and path.name not in IGNORAR_ARQUIVOS
        ],
        key=lambda path: path.relative_to(data_dir).as_posix().lower(),
    )


def resolve_rpgm_data_dir(project_dir: str | Path) -> Path | None:
    project = Path(project_dir)
    if not project.exists() or not project.is_dir():
        return None

    for candidate in [project / "www" / "data", project / "data", project]:
        if candidate.exists() and candidate.is_dir() and _iter_rpgm_json_files(candidate):
            return candidate

    return None


def describe_rpgm_data_dir(project_dir: str | Path, data_dir: str | Path) -> str:
    project = Path(project_dir).resolve()
    data = Path(data_dir).resolve()

    try:
        relative = data.relative_to(project)
    except ValueError:
        return str(data)

    text = relative.as_posix()
    return text if text != "." else "(pasta selecionada)"


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    pattern = (
        r"(\\[A-Za-z_]+(?:\[[^\]]+\])?|"
        r"\\[\\><\^._\|!\$\{\}\[\]]|"
        r"[<>].*?[<>])"
    )
    placeholders: list[str] = []

    def repl(match: re.Match[str]) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"[PLACEHOLDER_{idx}]"

    protegido = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
    return protegido, placeholders


def extrair_textos_json(caminho: Path) -> tuple[list[str], list[list[str]]]:
    textos: list[str] = []
    placeholders_list: list[list[str]] = []

    with caminho.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return [], []

    if isinstance(data, list):
        for item in data:
            if item is None:
                continue
            if "name" in item and isinstance(item["name"], str) and item["name"].strip():
                protegido, phs = proteger_placeholders(item["name"])
                textos.append(protegido)
                placeholders_list.append(phs)
            if (
                "description" in item
                and isinstance(item["description"], str)
                and item["description"].strip()
            ):
                protegido, phs = proteger_placeholders(item["description"])
                textos.append(protegido)
                placeholders_list.append(phs)

    elif isinstance(data, dict):
        events = data.get("events", [])
        for event in events:
            if event is None:
                continue
            pages = event.get("pages", [])
            for page in pages:
                if not isinstance(page, dict):
                    continue
                for cmd in page.get("list", []):
                    code = cmd.get("code")
                    params = cmd.get("parameters", [])
                    if not params:
                        continue

                    if code in [401, 405]:
                        texto_bruto = str(params[0])
                        protegido, phs = proteger_placeholders(texto_bruto)
                        textos.append(protegido)
                        placeholders_list.append(phs)
                    elif code == 102:
                        for escolha in params[0]:
                            protegido, phs = proteger_placeholders(str(escolha))
                            textos.append(protegido)
                            placeholders_list.append(phs)
                    elif code == 402:
                        texto_bruto = str(params[1])
                        protegido, phs = proteger_placeholders(texto_bruto)
                        textos.append(protegido)
                        placeholders_list.append(phs)
                    elif code in [355, 655]:
                        texto_script = str(params[0])
                        frases = re.findall(r'"([^"]{3,})"', texto_script)
                        for frase in frases:
                            if not frase.startswith("$") and not frase.endswith((".png", ".js")):
                                protegido, phs = proteger_placeholders(frase)
                                textos.append(protegido)
                                placeholders_list.append(phs)

    return textos, placeholders_list


def carregar_dados_globais(nome_txt: str | Path) -> dict[str, list[str]]:
    mapa: dict[str, list[str]] = {}
    path = Path(nome_txt)
    if not path.exists():
        return mapa

    with path.open("r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()
        mapa[filename] = linhas
    return mapa


def carregar_placeholders(nome_ph: str | Path) -> dict[str, list[list[str]]]:
    mapa: dict[str, list[list[str]]] = {}
    path = Path(nome_ph)
    if not path.exists():
        return mapa

    with path.open("r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()

        lista_phs: list[list[str]] = []
        for l in linhas:
            if l.strip() == "":
                lista_phs.append([])
            else:
                lista_phs.append(l.strip().split("|||"))
        mapa[filename] = lista_phs
    return mapa


def restaurar_placeholders(text: str, phs: list[str]) -> str:
    for i, ph in enumerate(phs):
        text = text.replace(f"[PLACEHOLDER_{i}]", ph)
    return text


def _wrap_dialogue_segment(segment: str, limit: int = RPGM_DIALOGUE_WRAP_LIMIT) -> str:
    if not segment or len(segment) <= limit:
        return segment

    protected, placeholders = proteger_placeholders(segment)
    parts = re.split(r"(\s+)", protected)

    lines: list[str] = []
    current = ""

    for part in parts:
        if part == "":
            continue

        candidate = f"{current}{part}" if current else part
        if current and not part.isspace() and len(candidate) > limit:
            lines.append(current.rstrip())
            current = part.lstrip()
        else:
            current = candidate

    if current.strip():
        lines.append(current.rstrip())

    if not lines:
        return segment

    # Evita a quebra "feia" quando sobra uma palavra muito curta na última linha.
    if len(lines) >= 2 and len(lines[-1].strip()) <= 10:
        previous = lines[-2].rstrip()
        tail = lines[-1].lstrip()
        if len(f"{previous} {tail}".strip()) <= limit + 12:
            lines[-2] = f"{previous} {tail}".strip()
            lines.pop()

    restored_lines = [restaurar_placeholders(line, placeholders) for line in lines]
    return "\n".join(restored_lines)


def wrap_dialogue_text_for_rpgm(text: str, limit: int = RPGM_DIALOGUE_WRAP_LIMIT) -> str:
    if not text or len(text) <= limit:
        return text

    chunks = text.split("\n")
    wrapped_chunks = [_wrap_dialogue_segment(chunk, limit=limit) for chunk in chunks]
    return "\n".join(wrapped_chunks)


def reintegrar_json(
    caminho: Path,
    traducoes: list[str],
    ph_map: list[list[str]],
    log: TextIO,
    *,
    display_name: str | None = None,
) -> None:
    name = display_name or caminho.name
    with caminho.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            log.write(f"[ERRO] {name} não é um JSON válido.\n")
            return

    idx_traducao = 0
    total_trads = len(traducoes)

    def injetar(texto_original: str) -> str:
        nonlocal idx_traducao
        if idx_traducao >= total_trads:
            return texto_original

        tr = traducoes[idx_traducao]
        tags = ph_map[idx_traducao] if idx_traducao < len(ph_map) else []
        tr_restaurado = restaurar_placeholders(tr, tags)

        if "[PLACEHOLDER_" in tr_restaurado:
            log.write(f"[FALHA DE TAG] {name} | idx {idx_traducao}\n")

        idx_traducao += 1
        return tr_restaurado

    if isinstance(data, list):
        for item in data:
            if item is None:
                continue
            if "name" in item and isinstance(item["name"], str) and item["name"].strip():
                item["name"] = injetar(item["name"])
            if (
                "description" in item
                and isinstance(item["description"], str)
                and item["description"].strip()
            ):
                item["description"] = injetar(item["description"])

    elif isinstance(data, dict):
        events = data.get("events", [])
        for event in events:
            if event is None:
                continue
            pages = event.get("pages", [])
            for page in pages:
                if not isinstance(page, dict):
                    continue
                for cmd in page.get("list", []):
                    code = cmd.get("code")
                    params = cmd.get("parameters", [])
                    if not params:
                        continue

                    if code in [401, 405]:
                        cmd["parameters"][0] = wrap_dialogue_text_for_rpgm(injetar(str(params[0])))
                    elif code == 102:
                        for i in range(len(cmd["parameters"][0])):
                            cmd["parameters"][0][i] = wrap_dialogue_text_for_rpgm(
                                injetar(str(cmd["parameters"][0][i]))
                            )
                    elif code == 402:
                        cmd["parameters"][1] = wrap_dialogue_text_for_rpgm(injetar(str(params[1])))
                    elif code in [355, 655]:
                        texto_script = str(params[0])
                        frases_originais = re.findall(r'"([^"]{3,})"', texto_script)
                        for frase in frases_originais:
                            if not frase.startswith("$") and not frase.endswith((".png", ".js")):
                                nova_frase = injetar(frase)
                                texto_script = texto_script.replace(
                                    f'"{frase}"', f'"{nova_frase}"'
                                )
                        cmd["parameters"][0] = texto_script

    with caminho.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)

    log.write(f"[OK] {name} processado. ({idx_traducao}/{total_trads} textos injetados)\n")


def _resolve_rpgm_mapped_file(data_dir: Path, stored_path: str) -> Path | None:
    normalized = str(stored_path or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return None

    simple_name = Path(normalized).name
    candidate = data_dir / Path(normalized)
    if candidate.exists() and candidate.is_file():
        return candidate

    if "/" not in normalized and "\\" not in str(stored_path):
        matches = [
            path
            for path in data_dir.rglob(simple_name)
            if path.is_file() and path.name.lower() == simple_name.lower()
        ]
        if len(matches) == 1:
            return matches[0]

    return None


def exportar_rpgm(project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)

    if not project.exists():
        return JobResult(success=False, message=f"Pasta não encontrada: {project}")

    data_dir = resolve_rpgm_data_dir(project)
    if data_dir is None:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado em www/data, data ou na pasta selecionada.",
        )

    arquivos_json = _iter_rpgm_json_files(data_dir)
    if not arquivos_json:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado na pasta selecionada.",
        )

    dict_txt: dict[str, list[str]] = {}
    dict_placeh: dict[str, list[list[str]]] = {}
    for caminho in arquivos_json:
        textos, phs_list = extrair_textos_json(caminho)
        if textos:
            relative_key = caminho.relative_to(data_dir).as_posix()
            dict_txt[relative_key] = textos
            dict_placeh[relative_key] = phs_list

    mapa_arquivos: dict[str, str] = {}
    translations_path = workspace / TRANSLATIONS_FILENAME
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME

    with translations_path.open("w", encoding="utf-8") as f_txt, placeholders_path.open(
        "w", encoding="utf-8"
    ) as f_ph:
        for i, (arq, textos) in enumerate(dict_txt.items()):
            chave_arquivo = f"ARQUIVO_{i:03d}"
            mapa_arquivos[chave_arquivo] = arq

            f_txt.write(f"=== {chave_arquivo} ===\n")
            for t in textos:
                f_txt.write(t + "\n")
            f_txt.write("\n")

            f_ph.write(f"=== {chave_arquivo} ===\n")
            for phs in dict_placeh[arq]:
                f_ph.write("|||".join(phs) + "\n")
            f_ph.write("\n")

    with map_path.open("w", encoding="utf-8") as f_map:
        json.dump(mapa_arquivos, f_map, indent=4, ensure_ascii=False)

    data_desc = describe_rpgm_data_dir(project, data_dir)
    return JobResult(
        success=True,
        message=f"Exportação RPGM concluída ({len(dict_txt)} arquivos). Pasta de dados usada: {data_desc}.",
        generated_files=[str(translations_path), str(placeholders_path), str(map_path)],
    )


def importar_rpgm(
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

    data_dir = resolve_rpgm_data_dir(project)
    if data_dir is None:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado em www/data, data ou na pasta selecionada.",
        )

    if not translated_path.exists():
        return JobResult(success=False, message=f"Arquivo traduzido não encontrado: {translated_path}")
    if not placeholders_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {placeholders_path}")
    if not map_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {map_path}")

    t_map = carregar_dados_globais(translated_path)
    p_map = carregar_placeholders(placeholders_path)

    with map_path.open("r", encoding="utf-8") as f_map:
        mapa_arquivos: dict[str, str] = json.load(f_map)

    warnings: list[str] = []
    targets: list[Path] = []
    for chave_arquivo, arq_original in mapa_arquivos.items():
        if chave_arquivo in t_map:
            caminho = _resolve_rpgm_mapped_file(data_dir, arq_original)
            if caminho is not None:
                targets.append(caminho)

    backup_dir: Path | None = None
    if criar_backup and targets:
        backup_dir = create_backup_snapshot("rpgm", project, workspace, targets)

    data_desc = describe_rpgm_data_dir(project, data_dir)
    with log_path.open("w", encoding="utf-8") as log:
        for chave_arquivo, arq_original in mapa_arquivos.items():
            if chave_arquivo not in t_map:
                continue

            caminho = _resolve_rpgm_mapped_file(data_dir, arq_original)
            if caminho is not None:
                phs = p_map.get(chave_arquivo, [])
                if len(t_map[chave_arquivo]) != len(phs):
                    alerta = (
                        f"{arq_original}: {len(t_map[chave_arquivo])} traduções vs {len(phs)} placeholders."
                    )
                    warnings.append(alerta)
                    log.write(f"[ALERTA DE DESVIO] {alerta}\n")
                reintegrar_json(
                    caminho,
                    t_map[chave_arquivo],
                    phs,
                    log,
                    display_name=arq_original,
                )
            else:
                if "/" not in str(arq_original) and "\\" not in str(arq_original):
                    aviso = (
                        f"Arquivo {arq_original} não encontrado na raiz da pasta de dados RPGM ({data_desc})."
                    )
                else:
                    aviso = (
                        f"Arquivo {arq_original} não encontrado dentro da pasta de dados RPGM ({data_desc})."
                    )
                warnings.append(aviso)
                log.write(f"[AVISO] {aviso}\n")

    message = f"Importação RPGM concluída. Pasta de dados usada: {data_desc}."
    if backup_dir:
        message += f" Backup criado em: {backup_dir}"

    return JobResult(
        success=True,
        message=message,
        warnings=warnings,
        generated_files=[str(log_path)],
        log_file=str(log_path),
    )


def parse_json_safely(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None
