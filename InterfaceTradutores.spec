# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path.cwd()

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all("tkinterdnd2")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all("UnityPy")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
hiddenimports += ["tkinter", "_tkinter"]

# PythonManager builds can fail tkinter auto-detection in PyInstaller.
# Explicitly ship Tcl/Tk data in paths expected by pyi_rth__tkinter.
_tcl_root = Path(sys.base_prefix) / "tcl"
_tcl_dirs = sorted([p for p in _tcl_root.glob("tcl*") if p.is_dir()])
_tk_dirs = sorted([p for p in _tcl_root.glob("tk*") if p.is_dir()])


def _collect_dir_files(src_dir: Path, dest_root: str) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    for file_path in src_dir.rglob("*"):
        if not file_path.is_file():
            continue
        rel_parent = file_path.relative_to(src_dir).parent
        dest_dir = str(Path(dest_root) / rel_parent) if str(rel_parent) != "." else dest_root
        collected.append((str(file_path), dest_dir))
    return collected


if _tcl_dirs:
    datas += _collect_dir_files(_tcl_dirs[-1], "_tcl_data")
if _tk_dirs:
    datas += _collect_dir_files(_tk_dirs[-1], "_tk_data")

tools_dir = project_root / "FERRAMENTAS - TRADUZIR - RENPY"
if tools_dir.is_dir():
    datas += _collect_dir_files(tools_dir, "FERRAMENTAS - TRADUZIR - RENPY")


a = Analysis(
    [str(project_root / "app.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InterfaceTradutores",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="InterfaceTradutores",
)
