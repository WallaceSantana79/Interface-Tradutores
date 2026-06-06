from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import sys
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .models import JobResult
from .utils import create_backup_snapshot, ensure_directory

try:
    import UnityPy  # type: ignore[import-not-found]
except ImportError:
    try:
        import site

        user_site = site.getusersitepackages()
        if isinstance(user_site, str) and user_site and user_site not in sys.path:
            sys.path.append(user_site)
        import UnityPy  # type: ignore[import-not-found,reimported]
    except Exception:
        UnityPy = None

TRANSLATIONS_FILENAME = "unity_translations.txt"
PLACEHOLDERS_FILENAME = "unity_placeholders.txt"
MAP_FILENAME = "unity_mapa_arquivos.json"
IMPORT_LOG_FILENAME = "unity_import_log.txt"

SUPPORTED_EXTENSIONS = {".json", ".csv", ".tsv", ".txt", ".xml", ".yml", ".yaml"}
EXCLUDED_SUFFIXES = {".assets", ".bundle", ".ress", ".dll", ".exe", ".meta", ".manifest"}
UNITY_BINARY_FILENAMES = {
    "globalgamemanagers",
    "globalgamemanagers.assets",
    "resources.assets",
    "sharedassets0.assets",
    "sharedassets1.assets",
}
UNITY_IGNORED_RELATIVE_TEXT_FILES = {
    "runtimeinitializeonloads.json",
    "scriptingassemblies.json",
    "streamingassets/aa/settings.json",
    "streamingassets/aa/addressableslink/link.xml",
}

