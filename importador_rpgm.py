import os
import tkinter as tk
from tkinter import filedialog

from translator_core.rpgm_core import TRANSLATIONS_FILENAME, importar_rpgm


def escolher_pasta() -> str:
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(
        title="Selecione a pasta 'data' do RPG Maker para INJETAR a tradução"
    )


def main() -> None:
    pasta = escolher_pasta()
    if not pasta:
        return

    translated_path = os.path.join(os.getcwd(), TRANSLATIONS_FILENAME)
    resultado = importar_rpgm(
        project_dir=pasta,
        workspace_dir=os.getcwd(),
        translated_txt_path=translated_path,
        criar_backup=False,
    )

    print(resultado.message)
    for aviso in resultado.warnings:
        print(f"[AVISO] {aviso}")

    if not resultado.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
