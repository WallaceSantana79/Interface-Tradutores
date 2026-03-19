from __future__ import annotations

import os
import platform
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from translator_core import exportar, importar, pre_validar_importacao
from translator_core.orchestrator import (
    ENGINE_RENPY,
    ENGINE_RPGM,
    engine_workspace_dir,
    normalize_engine,
    translation_filename_for_engine,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    HAS_DND = False
    DND_FILES = None
    TkinterDnD = None


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "v1.1"

DROP_DISABLED = "disabled"
DROP_PROJECT_DIR = "project_dir"
DROP_TRANSLATED_TXT = "translated_txt"


def _user_data_dir(app_name: str) -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / app_name


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


class TranslatorWizardApp:
    def __init__(self) -> None:
        if HAS_DND:
            self.root = TkinterDnD.Tk()  # type: ignore[union-attr]
        else:
            self.root = tk.Tk()

        self._configure_style()
        self.root.title(f"Interface Tradutores - {APP_VERSION}")
        self.root.geometry("760x540")
        self.root.minsize(700, 500)

        self.engine_var = tk.StringVar(value=ENGINE_RENPY)
        self.engine_display_var = tk.StringVar(value="")
        self.project_dir_var = tk.StringVar(value="")
        self.translated_file_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Etapa 1/5 - Escolha a engine")
        self.message_var = tk.StringVar(value="Escolha a engine para iniciar.")
        self.workspace_info_var = tk.StringVar(value=f"Pasta de trabalho base: {WORKSPACE_ROOT}")
        self.build_info_var = tk.StringVar(value=f"Build: {APP_VERSION}")

        self.current_step = 0
        self.drop_mode = DROP_DISABLED
        self.export_done = False
        self.last_log_file: str | None = None
        self.generated_translation_path: Path | None = None

        self._build_layout()
        self._update_engine_display()
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
        ttk.Entry(row, textvariable=self.project_dir_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ttk.Button(row, text="Selecionar pasta", command=self._pick_project_dir).pack(side="left")

        hint = "Você pode arrastar a pasta para qualquer área da janela nesta etapa." if HAS_DND else (
            "Arrastar e soltar indisponível (instale tkinterdnd2 para habilitar)."
        )
        ttk.Label(frame, text=hint).pack(anchor="w", pady=(10, 0))
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
        return frame

    def _engine_label(self) -> str:
        return "Ren'Py" if normalize_engine(self.engine_var.get()) == ENGINE_RENPY else "RPGM"

    def _update_engine_display(self) -> None:
        self.engine_display_var.set(f"Engine selecionada: {self._engine_label()}")

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

        self.workspace_info_var.set(f"Pasta de trabalho base: {WORKSPACE_ROOT}")
        self._refresh_drop_targets()

    def _on_back(self) -> None:
        self._show_step(self.current_step - 1)

    def _on_next(self) -> None:
        if self.current_step == 0:
            self._show_step(1)
            return
        if self.current_step == 1:
            if not self._validate_project_dir():
                return
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
        self.root.destroy()

    def _on_engine_change(self) -> None:
        engine = normalize_engine(self.engine_var.get())
        self.engine_var.set(engine)
        self._update_engine_display()
        self.export_done = False
        self.generated_translation_path = None
        self.generated_txt_label.configure(text="-")
        self.open_generated_button.configure(state="disabled")
        self.open_generated_folder_button.configure(state="disabled")
        self.translated_file_var.set("")
        self._set_message(
            f"Engine atualizada para {self._engine_label()}. Continue para escolher a pasta do projeto."
        )
        self._show_step(self.current_step)

    def _pick_project_dir(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta do projeto")
        if selected:
            self.project_dir_var.set(selected)
            self._set_message(f"Pasta do projeto definida para {self._engine_label()}.")

    def _pick_translated_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o TXT traduzido",
            filetypes=[("Text files", "*.txt"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            self.translated_file_var.set(selected)
            self._set_message("Arquivo TXT traduzido selecionado.")

    def _handle_drop(self, event: tk.Event) -> None:
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
                if used_file_parent:
                    self._set_message("Arquivo detectado no drop. Usei automaticamente a pasta dele.")
                else:
                    self._set_message("Pasta recebida por arrastar e soltar.")
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
        project_dir = Path(self.project_dir_var.get())
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
        self._set_message(f"Exportação {self._engine_label()} concluída. Agora traduza e selecione o TXT final.")

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
            warn_msg = "Foram encontrados alertas:\n\n" + "\n".join(f"- {w}" for w in pre.warnings)
            warn_msg += "\n\nDeseja continuar mesmo assim?"
            if not messagebox.askyesno("Alertas na pré-validação", warn_msg):
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

        details = result.message
        if result.warnings:
            details += "\n\nAlertas:\n" + "\n".join(f"- {w}" for w in result.warnings)

        messagebox.showinfo("Importação concluída", details)
        self._set_message(f"Importação {self._engine_label()} finalizada com sucesso.")

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
