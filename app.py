from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from translator_core import exportar, importar, pre_validar_importacao
from translator_core.orchestrator import (
    ENGINE_RENPY,
    ENGINE_RPGM,
    engine_workspace_dir,
    normalize_engine,
    translation_filename_for_engine,
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

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    HAS_DND = False
    DND_FILES = None
    TkinterDnD = None


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "v1.4"
APP_DEFAULT_GEOMETRY = "780x560"
APP_BASE_MIN_SIZE = (700, 500)
APP_RENPY_STEP2_MIN_SIZE = (760, 680)

DROP_DISABLED = "disabled"
DROP_PROJECT_DIR = "project_dir"
DROP_TRANSLATED_TXT = "translated_txt"
MANUAL_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


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
DEFAULT_UNREN_SOURCE = (
    r"C:\Users\velos\Documents\Exportador-Importador-Renpy\FERRAMENTAS - TRADUZIR - RENPY\UnRen-forall.bat"
)
DEFAULT_FORCE_LANGUAGE = (
    r"C:\Users\velos\Documents\Exportador-Importador-Renpy\FERRAMENTAS - TRADUZIR - RENPY\force_language.rpy"
)
DEFAULT_UN_RPY_SOURCE = (
    r"C:\Users\velos\Documents\Interface-Tradutores\FERRAMENTAS - TRADUZIR - RENPY\un.rpy"
)
DEFAULT_UN_RPYC_SOURCE = (
    r"C:\Users\velos\Documents\Interface-Tradutores\FERRAMENTAS - TRADUZIR - RENPY\un.rpyc"
)


def resolve_workspace_root(*, frozen: bool | None = None) -> Path:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return _user_data_dir("InterfaceTradutores") / "workspace"
    return APP_DIR / "workspace"


WORKSPACE_ROOT = resolve_workspace_root()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def open_in_os(path: str | Path) -> None:
    target = str(path)
    if platform.system() == "Windows":
        os.startfile(target)  # type: ignore[attr-defined]
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


def _project_settings_key(project_dir: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(Path(project_dir).resolve())))


def _default_settings() -> dict[str, Any]:
    return {
        "launchers_root": "",
        "unren_source_path": DEFAULT_UNREN_SOURCE,
        "force_language_path": DEFAULT_FORCE_LANGUAGE,
        "un_rpy_source_path": DEFAULT_UN_RPY_SOURCE,
        "un_rpyc_source_path": DEFAULT_UN_RPYC_SOURCE,
        "game_exe_by_project": {},
    }


