from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from translator_core import exportar, importar, pre_validar_importacao
from translator_core.models import JobResult
from translator_core.local_translate import (
    DEFAULT_CHUNK_LINES,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_TOTAL_TIMEOUT_SECONDS,
    LocalTranslateConfig,
    local_translated_path,
    translate_document_local,
)
from translator_core.text_parts import merge_parts_into_target, split_text_file
from translator_core.orchestrator import (
    ENGINE_BUZZ,
    ENGINE_RENPY,
    ENGINE_RPGM,
    ENGINE_UNITY,
    engine_workspace_dir,
    normalize_engine,
    translation_filename_for_engine,
)
from translator_core.buzz_prepare import (
    BUZZ_LANGUAGE_MENU_OPTIONS,
    BUZZ_MODEL_SIZES,
    BUZZ_MODEL_TYPES,
    BUZZ_OUTPUT_FORMATS,
    BUZZ_TASKS,
    BuzzRunConfig,
    detectar_buzz,
    executar_buzz,
    finalizar_execucao_buzz,
    iniciar_execucao_buzz,
)
from translator_core.rpgm_core import describe_rpgm_data_dir, resolve_rpgm_data_dir
from translator_core.renpy_prepare import (
    aplicar_force_language,
    abrir_processo_jogo,
    copiar_un_files_para_game,
    detectar_executavel_jogo,
    detectar_versao_renpy,
    listar_launchers,
    preparar_descompactador,
    processo_ativo,
    remover_un_files_de_game,
    remover_descompactador_temporario,
    selecionar_launcher_compativel,
)
from translator_core.unity_core import (
    clear_unity_selected_table_for_project,
    describe_unity_data_dir,
    detectar_tabelas_idioma_unity,
    get_unity_selected_table_for_project,
    resolve_unity_data_dir,
    set_unity_selected_table_for_project,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    HAS_DND = False
    DND_FILES = None
    TkinterDnD = None


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "v1.12"
APP_DEFAULT_GEOMETRY = "780x560"
APP_BASE_MIN_SIZE = (700, 500)
APP_RENPY_STEP2_MIN_SIZE = (740, 640)
APP_STEP2_MIN_SIZE = (740, 580)
APP_AUTO_FIT_SCREEN_MARGIN = 80

DROP_DISABLED = "disabled"
DROP_PROJECT_DIR = "project_dir"
DROP_TRANSLATED_TXT = "translated_txt"
MANUAL_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_valid_launch_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if _is_windows():
        return path.suffix.lower() == ".exe"
    return path.suffix.lower() in {".sh", ".command", ".exe"} or os.access(path, os.X_OK)


def _launch_filetypes() -> list[tuple[str, str]]:
    if _is_windows():
        return [("Executável", "*.exe"), ("Todos os arquivos", "*.*")]
    return [("Scripts/EXE", "*.sh *.command *.exe"), ("Todos os arquivos", "*.*")]


def _user_data_dir(app_name: str) -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / app_name


SETTINGS_PATH = _user_data_dir("InterfaceTradutores") / "settings.json"
TOOLS_DIR_NAME = "FERRAMENTAS - TRADUZIR - RENPY"


def _pick_existing_path(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return fallback


def _default_tools_dir() -> Path:
    return APP_DIR / TOOLS_DIR_NAME


def _default_unren_source() -> str:
    tools_dir = _default_tools_dir()
    if _is_windows():
        names = ["UnRen-forall.bat", "UnRen-forall.txt", "UnRen-Linux.sh", "UnRen-forall.sh"]
        candidates = [tools_dir / name for name in names]
    else:
        names = ["UnRen-Linux.sh", "UnRen-forall.sh", "UnRen-forall.bat", "UnRen-forall.txt"]
        command_candidates = sorted(tools_dir.glob("UnRen*.command"))
        candidates = command_candidates + [tools_dir / name for name in names]
    return str(_pick_existing_path(candidates, candidates[0]))


def _default_force_language() -> str:
    return str(_default_tools_dir() / "force_language.rpy")


def _default_un_rpy_source() -> str:
    return str(_default_tools_dir() / "un.rpy")


def _default_un_rpyc_source() -> str:
    return str(_default_tools_dir() / "un.rpyc")


def resolve_workspace_root(*, frozen: bool | None = None) -> Path:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return _user_data_dir("InterfaceTradutores") / "workspace"
    return APP_DIR / "workspace"


WORKSPACE_ROOT = resolve_workspace_root()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR = Path.home() / "Downloads"


def open_in_os(path: str | Path) -> None:
    target_path = Path(path)
    target = str(target_path)
    if platform.system() == "Windows":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if platform.system() == "Linux" and target_path.suffix.lower() in {".sh", ".command"}:
        if os.access(target_path, os.X_OK):
            subprocess.Popen([target], cwd=str(target_path.parent))
        else:
            subprocess.Popen(["bash", target], cwd=str(target_path.parent))
        return
    if platform.system() == "Linux" and target_path.suffix.lower() == ".exe":
        wine_bin = shutil.which("wine")
        if not wine_bin:
            raise RuntimeError(
                "Wine não encontrado. Instale o Wine para abrir executáveis .exe no Linux."
            )
        subprocess.Popen([wine_bin, target], cwd=str(target_path.parent))
        return
    if platform.system() == "Darwin":
        subprocess.run(["open", target], check=False)
        return
    subprocess.run(["xdg-open", target], check=False)


def normalize_dropped_items(raw_items: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in raw_items:
        dropped = raw
        if dropped.startswith("{") and dropped.endswith("}"):
            dropped = dropped[1:-1]
        dropped = dropped.strip()
        if dropped:
            paths.append(Path(dropped))
    return paths


def resolve_project_drop_path(paths: list[Path]) -> tuple[Path | None, bool]:
    for path in paths:
        if path.exists() and path.is_dir():
            return path, False

    for path in paths:
        if path.exists() and path.is_file():
            return path.parent, True

    if paths:
        candidate = paths[0]
        if candidate.suffix:
            return candidate.parent, True
        return candidate, False

    return None, False


def resolve_translated_txt_drop_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file() and path.suffix.lower() == ".txt":
            return path
    return None


def resolve_buzz_media_drop_path(paths: list[Path]) -> Path | None:
    allowed = {
        ".aac",
        ".ac3",
        ".aiff",
        ".amr",
        ".avi",
        ".flac",
        ".flv",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
    }
    for path in paths:
        if path.exists() and path.is_file() and path.suffix.lower() in allowed:
            return path
    return None


def _project_settings_key(project_dir: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(Path(project_dir).resolve())))


def _default_settings() -> dict[str, Any]:
    return {
        "launchers_root": "",
        "unren_source_path": _default_unren_source(),
        "force_language_path": _default_force_language(),
        "un_rpy_source_path": _default_un_rpy_source(),
        "un_rpyc_source_path": _default_un_rpyc_source(),
        "game_exe_by_project": {},
        "unity_table_selection_by_project": {},
        "buzz_model_type": "fasterwhisper",
        "buzz_model_size": "large-v3-turbo",
        "buzz_task": "transcribe",
        "buzz_language": "Detectar idioma (auto)",
        "buzz_word_timestamps": False,
        "buzz_extract_speech": False,
        "buzz_output_formats": ["srt"],
        "buzz_output_same_dir": True,
        "buzz_output_directory": "",
        "local_translation_model": DEFAULT_MODEL,
        "local_translation_timeout_seconds": str(DEFAULT_TOTAL_TIMEOUT_SECONDS),
        "local_translation_chunk_lines": str(DEFAULT_CHUNK_LINES),
    }


def load_app_settings() -> dict[str, Any]:
    defaults = _default_settings()
    settings = dict(defaults)
    if not SETTINGS_PATH.exists() or not SETTINGS_PATH.is_file():
        return settings

    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings

    for key in [
        "launchers_root",
        "unren_source_path",
        "force_language_path",
        "un_rpy_source_path",
        "un_rpyc_source_path",
        "buzz_model_type",
        "buzz_model_size",
        "buzz_task",
        "buzz_language",
        "buzz_output_directory",
        "local_translation_model",
        "local_translation_timeout_seconds",
        "local_translation_chunk_lines",
    ]:
        value = loaded.get(key)
        if isinstance(value, str):
            settings[key] = value

    buzz_extract_speech = loaded.get("buzz_extract_speech")
    if isinstance(buzz_extract_speech, bool):
        settings["buzz_extract_speech"] = buzz_extract_speech
    buzz_word_timestamps = loaded.get("buzz_word_timestamps")
    if isinstance(buzz_word_timestamps, bool):
        settings["buzz_word_timestamps"] = buzz_word_timestamps

    buzz_output_same_dir = loaded.get("buzz_output_same_dir")
    if isinstance(buzz_output_same_dir, bool):
        settings["buzz_output_same_dir"] = buzz_output_same_dir

    output_formats = loaded.get("buzz_output_formats")
    if isinstance(output_formats, list):
        normalized_formats = [
            value for value in output_formats if isinstance(value, str) and value in BUZZ_OUTPUT_FORMATS
        ]
        if normalized_formats:
            settings["buzz_output_formats"] = normalized_formats

    for map_key in ["game_exe_by_project", "unity_table_selection_by_project"]:
        saved_map = loaded.get(map_key)
        if not isinstance(saved_map, dict):
            continue
        normalized: dict[str, str] = {}
        for raw_project, raw_exe in saved_map.items():
            if isinstance(raw_project, str) and isinstance(raw_exe, str):
                normalized[raw_project] = raw_exe
        settings[map_key] = normalized

    # If stored paths are stale/nonexistent, fallback to project defaults.
    for key in ["unren_source_path", "force_language_path", "un_rpy_source_path", "un_rpyc_source_path"]:
        raw = str(settings.get(key) or "").strip()
        default_raw = str(defaults.get(key) or "").strip()
        if raw and Path(raw).exists():
            continue
        if default_raw:
            settings[key] = default_raw

    return settings


def save_app_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class TranslatorWizardApp:
    def __init__(self) -> None:
        if HAS_DND:
            self.root = TkinterDnD.Tk()  # type: ignore[union-attr]
        else:
            self.root = tk.Tk()

        self._configure_style()
        self.root.title(f"Interface Tradutores - {APP_VERSION}")
        self.root.geometry(APP_DEFAULT_GEOMETRY)
        self.root.minsize(*APP_BASE_MIN_SIZE)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self.settings = load_app_settings()
        self.engine_var = tk.StringVar(value=ENGINE_RENPY)
        self.engine_display_var = tk.StringVar(value="")
        self.project_dir_var = tk.StringVar(value="")
        self.translated_file_var = tk.StringVar(value="")
        self.launchers_root_var = tk.StringVar(value=self.settings["launchers_root"])
        self.unren_source_var = tk.StringVar(value=self.settings["unren_source_path"])
        self.force_language_source_var = tk.StringVar(value=self.settings["force_language_path"])
        self.un_rpy_source_var = tk.StringVar(value=self.settings["un_rpy_source_path"])
        self.un_rpyc_source_var = tk.StringVar(value=self.settings["un_rpyc_source_path"])
        self.renpy_version_var = tk.StringVar(value="Versão Ren'Py detectada: -")
        self.renpy_launcher_var = tk.StringVar(value="Launcher Ren'Py: -")
        self.manual_version_var = tk.StringVar(value="")
        self.renpy_launchers_root_info_var = tk.StringVar(value="")
        self.unren_source_info_var = tk.StringVar(value="")
        self.wine_status_var = tk.StringVar(value="")
        self.force_language_info_var = tk.StringVar(value="")
        self.un_rpy_info_var = tk.StringVar(value="")
        self.un_rpyc_info_var = tk.StringVar(value="")
        self.game_exe_info_var = tk.StringVar(value="Arquivo de inicialização do jogo: (defina a pasta do projeto)")
        self.unity_tables_info_var = tk.StringVar(value="Tables Unity: detectar para escolher o idioma/table.")
        self.unity_selected_table_var = tk.StringVar(value="Table selecionada: (nenhuma)")
        self.buzz_status_var = tk.StringVar(value="Buzz: verificando disponibilidade...")
        self.buzz_video_var = tk.StringVar(value="")
        self.buzz_model_type_var = tk.StringVar(value=self.settings["buzz_model_type"])
        self.buzz_model_size_var = tk.StringVar(value=self.settings["buzz_model_size"])
        self.buzz_task_var = tk.StringVar(value=self.settings["buzz_task"])
        self.buzz_language_var = tk.StringVar(value=self.settings["buzz_language"])
        self.buzz_word_timestamps_var = tk.BooleanVar(value=bool(self.settings["buzz_word_timestamps"]))
        self.buzz_extract_speech_var = tk.BooleanVar(value=bool(self.settings["buzz_extract_speech"]))
        self.buzz_output_same_dir_var = tk.BooleanVar(value=bool(self.settings["buzz_output_same_dir"]))
        self.buzz_output_dir_var = tk.StringVar(value=self.settings["buzz_output_directory"])
        self.local_translation_model_var = tk.StringVar(value=self.settings["local_translation_model"])
        self.local_translation_timeout_var = tk.StringVar(value=self.settings["local_translation_timeout_seconds"])
        self.local_translation_chunk_var = tk.StringVar(value=self.settings["local_translation_chunk_lines"])
        self.split_parts_var = tk.StringVar(value="4")
        self.ollama_status_var = tk.StringVar(value="Ollama: verificando...")
        self.ollama_models: list[str] = []
        self.buzz_output_srt_var = tk.BooleanVar(value=False)
        self.buzz_output_vtt_var = tk.BooleanVar(value=False)
        self.buzz_output_txt_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Etapa 1/5 - Escolha a engine")
        self.message_var = tk.StringVar(value="Escolha a engine para iniciar.")
        self.workspace_info_var = tk.StringVar(value=f"Pasta de trabalho base: {WORKSPACE_ROOT}")
        self.build_info_var = tk.StringVar(value=f"Build: {APP_VERSION}")

        self.current_step = 0
        self.drop_mode = DROP_DISABLED
        self.export_done = False
        self.last_log_file: str | None = None
        self.generated_translation_path: Path | None = None
        self.detected_renpy_version: str | None = None
        self.selected_launcher_path: Path | None = None
        self.unren_temp_bat_path: Path | None = None
        self.unren_temp_should_remove = False
        self.game_process: subprocess.Popen[bytes] | None = None
        self.game_process_mode: str | None = None
        self.running_game_exe: Path | None = None
        self.unity_table_candidates: list[tuple[str, str]] = []
        self.buzz_process: subprocess.Popen[str] | None = None
        self.buzz_running_config: BuzzRunConfig | None = None
        self.buzz_running_stdout: str = ""
        self.buzz_running_stderr: str = ""
        self.translation_thread: threading.Thread | None = None
        self.translation_cancel_event: threading.Event | None = None
        self.translation_result_queue: queue.Queue[JobResult | Exception] | None = None
        self.translation_on_done: Any = None
        self.buzz_video_var.trace_add("write", lambda *_args: self._refresh_renpy_prepare_ui_state())

        self._build_layout()
        self._normalize_buzz_settings()
        self._apply_buzz_output_vars_from_settings()
        self._refresh_renpy_settings_labels()
        self._refresh_buzz_status_label()
        self._refresh_ollama_status_and_models()
        self._update_engine_display()
        self._refresh_game_exe_info()
        self._show_step(0)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Engine.TLabel", font=("Segoe UI", 10, "bold"), foreground="#1f3a5f")
        style.configure("Hint.TLabel", foreground="#335d80")
        style.configure("TButton", padding=(10, 5))

    def _build_layout(self) -> None:
        self.container = ttk.Frame(self.root, padding=14)
        self.container.pack(fill="both", expand=True)

        ttk.Label(self.container, text="Assistente de Tradução Ren'Py/RPGM/Unity", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(self.container, textvariable=self.engine_display_var, style="Engine.TLabel").pack(
            anchor="w", pady=(2, 0)
        )
        ttk.Label(self.container, textvariable=self.build_info_var, style="Hint.TLabel").pack(
            anchor="w", pady=(1, 2)
        )
        ttk.Label(self.container, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor="w", pady=(2, 6)
        )
        self.step_progress = ttk.Progressbar(
            self.container, orient="horizontal", mode="determinate", maximum=5
        )
        self.step_progress.pack(fill="x")
        ttk.Label(self.container, textvariable=self.workspace_info_var, style="Hint.TLabel").pack(
            anchor="w", pady=(6, 10)
        )

        self.steps_wrap = ttk.Frame(self.container)
        self.steps_wrap.pack(fill="both", expand=True)

        self.step_frames = [
            self._build_step_engine(self.steps_wrap),
            self._build_step_project(self.steps_wrap),
            self._build_step_export(self.steps_wrap),
            self._build_step_translated_txt(self.steps_wrap),
            self._build_step_import(self.steps_wrap),
        ]
        for frame in self.step_frames:
            frame.pack_forget()

        ttk.Separator(self.container).pack(fill="x", pady=10)
        ttk.Label(self.container, textvariable=self.message_var, foreground="#1f3a5f").pack(anchor="w")

        nav = ttk.Frame(self.container)
        nav.pack(fill="x", pady=(10, 0))
        self.back_button = ttk.Button(nav, text="Voltar", command=self._on_back)
        self.back_button.pack(side="left")
        self.next_button = ttk.Button(nav, text="Próximo", command=self._on_next)
        self.next_button.pack(side="right")

    def _build_step_engine(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="1) Escolha o modo").pack(anchor="w", pady=(2, 12))
        ttk.Radiobutton(
            frame,
            text="Ren'Py",
            value=ENGINE_RENPY,
            variable=self.engine_var,
            command=self._on_engine_change,
        ).pack(anchor="w", pady=4)
        ttk.Radiobutton(
            frame,
            text="RPGM",
            value=ENGINE_RPGM,
            variable=self.engine_var,
            command=self._on_engine_change,
        ).pack(anchor="w", pady=4)
        ttk.Radiobutton(
            frame,
            text="Unity",
            value=ENGINE_UNITY,
            variable=self.engine_var,
            command=self._on_engine_change,
        ).pack(anchor="w", pady=4)
        ttk.Radiobutton(
            frame,
            text="Buzz (Legendas de Vídeo)",
            value=ENGINE_BUZZ,
            variable=self.engine_var,
            command=self._on_engine_change,
        ).pack(anchor="w", pady=4)
        ttk.Label(
            frame,
            text="O restante do fluxo será ajustado automaticamente para o modo escolhido.",
        ).pack(anchor="w", pady=(12, 0))
        return frame

    def _build_step_project(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.step2_title_var = tk.StringVar(value="2) Selecione (ou arraste) a pasta do projeto")
        self.step2_title_label = ttk.Label(frame, textvariable=self.step2_title_var)
        self.step2_title_label.pack(
            anchor="w", pady=(2, 12)
        )

        self.project_selection_row = ttk.Frame(frame)
        self.project_selection_row.pack(fill="x")
        self.project_dir_entry = ttk.Entry(self.project_selection_row, textvariable=self.project_dir_var)
        self.project_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pick_project_dir_button = ttk.Button(
            self.project_selection_row, text="Selecionar pasta", command=self._pick_project_dir
        )
        self.pick_project_dir_button.pack(side="left")

        hint = "Você pode arrastar a pasta para qualquer área da janela nesta etapa." if HAS_DND else (
            "Arrastar e soltar indisponível (instale tkinterdnd2 para habilitar)."
        )
        self.project_hint_label = ttk.Label(frame, text=hint)
        self.project_hint_label.pack(anchor="w", pady=(10, 0))

        self.renpy_prepare_frame = ttk.LabelFrame(frame, text="Preparação Ren'Py (pré-fluxo)")
        self.renpy_prepare_frame.pack(fill="x", pady=(14, 0))
        self.renpy_prepare_visible = True

        ttk.Label(self.renpy_prepare_frame, textvariable=self.renpy_version_var).pack(
            anchor="w", pady=(6, 2), padx=8
        )
        manual_version_row = ttk.Frame(self.renpy_prepare_frame)
        manual_version_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Entry(manual_version_row, textvariable=self.manual_version_var, width=18).pack(
            side="left", padx=(0, 8)
        )
        self.manual_version_button = ttk.Button(
            manual_version_row,
            text="Usar versão manual",
            command=self._apply_manual_version,
        )
        self.manual_version_button.pack(side="left")
        ttk.Label(self.renpy_prepare_frame, textvariable=self.renpy_launcher_var).pack(
            anchor="w", pady=(0, 8), padx=8
        )

        btn_row = ttk.Frame(self.renpy_prepare_frame)
        btn_row.pack(fill="x", padx=8)
        self.detect_version_button = ttk.Button(
            btn_row, text="Detectar versão", command=self._detect_renpy_version
        )
        self.detect_version_button.pack(side="left", padx=(0, 8), pady=(0, 8))
        self.refresh_launchers_button = ttk.Button(
            btn_row, text="Reverificar launchers", command=self._refresh_launchers
        )
        self.refresh_launchers_button.pack(side="left", padx=(0, 8), pady=(0, 8))
        self.pick_launcher_button = ttk.Button(
            btn_row, text="Selecionar launcher manual", command=self._pick_launcher_manually
        )
        self.pick_launcher_button.pack(side="left", padx=(0, 8), pady=(0, 8))
        self.open_launcher_button = ttk.Button(
            btn_row, text="Abrir launcher", command=self._open_selected_launcher
        )
        self.open_launcher_button.pack(side="left", pady=(0, 8))
        self.open_launcher_button.configure(state="disabled")

        btn_row2 = ttk.Frame(self.renpy_prepare_frame)
        btn_row2.pack(fill="x", padx=8)
        self.run_unren_button = ttk.Button(
            btn_row2, text="Executar UnRen", command=self._run_unren
        )
        self.run_unren_button.pack(side="left", padx=(0, 8), pady=(0, 8))
        self.open_game_prepare_button = ttk.Button(
            btn_row2, text="Abrir jogo (preparar)", command=self._run_open_game_prepare
        )
        self.open_game_prepare_button.pack(side="left", padx=(0, 8), pady=(0, 8))
        self.run_un_cycle_button = ttk.Button(
            btn_row2,
            text="Descompilar rpyc (un.rpy + un.rpyc)",
            command=self._run_un_rpyc_cycle,
        )
        self.run_un_cycle_button.pack(side="left", pady=(0, 8))

        config_row = ttk.Frame(self.renpy_prepare_frame)
        config_row.pack(fill="x", padx=8)
        ttk.Label(config_row, textvariable=self.renpy_launchers_root_info_var).pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )
        self.pick_launchers_root_button = ttk.Button(
            config_row,
            text="Configurar pasta dos launchers",
            command=self._pick_launchers_root,
        )
        self.pick_launchers_root_button.pack(side="left", padx=(8, 0), pady=(0, 6))

        wine_row = ttk.Frame(self.renpy_prepare_frame)
        wine_row.pack(fill="x", padx=8)
        ttk.Label(wine_row, textvariable=self.wine_status_var, style="Hint.TLabel").pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )

        unren_row = ttk.Frame(self.renpy_prepare_frame)
        unren_row.pack(fill="x", padx=8)
        ttk.Label(unren_row, textvariable=self.unren_source_info_var).pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )
        self.pick_unren_source_button = ttk.Button(
            unren_row,
            text="Configurar UnRen",
            command=self._pick_unren_source,
        )
        self.pick_unren_source_button.pack(side="left", padx=(8, 0), pady=(0, 6))

        force_row = ttk.Frame(self.renpy_prepare_frame)
        force_row.pack(fill="x", padx=8)
        ttk.Label(force_row, textvariable=self.force_language_info_var).pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )
        self.pick_force_language_button = ttk.Button(
            force_row,
            text="Configurar force_language",
            command=self._pick_force_language_source,
        )
        self.pick_force_language_button.pack(side="left", padx=(8, 0), pady=(0, 6))

        un_rpy_row = ttk.Frame(self.renpy_prepare_frame)
        un_rpy_row.pack(fill="x", padx=8)
        ttk.Label(un_rpy_row, textvariable=self.un_rpy_info_var).pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )
        self.pick_un_rpy_button = ttk.Button(
            un_rpy_row,
            text="Configurar un.rpy",
            command=self._pick_un_rpy_source,
        )
        self.pick_un_rpy_button.pack(side="left", padx=(8, 0), pady=(0, 6))

        un_rpyc_row = ttk.Frame(self.renpy_prepare_frame)
        un_rpyc_row.pack(fill="x", padx=8)
        ttk.Label(un_rpyc_row, textvariable=self.un_rpyc_info_var).pack(
            side="left", fill="x", expand=True, pady=(0, 6)
        )
        self.pick_un_rpyc_button = ttk.Button(
            un_rpyc_row,
            text="Configurar un.rpyc",
            command=self._pick_un_rpyc_source,
        )
        self.pick_un_rpyc_button.pack(side="left", padx=(8, 0), pady=(0, 6))

        self.renpy_prepare_hint = ttk.Label(
            self.renpy_prepare_frame,
            text=(
                "No Ren'Py: abra o jogo para preparar, rode o ciclo un.rpy/un.rpyc quando necessário, "
                "execute UnRen e abra o launcher compatível."
            ),
            style="Hint.TLabel",
        )
        self.renpy_prepare_hint.pack(anchor="w", padx=8, pady=(0, 8))

        self.renpy_prepare_buttons = [
            self.detect_version_button,
            self.manual_version_button,
            self.refresh_launchers_button,
            self.pick_launcher_button,
            self.open_launcher_button,
            self.run_unren_button,
            self.open_game_prepare_button,
            self.run_un_cycle_button,
            self.pick_launchers_root_button,
            self.pick_unren_source_button,
            self.pick_force_language_button,
            self.pick_un_rpy_button,
            self.pick_un_rpyc_button,
        ]

        self.unity_prepare_frame = ttk.LabelFrame(frame, text="Preparação Unity (localização)")
        self.unity_prepare_frame.pack(fill="x", pady=(12, 0))
        self.unity_prepare_visible = True

        ttk.Label(self.unity_prepare_frame, textvariable=self.unity_tables_info_var).pack(
            anchor="w", padx=8, pady=(6, 2)
        )
        ttk.Label(self.unity_prepare_frame, textvariable=self.unity_selected_table_var).pack(
            anchor="w", padx=8, pady=(0, 6)
        )

        self.unity_table_listbox = tk.Listbox(self.unity_prepare_frame, height=6, exportselection=False)
        self.unity_table_listbox.pack(fill="x", padx=8, pady=(0, 8))
        self.unity_table_listbox.bind("<<ListboxSelect>>", self._on_unity_table_highlighted)

        unity_btn_row = ttk.Frame(self.unity_prepare_frame)
        unity_btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.detect_unity_tables_button = ttk.Button(
            unity_btn_row,
            text="Detectar tables de idioma",
            command=self._detect_unity_tables,
        )
        self.detect_unity_tables_button.pack(side="left", padx=(0, 8))
        self.apply_unity_table_button = ttk.Button(
            unity_btn_row,
            text="Usar seleção para export/import",
            command=self._apply_unity_table_selection,
        )
        self.apply_unity_table_button.pack(side="left")
        self.clear_unity_table_button = ttk.Button(
            unity_btn_row,
            text="Limpar seleção",
            command=self._clear_unity_table_selection,
        )
        self.clear_unity_table_button.pack(side="left", padx=(8, 0))

        self.unity_prepare_hint = ttk.Label(
            self.unity_prepare_frame,
            text=(
                "Se houver várias tables de idioma, selecione a desejada. "
                "Se não detectar tables, o app exporta somente arquivos textuais comuns."
            ),
            style="Hint.TLabel",
        )
        self.unity_prepare_hint.pack(anchor="w", padx=8, pady=(0, 8))

        self.unity_prepare_buttons = [
            self.detect_unity_tables_button,
            self.apply_unity_table_button,
            self.clear_unity_table_button,
        ]

        self.buzz_prepare_frame = ttk.LabelFrame(frame, text="Buzz (legendas)")
        self.buzz_prepare_frame.pack(fill="x", pady=(10, 0))
        self.buzz_prepare_visible = True

        ttk.Label(self.buzz_prepare_frame, textvariable=self.buzz_status_var).pack(
            anchor="w", padx=8, pady=(4, 2)
        )

        buzz_video_row = ttk.Frame(self.buzz_prepare_frame)
        buzz_video_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Entry(buzz_video_row, textvariable=self.buzz_video_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self.pick_buzz_video_button = ttk.Button(
            buzz_video_row,
            text="Selecionar vídeo/áudio",
            command=self._pick_buzz_video_file,
        )
        self.pick_buzz_video_button.pack(side="left")

        config_row = ttk.Frame(self.buzz_prepare_frame)
        config_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(config_row, text="Tipo:").pack(side="left")
        self.buzz_model_type_combo = ttk.Combobox(
            config_row,
            textvariable=self.buzz_model_type_var,
            values=list(BUZZ_MODEL_TYPES),
            state="readonly",
            width=12,
        )
        self.buzz_model_type_combo.pack(side="left", padx=(4, 8))
        self.buzz_model_type_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())
        ttk.Label(config_row, text="Modelo:").pack(side="left")
        self.buzz_model_size_combo = ttk.Combobox(
            config_row,
            textvariable=self.buzz_model_size_var,
            values=list(BUZZ_MODEL_SIZES),
            state="readonly",
            width=13,
        )
        self.buzz_model_size_combo.pack(side="left", padx=(4, 8))
        self.buzz_model_size_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())
        ttk.Label(config_row, text="Task:").pack(side="left")
        self.buzz_task_combo = ttk.Combobox(
            config_row,
            textvariable=self.buzz_task_var,
            values=list(BUZZ_TASKS),
            state="readonly",
            width=10,
        )
        self.buzz_task_combo.pack(side="left", padx=(4, 6))
        self.buzz_task_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        extra_row = ttk.Frame(self.buzz_prepare_frame)
        extra_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(extra_row, text="Idioma:").pack(side="left")
        self.buzz_language_combo = ttk.Combobox(
            extra_row,
            textvariable=self.buzz_language_var,
            values=list(BUZZ_LANGUAGE_MENU_OPTIONS),
            state="readonly",
            width=22,
        )
        self.buzz_language_combo.pack(side="left", padx=(4, 10))
        self.buzz_language_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())
        self.buzz_word_timestamps_check = ttk.Checkbutton(
            extra_row,
            text="Tempos em nível de palavra",
            variable=self.buzz_word_timestamps_var,
            command=self._save_settings,
        )
        self.buzz_word_timestamps_check.pack(side="left", padx=(0, 10))
        self.buzz_extract_speech_check = ttk.Checkbutton(
            extra_row,
            text="Extrair fala",
            variable=self.buzz_extract_speech_var,
            command=self._save_settings,
        )
        self.buzz_extract_speech_check.pack(side="left")

        output_row = ttk.Frame(self.buzz_prepare_frame)
        output_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(output_row, text="Saída:").pack(side="left")
        self.buzz_srt_check = ttk.Checkbutton(
            output_row,
            text="SRT",
            variable=self.buzz_output_srt_var,
            command=self._save_settings,
        )
        self.buzz_srt_check.pack(side="left", padx=(8, 6))
        self.buzz_vtt_check = ttk.Checkbutton(
            output_row,
            text="VTT",
            variable=self.buzz_output_vtt_var,
            command=self._save_settings,
        )
        self.buzz_vtt_check.pack(side="left", padx=(0, 6))
        self.buzz_txt_check = ttk.Checkbutton(
            output_row,
            text="TXT",
            variable=self.buzz_output_txt_var,
            command=self._save_settings,
        )
        self.buzz_txt_check.pack(side="left")

        output_dir_row = ttk.Frame(self.buzz_prepare_frame)
        output_dir_row.pack(fill="x", padx=8, pady=(0, 4))
        self.buzz_same_dir_check = ttk.Checkbutton(
            output_dir_row,
            text="Salvar na mesma pasta do vídeo",
            variable=self.buzz_output_same_dir_var,
            command=self._on_buzz_output_dir_mode_change,
        )
        self.buzz_same_dir_check.pack(side="left")

        output_dir_pick_row = ttk.Frame(self.buzz_prepare_frame)
        output_dir_pick_row.pack(fill="x", padx=8, pady=(0, 6))
        self.buzz_output_dir_entry = ttk.Entry(
            output_dir_pick_row,
            textvariable=self.buzz_output_dir_var,
        )
        self.buzz_output_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pick_buzz_output_dir_button = ttk.Button(
            output_dir_pick_row,
            text="Selecionar pasta de saída",
            command=self._pick_buzz_output_dir,
        )
        self.pick_buzz_output_dir_button.pack(side="left")

        buzz_action_row = ttk.Frame(self.buzz_prepare_frame)
        buzz_action_row.pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_buzz_status_button = ttk.Button(
            buzz_action_row,
            text="Verificar Buzz",
            command=self._refresh_buzz_status_label,
        )
        self.refresh_buzz_status_button.pack(side="left", padx=(0, 8))
        self.run_buzz_button = ttk.Button(
            buzz_action_row,
            text="Gerar legenda (Buzz)",
            command=self._confirm_and_run_buzz,
        )
        self.run_buzz_button.pack(side="left")
        self.run_translate_buzz_button = ttk.Button(
            buzz_action_row,
            text="Gerar e traduzir legenda",
            command=self._run_buzz_and_auto_translate,
        )
        self.run_translate_buzz_button.pack(side="left", padx=(8, 0))

        self.buzz_hint_label = ttk.Label(
            self.buzz_prepare_frame,
            text=(
                "Padrão: transcribe + large-v3-turbo + SRT | "
                "A tarefa 'translate' no Buzz tende a produzir saída em inglês."
            ),
            style="Hint.TLabel",
        )
        self.buzz_hint_label.pack(anchor="w", padx=8, pady=(0, 6))

        self.buzz_prepare_buttons = [
            self.pick_buzz_video_button,
            self.buzz_model_type_combo,
            self.buzz_model_size_combo,
            self.buzz_task_combo,
            self.buzz_language_combo,
            self.buzz_word_timestamps_check,
            self.buzz_extract_speech_check,
            self.buzz_srt_check,
            self.buzz_vtt_check,
            self.buzz_txt_check,
            self.buzz_same_dir_check,
            self.buzz_output_dir_entry,
            self.pick_buzz_output_dir_button,
            self.refresh_buzz_status_button,
            self.run_buzz_button,
            self.run_translate_buzz_button,
        ]
        return frame

    def _build_step_export(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="3) Exportar textos").pack(anchor="w", pady=(2, 12))

        self.workspace_label = ttk.Label(frame, text="")
        self.workspace_label.pack(anchor="w", pady=(0, 8))

        ttk.Button(frame, text="Executar exportação", command=self._run_export).pack(anchor="w")
        self.auto_translate_import_button = ttk.Button(
            frame,
            text="Exportar + traduzir + importar automaticamente",
            command=self._run_auto_export_translate_import,
        )
        self.auto_translate_import_button.pack(anchor="w", pady=(8, 0))
        local_row = ttk.Frame(frame)
        local_row.pack(fill="x", pady=(10, 0))
        ttk.Label(local_row, textvariable=self.ollama_status_var, style="Hint.TLabel").pack(side="left", padx=(0, 10))
        self.refresh_ollama_button = ttk.Button(
            local_row,
            text="Atualizar Ollama",
            command=self._refresh_ollama_status_and_models,
        )
        self.refresh_ollama_button.pack(side="left", padx=(0, 12))
        ttk.Label(local_row, text="Modelo Ollama:").pack(side="left")
        self.local_model_combo = ttk.Combobox(
            local_row,
            textvariable=self.local_translation_model_var,
            state="normal",
            width=28,
        )
        self.local_model_combo.pack(side="left", padx=(6, 10))
        self.local_model_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())
        ttk.Label(local_row, text="Timeout total (s):").pack(side="left")
        ttk.Entry(local_row, textvariable=self.local_translation_timeout_var, width=8).pack(side="left", padx=(6, 10))
        ttk.Label(local_row, text="Chunk (linhas):").pack(side="left")
        ttk.Entry(local_row, textvariable=self.local_translation_chunk_var, width=6).pack(side="left", padx=(6, 0))
        self.cancel_translation_button = ttk.Button(
            frame,
            text="Cancelar tradução local em andamento",
            command=self._cancel_local_translation,
        )
        self.cancel_translation_button.pack(anchor="w", pady=(8, 0))
        self.cancel_translation_button.configure(state="disabled")

        file_row = ttk.Frame(frame)
        file_row.pack(fill="x", pady=(14, 0))
        ttk.Label(file_row, text="TXT gerado:").pack(side="left")
        self.generated_txt_label = ttk.Label(file_row, text="-")
        self.generated_txt_label.pack(side="left", padx=(8, 0))

        self.open_generated_button = ttk.Button(
            frame, text="Abrir TXT gerado", command=self._open_generated_txt
        )
        self.open_generated_button.pack(anchor="w", pady=(10, 0))
        self.open_generated_button.configure(state="disabled")

        self.open_generated_folder_button = ttk.Button(
            frame, text="Abrir pasta do TXT", command=self._open_generated_txt_folder
        )
        self.open_generated_folder_button.pack(anchor="w", pady=(8, 0))
        self.open_generated_folder_button.configure(state="disabled")

        ttk.Separator(frame).pack(fill="x", pady=(14, 10))
        split_row = ttk.Frame(frame)
        split_row.pack(fill="x")
        ttk.Label(split_row, text="Dividir em partes:").pack(side="left")
        ttk.Entry(split_row, textvariable=self.split_parts_var, width=6).pack(side="left", padx=(8, 10))
        self.split_generated_button = ttk.Button(
            split_row, text="Dividir TXT gerado", command=self._split_generated_txt
        )
        self.split_generated_button.pack(side="left", padx=(0, 8))
        self.join_parts_button = ttk.Button(
            split_row, text="Juntar partes traduzidas", command=self._join_split_parts
        )
        self.join_parts_button.pack(side="left")
        ttk.Label(
            frame,
            text=f"As partes ficam em {DOWNLOADS_DIR}. O merge substitui o TXT no workspace da engine.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(8, 0))
        self.split_generated_button.configure(state="disabled")
        self.join_parts_button.configure(state="disabled")
        return frame

    def _build_step_translated_txt(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="4) Escolher TXT traduzido final").pack(anchor="w", pady=(2, 12))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.translated_file_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ttk.Button(row, text="Selecionar arquivo", command=self._pick_translated_file).pack(
            side="left"
        )

        hint = "Nesta etapa, arraste para a janela apenas arquivo .txt." if HAS_DND else (
            "Selecione o TXT traduzido pelo botão ao lado."
        )
        ttk.Label(frame, text=hint).pack(anchor="w", pady=(10, 0))
        return frame

    def _build_step_import(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="5) Importar tradução no jogo").pack(anchor="w", pady=(2, 12))
        ttk.Button(frame, text="Executar importação", command=self._run_import).pack(anchor="w")
        self.open_log_button = ttk.Button(frame, text="Abrir log da importação", command=self._open_log)
        self.open_log_button.pack(anchor="w", pady=(10, 0))
        self.open_log_button.configure(state="disabled")

        ttk.Separator(frame).pack(fill="x", pady=(14, 10))
        ttk.Label(frame, textvariable=self.game_exe_info_var, style="Hint.TLabel").pack(anchor="w")
        self.pick_game_exe_button = ttk.Button(
            frame,
            text="Definir executável do jogo",
            command=self._pick_and_save_game_exe,
        )
        self.pick_game_exe_button.pack(anchor="w", pady=(8, 0))

        finish_row = ttk.Frame(frame)
        finish_row.pack(fill="x", pady=(14, 0))
        self.finish_open_button = ttk.Button(
            finish_row,
            text="Finalizar e abrir",
            command=self._on_finish_and_open,
        )
        self.finish_open_button.pack(side="left", padx=(0, 8))
        self.finish_restart_button = ttk.Button(
            finish_row,
            text="Finalizar e voltar ao início",
            command=self._on_finish_and_restart,
        )
        self.finish_restart_button.pack(side="left")
        return frame

    def _engine_label(self) -> str:
        engine = normalize_engine(self.engine_var.get())
        if engine == ENGINE_RENPY:
            return "Ren'Py"
        if engine == ENGINE_RPGM:
            return "RPGM"
        if engine == ENGINE_UNITY:
            return "Unity"
        if engine == ENGINE_BUZZ:
            return "Buzz (Legendas)"
        return engine

    def _update_engine_display(self) -> None:
        self.engine_display_var.set(f"Engine selecionada: {self._engine_label()}")

    def _refresh_renpy_settings_labels(self) -> None:
        launchers_root = self.launchers_root_var.get().strip() or "(não definida)"
        unren_source = self.unren_source_var.get().strip() or "(não definido)"
        force_source = self.force_language_source_var.get().strip() or "(não definido)"
        un_rpy_source = self.un_rpy_source_var.get().strip() or "(não definido)"
        un_rpyc_source = self.un_rpyc_source_var.get().strip() or "(não definido)"
        self.renpy_launchers_root_info_var.set(f"Pasta de versões Ren'Py: {launchers_root}")
        self.unren_source_info_var.set(f"Fonte UnRen: {unren_source}")
        self.force_language_info_var.set(f"Fonte force_language: {force_source}")
        self.un_rpy_info_var.set(f"Fonte un.rpy: {un_rpy_source}")
        self.un_rpyc_info_var.set(f"Fonte un.rpyc: {un_rpyc_source}")
        self._refresh_wine_status_label()

    def _refresh_wine_status_label(self) -> None:
        if platform.system() != "Linux":
            self.wine_status_var.set("Status Wine: não necessário neste sistema.")
            return
        wine_bin = shutil.which("wine")
        if wine_bin:
            self.wine_status_var.set(f"Status Wine: detectado ({wine_bin}).")
            return
        self.wine_status_var.set("Status Wine: não detectado (necessário para abrir .exe no Linux).")

    def _normalize_buzz_settings(self) -> None:
        if self.buzz_model_type_var.get().strip() not in BUZZ_MODEL_TYPES:
            self.buzz_model_type_var.set("fasterwhisper")
        if self.buzz_model_size_var.get().strip() not in BUZZ_MODEL_SIZES:
            self.buzz_model_size_var.set("large-v3-turbo")
        if self.buzz_task_var.get().strip() not in BUZZ_TASKS:
            self.buzz_task_var.set("transcribe")
        language_value = self.buzz_language_var.get().strip()
        if not language_value:
            self.buzz_language_var.set("Detectar idioma (auto)")

    def _apply_buzz_output_vars_from_settings(self) -> None:
        raw = self.settings.get("buzz_output_formats")
        output_formats: list[str]
        if isinstance(raw, list):
            output_formats = [value for value in raw if isinstance(value, str) and value in BUZZ_OUTPUT_FORMATS]
        else:
            output_formats = []
        if not output_formats:
            output_formats = ["srt"]
        self.buzz_output_srt_var.set("srt" in output_formats)
        self.buzz_output_vtt_var.set("vtt" in output_formats)
        self.buzz_output_txt_var.set("txt" in output_formats)

    def _selected_buzz_output_formats(self) -> list[str]:
        output_formats: list[str] = []
        if self.buzz_output_srt_var.get():
            output_formats.append("srt")
        if self.buzz_output_vtt_var.get():
            output_formats.append("vtt")
        if self.buzz_output_txt_var.get():
            output_formats.append("txt")
        if not output_formats:
            output_formats = ["srt"]
        return output_formats

    def _refresh_buzz_output_dir_ui_state(self) -> None:
        is_same_dir = bool(self.buzz_output_same_dir_var.get())
        entry_state = "disabled" if is_same_dir else "normal"
        button_state = "disabled" if is_same_dir else "normal"
        if self._game_running() or self._buzz_running():
            entry_state = "disabled"
            button_state = "disabled"
        self.buzz_output_dir_entry.configure(state=entry_state)
        self.pick_buzz_output_dir_button.configure(state=button_state)

    def _on_buzz_output_dir_mode_change(self) -> None:
        self._refresh_buzz_output_dir_ui_state()
        self._save_settings()

    def _refresh_buzz_status_label(self) -> None:
        detection = detectar_buzz()
        self.buzz_status_var.set(f"Buzz: {detection.message}")

    def _pick_buzz_video_file(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de selecionar mídia para Buzz.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione vídeo/áudio para legendagem (Buzz)",
            filetypes=[
                ("Mídia", "*.mp4 *.mkv *.mov *.webm *.avi *.mp3 *.wav *.m4a *.flac *.ogg *.opus"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not selected:
            return
        self.buzz_video_var.set(selected)
        self._set_message("Arquivo de mídia selecionado para legendagem com Buzz.")

    def _pick_buzz_output_dir(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de alterar pasta de saída do Buzz.")
            return
        if self.buzz_output_same_dir_var.get():
            self._set_message("Desmarque 'Salvar na mesma pasta do vídeo' para escolher outra pasta.")
            return
        selected = filedialog.askdirectory(title="Selecione a pasta de saída das legendas (Buzz)")
        if not selected:
            return
        self.buzz_output_dir_var.set(selected)
        self._save_settings()
        self._set_message("Pasta de saída do Buzz atualizada.")

    def _build_buzz_config_from_ui(self) -> BuzzRunConfig:
        output_directory: Path | None = None
        if not self.buzz_output_same_dir_var.get():
            raw_output = self.buzz_output_dir_var.get().strip()
            if not raw_output:
                raise ValueError("Defina uma pasta de saída do Buzz ou marque a opção de mesma pasta.")
            output_directory = Path(raw_output)

        return BuzzRunConfig(
            input_path=Path(self.buzz_video_var.get().strip()),
            model_type=self.buzz_model_type_var.get().strip(),
            model_size=self.buzz_model_size_var.get().strip(),
            task=self.buzz_task_var.get().strip(),
            language=self.buzz_language_var.get().strip(),
            word_timestamps=bool(self.buzz_word_timestamps_var.get()),
            extract_speech=bool(self.buzz_extract_speech_var.get()),
            output_formats=tuple(self._selected_buzz_output_formats()),
            output_directory=output_directory,
            hide_gui=True,
        )

    def _confirm_and_run_buzz(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de iniciar o Buzz.")
            return
        if self.buzz_process is not None and self.buzz_process.poll() is None:
            self._set_message("Já existe uma execução do Buzz em andamento.")
            return

        self._normalize_buzz_settings()
        self._save_settings()

        try:
            config = self._build_buzz_config_from_ui()
            detection = detectar_buzz()
            if not detection.available:
                raise ValueError(detection.message)
        except ValueError as exc:
            messagebox.showerror("Configuração Buzz inválida", str(exc))
            self._set_message(str(exc))
            return

        output_mode_text = (
            "mesma pasta do vídeo"
            if config.output_directory is None
            else str(config.output_directory)
        )
        should_run = messagebox.askyesno(
            "Confirmar geração de legenda",
            (
                "Executar Buzz com estas opções?\n\n"
                f"Arquivo: {config.input_path}\n"
                f"Tipo: {config.model_type}\n"
                f"Modelo: {config.model_size}\n"
                f"Tarefa: {config.task}\n"
                f"Idioma: {config.language or 'auto'}\n"
                f"Tempos em nível de palavra: {'sim' if config.word_timestamps else 'não'}\n"
                f"Formato(s): {', '.join(config.output_formats)}\n"
                f"Saída: {output_mode_text}"
            ),
        )
        if not should_run:
            self._set_message("Execução Buzz cancelada.")
            return

        try:
            self.buzz_process = iniciar_execucao_buzz(config)
        except Exception as exc:
            messagebox.showerror("Falha ao iniciar Buzz", str(exc))
            self._set_message(f"Falha ao iniciar Buzz: {exc}")
            return

        self.buzz_running_config = config
        self.buzz_running_stdout = ""
        self.buzz_running_stderr = ""
        self._set_message("Buzz em execução... isso pode levar alguns minutos no primeiro uso do modelo.")
        self._refresh_renpy_prepare_ui_state()
        self.root.after(600, self._monitor_buzz_process)

    def _monitor_buzz_process(self) -> None:
        if self.buzz_process is None:
            return
        if self.buzz_process.poll() is None:
            if self.root.winfo_exists():
                self.root.after(600, self._monitor_buzz_process)
            return

        stdout, stderr = self.buzz_process.communicate()
        returncode = self.buzz_process.returncode or 0
        config = self.buzz_running_config

        self.buzz_process = None
        self.buzz_running_config = None
        self.buzz_running_stdout = stdout or ""
        self.buzz_running_stderr = stderr or ""
        self._refresh_renpy_prepare_ui_state()

        if config is None:
            self._set_message("Execução Buzz finalizada, mas sem configuração associada.")
            return

        result = finalizar_execucao_buzz(
            config=config,
            returncode=returncode,
            stdout=self.buzz_running_stdout,
            stderr=self.buzz_running_stderr,
        )
        if not result.success:
            messagebox.showerror("Erro no Buzz", result.message)
            self._set_message(result.message)
            return

        details = result.message
        if result.generated_files:
            details += "\n\nArquivos gerados:\n" + "\n".join(f"- {path}" for path in result.generated_files)
        if result.warnings:
            details += "\n\nAlertas:\n" + "\n".join(f"- {warning}" for warning in result.warnings)
        messagebox.showinfo("Buzz concluído", details)

        if result.generated_files:
            self._set_message(f"Buzz finalizado com sucesso. Arquivo principal: {result.generated_files[0]}")
        else:
            self._set_message("Buzz finalizado. Revise a pasta de saída para confirmar os arquivos.")

    def _preferred_buzz_generated_file(self, generated_files: list[str]) -> Path | None:
        paths = [Path(item) for item in generated_files if item]
        for suffix in [".srt", ".vtt", ".txt"]:
            for path in paths:
                if path.exists() and path.is_file() and path.suffix.lower() == suffix:
                    return path
        for path in paths:
            if path.exists() and path.is_file():
                return path
        return None

    def _translation_running(self) -> bool:
        return self.translation_thread is not None and self.translation_thread.is_alive()

    def _cancel_local_translation(self) -> None:
        if self.translation_cancel_event is None or not self._translation_running():
            self._set_message("Não há tradução local em andamento para cancelar.")
            return
        self.translation_cancel_event.set()
        self._set_message("Cancelamento solicitado para a tradução local. Aguarde finalizar o bloco atual.")

    def _build_local_translate_config(self, input_path: Path, output_dir: Path) -> LocalTranslateConfig:
        model = self.local_translation_model_var.get().strip() or DEFAULT_MODEL
        timeout_raw = self.local_translation_timeout_var.get().strip() or str(DEFAULT_TOTAL_TIMEOUT_SECONDS)
        chunk_raw = self.local_translation_chunk_var.get().strip() or str(DEFAULT_CHUNK_LINES)
        try:
            total_timeout = int(timeout_raw)
            chunk_lines = int(chunk_raw)
        except ValueError as exc:
            raise ValueError("Timeout e chunk devem ser números inteiros.") from exc
        if total_timeout <= 0:
            raise ValueError("Timeout deve ser maior que zero.")
        if chunk_lines < 0:
            raise ValueError("Chunk deve ser zero ou maior.")
        normalized_chunk = chunk_lines
        if chunk_lines == 0:
            normalized_chunk = 10**9
        self.local_translation_model_var.set(model)
        self.local_translation_timeout_var.set(str(total_timeout))
        self.local_translation_chunk_var.set("0" if chunk_lines == 0 else str(chunk_lines))
        return LocalTranslateConfig(
            input_path=input_path,
            output_dir=output_dir,
            model=model,
            total_timeout_seconds=total_timeout,
            chunk_lines=normalized_chunk,
        )

    def _refresh_ollama_status_and_models(self) -> None:
        url = f"{DEFAULT_OLLAMA_URL.rstrip('/')}/api/tags"
        try:
            request = urllib.request.Request(url=url, method="GET")
            with urllib.request.urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models: list[str] = []
            for item in payload.get("models", []):
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        models.append(name.strip())
            self.ollama_models = sorted(set(models))
            self.local_model_combo.configure(values=self.ollama_models)
            current = self.local_translation_model_var.get().strip()
            if not current and self.ollama_models:
                self.local_translation_model_var.set(self.ollama_models[0])
            self.ollama_status_var.set(f"Ollama: online ({len(self.ollama_models)} modelo(s))")
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.ollama_models = []
            self.local_model_combo.configure(values=[])
            self.ollama_status_var.set("Ollama: offline")

    def _on_local_translation_progress(self, translated_lines: int, total_lines: int) -> None:
        if not self.root.winfo_exists():
            return
        progress = min(100, int((translated_lines / max(1, total_lines)) * 100))
        self.root.after(
            0,
            lambda: self._set_message(
                f"Tradução local em andamento: {translated_lines}/{total_lines} linhas ({progress}%)."
            ),
        )

    def _run_local_translation_async(self, config: LocalTranslateConfig, on_done) -> None:
        if self._translation_running():
            messagebox.showwarning("Tradução em andamento", "Já existe uma tradução local em andamento.")
            return

        self.translation_cancel_event = threading.Event()
        self.translation_result_queue = queue.Queue(maxsize=1)
        self.translation_on_done = on_done
        self.cancel_translation_button.configure(state="normal")
        runtime_config = LocalTranslateConfig(
            input_path=config.input_path,
            output_dir=config.output_dir,
            model=config.model,
            ollama_base_url=config.ollama_base_url,
            request_timeout_seconds=config.request_timeout_seconds,
            total_timeout_seconds=config.total_timeout_seconds,
            chunk_lines=config.chunk_lines,
            cancel_event=self.translation_cancel_event,
            progress_callback=self._on_local_translation_progress,
        )

        def worker() -> None:
            try:
                result = translate_document_local(runtime_config)
                self.translation_result_queue.put(result)
            except Exception as exc:
                self.translation_result_queue.put(exc)

        self.translation_thread = threading.Thread(target=worker, daemon=True, name="local-translate-worker")
        self.translation_thread.start()
        self._refresh_renpy_prepare_ui_state()
        self.root.after(300, self._poll_local_translation_result)

    def _poll_local_translation_result(self) -> None:
        if self.translation_result_queue is None:
            return
        try:
            payload = self.translation_result_queue.get_nowait()
        except queue.Empty:
            if self._translation_running() and self.root.winfo_exists():
                self.root.after(300, self._poll_local_translation_result)
            return

        self.translation_thread = None
        self.cancel_translation_button.configure(state="disabled")
        self._refresh_renpy_prepare_ui_state()
        on_done = self.translation_on_done
        self.translation_on_done = None
        self.translation_result_queue = None
        self.translation_cancel_event = None

        if isinstance(payload, Exception):
            result = JobResult(False, f"Falha inesperada na tradução local: {payload}")
        else:
            result = payload
        if callable(on_done):
            on_done(result)

    def _run_buzz_and_auto_translate(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de iniciar o Buzz.")
            return
        if self._buzz_running():
            self._set_message("Já existe uma execução do Buzz em andamento.")
            return
        if self._translation_running():
            self._set_message("Já existe uma tradução local em andamento.")
            return

        self._normalize_buzz_settings()
        self._save_settings()

        try:
            config = self._build_buzz_config_from_ui()
            detection = detectar_buzz()
            if not detection.available:
                raise ValueError(detection.message)
        except ValueError as exc:
            messagebox.showerror("Configuração Buzz inválida", str(exc))
            self._set_message(str(exc))
            return

        should_run = messagebox.askyesno(
            "Gerar e traduzir legenda",
            (
                "Executar Buzz e depois traduzir localmente (Ollama) a legenda gerada?\n\n"
                f"Arquivo: {config.input_path}\n"
                f"Formato(s): {', '.join(config.output_formats)}\n"
                "Destino da tradução: português"
            ),
        )
        if not should_run:
            self._set_message("Geração/tradução Buzz cancelada.")
            return

        self._set_message("Buzz em execução...")
        self.root.update_idletasks()
        buzz_result = executar_buzz(config)
        if not buzz_result.success:
            messagebox.showerror("Erro no Buzz", buzz_result.message)
            self._set_message(buzz_result.message)
            return

        subtitle_path = self._preferred_buzz_generated_file(buzz_result.generated_files)
        if subtitle_path is None:
            details = buzz_result.message
            if buzz_result.warnings:
                details += "\n\n" + "\n".join(f"- {warning}" for warning in buzz_result.warnings)
            messagebox.showwarning("Buzz sem arquivo traduzível", details)
            self._set_message("Buzz terminou, mas não encontrei legenda para enviar ao tradutor.")
            return

        self._set_message(f"Buzz concluído. Iniciando tradução local de {subtitle_path.name}...")
        self.root.update_idletasks()
        try:
            config_translate = self._build_local_translate_config(subtitle_path, subtitle_path.parent)
        except ValueError as exc:
            messagebox.showerror("Configuração de tradução inválida", str(exc))
            self._set_message(str(exc))
            return

        def on_done(translate_result: JobResult) -> None:
            if not translate_result.success:
                messagebox.showerror("Tradução local falhou", translate_result.message)
                self._set_message(
                    f"Buzz gerou {subtitle_path.name}, mas a tradução local falhou. Use o arquivo manualmente."
                )
                return
            details = translate_result.message
            if translate_result.generated_files:
                details += "\n\nArquivo traduzido:\n" + "\n".join(f"- {path}" for path in translate_result.generated_files)
            messagebox.showinfo("Legenda traduzida", details)
            self._set_message("Legenda gerada e traduzida localmente com sucesso.")

        self._run_local_translation_async(config_translate, on_done)

    def _get_game_exe_map(self) -> dict[str, str]:
        raw = self.settings.get("game_exe_by_project")
        if not isinstance(raw, dict):
            raw = {}
            self.settings["game_exe_by_project"] = raw
        normalized: dict[str, str] = {}
        for project_key, exe_path in raw.items():
            if isinstance(project_key, str) and isinstance(exe_path, str):
                normalized[project_key] = exe_path
        self.settings["game_exe_by_project"] = normalized
        return normalized

    def _get_unity_table_selection_map(self) -> dict[str, str]:
        raw = self.settings.get("unity_table_selection_by_project")
        if not isinstance(raw, dict):
            raw = {}
            self.settings["unity_table_selection_by_project"] = raw
        normalized: dict[str, str] = {}
        for project_key, selection_id in raw.items():
            if isinstance(project_key, str) and isinstance(selection_id, str):
                normalized[project_key] = selection_id
        self.settings["unity_table_selection_by_project"] = normalized
        return normalized

    def _get_saved_unity_table_selection_for_project(self, project: Path) -> str | None:
        project_key = _project_settings_key(project)
        return self._get_unity_table_selection_map().get(project_key)

    def _save_unity_table_selection_for_project(self, project: Path, selection_id: str | None) -> None:
        project_key = _project_settings_key(project)
        selection_map = self._get_unity_table_selection_map()
        if selection_id:
            selection_map[project_key] = selection_id
        else:
            selection_map.pop(project_key, None)
        self._save_settings()

    def _get_saved_game_exe_for_project(self, project: Path) -> Path | None:
        project_key = _project_settings_key(project)
        raw = self._get_game_exe_map().get(project_key)
        if not raw:
            return None
        return Path(raw)

    def _save_game_exe_for_project(self, project: Path, exe_path: Path) -> None:
        project_key = _project_settings_key(project)
        self._get_game_exe_map()[project_key] = str(exe_path)
        self._save_settings()

    def _refresh_game_exe_info(self) -> None:
        project = self._project_path_if_valid()
        if project is None:
            self.game_exe_info_var.set("Arquivo de inicialização do jogo: (defina a pasta do projeto)")
            return

        saved = self._get_saved_game_exe_for_project(project)
        if saved and saved.exists() and saved.is_file():
            self.game_exe_info_var.set(f"Arquivo salvo: {saved}")
            return
        if saved:
            self.game_exe_info_var.set(
                f"Arquivo salvo não encontrado: {saved} (será necessário redefinir)"
            )
            return

        detected = detectar_executavel_jogo(project)
        if detected and detected.exists() and detected.is_file():
            self.game_exe_info_var.set(f"Arquivo detectável: {detected} (ainda não salvo)")
            return

        self.game_exe_info_var.set("Arquivo de inicialização não detectado (defina manualmente)")

    def _save_settings(self) -> None:
        self.settings["launchers_root"] = self.launchers_root_var.get().strip()
        self.settings["unren_source_path"] = self.unren_source_var.get().strip()
        self.settings["force_language_path"] = self.force_language_source_var.get().strip()
        self.settings["un_rpy_source_path"] = self.un_rpy_source_var.get().strip()
        self.settings["un_rpyc_source_path"] = self.un_rpyc_source_var.get().strip()
        self.settings["buzz_model_type"] = self.buzz_model_type_var.get().strip()
        self.settings["buzz_model_size"] = self.buzz_model_size_var.get().strip()
        self.settings["buzz_task"] = self.buzz_task_var.get().strip()
        self.settings["buzz_language"] = self.buzz_language_var.get().strip()
        self.settings["buzz_word_timestamps"] = bool(self.buzz_word_timestamps_var.get())
        self.settings["buzz_extract_speech"] = bool(self.buzz_extract_speech_var.get())
        self.settings["buzz_output_same_dir"] = bool(self.buzz_output_same_dir_var.get())
        self.settings["buzz_output_directory"] = self.buzz_output_dir_var.get().strip()
        self.settings["buzz_output_formats"] = self._selected_buzz_output_formats()
        self.settings["local_translation_model"] = self.local_translation_model_var.get().strip() or DEFAULT_MODEL
        self.settings["local_translation_timeout_seconds"] = self.local_translation_timeout_var.get().strip()
        self.settings["local_translation_chunk_lines"] = self.local_translation_chunk_var.get().strip()
        self.settings["game_exe_by_project"] = self._get_game_exe_map()
        self.settings["unity_table_selection_by_project"] = self._get_unity_table_selection_map()
        save_app_settings(self.settings)
        self._refresh_renpy_settings_labels()
        self._refresh_game_exe_info()

    def _refresh_renpy_prepare_ui_state(self) -> None:
        engine = normalize_engine(self.engine_var.get())
        is_renpy = engine == ENGINE_RENPY
        is_unity = engine == ENGINE_UNITY
        is_buzz = engine == ENGINE_BUZZ
        game_busy = self._game_running()
        buzz_busy = self._buzz_running()
        translation_busy = self._translation_running()
        app_busy = game_busy or buzz_busy or translation_busy
        self._refresh_wine_status_label()

        if self.current_step == 1 and is_buzz:
            self.step2_title_var.set("2) Buzz: selecione vídeo/áudio e gere legenda")
        else:
            self.step2_title_var.set("2) Selecione (ou arraste) a pasta do projeto")

        if is_buzz:
            if self.project_selection_row.winfo_manager():
                self.project_selection_row.pack_forget()
            if self.project_hint_label.winfo_manager():
                self.project_hint_label.pack_forget()
        else:
            if not self.project_selection_row.winfo_manager():
                self.project_selection_row.pack(fill="x")
            if not self.project_hint_label.winfo_manager():
                self.project_hint_label.pack(anchor="w", pady=(10, 0))

        if is_renpy and not self.renpy_prepare_visible:
            self.renpy_prepare_frame.pack(fill="x", pady=(14, 0))
            self.renpy_prepare_visible = True
        if not is_renpy and self.renpy_prepare_visible:
            self.renpy_prepare_frame.pack_forget()
            self.renpy_prepare_visible = False

        if is_unity and not self.unity_prepare_visible:
            self.unity_prepare_frame.pack(fill="x", pady=(12, 0))
            self.unity_prepare_visible = True
        if not is_unity and self.unity_prepare_visible:
            self.unity_prepare_frame.pack_forget()
            self.unity_prepare_visible = False

        if is_buzz and not self.buzz_prepare_visible:
            self.buzz_prepare_frame.pack(fill="x", pady=(10, 0))
            self.buzz_prepare_visible = True
        if not is_buzz and self.buzz_prepare_visible:
            self.buzz_prepare_frame.pack_forget()
            self.buzz_prepare_visible = False

        for button in self.renpy_prepare_buttons:
            button.configure(state="normal" if (is_renpy and not app_busy) else "disabled")
        for button in self.unity_prepare_buttons:
            button.configure(state="normal" if (is_unity and not app_busy) else "disabled")
        for widget in self.buzz_prepare_buttons:
            widget.configure(state="normal" if (is_buzz and not app_busy) else "disabled")
        self.unity_table_listbox.configure(state="normal" if (is_unity and not app_busy) else "disabled")
        self.project_dir_entry.configure(state="normal" if (not is_buzz and not app_busy) else "disabled")
        self.pick_project_dir_button.configure(state="normal" if (not is_buzz and not app_busy) else "disabled")
        if hasattr(self, "pick_game_exe_button"):
            self.pick_game_exe_button.configure(state="normal" if not app_busy else "disabled")
        if hasattr(self, "finish_open_button"):
            self.finish_open_button.configure(state="normal" if not app_busy else "disabled")
        if hasattr(self, "finish_restart_button"):
            self.finish_restart_button.configure(state="normal" if not app_busy else "disabled")
        self.back_button.configure(state="disabled" if app_busy else ("normal" if self.current_step > 0 else "disabled"))
        next_state = "disabled" if app_busy else "normal"
        if is_buzz and self.current_step == 1:
            next_state = "disabled"
        self.next_button.configure(state=next_state)
        self._refresh_buzz_output_dir_ui_state()
        if is_buzz and not app_busy:
            buzz_video_ready = bool(self.buzz_video_var.get().strip())
            self.run_buzz_button.configure(state="normal" if buzz_video_ready else "disabled")
            self.run_translate_buzz_button.configure(state="normal" if buzz_video_ready else "disabled")
        if hasattr(self, "auto_translate_import_button"):
            self.auto_translate_import_button.configure(state="disabled" if app_busy else "normal")
        if hasattr(self, "cancel_translation_button"):
            self.cancel_translation_button.configure(state="normal" if translation_busy else "disabled")

        if not is_renpy:
            if self.current_step == 1:
                self.root.minsize(*APP_STEP2_MIN_SIZE)
            else:
                self.root.minsize(*APP_BASE_MIN_SIZE)
            self.open_launcher_button.configure(state="disabled")
            if is_unity:
                self.unity_prepare_hint.configure(
                    text=(
                        "No Unity: detecte tables de idioma, selecione a desejada e aplique. "
                        "Sem table selecionada, o fluxo usa apenas arquivos textuais comuns."
                    )
                )
            return

        if self.current_step == 1:
            min_w, min_h = APP_RENPY_STEP2_MIN_SIZE
            self.root.minsize(min_w, min_h)
            self.root.update_idletasks()
            if self.root.winfo_width() < min_w or self.root.winfo_height() < min_h:
                self.root.geometry(
                    f"{max(self.root.winfo_width(), min_w)}x{max(self.root.winfo_height(), min_h)}"
                )
        else:
            self.root.minsize(*APP_BASE_MIN_SIZE)

        if game_busy:
            exe_name = self.running_game_exe.name if self.running_game_exe else "jogo"
            self.renpy_prepare_hint.configure(
                text=(
                    f"{exe_name} está em execução. Feche o jogo para concluir esta preparação e liberar os botões."
                )
            )
        else:
            self.renpy_prepare_hint.configure(
                text=(
                    "No Ren'Py: abra o jogo para preparar, rode o ciclo un.rpy/un.rpyc quando necessário, "
                    "execute UnRen e abra o launcher compatível."
                )
            )
        self.open_launcher_button.configure(
            state=(
                "normal"
                if (
                    not game_busy
                    and self.selected_launcher_path
                    and self.selected_launcher_path.exists()
                )
                else "disabled"
            )
        )

    def _set_selected_launcher(
        self,
        launcher_path: Path | None,
        *,
        version_label: str | None = None,
    ) -> None:
        self.selected_launcher_path = launcher_path
        if launcher_path is None:
            self.renpy_launcher_var.set("Launcher Ren'Py: -")
            self.open_launcher_button.configure(state="disabled")
            return

        version_prefix = f"[{version_label}] " if version_label else ""
        self.renpy_launcher_var.set(f"Launcher Ren'Py: {version_prefix}{launcher_path}")
        self._refresh_renpy_prepare_ui_state()

    def _pick_launchers_root(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para alterar a pasta dos launchers.")
            return
        selected = filedialog.askdirectory(title="Selecione a pasta com versões Ren'Py")
        if not selected:
            return
        self.launchers_root_var.set(selected)
        self._save_settings()
        self._refresh_launchers(show_status=False)
        self._set_message("Pasta dos launchers atualizada.")

    def _pick_unren_source(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para alterar a fonte do UnRen.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione o script do UnRen (.bat/.sh/.command/.txt)",
            filetypes=[("Script/Texto", "*.bat *.sh *.command *.txt"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return
        self.unren_source_var.set(selected)
        self._save_settings()
        self._set_message("Fonte do UnRen atualizada.")

    def _pick_force_language_source(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para alterar o force_language.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione o force_language.rpy",
            filetypes=[("Ren'Py script", "*.rpy"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return
        self.force_language_source_var.set(selected)
        self._save_settings()
        self._set_message("Fonte do force_language atualizada.")

    def _pick_un_rpy_source(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para alterar a fonte un.rpy.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione o arquivo un.rpy",
            filetypes=[("Ren'Py script", "*.rpy"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return
        self.un_rpy_source_var.set(selected)
        self._save_settings()
        self._set_message("Fonte un.rpy atualizada.")

    def _pick_un_rpyc_source(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para alterar a fonte un.rpyc.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione o arquivo un.rpyc",
            filetypes=[("Ren'Py compiled", "*.rpyc"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return
        self.un_rpyc_source_var.set(selected)
        self._save_settings()
        self._set_message("Fonte un.rpyc atualizada.")

    def _project_path_if_valid(self) -> Path | None:
        raw = self.project_dir_var.get().strip()
        if not raw:
            return None
        project = Path(raw)
        if not project.exists() or not project.is_dir():
            return None
        return project

    def _ensure_renpy_project_ready(self) -> bool:
        if normalize_engine(self.engine_var.get()) != ENGINE_RENPY:
            self._set_message("Essa ação está disponível apenas para Ren'Py.")
            return False
        return self._validate_project_dir()

    def _resolve_game_executable(
        self,
        *,
        prefer_saved: bool = True,
        allow_manual: bool = True,
        remember_selection: bool = True,
        prompt_title: str = "Selecione o arquivo principal de inicialização do jogo",
    ) -> Path | None:
        project = self._project_path_if_valid()
        if project is None:
            return None

        if prefer_saved:
            saved = self._get_saved_game_exe_for_project(project)
            if saved and saved.exists() and saved.is_file():
                self._refresh_game_exe_info()
                self._set_message(f"Arquivo resolvido pelo cadastro salvo deste projeto: {saved}")
                return saved

        auto_detected = detectar_executavel_jogo(project)
        if auto_detected and auto_detected.exists() and auto_detected.is_file():
            if remember_selection:
                self._save_game_exe_for_project(project, auto_detected)
            else:
                self._refresh_game_exe_info()
            self._set_message(f"Arquivo resolvido automaticamente: {auto_detected}")
            return auto_detected

        if not allow_manual:
            self._refresh_game_exe_info()
            return None

        selected = filedialog.askopenfilename(
            title=prompt_title,
            initialdir=str(project),
            filetypes=_launch_filetypes(),
        )
        if not selected:
            return None

        exe_path = Path(selected)
        if not _is_valid_launch_file(exe_path):
            if _is_windows():
                messagebox.showerror("Executável inválido", "Selecione um arquivo .exe válido.")
            else:
                messagebox.showerror(
                    "Arquivo inválido",
                    "Selecione um arquivo válido (.sh, .command, .exe via Wine ou arquivo com permissão de execução).",
                )
            return None

        if remember_selection:
            self._save_game_exe_for_project(project, exe_path)
        else:
            self._refresh_game_exe_info()
        self._set_message(f"Arquivo de inicialização definido manualmente: {exe_path}")
        return exe_path

    def _ensure_un_sources(self) -> tuple[Path, Path] | None:
        un_rpy = Path(self.un_rpy_source_var.get().strip())
        un_rpyc = Path(self.un_rpyc_source_var.get().strip())

        if not un_rpy.exists() or not un_rpy.is_file():
            self._set_message("Fonte un.rpy não encontrada. Selecione manualmente.")
            selected = filedialog.askopenfilename(
                title="Selecione o arquivo un.rpy",
                filetypes=[("Ren'Py script", "*.rpy"), ("Todos os arquivos", "*.*")],
            )
            if not selected:
                return None
            un_rpy = Path(selected)
            self.un_rpy_source_var.set(str(un_rpy))
            self._save_settings()

        if not un_rpyc.exists() or not un_rpyc.is_file():
            self._set_message("Fonte un.rpyc não encontrada. Selecione manualmente.")
            selected = filedialog.askopenfilename(
                title="Selecione o arquivo un.rpyc",
                filetypes=[("Ren'Py compiled", "*.rpyc"), ("Todos os arquivos", "*.*")],
            )
            if not selected:
                return None
            un_rpyc = Path(selected)
            self.un_rpyc_source_var.set(str(un_rpyc))
            self._save_settings()

        return (un_rpy, un_rpyc)

    def _pick_and_save_game_exe(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para definir o executável.")
            return
        if not self._validate_project_dir():
            return

        project = self._project_path_if_valid()
        if project is None:
            return

        selected = filedialog.askopenfilename(
            title="Selecione o arquivo principal de inicialização do jogo",
            initialdir=str(project),
            filetypes=_launch_filetypes(),
        )
        if not selected:
            return

        exe_path = Path(selected)
        if not _is_valid_launch_file(exe_path):
            if _is_windows():
                messagebox.showerror("Executável inválido", "Selecione um arquivo .exe válido.")
            else:
                messagebox.showerror(
                    "Arquivo inválido",
                    "Selecione um arquivo válido (.sh, .command, .exe via Wine ou arquivo com permissão de execução).",
                )
            return

        self._save_game_exe_for_project(project, exe_path)
        self._set_message(f"Arquivo de inicialização salvo para este projeto: {exe_path}")

    def _game_running(self) -> bool:
        return processo_ativo(self.game_process)

    def _buzz_running(self) -> bool:
        return self.buzz_process is not None and self.buzz_process.poll() is None

    def _start_game_process(self, *, exe_path: Path, mode: str, started_message: str) -> bool:
        project = self._project_path_if_valid()
        if project is None:
            messagebox.showerror("Pasta inválida", "Selecione uma pasta de projeto válida.")
            return False

        try:
            process = abrir_processo_jogo(exe_path, project)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir jogo", str(exc))
            self._set_message(f"Falha ao abrir jogo: {exc}")
            return False

        self.game_process = process
        self.game_process_mode = mode
        self.running_game_exe = exe_path
        self._refresh_renpy_prepare_ui_state()
        self._set_message(started_message)
        self.root.after(800, self._monitor_game_process)
        return True

    def _refresh_detected_version_after_game(self) -> str:
        project = self._project_path_if_valid()
        if project is None:
            self.detected_renpy_version = None
            self.renpy_version_var.set("Versão Ren'Py detectada: pasta do projeto inválida")
            self._set_selected_launcher(None)
            return "Projeto não encontrado para redetectar versão."

        version = detectar_versao_renpy(project)
        self.detected_renpy_version = version
        if version:
            self.renpy_version_var.set(f"Versão Ren'Py detectada: {version}")
            self._refresh_launchers(show_status=False)
            return f"Versão Ren'Py redetectada: {version}."

        self.renpy_version_var.set("Versão Ren'Py detectada: não encontrada")
        self._set_selected_launcher(None)
        return "Não foi possível redetectar a versão Ren'Py após fechar o jogo."

    def _monitor_game_process(self) -> None:
        if self.game_process is None:
            return

        if processo_ativo(self.game_process):
            if self.root.winfo_exists():
                self.root.after(800, self._monitor_game_process)
            return

        mode = self.game_process_mode
        process_message = "Jogo fechado. "
        cleanup_message = ""
        if mode == "decompile":
            try:
                removed = remover_un_files_de_game(self.project_dir_var.get())
                if removed:
                    cleanup_message = "Arquivos un.rpy/un.rpyc removidos de game/. "
                else:
                    cleanup_message = "Nenhum arquivo un.rpy/un.rpyc precisou ser removido. "
            except Exception as exc:
                cleanup_message = f"Falha ao remover un.rpy/un.rpyc: {exc}. "

        self.game_process = None
        self.game_process_mode = None
        self.running_game_exe = None
        self._refresh_renpy_prepare_ui_state()

        version_message = ""
        if normalize_engine(self.engine_var.get()) == ENGINE_RENPY:
            version_message = self._refresh_detected_version_after_game()

        self._set_message(f"{process_message}{cleanup_message}{version_message}".strip())

    def _run_open_game_prepare(self) -> None:
        if not self._ensure_renpy_project_ready():
            return
        if self._game_running():
            self._set_message("Já existe um jogo em execução. Feche-o para iniciar outra ação.")
            return

        exe_path = self._resolve_game_executable()
        if exe_path is None:
            self._set_message("Abertura do jogo cancelada.")
            return

        started_message = (
            f"Jogo aberto para preparação ({exe_path.name}). Feche manualmente para continuar."
        )
        self._start_game_process(exe_path=exe_path, mode="prepare", started_message=started_message)

    def _run_un_rpyc_cycle(self) -> None:
        if not self._ensure_renpy_project_ready():
            return
        if self._game_running():
            self._set_message("Já existe um jogo em execução. Feche-o para iniciar outra ação.")
            return

        sources = self._ensure_un_sources()
        if sources is None:
            self._set_message("Ciclo un.rpy/un.rpyc cancelado.")
            return

        exe_path = self._resolve_game_executable()
        if exe_path is None:
            self._set_message("Ciclo un.rpy/un.rpyc cancelado (executável não selecionado).")
            return

        try:
            copied = copiar_un_files_para_game(self.project_dir_var.get(), sources[0], sources[1])
        except Exception as exc:
            messagebox.showerror("Erro ao preparar ciclo un.rpy/un.rpyc", str(exc))
            self._set_message(f"Falha ao copiar un.rpy/un.rpyc: {exc}")
            return

        started = self._start_game_process(
            exe_path=exe_path,
            mode="decompile",
            started_message=(
                f"Arquivos un.rpy/un.rpyc copiados ({len(copied)}). "
                f"Jogo aberto ({exe_path.name}); feche manualmente para limpeza automática."
            ),
        )
        if started:
            return

        try:
            remover_un_files_de_game(self.project_dir_var.get())
        except Exception:
            pass

    def _detect_renpy_version(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para redetectar a versão.")
            return
        if normalize_engine(self.engine_var.get()) != ENGINE_RENPY:
            self._set_message("Detecção de versão disponível apenas para projetos Ren'Py.")
            return
        if not self._validate_project_dir():
            return

        version = detectar_versao_renpy(self.project_dir_var.get())
        self.detected_renpy_version = version
        if version:
            self.renpy_version_var.set(f"Versão Ren'Py detectada: {version}")
            self._refresh_launchers(show_status=False)
            self._set_message(f"Versão Ren'Py detectada: {version}.")
            return

        self.renpy_version_var.set("Versão Ren'Py detectada: não encontrada")
        self._set_selected_launcher(None)
        self._set_message("Não foi possível detectar a versão Ren'Py automaticamente.")

    def _apply_manual_version(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para ajustar a versão manual.")
            return
        raw = self.manual_version_var.get().strip()
        if not MANUAL_VERSION_RE.match(raw):
            messagebox.showerror(
                "Versão inválida",
                "Informe a versão no formato 8.5 ou 8.5.2.",
            )
            return

        self.detected_renpy_version = raw
        self.renpy_version_var.set(f"Versão Ren'Py detectada: {raw} (manual)")
        self._refresh_launchers(show_status=False)
        self._set_message(f"Versão manual aplicada: {raw}.")

    def _refresh_launchers(self, *, show_status: bool = True) -> None:
        if self._game_running():
            if show_status:
                self._set_message("Feche o jogo em execução para reverificar os launchers.")
            return
        launchers_root = self.launchers_root_var.get().strip()
        if not launchers_root:
            self._set_selected_launcher(None)
            if show_status:
                self._set_message("Defina a pasta de versões Ren'Py para buscar launchers.")
            return

        candidates = listar_launchers(launchers_root)
        if not candidates:
            self._set_selected_launcher(None)
            if show_status:
                self._set_message("Nenhum launcher válido encontrado na pasta configurada.")
            return

        selected = selecionar_launcher_compativel(self.detected_renpy_version, candidates)
        if selected is None:
            self._set_selected_launcher(None)
            if show_status:
                if self.detected_renpy_version:
                    self._set_message(
                        f"Não existe launcher compatível para Ren'Py {self.detected_renpy_version}. "
                        "Use seleção manual ou adicione versão próxima."
                    )
                else:
                    self._set_message("Detecte a versão Ren'Py antes de selecionar launcher automaticamente.")
            return

        self._set_selected_launcher(selected.exe_path, version_label=selected.version)
        if show_status:
            self._set_message(f"Launcher compatível encontrado: {selected.exe_path}.")

    def _pick_launcher_manually(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para selecionar launcher.")
            return
        selected = filedialog.askopenfilename(
            title="Selecione manualmente o launcher Ren'Py",
            filetypes=_launch_filetypes(),
        )
        if not selected:
            return
        self._set_selected_launcher(Path(selected), version_label="manual")
        self._set_message("Launcher Ren'Py selecionado manualmente.")

    def _open_selected_launcher(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para abrir o launcher.")
            return
        if not self.selected_launcher_path:
            messagebox.showerror("Launcher não definido", "Selecione um launcher Ren'Py primeiro.")
            return
        if not self.selected_launcher_path.exists():
            messagebox.showerror("Launcher inválido", f"Arquivo não encontrado: {self.selected_launcher_path}")
            return

        try:
            open_in_os(self.selected_launcher_path)
            self._set_message("Launcher Ren'Py aberto.")
        except Exception as exc:
            messagebox.showerror("Erro ao abrir launcher", str(exc))

    def _run_unren(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para rodar o UnRen.")
            return
        if normalize_engine(self.engine_var.get()) != ENGINE_RENPY:
            self._set_message("Execução do UnRen disponível apenas para Ren'Py.")
            return
        if not self._validate_project_dir():
            return

        source_path = Path(self.unren_source_var.get().strip())
        project_path = Path(self.project_dir_var.get())
        destination = project_path / "UnRen-forall.bat"
        if platform.system() != "Windows":
            if source_path.suffix.lower() == ".txt":
                destination = project_path / "UnRen-forall.sh"
            else:
                destination = project_path / source_path.name
        destination_was_temp = (
            self.unren_temp_bat_path is not None
            and self.unren_temp_bat_path == destination
            and self.unren_temp_should_remove
        )
        destination_exists = destination.exists() and not destination_was_temp

        try:
            created_path = preparar_descompactador(project_path, source_path, abrir_interativo=True)
        except Exception as exc:
            messagebox.showerror("Erro ao executar UnRen", str(exc))
            self._set_message(f"Falha ao preparar UnRen: {exc}")
            return

        self.unren_temp_bat_path = created_path
        self.unren_temp_should_remove = not destination_exists
        if destination_exists:
            self._set_message("UnRen aberto. Como já existia arquivo na raiz, ele será mantido.")
        else:
            self._set_message("UnRen aberto em modo interativo. O arquivo temporário será removido ao avançar etapa.")

    def _cleanup_unren_temp_file(self, *, notify: bool) -> None:
        if not self.unren_temp_bat_path:
            return

        if not self.unren_temp_should_remove:
            self.unren_temp_bat_path = None
            self.unren_temp_should_remove = False
            return

        removed = False
        try:
            removed = remover_descompactador_temporario(self.unren_temp_bat_path)
        except OSError:
            removed = False

        if removed and notify:
            self._set_message("Arquivo temporário do UnRen removido da raiz do projeto.")
        elif notify and not removed:
            self._set_message("Não foi possível remover automaticamente o arquivo temporário do UnRen.")

        if removed:
            self.unren_temp_bat_path = None
            self.unren_temp_should_remove = False

    def _iter_widget_tree(self, root_widget: tk.Misc) -> list[tk.Misc]:
        items: list[tk.Misc] = [root_widget]
        for child in root_widget.winfo_children():
            items.extend(self._iter_widget_tree(child))
        return items

    def _enable_window_drop(self, widgets: list[tk.Misc]) -> None:
        if not HAS_DND:
            return
        for widget in widgets:
            try:
                widget.drop_target_register(DND_FILES)  # type: ignore[union-attr]
                widget.dnd_bind("<<Drop>>", self._handle_drop)  # type: ignore[union-attr]
            except Exception:
                continue

    def _refresh_drop_targets(self) -> None:
        if not HAS_DND:
            return
        self._enable_window_drop(self._iter_widget_tree(self.root))

    def _ensure_window_fits_content(self) -> None:
        self.root.update_idletasks()

        req_w = max(APP_BASE_MIN_SIZE[0], self.root.winfo_reqwidth() + 8)
        req_h = max(APP_BASE_MIN_SIZE[1], self.root.winfo_reqheight() + 8)

        max_w = max(APP_BASE_MIN_SIZE[0], self.root.winfo_screenwidth() - APP_AUTO_FIT_SCREEN_MARGIN)
        max_h = max(APP_BASE_MIN_SIZE[1], self.root.winfo_screenheight() - APP_AUTO_FIT_SCREEN_MARGIN)

        target_w = min(req_w, max_w)
        target_h = min(req_h, max_h)

        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()
        if cur_w >= target_w and cur_h >= target_h:
            return

        new_w = max(cur_w, target_w)
        new_h = max(cur_h, target_h)
        self.root.geometry(f"{new_w}x{new_h}")

    def _show_step(self, step: int) -> None:
        self.current_step = max(0, min(step, len(self.step_frames) - 1))
        for idx, frame in enumerate(self.step_frames):
            if idx == self.current_step:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        titles = [
            "Etapa 1/5 - Engine",
            "Etapa 2/5 - Pasta do projeto",
            "Etapa 3/5 - Exportação",
            "Etapa 4/5 - TXT traduzido",
            "Etapa 5/5 - Importação",
        ]
        if normalize_engine(self.engine_var.get()) == ENGINE_BUZZ:
            titles[1] = "Etapa 2/5 - Buzz (legendas)"
        self.status_var.set(f"{titles[self.current_step]} | Engine: {self._engine_label()}")
        self.step_progress.configure(value=self.current_step + 1)
        self.back_button.configure(state="normal" if self.current_step > 0 else "disabled")

        if self.current_step == len(self.step_frames) - 1:
            self.next_button.configure(text="Finalizar", command=self._on_finish, state="normal")
        else:
            self.next_button.configure(text="Próximo", command=self._on_next, state="normal")

        if self.current_step == 1:
            self.drop_mode = DROP_PROJECT_DIR
        elif self.current_step == 3:
            self.drop_mode = DROP_TRANSLATED_TXT
        else:
            self.drop_mode = DROP_DISABLED

        if self.current_step == 2:
            ws = engine_workspace_dir(self.engine_var.get(), WORKSPACE_ROOT)
            self.workspace_label.configure(text=f"Pasta de trabalho: {ws}")

        self._refresh_renpy_prepare_ui_state()
        self.workspace_info_var.set(f"Pasta de trabalho base: {WORKSPACE_ROOT}")
        self._refresh_game_exe_info()
        if normalize_engine(self.engine_var.get()) == ENGINE_UNITY:
            self._sync_unity_selection_to_core()
        self._refresh_drop_targets()
        self._ensure_window_fits_content()

    def _on_back(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para continuar.")
            return
        if self._buzz_running():
            self._set_message("Aguarde a execução atual do Buzz terminar para continuar.")
            return
        if self.current_step == 1:
            self._cleanup_unren_temp_file(notify=False)
        self._show_step(self.current_step - 1)

    def _on_next(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para continuar.")
            return
        if self._buzz_running():
            self._set_message("Aguarde a execução atual do Buzz terminar para continuar.")
            return
        if self._translation_running():
            self._set_message("Aguarde a tradução local terminar para continuar.")
            return
        if self.current_step == 0:
            self._show_step(1)
            return
        if self.current_step == 1:
            if normalize_engine(self.engine_var.get()) == ENGINE_BUZZ:
                self._set_message("No modo Buzz, use a etapa 2 para gerar legendas de vídeo/áudio.")
                return
            if not self._validate_project_dir():
                return
            self._cleanup_unren_temp_file(notify=True)
            self._show_step(2)
            return
        if self.current_step == 2:
            if not self.export_done:
                self._set_message("Execute a exportação antes de avançar.")
                return
            self._show_step(3)
            return
        if self.current_step == 3:
            if not self._validate_translated_file():
                return
            self._show_step(4)
            return

    def _on_finish(self) -> None:
        if self._game_running():
            messagebox.showwarning(
                "Jogo em execução",
                "Feche o jogo aberto na preparação Ren'Py antes de finalizar.",
            )
            return
        if self._buzz_running():
            messagebox.showwarning(
                "Buzz em execução",
                "Aguarde o Buzz finalizar antes de encerrar o app.",
            )
            return
        if self._translation_running():
            messagebox.showwarning(
                "Tradução em execução",
                "Aguarde a tradução local finalizar ou cancele antes de encerrar o app.",
            )
            return
        self._cleanup_unren_temp_file(notify=False)
        self.root.destroy()

    def _reset_wizard_to_start(self) -> None:
        self._cleanup_unren_temp_file(notify=False)
        self.engine_var.set(ENGINE_RENPY)
        self._update_engine_display()
        self.project_dir_var.set("")
        self.translated_file_var.set("")
        self.export_done = False
        self.last_log_file = None
        self.generated_translation_path = None
        self.generated_txt_label.configure(text="-")
        self.open_generated_button.configure(state="disabled")
        self.open_generated_folder_button.configure(state="disabled")
        self._set_split_join_buttons_state(False)
        self.open_log_button.configure(state="disabled")
        self.detected_renpy_version = None
        self.renpy_version_var.set("Versão Ren'Py detectada: -")
        self.manual_version_var.set("")
        self._set_selected_launcher(None)
        self.unity_table_candidates = []
        self._refresh_unity_table_list_ui()
        self.unity_tables_info_var.set("Tables Unity: detectar para escolher o idioma/table.")
        self.unity_selected_table_var.set("Table selecionada: (nenhuma)")
        self.buzz_video_var.set("")
        self.buzz_process = None
        self.buzz_running_config = None
        self.buzz_running_stdout = ""
        self.buzz_running_stderr = ""
        self._refresh_buzz_status_label()
        self._refresh_game_exe_info()
        self._show_step(0)
        self._set_message("Fluxo finalizado. Escolha a engine para iniciar um novo projeto.")

    def _on_finish_and_open(self) -> None:
        if self._game_running():
            messagebox.showwarning(
                "Jogo em execução",
                "Feche o jogo aberto na preparação Ren'Py antes de finalizar.",
            )
            return
        if self._buzz_running():
            messagebox.showwarning(
                "Buzz em execução",
                "Aguarde o Buzz finalizar antes de encerrar o app.",
            )
            return
        if not self._validate_project_dir():
            return

        exe_path = self._resolve_game_executable(
            prefer_saved=True,
            allow_manual=True,
            remember_selection=True,
            prompt_title="Selecione o executável para abrir após finalizar",
        )
        if exe_path is None:
            self._set_message("Finalização com abertura cancelada (executável não definido).")
            return

        project = self._project_path_if_valid()
        if project is None:
            return

        try:
            abrir_processo_jogo(exe_path, project)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir jogo", str(exc))
            self._set_message(f"Falha ao abrir jogo na finalização: {exc}")
            return

        self._cleanup_unren_temp_file(notify=False)
        self.root.destroy()

    def _on_finish_and_restart(self) -> None:
        if self._game_running():
            messagebox.showwarning(
                "Jogo em execução",
                "Feche o jogo aberto na preparação Ren'Py antes de finalizar.",
            )
            return
        if self._buzz_running():
            messagebox.showwarning(
                "Buzz em execução",
                "Aguarde o Buzz finalizar antes de reiniciar o fluxo.",
            )
            return
        self._reset_wizard_to_start()

    def _on_window_close(self) -> None:
        if self._game_running():
            messagebox.showwarning(
                "Jogo em execução",
                "Feche o jogo aberto na preparação Ren'Py antes de sair.",
            )
            return
        if self._buzz_running():
            messagebox.showwarning(
                "Buzz em execução",
                "Aguarde o Buzz finalizar antes de sair.",
            )
            return
        if self._translation_running():
            messagebox.showwarning(
                "Tradução em execução",
                "Aguarde a tradução local finalizar ou cancele antes de sair.",
            )
            return
        self._cleanup_unren_temp_file(notify=False)
        self.root.destroy()

    def _on_engine_change(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de trocar a engine.")
            return
        if self._buzz_running():
            self._set_message("Aguarde o Buzz finalizar antes de trocar a engine.")
            return
        engine = normalize_engine(self.engine_var.get())
        self.engine_var.set(engine)
        self._update_engine_display()
        self.export_done = False
        self.generated_translation_path = None
        self.generated_txt_label.configure(text="-")
        self.open_generated_button.configure(state="disabled")
        self.open_generated_folder_button.configure(state="disabled")
        self._set_split_join_buttons_state(False)
        self.translated_file_var.set("")
        self.detected_renpy_version = None
        self.renpy_version_var.set("Versão Ren'Py detectada: -")
        self.manual_version_var.set("")
        self._set_selected_launcher(None)
        self.unity_table_candidates = []
        self._refresh_unity_table_list_ui()
        self.unity_tables_info_var.set("Tables Unity: detectar para escolher o idioma/table.")
        self.unity_selected_table_var.set("Table selecionada: (nenhuma)")
        project = self._project_path_if_valid()
        if project is not None:
            if engine == ENGINE_UNITY:
                self._sync_unity_selection_to_core()
            else:
                clear_unity_selected_table_for_project(project)
        self._refresh_game_exe_info()
        self._set_message(
            f"Engine atualizada para {self._engine_label()}. Continue para escolher a pasta do projeto."
        )
        self._show_step(self.current_step)

    def _pick_project_dir(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de trocar a pasta do projeto.")
            return
        if self._buzz_running():
            self._set_message("Aguarde o Buzz finalizar antes de trocar a pasta do projeto.")
            return
        selected = filedialog.askdirectory(title="Selecione a pasta do projeto")
        if selected:
            self.project_dir_var.set(selected)
            self._refresh_game_exe_info()
            self._set_project_resolution_message()
            engine = normalize_engine(self.engine_var.get())
            if engine == ENGINE_RENPY:
                self._detect_renpy_version()
            elif engine == ENGINE_UNITY:
                self._detect_unity_tables()

    def _pick_translated_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o TXT traduzido",
            filetypes=[("Text files", "*.txt"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            self.translated_file_var.set(selected)
            self._set_message("Arquivo TXT traduzido selecionado.")

    def _handle_drop(self, event: tk.Event) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de usar arrastar e soltar.")
            return
        if self._buzz_running():
            self._set_message("Aguarde o Buzz finalizar antes de usar arrastar e soltar.")
            return
        try:
            items = self.root.tk.splitlist(event.data)
            paths = normalize_dropped_items(list(items))
            if not paths:
                self._set_message("Drop recebido, mas sem caminho válido.")
                return

            if self.drop_mode == DROP_PROJECT_DIR:
                engine = normalize_engine(self.engine_var.get())
                if engine == ENGINE_BUZZ:
                    media_path = resolve_buzz_media_drop_path(paths)
                    if media_path is None:
                        self._set_message("No modo Buzz, solte um arquivo de vídeo/áudio válido.")
                        return
                    self.buzz_video_var.set(str(media_path))
                    self._set_message(f"Mídia selecionada via drop para Buzz: {media_path.name}")
                    return

                selected_dir, used_file_parent = resolve_project_drop_path(paths)
                if selected_dir is None:
                    self._set_message("Não foi possível identificar uma pasta válida no item arrastado.")
                    return
                self.project_dir_var.set(str(selected_dir))
                self._refresh_game_exe_info()
                if engine == ENGINE_RENPY:
                    self._detect_renpy_version()
                else:
                    self._set_project_resolution_message(via_drop=True, used_file_parent=used_file_parent)
                    if engine == ENGINE_UNITY:
                        self._detect_unity_tables()
                return

            if self.drop_mode == DROP_TRANSLATED_TXT:
                txt_path = resolve_translated_txt_drop_path(paths)
                if txt_path is None:
                    self._set_message("Na etapa 4, solte um arquivo .txt válido.")
                    return
                self.translated_file_var.set(str(txt_path))
                self._set_message(f"TXT traduzido selecionado via drop: {txt_path.name}")
                return

            self._set_message("Arraste e solte habilitado apenas na etapa 2 (pasta) e etapa 4 (TXT).")
        except Exception as exc:
            self._set_message(f"Falha no arrastar e soltar: {exc}")

    def _validate_project_dir(self) -> bool:
        raw = self.project_dir_var.get().strip()
        if not raw:
            messagebox.showerror("Pasta inválida", "Selecione uma pasta de projeto válida.")
            return False
        project_dir = Path(raw)
        if not project_dir.exists() or not project_dir.is_dir():
            messagebox.showerror("Pasta inválida", "Selecione uma pasta de projeto válida.")
            return False
        return True

    def _validate_translated_file(self) -> bool:
        file_path = Path(self.translated_file_var.get())
        if not file_path.exists() or not file_path.is_file() or file_path.suffix.lower() != ".txt":
            messagebox.showerror("Arquivo inválido", "Selecione um arquivo TXT traduzido válido.")
            return False
        return True

    def _set_message(self, text: str) -> None:
        self.message_var.set(text)

    def _confirm_import_with_warnings(self, warnings: list[str]) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title("Alertas na pré-validação")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.minsize(560, 320)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(900, max(640, screen_w - 140))
        height = min(560, max(360, screen_h - 180))
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text=(
                "Foram encontrados alertas na pré-validação.\n"
                "Revise a lista abaixo e escolha se deseja continuar a importação."
            ),
            justify="left",
        ).pack(anchor="w")

        text_wrap = ttk.Frame(container)
        text_wrap.pack(fill="both", expand=True, pady=(10, 10))

        scrollbar = ttk.Scrollbar(text_wrap, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        warning_box = tk.Text(
            text_wrap,
            wrap="word",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
        )
        warning_box.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=warning_box.yview)

        for warning in warnings:
            warning_box.insert("end", f"- {warning}\n")
        warning_box.configure(state="disabled")

        result = {"continue": False}

        def on_continue() -> None:
            result["continue"] = True
            dialog.destroy()

        def on_cancel() -> None:
            result["continue"] = False
            dialog.destroy()

        buttons = ttk.Frame(container)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancelar", command=on_cancel).pack(side="right")
        ttk.Button(buttons, text="Continuar importação", command=on_continue).pack(
            side="right", padx=(0, 8)
        )

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.bind("<Escape>", lambda _e: on_cancel())
        dialog.bind("<Return>", lambda _e: on_continue())
        warning_box.focus_set()
        self.root.wait_window(dialog)
        return result["continue"]

    def _show_import_result_dialog(
        self,
        *,
        message: str,
        extra_notes: list[str],
        warnings: list[str],
    ) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Importação concluída")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.minsize(560, 320)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(920, max(660, screen_w - 120))
        height = min(580, max(380, screen_h - 160))
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Resumo da importação",
            style="Status.TLabel",
        ).pack(anchor="w")

        text_wrap = ttk.Frame(container)
        text_wrap.pack(fill="both", expand=True, pady=(10, 10))

        scrollbar = ttk.Scrollbar(text_wrap, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        result_box = tk.Text(
            text_wrap,
            wrap="word",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
        )
        result_box.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=result_box.yview)

        result_box.insert("end", message + "\n")
        if extra_notes:
            result_box.insert("end", "\nNotas adicionais:\n")
            for note in extra_notes:
                result_box.insert("end", f"- {note}\n")
        if warnings:
            result_box.insert("end", "\nAlertas:\n")
            for warning in warnings:
                result_box.insert("end", f"- {warning}\n")
        result_box.configure(state="disabled")

        def on_close() -> None:
            dialog.destroy()

        buttons = ttk.Frame(container)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Fechar", command=on_close).pack(side="right")
        if self.last_log_file:
            ttk.Button(buttons, text="Abrir log", command=self._open_log).pack(side="right", padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", on_close)
        dialog.bind("<Escape>", lambda _e: on_close())
        result_box.focus_set()
        self.root.wait_window(dialog)

    def _set_project_resolution_message(
        self,
        *,
        via_drop: bool = False,
        used_file_parent: bool = False,
    ) -> None:
        engine = normalize_engine(self.engine_var.get())
        if engine == ENGINE_RENPY:
            if via_drop and used_file_parent:
                self._set_message("Arquivo detectado no drop. Usei automaticamente a pasta dele.")
            elif via_drop:
                self._set_message("Pasta recebida por arrastar e soltar.")
            else:
                self._set_message(f"Pasta do projeto definida para {self._engine_label()}.")
            return

        if engine == ENGINE_UNITY:
            project = Path(self.project_dir_var.get())
            data_dir, data_warnings = resolve_unity_data_dir(project)
            prefix = (
                "Arquivo detectado no drop. Usei automaticamente a pasta dele."
                if via_drop and used_file_parent
                else ("Pasta recebida por arrastar e soltar." if via_drop else "Pasta do projeto definida para Unity.")
            )

            if data_dir is None:
                warning_text = f" {' '.join(data_warnings)}" if data_warnings else ""
                self._set_message(
                    f"{prefix} Ainda não foi possível resolver a pasta *_Data do Unity.{warning_text}"
                )
                return

            data_desc = describe_unity_data_dir(project, data_dir)
            warning_text = f" {' '.join(data_warnings)}" if data_warnings else ""
            self._set_message(f"{prefix} Pasta Unity resolvida: {data_desc}.{warning_text}")
            return

        project = Path(self.project_dir_var.get())
        data_dir = resolve_rpgm_data_dir(project)
        prefix = "Arquivo detectado no drop. Usei automaticamente a pasta dele." if via_drop and used_file_parent else (
            "Pasta recebida por arrastar e soltar." if via_drop else "Pasta do projeto definida para RPGM."
        )

        if data_dir is None:
            self._set_message(f"{prefix} Ainda não foi possível resolver a pasta de dados RPGM.")
            return

        data_desc = describe_rpgm_data_dir(project, data_dir)
        self._set_message(f"{prefix} Pasta de dados RPGM resolvida: {data_desc}.")

    def _refresh_unity_table_list_ui(self) -> None:
        self.unity_table_listbox.delete(0, tk.END)
        for _candidate_id, label in self.unity_table_candidates:
            self.unity_table_listbox.insert(tk.END, label)

    def _selected_unity_candidate_from_listbox(self) -> tuple[str, str] | None:
        selected_idx = self.unity_table_listbox.curselection()
        if not selected_idx:
            return None
        idx = selected_idx[0]
        if idx < 0 or idx >= len(self.unity_table_candidates):
            return None
        return self.unity_table_candidates[idx]

    def _on_unity_table_highlighted(self, _event: tk.Event | None = None) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            return
        selected = self._selected_unity_candidate_from_listbox()
        if not selected:
            return
        _candidate_id, label = selected
        self._set_message(
            f"Table em destaque: {label}. "
            "Ela será aplicada automaticamente ao exportar/importar, ou você pode clicar em 'Usar seleção para export/import'."
        )

    def _clear_unity_table_selection(self) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            self._set_message("Limpeza de seleção disponível apenas para Unity.")
            return
        project = self._project_path_if_valid()
        if project is None:
            self._set_message("Defina uma pasta de projeto Unity válida primeiro.")
            return

        self.unity_table_listbox.selection_clear(0, tk.END)
        self.unity_selected_table_var.set("Table selecionada: (nenhuma)")
        clear_unity_selected_table_for_project(project)
        self._save_unity_table_selection_for_project(project, None)
        self._set_message("Seleção de table limpa. O fluxo Unity usará apenas arquivos textuais comuns.")

    def _auto_apply_unity_table_highlight(self) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            return
        project = self._project_path_if_valid()
        if project is None:
            return

        highlighted = self._selected_unity_candidate_from_listbox()
        if highlighted is None:
            self._sync_unity_selection_to_core()
            return

        candidate_id, label = highlighted
        saved = self._get_saved_unity_table_selection_for_project(project)
        if saved == candidate_id:
            self._sync_unity_selection_to_core()
            return

        set_unity_selected_table_for_project(project, candidate_id)
        self._save_unity_table_selection_for_project(project, candidate_id)
        self.unity_selected_table_var.set(f"Table selecionada: {label}")
        self._set_message(f"Table Unity aplicada automaticamente para esta exportação/importação: {label}")

    def _sync_unity_selection_to_core(self) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            return
        project = self._project_path_if_valid()
        if project is None:
            return
        selected = self._get_saved_unity_table_selection_for_project(project)
        if selected:
            set_unity_selected_table_for_project(project, selected)
        else:
            clear_unity_selected_table_for_project(project)

    def _detect_unity_tables(self) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            self._set_message("Detecção de tables disponível apenas para Unity.")
            return
        if not self._validate_project_dir():
            return

        project = self._project_path_if_valid()
        if project is None:
            return

        candidates, warnings = detectar_tabelas_idioma_unity(project)
        self.unity_table_candidates = [(item.candidate_id, item.label) for item in candidates]
        self._refresh_unity_table_list_ui()

        saved = self._get_saved_unity_table_selection_for_project(project)
        saved_applied = False
        if saved:
            for idx, (candidate_id, label) in enumerate(self.unity_table_candidates):
                if candidate_id == saved:
                    self.unity_table_listbox.selection_clear(0, tk.END)
                    self.unity_table_listbox.selection_set(idx)
                    self.unity_table_listbox.activate(idx)
                    self.unity_selected_table_var.set(f"Table selecionada: {label}")
                    set_unity_selected_table_for_project(project, candidate_id)
                    saved_applied = True
                    break
        if saved and not saved_applied:
            self._save_unity_table_selection_for_project(project, None)
            clear_unity_selected_table_for_project(project)
            self.unity_selected_table_var.set("Table selecionada: (nenhuma)")
        if not saved_applied:
            self.unity_selected_table_var.set("Table selecionada: (nenhuma)")

        if not self.unity_table_candidates:
            self.unity_tables_info_var.set("Tables Unity detectadas: nenhuma.")
            clear_unity_selected_table_for_project(project)
            self.unity_selected_table_var.set("Table selecionada: (nenhuma)")
            warning_text = f" {' '.join(warnings)}" if warnings else ""
            self._set_message(
                f"Nenhuma table de idioma detectada. O fluxo Unity usará apenas arquivos textuais comuns.{warning_text}"
            )
            return

        known = sum(1 for _id, label in self.unity_table_candidates if not label.lower().startswith("desconhecido"))
        unknown = len(self.unity_table_candidates) - known
        self.unity_tables_info_var.set(
            f"Tables Unity detectadas: {len(self.unity_table_candidates)} (idioma conhecido: {known}, desconhecido: {unknown})."
        )
        warning_text = f" {' '.join(warnings)}" if warnings else ""
        self._set_message(
            "Tables detectadas. Selecione uma na lista; ela também será aplicada automaticamente no export/import."
            + warning_text
        )

    def _apply_unity_table_selection(self) -> None:
        if normalize_engine(self.engine_var.get()) != ENGINE_UNITY:
            self._set_message("Seleção de table disponível apenas para Unity.")
            return
        project = self._project_path_if_valid()
        if project is None:
            self._set_message("Defina uma pasta de projeto Unity válida primeiro.")
            return
        if not self.unity_table_candidates:
            self._set_message("Nenhuma table detectada. Clique em 'Detectar tables de idioma' primeiro.")
            return

        selected = self._selected_unity_candidate_from_listbox()
        if selected is None:
            self._set_message("Selecione uma table na lista antes de confirmar.")
            return

        candidate_id, label = selected
        set_unity_selected_table_for_project(project, candidate_id)
        self._save_unity_table_selection_for_project(project, candidate_id)
        self.unity_selected_table_var.set(f"Table selecionada: {label}")
        self._set_message(f"Table Unity selecionada para este projeto: {label}")

    def _run_export(self) -> None:
        if not self._validate_project_dir():
            return

        engine = self.engine_var.get()
        if normalize_engine(engine) == ENGINE_UNITY:
            self._auto_apply_unity_table_highlight()
        result = exportar(engine, self.project_dir_var.get(), WORKSPACE_ROOT)
        if not result.success:
            messagebox.showerror("Erro na exportação", result.message)
            self._set_message(result.message)
            return

        engine_ws = engine_workspace_dir(engine, WORKSPACE_ROOT)
        txt_name = translation_filename_for_engine(engine)
        self.generated_translation_path = engine_ws / txt_name
        self.generated_txt_label.configure(text=str(self.generated_translation_path))
        self.translated_file_var.set(str(self.generated_translation_path))
        self.export_done = True
        self.open_generated_button.configure(state="normal")
        self.open_generated_folder_button.configure(state="normal")
        self._set_split_join_buttons_state(True)

        details = result.message
        if result.warnings:
            details += "\n\n" + "\n".join(f"- {w}" for w in result.warnings)
        messagebox.showinfo("Exportação concluída", details)
        self._set_message(f"{result.message} Agora traduza e selecione o TXT final.")

    def _run_auto_export_translate_import(self) -> None:
        if not self._validate_project_dir():
            return
        if self._translation_running():
            self._set_message("Aguarde a tradução local em andamento antes de iniciar outro fluxo automático.")
            return

        engine = self.engine_var.get()
        if normalize_engine(engine) == ENGINE_BUZZ:
            self._set_message("No modo Buzz, use 'Gerar e traduzir legenda' na etapa 2.")
            return

        should_run = messagebox.askyesno(
            "Tradução automática",
            (
                "Exportar, traduzir localmente com Ollama e importar automaticamente?\n\n"
                "Se a tradução falhar, o TXT exportado ficará pronto para o fluxo manual."
            ),
        )
        if not should_run:
            self._set_message("Tradução automática cancelada.")
            return

        if normalize_engine(engine) == ENGINE_UNITY:
            self._auto_apply_unity_table_highlight()

        self._set_message("Exportando textos...")
        self.root.update_idletasks()
        export_result = exportar(engine, self.project_dir_var.get(), WORKSPACE_ROOT)
        if not export_result.success:
            messagebox.showerror("Erro na exportação", export_result.message)
            self._set_message(export_result.message)
            return

        engine_ws = engine_workspace_dir(engine, WORKSPACE_ROOT)
        txt_name = translation_filename_for_engine(engine)
        self.generated_translation_path = engine_ws / txt_name
        self.generated_txt_label.configure(text=str(self.generated_translation_path))
        self.translated_file_var.set(str(self.generated_translation_path))
        self.export_done = True
        self.open_generated_button.configure(state="normal")
        self.open_generated_folder_button.configure(state="normal")
        self._set_split_join_buttons_state(True)

        translated_output = local_translated_path(self.generated_translation_path, engine_ws)
        self._set_message(f"Iniciando tradução local: {self.generated_translation_path.name}")
        try:
            config_translate = self._build_local_translate_config(self.generated_translation_path, engine_ws)
        except ValueError as exc:
            messagebox.showerror("Configuração de tradução inválida", str(exc))
            self._set_message(str(exc))
            return

        def on_done(translate_result: JobResult) -> None:
            if not translate_result.success:
                details = (
                    f"{export_result.message}\n\n"
                    f"{translate_result.message}\n\n"
                    f"TXT exportado mantido para tradução manual:\n{self.generated_translation_path}"
                )
                messagebox.showerror("Tradução automática falhou", details)
                self._set_message(
                    "Exportação concluída, mas a tradução local falhou. Use o fluxo manual com o TXT exportado."
                )
                return

            generated = (
                translate_result.generated_files[0]
                if translate_result.generated_files
                else str(translated_output)
            )
            self.translated_file_var.set(generated)
            self._set_message("Tradução local concluída. Validando importação...")
            self.root.update_idletasks()
            self._run_import_for_selected_file(auto_mode=True)

        self._run_local_translation_async(config_translate, on_done)

    def _open_generated_txt(self) -> None:
        if not self.generated_translation_path:
            return
        try:
            open_in_os(self.generated_translation_path)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir arquivo", str(exc))

    def _open_generated_txt_folder(self) -> None:
        if not self.generated_translation_path:
            return
        try:
            open_in_os(self.generated_translation_path.parent)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir pasta", str(exc))

    def _set_split_join_buttons_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        if hasattr(self, "split_generated_button"):
            self.split_generated_button.configure(state=state)
        if hasattr(self, "join_parts_button"):
            self.join_parts_button.configure(state=state)

    def _read_split_parts_count(self) -> int:
        raw = self.split_parts_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Informe uma quantidade de partes válida (número inteiro >= 2).") from exc
        if value < 2:
            raise ValueError("A divisão precisa ter pelo menos 2 partes.")
        self.split_parts_var.set(str(value))
        return value

    def _split_generated_txt(self) -> None:
        if not self.generated_translation_path or not self.generated_translation_path.exists():
            self._set_message("Execute a exportação antes de dividir o TXT gerado.")
            return
        try:
            parts_count = self._read_split_parts_count()
        except ValueError as exc:
            messagebox.showerror("Divisão inválida", str(exc))
            self._set_message(str(exc))
            return

        try:
            created_files = split_text_file(self.generated_translation_path, DOWNLOADS_DIR, parts_count)
        except ValueError as exc:
            messagebox.showwarning("Divisão inválida", str(exc))
            self._set_message(f"Divisão cancelada: {exc}")
            return

        self._set_message(f"TXT dividido em {len(created_files)} partes em {DOWNLOADS_DIR}.")
        messagebox.showinfo(
            "Divisão concluída",
            f"Foram geradas {len(created_files)} partes em:\n{DOWNLOADS_DIR}",
        )

    def _join_split_parts(self) -> None:
        if not self.generated_translation_path:
            self._set_message("Execute a exportação antes de juntar as partes.")
            return
        try:
            ordered_parts, removed = merge_parts_into_target(
                DOWNLOADS_DIR, self.generated_translation_path, cleanup=True
            )
        except FileNotFoundError:
            messagebox.showwarning(
                "Nenhuma parte encontrada",
                f"Nenhum arquivo parte_*.txt foi encontrado em:\n{DOWNLOADS_DIR}",
            )
            self._set_message("Junção cancelada: nenhuma parte encontrada em Downloads.")
            return

        target_path = self.generated_translation_path
        self.translated_file_var.set(str(target_path))
        self._set_message(
            f"Partes unidas em {target_path}. {removed} parte(s) removida(s) de {DOWNLOADS_DIR}."
        )
        messagebox.showinfo(
            "Junção concluída",
            (
                f"Arquivo final sobrescrito em:\n{target_path}\n\n"
                f"Partes removidas: {removed}/{len(ordered_parts)}"
            ),
        )

    def _run_import(self) -> None:
        self._run_import_for_selected_file(auto_mode=False)

    def _run_import_for_selected_file(self, *, auto_mode: bool) -> None:
        if not self._validate_project_dir() or not self._validate_translated_file():
            return

        engine = self.engine_var.get()
        if normalize_engine(engine) == ENGINE_UNITY:
            self._auto_apply_unity_table_highlight()
        pre = pre_validar_importacao(
            engine=engine,
            project_dir=self.project_dir_var.get(),
            workspace_dir=WORKSPACE_ROOT,
            translated_txt_path=self.translated_file_var.get(),
        )
        if not pre.success:
            messagebox.showerror("Pré-validação falhou", pre.message)
            self._set_message(pre.message)
            return

        if pre.warnings:
            if not self._confirm_import_with_warnings(pre.warnings):
                prefix = "Tradução automática concluída, mas " if auto_mode else ""
                self._set_message(f"{prefix}Importação cancelada para revisão dos alertas.")
                return

        criar_backup = messagebox.askyesno(
            "Backup antes de importar",
            "Deseja criar backup dos arquivos antes de importar?",
        )

        result = importar(
            engine=engine,
            project_dir=self.project_dir_var.get(),
            workspace_dir=WORKSPACE_ROOT,
            translated_txt_path=self.translated_file_var.get(),
            criar_backup=criar_backup,
        )
        if not result.success:
            messagebox.showerror("Erro na importação", result.message)
            self._set_message(result.message)
            return

        self.last_log_file = result.log_file
        if self.last_log_file:
            self.open_log_button.configure(state="normal")

        extra_notes: list[str] = []
        if normalize_engine(engine) == ENGINE_RENPY:
            try:
                destination = aplicar_force_language(
                    project_dir=self.project_dir_var.get(),
                    force_language_src=self.force_language_source_var.get(),
                )
                extra_notes.append(f"force_language.rpy aplicado em: {destination}")
            except Exception as exc:
                result.warnings.append(f"Falha ao aplicar force_language.rpy: {exc}")

        self._show_import_result_dialog(
            message=result.message,
            extra_notes=extra_notes,
            warnings=result.warnings,
        )
        if auto_mode:
            self._set_message(f"Fluxo automático concluído. {result.message}")
        else:
            self._set_message(result.message)

    def _open_log(self) -> None:
        if not self.last_log_file:
            return
        try:
            open_in_os(self.last_log_file)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir log", str(exc))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    app = TranslatorWizardApp()
    app.run()


