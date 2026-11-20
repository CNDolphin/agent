# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置:Windows 桌面客户端(one-folder)。

数据文件按源码树中的相对路径落到 ``_internal/`` 下,与应用内
``Path(__file__)`` 的定位方式保持一致,无需改动业务代码。
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parents[2]  # packaging/windows/ -> 仓库根

datas = [
    (str(ROOT / "client" / "web" / "dist"), "client/web/dist"),
    (str(ROOT / "skills"), "skills"),
    (str(ROOT / "mhagent" / "data"), "mhagent/data"),
    (str(ROOT / "mhagent" / "tools" / "data"), "mhagent/tools/data"),
]
datas += collect_data_files("webview")

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]
if sys.platform == "win32":
    hiddenimports.append("clr")

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "numpy", "pandas", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mhagent-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="mhagent-desktop",
)