_HAS_LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_URL_RE = re.compile(r"^(https?://|www\.)", flags=re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]{8,}$", flags=re.IGNORECASE)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    flags=re.IGNORECASE,
)
_CAB_HASH_RE = re.compile(r"^cab-[0-9a-f]{32}$", flags=re.IGNORECASE)
_FILE_EXT_HINT_RE = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|bmp|ico|mp3|ogg|wav|m4a|webm|mp4|avi|mov|"
    r"txt|json|xml|yaml|yml|bytes|asset|prefab|mat|anim|controller|ttf|otf|woff2?|"
    r"bundle|dll|exe)(?:$|\?)",
    flags=re.IGNORECASE,
)
_YAML_KEY_VALUE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[^:#\n][^:\n]*?):(?P<ws>\s*)(?P<value>.*)$")
_KNOWN_BUNDLE_MARKERS = ("localization", "string-table", "stringtable", "locales", "locale")
_UNITY_BUNDLE_KIND = "unity_bundle_table"
_UNITY_FILE_KIND = "unity_text_file"
_CATALOG_CRC_OFFSET_AFTER_BUNDLE_NAME = 60

_TECHNICAL_KEY_TOKENS = {
    "id",
    "guid",
    "path",
    "file",
    "filename",
    "filepath",
    "asset",
    "resource",
    "bundle",
    "scene",
    "prefab",
    "icon",
    "image",
    "sprite",
    "hash",
    "url",
    "token",
    "type",
    "class",
    "script",
    "address",
    "key",
    "assembly",
    "namespace",
    "classname",
    "methodname",
    "loadtypes",
    "isunityclass",
}

_LIKELY_TEXT_KEY_TOKENS = {
    "text",
    "title",
    "subtitle",
    "label",
    "caption",
    "message",
    "description",
    "desc",
    "hint",
    "name",
    "dialogue",
    "line",
    "content",
    "tooltip",
}

_LANGUAGE_LABELS = {
    "english": "English",
    "en": "English",
    "russian": "Russian",
    "ru": "Russian",
    "japanese": "Japanese",
    "jp": "Japanese",
    "korean": "Korean",
    "kr": "Korean",
    "chinese": "Chinese",
    "zh": "Chinese",
    "spanish": "Spanish",
    "es": "Spanish",
    "portuguese": "Portuguese",
    "pt": "Portuguese",
    "french": "French",
    "fr": "French",
    "german": "German",
    "de": "German",
    "italian": "Italian",
    "it": "Italian",
}

_UNITY_SELECTED_TABLE_BY_PROJECT: dict[str, str | None] = {}


@dataclass
class _TextTarget:
    protected_text: str
    placeholders: list[str]
    apply: Callable[[str], None]


@dataclass
class _LoadedUnityFile:
    kind: str
    data: Any
    targets: list[_TextTarget]
    warnings: list[str]
    newline_at_end: bool = False
    delimiter: str = ","
    xml_has_declaration: bool = False


@dataclass(frozen=True)
class UnityTableCandidate:
    candidate_id: str
    label: str
    language: str | None
    bundle_relpath: str


@dataclass
class _BundlePatch:
    obj: Any
    tree: Any
    targets: list[_TextTarget]


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


def _project_settings_key(project_dir: str | Path) -> str:
    return str(Path(project_dir).resolve()).lower()


def set_unity_selected_table_for_project(project_dir: str | Path, candidate_id: str | None) -> None:
    key = _project_settings_key(project_dir)
    _UNITY_SELECTED_TABLE_BY_PROJECT[key] = candidate_id


def get_unity_selected_table_for_project(project_dir: str | Path) -> str | None:
    return _UNITY_SELECTED_TABLE_BY_PROJECT.get(_project_settings_key(project_dir))


def clear_unity_selected_table_for_project(project_dir: str | Path) -> None:
    _UNITY_SELECTED_TABLE_BY_PROJECT.pop(_project_settings_key(project_dir), None)


def _language_from_filename(name: str) -> str | None:
    base = Path(name).stem.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", base) if token]
    for token in tokens:
        label = _LANGUAGE_LABELS.get(token)
        if label:
            return label
    return None


def _make_unity_candidate_id(bundle_relpath: str) -> str:
    return f"bundle::{bundle_relpath.replace('\\', '/')}"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _encode_unity_text_line(value: str) -> str:
    # Keep each translation in a single physical line, preserving embedded newlines safely.
    return json.dumps(value, ensure_ascii=False)


def _decode_unity_text_line(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, str):
            return parsed
    except Exception:
        pass
    return value


def _encode_unity_placeholders_line(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _decode_unity_placeholders_line(value: str) -> list[str]:
    stripped = value.strip()
    if stripped == "":
        # Legacy export: blank line means "no placeholders"
        return []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return parsed
    except Exception:
        pass
    # Legacy fallback: old delimiter format.
    return stripped.split("|||")


def _split_unity_inline_comment(value: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for idx, ch in enumerate(value):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote is None and ch in {"'", '"'}:
            quote = ch
            continue
        if quote is not None and ch == quote:
            quote = None
            continue
        if quote is None and ch == "#":
            return value[:idx], value[idx:]
    return value, ""


def _looks_like_technical_path(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return False
    if _URL_RE.search(raw):
        return True
    if "/" in raw or "\\" in raw:
        if _FILE_EXT_HINT_RE.search(raw):
            return True
    if _FILE_EXT_HINT_RE.search(raw) and re.fullmatch(r"[A-Za-z0-9_.\- ]+", raw):
        return True
    return False


def _should_translate_text(value: str, *, key_name: str | None = None) -> bool:
    text = value.strip()
    if not text:
        return False
    if _CAB_HASH_RE.fullmatch(text):
        return False
    if text.lower() in {"en", "ru", "jp", "kr", "zh", "es", "de", "fr", "it", "pt"}:
        return False
    if not _HAS_LETTER_RE.search(text):
        return False
    if _UUID_RE.fullmatch(text):
        return False
    if len(text) >= 16 and _HEX_RE.fullmatch(text):
        return False
    if "." in text and " " not in text and re.fullmatch(r"[A-Za-z0-9_.\-]+", text):
        return False
    if _looks_like_technical_path(text):
        return False
    if text.startswith("$") and " " not in text:
        return False

    if key_name:
        key = key_name.strip().lower().replace(" ", "")
        if any(token in key for token in _TECHNICAL_KEY_TOKENS):
            if " " not in text or _FILE_EXT_HINT_RE.search(text):
                return False
        if any(token in key for token in _LIKELY_TEXT_KEY_TOKENS):
            return True

    return True


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    pattern = (
        r"(\\[A-Za-z_]+(?:\[[^\]]+\])?|"
        r"\\[\\><\^._\|!\$\{\}\[\]]|"
        r"<[^>]+>)"
    )
    placeholders: list[str] = []

    def repl(match: re.Match[str]) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"[PLACEHOLDER_{idx}]"

    protegido = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
    return protegido, placeholders


def restaurar_placeholders(text: str, phs: list[str]) -> str:
    for _ in range(len(phs) + 1):
        before = text
        for i in range(len(phs) - 1, -1, -1):
            text = text.replace(f"[PLACEHOLDER_{i}]", phs[i])
        if text == before or "[PLACEHOLDER_" not in text:
            break
    return text


def _target_original_text(target: _TextTarget) -> str:
    return restaurar_placeholders(target.protected_text, target.placeholders)


def carregar_dados_globais(nome_txt: str | Path) -> dict[str, list[str]]:
    mapa: dict[str, list[str]] = {}
    path = Path(nome_txt)
    if not path.exists():
        return mapa

    content = _read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()
        mapa[filename] = [_decode_unity_text_line(linha) for linha in linhas]
    return mapa


def carregar_placeholders(nome_ph: str | Path) -> dict[str, list[list[str]]]:
    mapa: dict[str, list[list[str]]] = {}
    path = Path(nome_ph)
    if not path.exists():
        return mapa

    content = _read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()

        phs_rows: list[list[str]] = []
        for linha in linhas:
            phs_rows.append(_decode_unity_placeholders_line(linha))
        mapa[filename] = phs_rows
    return mapa


def _detect_preferred_exe(project_dir: Path) -> Path | None:
    is_windows = platform.system() == "Windows"

    def is_candidate(path: Path) -> bool:
        if not path.is_file():
            return False
        if path.suffix.lower() == ".exe":
            return True
        if is_windows:
            return path.suffix.lower() == ".exe"
        return path.suffix.lower() == ".sh" or os.access(path, os.X_OK)

    candidates = [p for p in project_dir.iterdir() if is_candidate(p)]
    if not candidates:
        return None

    ignored_tokens = ("unitycrashhandler", "unins", "updater", "crashpad")
    project_name = project_dir.name.lower()

    def score(path: Path) -> tuple[int, int]:
        stem = path.stem.lower()
        points = 0
        if stem == project_name:
            points += 120
        if project_name and project_name in stem:
            points += 40
        if not any(token in stem for token in ignored_tokens):
            points += 25
        size = path.stat().st_size if path.exists() else 0
        return (points, size)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def resolve_unity_data_dir(project_dir: str | Path) -> tuple[Path | None, list[str]]:
    project = Path(project_dir)
    warnings: list[str] = []

    if not project.exists() or not project.is_dir():
        return None, warnings

    if project.name.lower().endswith("_data"):
        return project, warnings

    preferred_exe = _detect_preferred_exe(project)
    if preferred_exe is not None:
        preferred_data = project / f"{preferred_exe.stem}_Data"
        if preferred_data.exists() and preferred_data.is_dir():
            return preferred_data, warnings
        warnings.append(
            f"Não encontrei {preferred_data.name}; usando fallback determinístico entre pastas *_Data."
        )

    data_dirs = sorted(
        [
            child
            for child in project.iterdir()
            if child.is_dir() and child.name.lower().endswith("_data")
        ],
        key=lambda p: p.name.lower(),
    )
    if not data_dirs:
        return None, warnings
    if len(data_dirs) > 1:
        warnings.append(
            f"Foram encontradas múltiplas pastas *_Data. Usando: {data_dirs[0].name}."
        )
    return data_dirs[0], warnings


def describe_unity_data_dir(project_dir: str | Path, data_dir: str | Path) -> str:
    project = Path(project_dir).resolve()
    data = Path(data_dir).resolve()
    try:
        relative = data.relative_to(project)
    except ValueError:
        return str(data)
    return relative.as_posix()


def detectar_tabelas_idioma_unity(project_dir: str | Path) -> tuple[list[UnityTableCandidate], list[str]]:
    data_dir, base_warnings = resolve_unity_data_dir(project_dir)
    warnings = list(base_warnings)
    if data_dir is None:
        return [], warnings

    aa_root = data_dir / "StreamingAssets" / "aa"
    if not aa_root.exists() or not aa_root.is_dir():
        warnings.append("Pasta Addressables não encontrada em StreamingAssets/aa.")
        return [], warnings

    bundle_paths = sorted(
        [
            path
            for path in aa_root.rglob("*")
            if path.is_file()
            and (
                path.suffix.lower() == ".bundle"
                or any(marker in path.name.lower() for marker in _KNOWN_BUNDLE_MARKERS)
            )
        ],
        key=lambda p: p.relative_to(data_dir).as_posix().lower(),
    )

    candidates: list[UnityTableCandidate] = []
    for path in bundle_paths:
        rel = path.relative_to(data_dir).as_posix()
        lower_name = path.name.lower()
        if not any(marker in lower_name for marker in _KNOWN_BUNDLE_MARKERS):
            if path.suffix.lower() == ".bundle" and "localization" not in rel.lower():
                continue

        language = _language_from_filename(path.name)
        label_prefix = language if language else "Desconhecido"
        label = f"{label_prefix} | {rel}"
        candidates.append(
            UnityTableCandidate(
                candidate_id=_make_unity_candidate_id(rel),
                label=label,
                language=language,
                bundle_relpath=rel,
            )
        )

    candidates.sort(
        key=lambda c: (
            1 if c.language is None else 0,
            (c.language or "").lower(),
            c.bundle_relpath.lower(),
        )
    )

    return candidates, warnings


def resolver_candidato_tabela_unity(
    project_dir: str | Path,
    candidate_id: str | None,
) -> tuple[UnityTableCandidate | None, list[UnityTableCandidate], list[str]]:
    candidates, warnings = detectar_tabelas_idioma_unity(project_dir)
    if not candidate_id:
        return None, candidates, warnings
    for candidate in candidates:
        if candidate.candidate_id == candidate_id:
            return candidate, candidates, warnings
    warnings.append(
        "A tabela de idioma previamente selecionada não foi encontrada nesta pasta. Usando modo sem tabela."
    )
    return None, candidates, warnings


def _iter_unity_text_files(data_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir).as_posix().lower()
        name = path.name.lower()
        suffix = path.suffix.lower()
        if rel in UNITY_IGNORED_RELATIVE_TEXT_FILES:
            continue
        if name in UNITY_BINARY_FILENAMES:
            continue
        if suffix in EXCLUDED_SUFFIXES:
            continue
        if suffix not in SUPPORTED_EXTENSIONS:
            continue
        files.append(path)
    files.sort(key=lambda p: p.relative_to(data_dir).as_posix().lower())
    return files


def _load_json_targets(path: Path) -> _LoadedUnityFile | None:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError:
        return None

    targets: list[_TextTarget] = []

    def walk(node: Any, parent: Any, key: Any) -> None:
        if isinstance(node, dict):
            for sub_key, sub_value in node.items():
                walk(sub_value, node, sub_key)
            return
        if isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, node, idx)
            return
        if not isinstance(node, str):
            return

        key_name = key if isinstance(key, str) else None
        if not _should_translate_text(node, key_name=key_name):
            return

        protected, placeholders = proteger_placeholders(node)

        def apply(translated: str, *, holder: Any = parent, holder_key: Any = key) -> None:
            if isinstance(holder, dict):
                holder[holder_key] = translated
            elif isinstance(holder, list) and isinstance(holder_key, int) and 0 <= holder_key < len(holder):
                holder[holder_key] = translated

        targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

    if isinstance(data, dict):
        for k, v in data.items():
            walk(v, data, k)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            walk(item, data, i)
    else:
        return _LoadedUnityFile(kind="json", data=data, targets=[], warnings=[])

    return _LoadedUnityFile(kind="json", data=data, targets=targets, warnings=[])


def _sniff_csv_delimiter(text: str) -> str:
    sample = text[:4096]
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _load_delimited_targets(path: Path, *, forced_delimiter: str | None = None) -> _LoadedUnityFile:
    raw = _read_text(path)
    delimiter = forced_delimiter or _sniff_csv_delimiter(raw)
    rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    targets: list[_TextTarget] = []

    for row_idx, row in enumerate(rows):
        for col_idx, cell in enumerate(row):
            if not _should_translate_text(cell):
                continue
            protected, placeholders = proteger_placeholders(cell)

            def apply(
                translated: str,
                *,
                r: int = row_idx,
                c: int = col_idx,
            ) -> None:
                rows[r][c] = translated

            targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

    return _LoadedUnityFile(
        kind="delimited",
        data=rows,
        targets=targets,
        warnings=[],
        newline_at_end=raw.endswith("\n"),
        delimiter=delimiter,
    )


def _load_txt_targets(path: Path) -> _LoadedUnityFile:
    raw = _read_text(path)
    lines = raw.splitlines()
    targets: list[_TextTarget] = []

    for idx, line in enumerate(lines):
        if not _should_translate_text(line):
            continue
        protected, placeholders = proteger_placeholders(line)

        def apply(translated: str, *, line_idx: int = idx) -> None:
            lines[line_idx] = translated

        targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

    return _LoadedUnityFile(
        kind="txt",
        data=lines,
        targets=targets,
        warnings=[],
        newline_at_end=raw.endswith("\n"),
    )


def _load_xml_targets(path: Path) -> _LoadedUnityFile | None:
    raw = _read_text(path)
    has_decl = raw.lstrip().startswith("<?xml")
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    targets: list[_TextTarget] = []
    for element in root.iter():
        if element.text and _should_translate_text(element.text, key_name=element.tag):
            protected, placeholders = proteger_placeholders(element.text)

            def apply(translated: str, *, node: ET.Element = element) -> None:
                node.text = translated

            targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

        if element.tail and _should_translate_text(element.tail):
            protected, placeholders = proteger_placeholders(element.tail)

            def apply_tail(translated: str, *, node: ET.Element = element) -> None:
                node.tail = translated

            targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply_tail))

    return _LoadedUnityFile(
        kind="xml",
        data=tree,
        targets=targets,
        warnings=[],
        xml_has_declaration=has_decl,
    )


def _is_complex_yaml_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if stripped[0] in {"[", "{", "|", ">", "&", "*", "!", "?"}:
        return True
    if stripped.startswith("- "):
        return True
    if stripped.startswith("!!"):
        return True
    return False


def _escape_yaml_quoted(value: str, quote_char: str) -> str:
    if quote_char == "'":
        return value.replace("'", "''")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _load_yaml_targets(path: Path) -> _LoadedUnityFile:
    raw = _read_text(path)
    lines = raw.splitlines()
    targets: list[_TextTarget] = []
    warnings: list[str] = []
    complex_count = 0

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _YAML_KEY_VALUE_RE.match(line)
        if not match:
            continue

        indent = match.group("indent")
        key = match.group("key")
        ws = match.group("ws")
        value_raw = match.group("value")
        value_part, comment = _split_unity_inline_comment(value_raw)
        value_clean = value_part.strip()

        if not value_clean:
            continue
        if _is_complex_yaml_value(value_clean):
            complex_count += 1
            continue

        quote_char = ""
        parse_value = value_clean
        if (
            len(value_clean) >= 2
            and value_clean[0] in {"'", '"'}
            and value_clean[-1] == value_clean[0]
        ):
            quote_char = value_clean[0]
            parse_value = value_clean[1:-1]
            if quote_char == "'":
                parse_value = parse_value.replace("''", "'")
            else:
                parse_value = parse_value.replace('\\"', '"').replace("\\\\", "\\")

        if not _should_translate_text(parse_value, key_name=key):
            continue

        protected, placeholders = proteger_placeholders(parse_value)

        def apply(
            translated: str,
            *,
            line_idx: int = idx,
            line_indent: str = indent,
            raw_key: str = key,
            spaces: str = ws,
            comment_raw: str = comment,
            q: str = quote_char,
        ) -> None:
            normalized = translated
            if q:
                normalized = _escape_yaml_quoted(normalized, q)
                normalized = f"{q}{normalized}{q}"
            rebuilt = f"{line_indent}{raw_key}:{spaces}{normalized}"
            if comment_raw.strip():
                rebuilt = f"{rebuilt} {comment_raw.lstrip()}"
            lines[line_idx] = rebuilt

        targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

    if complex_count > 0:
        warnings.append(
            f"{path.name}: {complex_count} linhas YAML complexas foram ignoradas no modo seguro."
        )

    return _LoadedUnityFile(
        kind="yaml",
        data=lines,
        targets=targets,
        warnings=warnings,
        newline_at_end=raw.endswith("\n"),
    )


def _collect_targets_from_container(data: Any, *, parent_key: str | None = None) -> list[_TextTarget]:
    targets: list[_TextTarget] = []

    def walk(node: Any, parent: Any, key: Any, key_hint: str | None) -> None:
        if isinstance(node, dict):
            for sub_key, sub_value in node.items():
                next_hint = sub_key if isinstance(sub_key, str) else key_hint
                walk(sub_value, node, sub_key, next_hint)
            return
        if isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, node, idx, key_hint)
            return
        if not isinstance(node, str):
            return
        if not _should_translate_text(node, key_name=key_hint):
            return

        protected, placeholders = proteger_placeholders(node)

        def apply(translated: str, *, holder: Any = parent, holder_key: Any = key) -> None:
            if isinstance(holder, dict):
                holder[holder_key] = translated
            elif isinstance(holder, list) and isinstance(holder_key, int) and 0 <= holder_key < len(holder):
                holder[holder_key] = translated

        targets.append(_TextTarget(protected_text=protected, placeholders=placeholders, apply=apply))

    if isinstance(data, dict):
        for k, v in data.items():
            hint = k if isinstance(k, str) else parent_key
            walk(v, data, k, hint)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            walk(item, data, idx, parent_key)
    return targets


