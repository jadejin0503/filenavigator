# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：PFN 临床试验项目导航
# 运行: pyinstaller build.spec

import os

block_cipher = None
_spec_dir = os.path.dirname(os.path.abspath(SPEC))
# 桌面/资源管理器中的 exe 图标来自此 ICO（与运行时 setWindowIcon 无关）。
# 换 Logo 后请先运行: python scripts/build_app_icon_from_png.py
_APP_ICO = os.path.normpath(os.path.join(_spec_dir, "assets", "app_icon.ico"))
if os.path.isfile(_APP_ICO):
    print("[build.spec] exe icon:", _APP_ICO, os.path.getsize(_APP_ICO), "bytes")
else:
    print("[build.spec] WARNING: app_icon.ico 不存在，exe 将无自定义图标:", _APP_ICO)

a = Analysis(
    ['app_qt.py'],
    pathex=[],
    binaries=[],
    datas=[],  # 不打包 config.json，别人拿到 exe 后是空项目
    hiddenimports=['PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets'],
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
    name='PFN',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩后，部分环境下资源管理器对 exe 内嵌图标的显示会异常（仍显示旧图或默认图标）
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_APP_ICO if os.path.isfile(_APP_ICO) else None,
)
