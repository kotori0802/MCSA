# -*- mode: python ; coding: utf-8 -*-
"""One-directory Windows package for MCSA 1.0.0.

PyInstaller 6.x. UPX is disabled. Tk is excluded from the frozen GUI.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
shiboken_datas, shiboken_binaries, shiboken_hidden = collect_all("shiboken6")
openpyxl_datas, openpyxl_binaries, openpyxl_hidden = collect_all("openpyxl")
pkg_datas = collect_data_files("mouse_click_stability_analyzer")
pkg_hidden = collect_submodules("mouse_click_stability_analyzer")

hiddenimports = sorted(
    set(pyside_hidden)
    | set(shiboken_hidden)
    | set(openpyxl_hidden)
    | set(pkg_hidden)
    | {"PySide6.QtSvg", "PySide6.QtSvgWidgets"}
)

a = Analysis(
    [str(ROOT / "packaging" / "mcsa_entry.py")],
    pathex=[str(SRC)],
    binaries=pyside_binaries + shiboken_binaries + openpyxl_binaries,
    datas=pyside_datas + shiboken_datas + openpyxl_datas + pkg_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "turtle", "IPython", "jupyter", "matplotlib"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MCSA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "packaging" / "file_version_info.txt"),
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MCSA-1.0.0-win64",
)