def load_app_settings() -> dict[str, Any]:
    settings = _default_settings()
    if not SETTINGS_PATH.exists() or not SETTINGS_PATH.is_file():
        return settings

    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings

    for key in ["launchers_root", "unren_source_path", "force_language_path", "un_rpy_source_path", "un_rpyc_source_path"]:
        value = loaded.get(key)
        if isinstance(value, str):
            settings[key] = value

    saved_exe_map = loaded.get("game_exe_by_project")
    if isinstance(saved_exe_map, dict):
        normalized: dict[str, str] = {}
        for raw_project, raw_exe in saved_exe_map.items():
            if isinstance(raw_project, str) and isinstance(raw_exe, str):
                normalized[raw_project] = raw_exe
        settings["game_exe_by_project"] = normalized

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
        self.force_language_info_var = tk.StringVar(value="")
        self.un_rpy_info_var = tk.StringVar(value="")
        self.un_rpyc_info_var = tk.StringVar(value="")
        self.game_exe_info_var = tk.StringVar(value="Executável do jogo: (defina a pasta do projeto)")
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

        self._build_layout()
        self._refresh_renpy_settings_labels()
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

        ttk.Label(self.container, text="Assistente de Tradução Ren'Py/RPGM", style="Title.TLabel").pack(
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
        ttk.Label(frame, text="1) Escolha o tipo de projeto").pack(anchor="w", pady=(2, 12))
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
        ttk.Label(
            frame,
            text="O restante do fluxo será ajustado automaticamente para a engine escolhida.",
        ).pack(anchor="w", pady=(12, 0))
        return frame

    def _build_step_project(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="2) Selecione (ou arraste) a pasta do projeto").pack(
            anchor="w", pady=(2, 12)
        )

        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.project_dir_entry = ttk.Entry(row, textvariable=self.project_dir_var)
        self.project_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pick_project_dir_button = ttk.Button(
            row, text="Selecionar pasta", command=self._pick_project_dir
        )
        self.pick_project_dir_button.pack(side="left")

        hint = "Você pode arrastar a pasta para qualquer área da janela nesta etapa." if HAS_DND else (
            "Arrastar e soltar indisponível (instale tkinterdnd2 para habilitar)."
        )
        ttk.Label(frame, text=hint).pack(anchor="w", pady=(10, 0))

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
        return frame

    def _build_step_export(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="3) Exportar textos").pack(anchor="w", pady=(2, 12))

        self.workspace_label = ttk.Label(frame, text="")
        self.workspace_label.pack(anchor="w", pady=(0, 8))

        ttk.Button(frame, text="Executar exportação", command=self._run_export).pack(anchor="w")

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
        return "Ren'Py" if normalize_engine(self.engine_var.get()) == ENGINE_RENPY else "RPGM"

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
            self.game_exe_info_var.set("Executável do jogo: (defina a pasta do projeto)")
            return

        saved = self._get_saved_game_exe_for_project(project)
        if saved and saved.exists() and saved.is_file():
            self.game_exe_info_var.set(f"Executável salvo: {saved}")
            return
        if saved:
            self.game_exe_info_var.set(
                f"Executável salvo não encontrado: {saved} (será necessário redefinir)"
            )
            return

        detected = detectar_executavel_jogo(project)
        if detected and detected.exists() and detected.is_file():
            self.game_exe_info_var.set(f"Executável detectável: {detected} (ainda não salvo)")
            return

        self.game_exe_info_var.set("Executável do jogo: não detectado (defina manualmente)")

    def _save_settings(self) -> None:
        self.settings["launchers_root"] = self.launchers_root_var.get().strip()
        self.settings["unren_source_path"] = self.unren_source_var.get().strip()
        self.settings["force_language_path"] = self.force_language_source_var.get().strip()
        self.settings["un_rpy_source_path"] = self.un_rpy_source_var.get().strip()
        self.settings["un_rpyc_source_path"] = self.un_rpyc_source_var.get().strip()
        self.settings["game_exe_by_project"] = self._get_game_exe_map()
        save_app_settings(self.settings)
        self._refresh_renpy_settings_labels()
        self._refresh_game_exe_info()

    def _refresh_renpy_prepare_ui_state(self) -> None:
        is_renpy = normalize_engine(self.engine_var.get()) == ENGINE_RENPY
        game_busy = self._game_running()

        if is_renpy and not self.renpy_prepare_visible:
            self.renpy_prepare_frame.pack(fill="x", pady=(14, 0))
            self.renpy_prepare_visible = True
        if not is_renpy and self.renpy_prepare_visible:
            self.renpy_prepare_frame.pack_forget()
            self.renpy_prepare_visible = False

        for button in self.renpy_prepare_buttons:
            button.configure(state="normal" if (is_renpy and not game_busy) else "disabled")
        self.project_dir_entry.configure(state="normal" if not game_busy else "disabled")
        self.pick_project_dir_button.configure(state="normal" if not game_busy else "disabled")
        if hasattr(self, "pick_game_exe_button"):
            self.pick_game_exe_button.configure(state="normal" if not game_busy else "disabled")
        if hasattr(self, "finish_open_button"):
            self.finish_open_button.configure(state="normal" if not game_busy else "disabled")
        if hasattr(self, "finish_restart_button"):
            self.finish_restart_button.configure(state="normal" if not game_busy else "disabled")
        self.back_button.configure(state="disabled" if game_busy else ("normal" if self.current_step > 0 else "disabled"))
        self.next_button.configure(state="disabled" if game_busy else "normal")

        if not is_renpy:
            self.root.minsize(*APP_BASE_MIN_SIZE)
            self.renpy_prepare_hint.configure(
                text="Pré-fluxo disponível apenas para Ren'Py. Para RPGM, siga o fluxo normal."
            )
            self.open_launcher_button.configure(state="disabled")
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
            title="Selecione o UnRen (.bat ou .txt)",
            filetypes=[("Batch ou Texto", "*.bat *.txt"), ("Todos os arquivos", "*.*")],
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
        prompt_title: str = "Selecione o executável principal do jogo",
    ) -> Path | None:
        project = self._project_path_if_valid()
        if project is None:
            return None

        if prefer_saved:
            saved = self._get_saved_game_exe_for_project(project)
            if saved and saved.exists() and saved.is_file():
                self._refresh_game_exe_info()
                self._set_message(f"Executável resolvido pelo cadastro salvo deste projeto: {saved}")
                return saved

        auto_detected = detectar_executavel_jogo(project)
        if auto_detected and auto_detected.exists() and auto_detected.is_file():
            if remember_selection:
                self._save_game_exe_for_project(project, auto_detected)
            else:
                self._refresh_game_exe_info()
            self._set_message(f"Executável resolvido automaticamente: {auto_detected}")
            return auto_detected

        if not allow_manual:
            self._refresh_game_exe_info()
            return None

        selected = filedialog.askopenfilename(
            title=prompt_title,
            initialdir=str(project),
            filetypes=[("Executável", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return None

        exe_path = Path(selected)
        if exe_path.suffix.lower() != ".exe":
            messagebox.showerror("Executável inválido", "Selecione um arquivo .exe válido.")
            return None
        if not exe_path.exists() or not exe_path.is_file():
            messagebox.showerror("Executável inválido", f"Arquivo não encontrado: {exe_path}")
            return None

        if remember_selection:
            self._save_game_exe_for_project(project, exe_path)
        else:
            self._refresh_game_exe_info()
        self._set_message(f"Executável definido manualmente: {exe_path}")
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
            title="Selecione o executável principal do jogo",
            initialdir=str(project),
            filetypes=[("Executável", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if not selected:
            return

        exe_path = Path(selected)
        if exe_path.suffix.lower() != ".exe" or not exe_path.exists() or not exe_path.is_file():
            messagebox.showerror("Executável inválido", "Selecione um arquivo .exe válido.")
            return

        self._save_game_exe_for_project(project, exe_path)
        self._set_message(f"Executável salvo para este projeto: {exe_path}")

    def _game_running(self) -> bool:
        return processo_ativo(self.game_process)

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
            title="Selecione manualmente o renpy.exe",
            filetypes=[("Executável", "*.exe"), ("Todos os arquivos", "*.*")],
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
            self._set_message("UnRen aberto. Como já existia BAT na raiz, ele será mantido.")
        else:
            self._set_message("UnRen aberto em modo interativo. O BAT temporário será removido ao avançar etapa.")

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
            self._set_message("BAT temporário do UnRen removido da raiz do projeto.")
        elif notify and not removed:
            self._set_message("Não foi possível remover automaticamente o BAT temporário do UnRen.")

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
        self._refresh_drop_targets()

    def _on_back(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para continuar.")
            return
        if self.current_step == 1:
            self._cleanup_unren_temp_file(notify=False)
        self._show_step(self.current_step - 1)

    def _on_next(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução para continuar.")
            return
        if self.current_step == 0:
            self._show_step(1)
            return
        if self.current_step == 1:
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
        self.open_log_button.configure(state="disabled")
        self.detected_renpy_version = None
        self.renpy_version_var.set("Versão Ren'Py detectada: -")
        self.manual_version_var.set("")
        self._set_selected_launcher(None)
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
        self._reset_wizard_to_start()

    def _on_window_close(self) -> None:
        if self._game_running():
            messagebox.showwarning(
                "Jogo em execução",
                "Feche o jogo aberto na preparação Ren'Py antes de sair.",
            )
            return
        self._cleanup_unren_temp_file(notify=False)
        self.root.destroy()

    def _on_engine_change(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de trocar a engine.")
            return
        engine = normalize_engine(self.engine_var.get())
        self.engine_var.set(engine)
        self._update_engine_display()
        self.export_done = False
        self.generated_translation_path = None
        self.generated_txt_label.configure(text="-")
        self.open_generated_button.configure(state="disabled")
        self.open_generated_folder_button.configure(state="disabled")
        self.translated_file_var.set("")
        self.detected_renpy_version = None
        self.renpy_version_var.set("Versão Ren'Py detectada: -")
        self.manual_version_var.set("")
        self._set_selected_launcher(None)
        self._refresh_game_exe_info()
        self._set_message(
            f"Engine atualizada para {self._engine_label()}. Continue para escolher a pasta do projeto."
        )
        self._show_step(self.current_step)

    def _pick_project_dir(self) -> None:
        if self._game_running():
            self._set_message("Feche o jogo em execução antes de trocar a pasta do projeto.")
            return
        selected = filedialog.askdirectory(title="Selecione a pasta do projeto")
        if selected:
            self.project_dir_var.set(selected)
            self._refresh_game_exe_info()
            self._set_project_resolution_message()
            if normalize_engine(self.engine_var.get()) == ENGINE_RENPY:
                self._detect_renpy_version()

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
        try:
            items = self.root.tk.splitlist(event.data)
            paths = normalize_dropped_items(list(items))
            if not paths:
                self._set_message("Drop recebido, mas sem caminho válido.")
                return

            if self.drop_mode == DROP_PROJECT_DIR:
                selected_dir, used_file_parent = resolve_project_drop_path(paths)
                if selected_dir is None:
                    self._set_message("Não foi possível identificar uma pasta válida no item arrastado.")
                    return
                self.project_dir_var.set(str(selected_dir))
                self._refresh_game_exe_info()
                if normalize_engine(self.engine_var.get()) == ENGINE_RENPY:
                    self._detect_renpy_version()
                else:
                    self._set_project_resolution_message(via_drop=True, used_file_parent=used_file_parent)
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

    def _run_export(self) -> None:
        if not self._validate_project_dir():
            return

        engine = self.engine_var.get()
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

        details = result.message
        if result.warnings:
            details += "\n\n" + "\n".join(f"- {w}" for w in result.warnings)
        messagebox.showinfo("Exportação concluída", details)
        self._set_message(f"{result.message} Agora traduza e selecione o TXT final.")

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

    def _run_import(self) -> None:
        if not self._validate_project_dir() or not self._validate_translated_file():
            return

        engine = self.engine_var.get()
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
                self._set_message("Importação cancelada para revisão dos alertas.")
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
