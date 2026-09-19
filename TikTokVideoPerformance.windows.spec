# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH)

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
app_hiddenimports = collect_submodules("app")
openpyxl_hiddenimports = collect_submodules("openpyxl")

hiddenimports = list(dict.fromkeys(
    playwright_hiddenimports
    + app_hiddenimports
    + openpyxl_hiddenimports
))

icon_path = project_root / "assets" / "app.ico"
icon_value = str(icon_path) if icon_path.exists() else None

a = Analysis(
    [str(project_root / "gui_app.py")],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
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
    name="TikTok Video Performance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_value,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TikTok Video Performance",
)
