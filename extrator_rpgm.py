import os
import tkinter as tk
from tkinter import filedialog

from translator_core.rpgm_core import exportar_rpgm


def escolher_pasta() -> str:
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(
        title="Selecione a pasta 'data' do RPG Maker (Ex: SeuJogo/data)"
    )


def main() -> None:
    pasta = escolher_pasta()
    if not pasta:
        return

    resultado = exportar_rpgm(project_dir=pasta, workspace_dir=os.getcwd())
    print(resultado.message)
    for aviso in resultado.warnings:
        print(f"[AVISO] {aviso}")

    if not resultado.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
