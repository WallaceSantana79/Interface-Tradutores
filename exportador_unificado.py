import os
import tkinter as tk
from tkinter import filedialog

from translator_core.renpy_core import exportar_renpy


def escolher_pasta() -> str:
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title="Selecione a pasta com os arquivos .rpy")


def main() -> None:
    pasta = escolher_pasta()
    if not pasta:
        return

    resultado = exportar_renpy(project_dir=pasta, workspace_dir=os.getcwd())
    print(resultado.message)
    for aviso in resultado.warnings:
        print(f"[AVISO] {aviso}")

    if not resultado.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