def _collect_bundle_localized_targets(tree: Any) -> list[_TextTarget]:
    targets: list[_TextTarget] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            table_data = node.get("m_TableData")
            if isinstance(table_data, list):
                for row in table_data:
                    if not isinstance(row, dict):
                        continue
                    localized_value = row.get("m_Localized")
                    if not isinstance(localized_value, str):
                        continue
                    if not _should_translate_text(localized_value, key_name="m_Localized"):
                        continue
                    protected, placeholders = proteger_placeholders(localized_value)

                    def apply(translated: str, *, holder: dict[str, Any] = row) -> None:
                        holder["m_Localized"] = translated

                    targets.append(
                        _TextTarget(
                            protected_text=protected,
                            placeholders=placeholders,
                            apply=apply,
                        )
                    )
            for value in node.values():
                walk(value)
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(tree)
    return targets


def _collect_bundle_patches(bundle_path: Path) -> tuple[list[_BundlePatch], list[str]]:
    warnings: list[str] = []
    if UnityPy is None:
        warnings.append("UnityPy não está instalado; não foi possível ler tables de bundles.")
        return [], warnings

    try:
        env = UnityPy.load(str(bundle_path))
    except Exception as exc:
        warnings.append(f"Falha ao abrir bundle {bundle_path.name}: {exc}")
        return [], warnings

    patches: list[_BundlePatch] = []
    objects = getattr(env, "objects", [])
    for obj in objects:
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, (dict, list)):
            continue

        targets = _collect_bundle_localized_targets(tree)
        if not targets:
            continue
        patches.append(_BundlePatch(obj=obj, tree=tree, targets=targets))

    return patches, warnings


