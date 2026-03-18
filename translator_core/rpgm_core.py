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


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    pattern = r"(\\\\[a-zA-Z]+\[\d+\]|\\[a-zA-Z]+\[\d+\]|\\[><\^.\|!\]]|[<>].*?[<>])"
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


def reintegrar_json(caminho: Path, traducoes: list[str], ph_map: list[list[str]], log: TextIO) -> None:
    name = caminho.name
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
                        cmd["parameters"][0] = injetar(str(params[0]))
                    elif code == 102:
                        for i in range(len(cmd["parameters"][0])):
                            cmd["parameters"][0][i] = injetar(str(cmd["parameters"][0][i]))
                    elif code == 402:
                        cmd["parameters"][1] = injetar(str(params[1]))
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


def exportar_rpgm(project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)

    if not project.exists():
        return JobResult(success=False, message=f"Pasta não encontrada: {project}")

    arquivos_json = sorted(
        [
            p
            for p in project.glob("*.json")
            if p.is_file() and p.name not in IGNORAR_ARQUIVOS
        ],
        key=lambda p: p.name.lower(),
    )
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
            dict_txt[caminho.name] = textos
            dict_placeh[caminho.name] = phs_list

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

    return JobResult(
        success=True,
        message=f"Exportação RPGM concluída ({len(dict_txt)} arquivos).",
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
            caminho = project / arq_original
            if caminho.exists():
                targets.append(caminho)

    backup_dir: Path | None = None
    if criar_backup and targets:
        backup_dir = create_backup_snapshot("rpgm", project, workspace, targets)

    with log_path.open("w", encoding="utf-8") as log:
        for chave_arquivo, arq_original in mapa_arquivos.items():
            if chave_arquivo not in t_map:
                continue

            caminho = project / arq_original
            if caminho.exists():
                phs = p_map.get(chave_arquivo, [])
                if len(t_map[chave_arquivo]) != len(phs):
                    alerta = (
                        f"{arq_original}: {len(t_map[chave_arquivo])} traduções vs {len(phs)} placeholders."
                    )
                    warnings.append(alerta)
                    log.write(f"[ALERTA DE DESVIO] {alerta}\n")
                reintegrar_json(caminho, t_map[chave_arquivo], phs, log)
            else:
                aviso = f"Arquivo {arq_original} não encontrado na pasta selecionada."
                warnings.append(aviso)
                log.write(f"[AVISO] {aviso}\n")

    message = "Importação RPGM concluída."
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
