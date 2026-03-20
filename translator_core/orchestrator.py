from __future__ import annotations

from pathlib import Path

from .models import JobResult
from .renpy_core import (
    MAP_FILENAME as RENPY_MAP,
    PLACEHOLDERS_FILENAME as RENPY_PLACEHOLDERS,
    TRANSLATIONS_FILENAME as RENPY_TRANSLATIONS,
    carregar_placeholders_global as renpy_load_placeholders,
    carregar_traducoes_global as renpy_load_translations,
    exportar_renpy,
    importar_renpy,
    resolve_renpy_portuguese_dir,
)
from .rpgm_core import (
    MAP_FILENAME as RPGM_MAP,
    PLACEHOLDERS_FILENAME as RPGM_PLACEHOLDERS,
    TRANSLATIONS_FILENAME as RPGM_TRANSLATIONS,
    carregar_dados_globais as rpgm_load_translations,
    carregar_placeholders as rpgm_load_placeholders,
    describe_rpgm_data_dir,
    exportar_rpgm,
    importar_rpgm,
    resolve_rpgm_data_dir,
)
from .unity_core import (
    MAP_FILENAME as UNITY_MAP,
    PLACEHOLDERS_FILENAME as UNITY_PLACEHOLDERS,
    TRANSLATIONS_FILENAME as UNITY_TRANSLATIONS,
    carregar_dados_globais as unity_load_translations,
    carregar_placeholders as unity_load_placeholders,
    describe_unity_data_dir,
    exportar_unity,
    importar_unity,
    resolve_unity_data_dir,
)

ENGINE_RENPY = "renpy"
ENGINE_RPGM = "rpgm"
ENGINE_UNITY = "unity"


def normalize_engine(engine: str) -> str:
    raw = (engine or "").strip().lower().replace("'", "")
    if raw in {"renpy", "ren py", "ren-py"}:
        return ENGINE_RENPY
    if raw in {"rpgm", "rpg maker", "rpgmaker"}:
        return ENGINE_RPGM
    if raw in {"unity"}:
        return ENGINE_UNITY
    return raw


def engine_workspace_dir(engine: str, workspace_root: str | Path) -> Path:
    normalized = normalize_engine(engine)
    return Path(workspace_root) / normalized


def _validate_project_directory(engine: str, project_dir: Path) -> JobResult:
    if not project_dir.exists() or not project_dir.is_dir():
        return JobResult(False, f"Pasta de projeto inválida: {project_dir}")

    if engine == ENGINE_RENPY:
        tl_portuguese = resolve_renpy_portuguese_dir(project_dir)
        if tl_portuguese is None:
            return JobResult(
                False,
                "Pasta Ren'Py inválida: não encontrei game/tl/portuguese.",
            )
        has_files = any(p.is_file() for p in tl_portuguese.rglob("*.rpy"))
        if not has_files:
            return JobResult(
                False,
                "Pasta Ren'Py inválida: game/tl/portuguese não possui arquivos .rpy.",
            )
    elif engine == ENGINE_RPGM:
        data_dir = resolve_rpgm_data_dir(project_dir)
        if data_dir is None:
            return JobResult(
                False,
                "Pasta RPGM inválida: não encontrei .json em www/data, data ou na pasta selecionada.",
            )
        data_desc = describe_rpgm_data_dir(project_dir, data_dir)
        return JobResult(True, f"Pasta RPGM válida. Pasta de dados: {data_desc}.")
    elif engine == ENGINE_UNITY:
        data_dir, data_warnings = resolve_unity_data_dir(project_dir)
        if data_dir is None:
            message = "Pasta Unity inválida: não encontrei pasta *_Data na raiz selecionada."
            if data_warnings:
                message += " " + " ".join(data_warnings)
            return JobResult(False, message)
        data_desc = describe_unity_data_dir(project_dir, data_dir)
        return JobResult(True, f"Pasta Unity válida. Pasta de dados: {data_desc}.", warnings=data_warnings)
    else:
        return JobResult(False, f"Engine não suportada: {engine}")

    return JobResult(True, "Pasta válida.")