def _save_bundle_patches(bundle_path: Path, patches: list[_BundlePatch]) -> tuple[bool, str | None]:
    if UnityPy is None:
        return False, "UnityPy não está instalado."
    try:
        env = UnityPy.load(str(bundle_path))
    except Exception as exc:
        return False, f"Falha ao reabrir bundle {bundle_path.name}: {exc}"

    by_path_id: dict[int, _BundlePatch] = {}
    for patch in patches:
        path_id = getattr(patch.obj, "path_id", None)
        if isinstance(path_id, int):
            by_path_id[path_id] = patch

    for obj in getattr(env, "objects", []):
        path_id = getattr(obj, "path_id", None)
        if not isinstance(path_id, int) or path_id not in by_path_id:
            continue
        patch = by_path_id[path_id]
        try:
            obj.save_typetree(patch.tree)
        except Exception as exc:
            return False, f"Falha ao salvar objeto {path_id} no bundle {bundle_path.name}: {exc}"

    payload: bytes | None = None
    if hasattr(env, "file") and hasattr(env.file, "save"):
        try:
            payload = env.file.save("original")
        except Exception:
            payload = None
    if payload is None and hasattr(env, "save"):
        try:
            payload = env.save(pack="original")
        except Exception:
            payload = None
    if not isinstance(payload, (bytes, bytearray)):
        return False, f"Não foi possível serializar o bundle {bundle_path.name}."

    bundle_path.write_bytes(bytes(payload))
    return True, None


