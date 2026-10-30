# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve()

def is_browser_or_user_data(item):
    """Filter out playwright browser downloads (.local-browsers / Chromium .app)
    and any user session/cache files so PyInstaller does not fail codesign during COLLECT.
    Chromium is copied separately to Contents/Resources/ms-playwright after build.
    """
    paths = []
    if isinstance(item, (tuple, list)):
        for x in item[:2]:
            if isinstance(x, (str, Path)):
                paths.append(str(x))
    elif isinstance(item, (str, Path)):
        paths.append(str(item))

    target = " ".join(paths).replace("\\", "/").lower()
    return (
        ".local-browsers" in target
        or "chrome-mac" in target
        or "chromium" in target
        or "google chrome for testing" in target
        or "tiktok_state.json" in target
        or ".ds_store" in target
    )


# Playwright carries a bundled Node driver and package data that must be
# present inside the packaged application.
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all(
    "playwright"
)

# Filter out browser binaries and data from playwright collection
playwright_datas = [d for d in playwright_datas if not is_browser_or_user_data(d)]
playwright_binaries = [b for b in playwright_binaries if not is_browser_or_user_data(b)]

hiddenimports = list(playwright_hiddenimports)
hiddenimports += collect_submodules("playwright")
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("openpyxl")

# De-duplicate while preserving order.
hiddenimports = list(dict.fromkeys(hiddenimports))

runtime_hooks = []
pw_rthook = PROJECT_ROOT / "rthook_playwright.py"
if pw_rthook.is_file():
    runtime_hooks.append(str(pw_rthook))

a = Analysis(
    [str(PROJECT_ROOT / "gui_app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=playwright_binaries,
    datas=playwright_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
    optimize=0,
)

# Crucial step: filter again after Analysis to remove any binaries or datas
# that PyInstaller's binary vs data reclassification might have swept in
a.binaries = [b for b in a.binaries if not is_browser_or_user_data(b)]
a.datas = [d for d in a.datas if not is_browser_or_user_data(d)]

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
    upx=False,
    upx_exclude=[],
    name="TikTok Video Performance",
)

app = BUNDLE(
    coll,
    name="TikTok Video Performance.app",
    icon=None,
    bundle_identifier="com.tiktokvideoperformance.desktop",
    info_plist={
        "CFBundleName": "TikTok Video Performance",
        "CFBundleDisplayName": "TikTok Video Performance",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