def exportar(engine: str, project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
    normalized = normalize_engine(engine)
    project = Path(project_dir)
    workspace = engine_workspace_dir(normalized, workspace_dir)

    valid = _validate_project_directory(normalized, project)
    if not valid.success:
        return valid

    if normalized == ENGINE_RENPY:
        return exportar_renpy(project, workspace)
    if normalized == ENGINE_RPGM:
        return exportar_rpgm(project, workspace)
    if normalized == ENGINE_UNITY:
        return exportar_unity(project, workspace)
    return JobResult(False, f"Engine não suportada: {engine}")


def pre_validar_importacao(
    engine: str,
    project_dir: str | Path,
    workspace_dir: str | Path,
    translated_txt_path: str | Path,
) -> JobResult:
    normalized = normalize_engine(engine)
    project = Path(project_dir)
    translated = Path(translated_txt_path)
    workspace = engine_workspace_dir(normalized, workspace_dir)

    valid_project = _validate_project_directory(normalized, project)
    if not valid_project.success:
        return valid_project

    if not translated.exists() or not translated.is_file():
        return JobResult(False, f"Arquivo traduzido inválido: {translated}")

    warnings: list[str] = []

    if normalized == ENGINE_RENPY:
        placeholders = workspace / RENPY_PLACEHOLDERS
        map_file = workspace / RENPY_MAP
        if not placeholders.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {placeholders}")
        if not map_file.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {map_file}")

        t_map = renpy_load_translations(translated)
        p_map = renpy_load_placeholders(placeholders)
        if not t_map:
            return JobResult(False, "TXT traduzido não possui blocos válidos (Ren'Py).")

        for chave, tr_list in t_map.items():
            ph_list = p_map.get(chave)
            if ph_list is None:
                warnings.append(f"Chave {chave} sem placeholders correspondentes.")
                continue
            if len(tr_list) != len(ph_list):
                warnings.append(
                    f"Chave {chave}: {len(tr_list)} traduções vs {len(ph_list)} placeholders."
                )

    elif normalized == ENGINE_RPGM:
        placeholders = workspace / RPGM_PLACEHOLDERS
        map_file = workspace / RPGM_MAP
        if not placeholders.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {placeholders}")
        if not map_file.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {map_file}")

        t_map = rpgm_load_translations(translated)
        p_map = rpgm_load_placeholders(placeholders)
        if not t_map:
            return JobResult(False, "TXT traduzido não possui blocos válidos (RPGM).")

        for chave, tr_list in t_map.items():
            ph_list = p_map.get(chave)
            if ph_list is None:
                warnings.append(f"Chave {chave} sem placeholders correspondentes.")
                continue
            if len(tr_list) != len(ph_list):
                warnings.append(
                    f"Chave {chave}: {len(tr_list)} traduções vs {len(ph_list)} placeholders."
                )
    elif normalized == ENGINE_UNITY:
        placeholders = workspace / UNITY_PLACEHOLDERS
        map_file = workspace / UNITY_MAP
        if not placeholders.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {placeholders}")
        if not map_file.exists():
            return JobResult(False, f"Arquivo obrigatório ausente: {map_file}")

        t_map = unity_load_translations(translated)
        p_map = unity_load_placeholders(placeholders)
        if not t_map:
            return JobResult(False, "TXT traduzido não possui blocos válidos (Unity).")

        for chave, tr_list in t_map.items():
            ph_list = p_map.get(chave)
            if ph_list is None:
                warnings.append(f"Chave {chave} sem placeholders correspondentes.")
                continue
            if len(tr_list) != len(ph_list):
                warnings.append(
                    f"Chave {chave}: {len(tr_list)} traduções vs {len(ph_list)} placeholders."
                )
    else:
        return JobResult(False, f"Engine não suportada: {engine}")

    message = "Pré-validação concluída."
    if warnings:
        message = "Pré-validação concluída com alertas."
    return JobResult(True, message, warnings=warnings)


def importar(
    engine: str,
    project_dir: str | Path,
    workspace_dir: str | Path,
    translated_txt_path: str | Path,
    criar_backup: bool,
) -> JobResult:
    normalized = normalize_engine(engine)
    workspace = engine_workspace_dir(normalized, workspace_dir)

    pre = pre_validar_importacao(normalized, project_dir, workspace_dir, translated_txt_path)
    if not pre.success:
        return pre

    if normalized == ENGINE_RENPY:
        result = importar_renpy(
            project_dir,
            workspace,
            translated_txt_path=translated_txt_path,
            criar_backup=criar_backup,
        )
    elif normalized == ENGINE_RPGM:
        result = importar_rpgm(
            project_dir,
            workspace,
            translated_txt_path=translated_txt_path,
            criar_backup=criar_backup,
        )
    elif normalized == ENGINE_UNITY:
        result = importar_unity(
            project_dir,
            workspace,
            translated_txt_path=translated_txt_path,
            criar_backup=criar_backup,
        )
    else:
        return JobResult(False, f"Engine não suportada: {engine}")

    all_warnings = pre.warnings + result.warnings
    result.warnings = all_warnings
    return result


def translation_filename_for_engine(engine: str) -> str:
    normalized = normalize_engine(engine)
    if normalized == ENGINE_RENPY:
        return RENPY_TRANSLATIONS
    if normalized == ENGINE_RPGM:
        return RPGM_TRANSLATIONS
    if normalized == ENGINE_UNITY:
        return UNITY_TRANSLATIONS
    raise ValueError(f"Engine não suportada: {engine}")