def _compute_bundle_runtime_crc(bundle_path: Path) -> tuple[int | None, str | None]:
    if UnityPy is None:
        return None, "UnityPy não está instalado."
    try:
        env = UnityPy.load(str(bundle_path))
    except Exception as exc:
        return None, f"Falha ao abrir bundle para CRC ({bundle_path.name}): {exc}"

    file_obj = getattr(env, "file", None)
    files = getattr(file_obj, "files", None)
    if not isinstance(files, dict) or not files:
        return None, f"Bundle sem arquivos internos para calcular CRC: {bundle_path.name}"

    payload = bytearray()
    for entry in files.values():
        data: bytes | bytearray | None = None
        if hasattr(entry, "bytes"):
            try:
                data = entry.bytes
            except Exception:
                data = None
        if data is None and hasattr(entry, "save"):
            try:
                data = entry.save()
            except Exception:
                data = None
        if not isinstance(data, (bytes, bytearray)):
            return None, f"Não foi possível ler payload interno para CRC: {bundle_path.name}"
        payload.extend(data)

    return zlib.crc32(bytes(payload)) & 0xFFFFFFFF, None


def _patch_catalog_crc_for_bundle(
    data_dir: Path,
    bundle_relpath: str,
    new_crc: int,
) -> tuple[bool, str]:
    catalog_path = data_dir / "StreamingAssets" / "aa" / "catalog.bin"
    if not catalog_path.exists() or not catalog_path.is_file():
        return False, f"catalog.bin não encontrado para atualizar CRC: {catalog_path}"

    raw = bytearray(catalog_path.read_bytes())
    bundle_name = Path(bundle_relpath).name
    bundle_name_bytes = bundle_name.encode("utf-8")

    offsets: list[int] = []
    start = 0
    while True:
        idx = raw.find(bundle_name_bytes, start)
        if idx < 0:
            break
        offsets.append(idx)
        start = idx + 1

    if not offsets:
        return False, f"Entrada do bundle não encontrada no catalog.bin: {bundle_name}"

    chosen_idx = offsets[0]
    for idx in offsets:
        prefix = raw[max(0, idx - 96) : idx]
        if b"StandaloneWindows64\\" in prefix or b"/StandaloneWindows64/" in prefix:
            chosen_idx = idx
            break

    crc_pos = chosen_idx + len(bundle_name_bytes) + _CATALOG_CRC_OFFSET_AFTER_BUNDLE_NAME
    if crc_pos + 4 > len(raw):
        return (
            False,
            f"Posição de CRC fora do limite no catalog.bin para bundle {bundle_name}.",
        )

    old_crc = int.from_bytes(raw[crc_pos : crc_pos + 4], "little", signed=False)
    if old_crc == new_crc:
        return True, f"CRC do catálogo já estava atualizado para {bundle_name}: 0x{new_crc:08x}."

    raw[crc_pos : crc_pos + 4] = int(new_crc).to_bytes(4, "little", signed=False)
    catalog_path.write_bytes(bytes(raw))
    return (
        True,
        f"CRC do catálogo atualizado para {bundle_name}: 0x{old_crc:08x} -> 0x{new_crc:08x}.",
    )


