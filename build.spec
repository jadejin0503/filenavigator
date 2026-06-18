# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 单文件打包：生成唯一 PFN.exe，可复制到任意路径单独运行。
# 运行: pyinstaller build.spec   或   build.bat

import os

block_cipher = None
_spec_dir = os.path.dirname(os.path.abspath(SPEC))

_ROOT_ICO = os.path.normpath(os.path.join(_spec_dir, "icon.ico"))
if os.path.isfile(_ROOT_ICO):
    print("[build.spec] exe icon:", _ROOT_ICO, os.path.getsize(_ROOT_ICO), "bytes")
else:
    print("[build.spec] WARNING: icon.ico 不存在，将尝试使用 assets/app_icon.ico:", _ROOT_ICO)

_FALLBACK_ICO = os.path.normpath(os.path.join(_spec_dir, "assets", "app_icon.ico"))
_exe_icon = _ROOT_ICO if os.path.isfile(_ROOT_ICO) else (_FALLBACK_ICO if os.path.isfile(_FALLBACK_ICO) else None)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/app_icon.ico", "assets"),
    ],
    hiddenimports=["PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "pfn_crash_log"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PFN",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_exe_icon,
)
