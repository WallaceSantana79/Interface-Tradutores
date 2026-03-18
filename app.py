from __future__ import annotations

import os
import platform
import subprocess
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
WORKSPACE_ROOT = APP_DIR / "workspace"


def open_in_os(path: str | Path) -> None:
    target = str(path)
    if platform.system() == "Windows":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if platform.system() == "Darwin":
        subprocess.run(["open", target], check=False)
        return
    subprocess.run(["xdg-open", target], check=False)


class TranslatorWizardApp:
    def __init__(self) -> None:
        if HAS_DND:
            self.root = TkinterDnD.Tk()  # type: ignore[union-attr]
        else:
            self.root = tk.Tk()

        self.root.title("Interface Tradutores - V1")
        self.root.geometry("760x520")
        self.root.minsize(700, 470)

        self.engine_var = tk.StringVar(value=ENGINE_RENPY)
        self.project_dir_var = tk.StringVar(value="")
        self.translated_file_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Etapa 1/5 - Escolha a engine")
        self.message_var = tk.StringVar(value="Escolha a engine para iniciar.")

        self.current_step = 0
        self.export_done = False
        self.last_log_file: str | None = None
        self.generated_translation_path: Path | None = None

        self._build_layout()
        self._show_step(0)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container, text="Assistente de Tradução Ren'Py/RPGM", font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(2, 10))

        self.steps_wrap = ttk.Frame(container)
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

        ttk.Separator(container).pack(fill="x", pady=10)
        ttk.Label(container, textvariable=self.message_var, foreground="#1f3a5f").pack(anchor="w")

        nav = ttk.Frame(container)
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

        entry = ttk.Entry(row, textvariable=self.project_dir_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text="Selecionar pasta", command=self._pick_project_dir).pack(side="left")

        hint = "Você também pode arrastar a pasta para o campo acima." if HAS_DND else (
            "Arrastar e soltar indisponível (instale tkinterdnd2 para habilitar)."
        )
        ttk.Label(frame, text=hint).pack(anchor="w", pady=(10, 0))

        if HAS_DND:
            entry.drop_target_register(DND_FILES)  # type: ignore[union-attr]
            entry.dnd_bind("<<Drop>>", self._handle_drop)  # type: ignore[union-attr]

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

        ttk.Label(
            frame,
            text="Depois de traduzir externamente (ex.: DocTranslator), selecione aqui o TXT final.",
        ).pack(anchor="w", pady=(10, 0))
        return frame

    def _build_step_import(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="5) Importar tradução no jogo").pack(anchor="w", pady=(2, 12))

        ttk.Button(frame, text="Executar importação", command=self._run_import).pack(anchor="w")
        self.open_log_button = ttk.Button(frame, text="Abrir log da importação", command=self._open_log)
        self.open_log_button.pack(anchor="w", pady=(10, 0))
        self.open_log_button.configure(state="disabled")
        return frame

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
        self.status_var.set(titles[self.current_step])
        self.back_button.configure(state="normal" if self.current_step > 0 else "disabled")

        if self.current_step == len(self.step_frames) - 1:
            self.next_button.configure(text="Finalizar", command=self._on_finish, state="normal")
        else:
            self.next_button.configure(text="Próximo", command=self._on_next, state="normal")

        if self.current_step == 2:
            ws = engine_workspace_dir(self.engine_var.get(), WORKSPACE_ROOT)
            self.workspace_label.configure(text=f"Pasta de trabalho: {ws}")

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
        self.export_done = False
        self.generated_translation_path = None
        self.generated_txt_label.configure(text="-")
        self.open_generated_button.configure(state="disabled")
        self.open_generated_folder_button.configure(state="disabled")
        self.translated_file_var.set("")
        self._set_message("Engine atualizada. Continue para escolher a pasta do projeto.")

    def _pick_project_dir(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta do projeto")
        if selected:
            self.project_dir_var.set(selected)
            self._set_message("Pasta selecionada.")

    def _pick_translated_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o TXT traduzido",
            filetypes=[("Text files", "*.txt"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            self.translated_file_var.set(selected)
            self._set_message("Arquivo traduzido selecionado.")

    def _handle_drop(self, event: tk.Event) -> None:
        try:
            items = self.root.tk.splitlist(event.data)
            if not items:
                return
            dropped = items[0]
            if dropped.startswith("{") and dropped.endswith("}"):
                dropped = dropped[1:-1]
            self.project_dir_var.set(dropped)
            self._set_message("Pasta recebida por arrastar e soltar.")
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
        if not file_path.exists() or not file_path.is_file():
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
        self._set_message("Exportação concluída. Agora traduza e selecione o TXT final.")

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
        self._set_message("Importação finalizada com sucesso.")

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