def _load_unity_file(path: Path) -> _LoadedUnityFile | None:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json_targets(path)
    if suffix == ".csv":
        return _load_delimited_targets(path)
    if suffix == ".tsv":
        return _load_delimited_targets(path, forced_delimiter="\t")
    if suffix == ".txt":
        return _load_txt_targets(path)
    if suffix == ".xml":
        return _load_xml_targets(path)
    if suffix in {".yml", ".yaml"}:
        return _load_yaml_targets(path)
    return None


def _write_unity_file(path: Path, loaded: _LoadedUnityFile) -> None:
    if loaded.kind == "json":
        _write_text(path, json.dumps(loaded.data, ensure_ascii=False, separators=(",", ":")))
        return
    if loaded.kind == "delimited":
        output = io.StringIO()
        writer = csv.writer(output, delimiter=loaded.delimiter, lineterminator="\n")
        writer.writerows(loaded.data)
        text = output.getvalue()
        if not loaded.newline_at_end and text.endswith("\n"):
            text = text[:-1]
        _write_text(path, text)
        return
    if loaded.kind in {"txt", "yaml"}:
        text = "\n".join(loaded.data)
        if loaded.newline_at_end:
            text += "\n"
        _write_text(path, text)
        return
    if loaded.kind == "xml":
        tree: ET.ElementTree = loaded.data
        tree.write(path, encoding="utf-8", xml_declaration=loaded.xml_has_declaration)
        return
    raise ValueError(f"Tipo de arquivo Unity não suportado para gravação: {loaded.kind}")


def exportar_unity(project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)

    if not project.exists() or not project.is_dir():
        return JobResult(False, f"Pasta de projeto inválida: {project}")

    data_dir, resolution_warnings = resolve_unity_data_dir(project)
    if data_dir is None:
        message = "Pasta Unity inválida: não foi possível localizar uma pasta *_Data na raiz do projeto."
        if resolution_warnings:
            message += " " + " ".join(resolution_warnings)
        return JobResult(False, message)

    unity_files = _iter_unity_text_files(data_dir)
    warnings: list[str] = list(resolution_warnings)

    dict_txt: dict[str, list[str]] = {}
    dict_placeh: dict[str, list[list[str]]] = {}
    mapa_origem: dict[str, str | dict[str, Any]] = {}

    # Arquivos textuais comuns
    for path in unity_files:
        loaded = _load_unity_file(path)
        if loaded is None:
            warnings.append(f"Ignorado (parse inválido): {path.relative_to(data_dir).as_posix()}")
            continue

        warnings.extend(loaded.warnings)
        if not loaded.targets:
            continue

        rel = path.relative_to(data_dir).as_posix()
        dict_txt[rel] = [target.protected_text for target in loaded.targets]
        dict_placeh[rel] = [target.placeholders for target in loaded.targets]

    # Table de idioma selecionada (Addressables)
    selected_id = get_unity_selected_table_for_project(project)
    selected_candidate, candidates, detection_warnings = resolver_candidato_tabela_unity(project, selected_id)
    warnings.extend(detection_warnings)
    if candidates:
        ignored_count = len(candidates) - (1 if selected_candidate else 0)
        if ignored_count > 0:
            warnings.append(f"{ignored_count} table(s) de idioma foram ignoradas nesta exportação.")
    if selected_candidate is not None:
        bundle_path = data_dir / selected_candidate.bundle_relpath
        patches, bundle_warnings = _collect_bundle_patches(bundle_path)
        warnings.extend(bundle_warnings)
        if patches:
            bundle_key = f"bundle::{selected_candidate.bundle_relpath}"
            bundle_targets = [target for patch in patches for target in patch.targets]
            if bundle_targets:
                dict_txt[bundle_key] = [target.protected_text for target in bundle_targets]
                dict_placeh[bundle_key] = [target.placeholders for target in bundle_targets]
                mapa_origem[bundle_key] = {
                    "kind": _UNITY_BUNDLE_KIND,
                    "bundle_relpath": selected_candidate.bundle_relpath,
                    "candidate_id": selected_candidate.candidate_id,
                    "label": selected_candidate.label,
                }
        else:
            warnings.append(
                f"Nenhum texto elegível encontrado na table selecionada: {selected_candidate.label}."
            )

    if not dict_txt:
        unitypy_missing = any("UnityPy não está instalado" in warning for warning in warnings)
        if selected_candidate is not None:
            if unitypy_missing:
                message = (
                    "A table de idioma foi detectada, mas não foi possível ler bundles porque o UnityPy "
                    "não está disponível neste ambiente/EXE. Rebuild o aplicativo incluindo UnityPy."
                )
            else:
                message = (
                    "Nenhum texto elegível para tradução foi encontrado no Unity para a table selecionada: "
                    f"{selected_candidate.label}. Tente outra table de idioma na etapa 2."
                )
        elif candidates:
            if unitypy_missing:
                message = (
                    "Foram detectadas tables de idioma no Unity, mas o UnityPy não está disponível neste "
                    "ambiente/EXE para ler os bundles. Rebuild o aplicativo incluindo UnityPy."
                )
            else:
                message = (
                    "Nenhum texto elegível para tradução foi encontrado no Unity. "
                    "Foram detectadas tables de idioma; selecione uma na etapa 2 e aplique antes de exportar."
                )
        else:
            message = (
                "Nenhum texto elegível para tradução foi encontrado no Unity "
                "(arquivos comuns e table selecionada)."
            )
        return JobResult(
            False,
            message,
            warnings=warnings,
        )

    mapa_arquivos: dict[str, str | dict[str, Any]] = {}
    translations_path = workspace / TRANSLATIONS_FILENAME
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME

    with translations_path.open("w", encoding="utf-8") as f_txt, placeholders_path.open(
        "w", encoding="utf-8"
    ) as f_ph:
        for idx, (rel, textos) in enumerate(dict_txt.items()):
            key = f"ARQUIVO_{idx:03d}"
            if rel in mapa_origem:
                mapa_arquivos[key] = mapa_origem[rel]
            else:
                mapa_arquivos[key] = {
                    "kind": _UNITY_FILE_KIND,
                    "path": rel,
                }

            f_txt.write(f"=== {key} ===\n")
            for text in textos:
                f_txt.write(_encode_unity_text_line(text) + "\n")
            f_txt.write("\n")

            f_ph.write(f"=== {key} ===\n")
            for phs in dict_placeh[rel]:
                f_ph.write(_encode_unity_placeholders_line(phs) + "\n")
            f_ph.write("\n")

    map_path.write_text(json.dumps(mapa_arquivos, ensure_ascii=False, indent=4), encoding="utf-8")

    data_desc = describe_unity_data_dir(project, data_dir)
    selected_text = ""
    if selected_candidate is not None:
        selected_text = f" Table selecionada: {selected_candidate.label}."
    elif candidates:
        selected_text = " Nenhuma table de idioma foi selecionada; somente arquivos textuais comuns foram exportados."
    return JobResult(
        success=True,
        message=(
            f"Exportação Unity concluída ({len(dict_txt)} arquivos). "
            f"Pasta de dados usada: {data_desc}.{selected_text}"
        ),
        warnings=warnings,
        generated_files=[str(translations_path), str(placeholders_path), str(map_path)],
    )


