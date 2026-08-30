# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the KeRui Recruit local sidecar.

Build with:
    pyinstaller backend/packaging/kerui_recruit.spec

The result is a self-contained ``kerui-recruit-sidecar`` executable that binds
only to 127.0.0.1 with a per-launch session token.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("uvicorn")
if os.name == "nt":
    hiddenimports += collect_submodules("win32com")
    hiddenimports += ["pythoncom", "pywintypes"]

datas = []
datas += collect_data_files("uvicorn")
datas += collect_data_files("pydantic")

a = Analysis(
    [os.path.join(SPECPATH, "run_sidecar.py")],
    pathex=[os.path.join(SPECPATH, "..", "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pandas", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="kerui-recruit-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