def importar_unity(
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

    data_dir, resolution_warnings = resolve_unity_data_dir(project)
    if data_dir is None:
        message = "Pasta Unity inválida: não foi possível localizar uma pasta *_Data na raiz do projeto."
        if resolution_warnings:
            message += " " + " ".join(resolution_warnings)
        return JobResult(False, message)

    if not translated_path.exists() or not translated_path.is_file():
        return JobResult(False, f"Arquivo traduzido não encontrado: {translated_path}")
    if not placeholders_path.exists() or not placeholders_path.is_file():
        return JobResult(False, f"Arquivo não encontrado: {placeholders_path}")
    if not map_path.exists() or not map_path.is_file():
        return JobResult(False, f"Arquivo não encontrado: {map_path}")

    t_map = carregar_dados_globais(translated_path)
    p_map = carregar_placeholders(placeholders_path)
    try:
        mapa_arquivos: dict[str, Any] = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return JobResult(False, f"Mapa inválido (JSON): {map_path}")

    warnings: list[str] = list(resolution_warnings)
    resolved_file_targets: dict[str, Path] = {}
    resolved_bundle_targets: dict[str, tuple[Path, dict[str, Any]]] = {}

    def parse_entry(entry: Any) -> tuple[str, str | None, dict[str, Any] | None]:
        # compat legado: string simples = arquivo textual
        if isinstance(entry, str):
            return _UNITY_FILE_KIND, entry, {"kind": _UNITY_FILE_KIND, "path": entry}
        if isinstance(entry, dict):
            kind = str(entry.get("kind", "")).strip().lower()
            if kind == _UNITY_BUNDLE_KIND:
                rel = entry.get("bundle_relpath")
                if isinstance(rel, str):
                    return _UNITY_BUNDLE_KIND, rel, entry
            path = entry.get("path")
            if isinstance(path, str):
                return _UNITY_FILE_KIND, path, entry
        return "", None, None

    for key, entry in mapa_arquivos.items():
        if key not in t_map:
            continue
        kind, rel, meta = parse_entry(entry)
        if not rel or not meta:
            warnings.append(f"Entrada de mapa Unity inválida para {key}.")
            continue
        full = (data_dir / rel).resolve()
        if not full.exists() or not full.is_file():
            warnings.append(f"Arquivo Unity mapeado não encontrado: {rel}")
            continue
        if kind == _UNITY_BUNDLE_KIND:
            resolved_bundle_targets[key] = (full, meta)
        else:
            resolved_file_targets[key] = full

    backup_dir: Path | None = None
    if criar_backup and (resolved_file_targets or resolved_bundle_targets):
        backup_catalog: list[Path] = []
        if resolved_bundle_targets:
            catalog_path = data_dir / "StreamingAssets" / "aa" / "catalog.bin"
            if catalog_path.exists() and catalog_path.is_file():
                backup_catalog.append(catalog_path)
        unique_targets = sorted(
            {
                path.resolve()
                for path in list(resolved_file_targets.values())
                + [bundle_path for bundle_path, _meta in resolved_bundle_targets.values()]
                + backup_catalog
            },
            key=lambda p: str(p).lower(),
        )
        backup_dir = create_backup_snapshot("unity", project, workspace, unique_targets)

    data_desc = describe_unity_data_dir(project, data_dir)
    with log_path.open("w", encoding="utf-8") as log:
        for key, entry in mapa_arquivos.items():
            if key not in t_map:
                continue

            translations = t_map[key]
            placeholders = p_map.get(key, [])
            if len(placeholders) < len(translations):
                # Legacy exports may have empty placeholder lines collapsed by older parser.
                placeholders = placeholders + [[] for _ in range(len(translations) - len(placeholders))]
            elif len(placeholders) > len(translations):
                placeholders = placeholders[: len(translations)]

            # arquivo textual comum
            if key in resolved_file_targets:
                full = resolved_file_targets[key]
                kind, rel, _meta = parse_entry(entry)
                rel_label = rel or full.relative_to(data_dir).as_posix()

                loaded = _load_unity_file(full)
                if loaded is None:
                    warning = f"{rel_label}: parse inválido durante importação."
                    warnings.append(warning)
                    log.write(f"[ERRO] {warning}\n")
                    continue

                for extra_warning in loaded.warnings:
                    warnings.append(extra_warning)
                    log.write(f"[AVISO] {extra_warning}\n")

                targets = loaded.targets
                if len(translations) != len(targets):
                    alert = (
                        f"{rel_label}: contagem incompatível entre export/import "
                        f"({len(translations)} traduções vs {len(targets)} alvos). "
                        "Importação desse item foi ignorada por segurança."
                    )
                    warnings.append(alert)
                    log.write(f"[BLOQUEADO] {alert}\n")
                    continue
                intended: list[str] = []
                originals = [_target_original_text(target) for target in targets]
                for idx in range(len(targets)):
                    tags = placeholders[idx] if idx < len(placeholders) else []
                    intended.append(restaurar_placeholders(translations[idx], tags))
                if intended == originals:
                    log.write(f"[OK] {rel_label} sem alterações; gravação ignorada.\n")
                    continue
                applied = 0
                for idx, target in enumerate(targets):
                    if idx >= len(translations):
                        break
                    tags = placeholders[idx] if idx < len(placeholders) else []
                    restored = restaurar_placeholders(translations[idx], tags)
                    if "[PLACEHOLDER_" in restored:
                        log.write(f"[FALHA DE TAG] {rel_label} | idx {idx}\n")
                    target.apply(restored)
                    applied += 1

                if len(translations) > len(targets):
                    warning = f"{rel_label}: {len(translations) - len(targets)} linhas extras sem alvo."
                    warnings.append(warning)
                    log.write(f"[ALERTA] {warning}\n")
                elif len(targets) > len(translations):
                    warning = f"{rel_label}: {len(targets) - len(translations)} textos sem tradução."
                    warnings.append(warning)
                    log.write(f"[ALERTA] {warning}\n")

                _write_unity_file(full, loaded)
                log.write(
                    f"[OK] {rel_label} processado. ({applied}/{len(translations)} traduções aplicadas; "
                    f"{len(targets)} alvos encontrados)\n"
                )
                continue

            # table/bundle selecionado
            if key in resolved_bundle_targets:
                bundle_path, meta = resolved_bundle_targets[key]
                bundle_rel = str(meta.get("bundle_relpath", bundle_path.relative_to(data_dir).as_posix()))
                patches, bundle_warnings = _collect_bundle_patches(bundle_path)
                for warning in bundle_warnings:
                    warnings.append(warning)
                    log.write(f"[AVISO] {warning}\n")
                if not patches:
                    warning = f"{bundle_rel}: nenhum alvo de texto encontrado na table do bundle."
                    warnings.append(warning)
                    log.write(f"[AVISO] {warning}\n")
                    continue

                targets = [target for patch in patches for target in patch.targets]
                if len(translations) != len(targets):
                    alert = (
                        f"{bundle_rel}: contagem incompatível entre export/import "
                        f"({len(translations)} traduções vs {len(targets)} alvos). "
                        "Importação dessa table foi ignorada por segurança."
                    )
                    warnings.append(alert)
                    log.write(f"[BLOQUEADO] {alert}\n")
                    continue
                intended: list[str] = []
                originals = [_target_original_text(target) for target in targets]
                for idx in range(len(targets)):
                    tags = placeholders[idx] if idx < len(placeholders) else []
                    intended.append(restaurar_placeholders(translations[idx], tags))
                if intended == originals:
                    log.write(f"[OK] {bundle_rel} sem alterações; gravação ignorada.\n")
                    continue
                applied = 0
                for idx, target in enumerate(targets):
                    if idx >= len(translations):
                        break
                    tags = placeholders[idx] if idx < len(placeholders) else []
                    restored = restaurar_placeholders(translations[idx], tags)
                    if "[PLACEHOLDER_" in restored:
                        log.write(f"[FALHA DE TAG] {bundle_rel} | idx {idx}\n")
                    target.apply(restored)
                    applied += 1

                if len(translations) > len(targets):
                    warning = f"{bundle_rel}: {len(translations) - len(targets)} linhas extras sem alvo."
                    warnings.append(warning)
                    log.write(f"[ALERTA] {warning}\n")
                elif len(targets) > len(translations):
                    warning = f"{bundle_rel}: {len(targets) - len(translations)} textos sem tradução."
                    warnings.append(warning)
                    log.write(f"[ALERTA] {warning}\n")

                saved, save_error = _save_bundle_patches(bundle_path, patches)
                if not saved:
                    warning = f"{bundle_rel}: falha ao salvar bundle ({save_error})."
                    warnings.append(warning)
                    log.write(f"[ERRO] {warning}\n")
                    continue
                runtime_crc, crc_error = _compute_bundle_runtime_crc(bundle_path)
                if runtime_crc is None:
                    warning = f"{bundle_rel}: não foi possível calcular CRC pós-save ({crc_error})."
                    warnings.append(warning)
                    log.write(f"[AVISO] {warning}\n")
                else:
                    patched, patch_msg = _patch_catalog_crc_for_bundle(data_dir, bundle_rel, runtime_crc)
                    if patched:
                        log.write(f"[OK] {patch_msg}\n")
                    else:
                        warnings.append(patch_msg)
                        log.write(f"[AVISO] {patch_msg}\n")

                log.write(
                    f"[OK] {bundle_rel} (table) processado. ({applied}/{len(translations)} traduções aplicadas; "
                    f"{len(targets)} alvos encontrados)\n"
                )
                continue

            kind, rel, _meta = parse_entry(entry)
            rel_label = rel or f"entrada:{key}"
            log.write(f"[AVISO] Arquivo Unity mapeado não encontrado: {rel_label}\n")

    message = f"Importação Unity concluída. Pasta de dados usada: {data_desc}."
    if backup_dir:
        message += f" Backup criado em: {backup_dir}"

    return JobResult(
        success=True,
        message=message,
        warnings=warnings,
        generated_files=[str(log_path)],
        log_file=str(log_path),
    )
