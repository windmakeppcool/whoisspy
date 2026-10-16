# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（pc-game 二：--onedir 打包 backend/，Electron extraResources 携带）
# 用法：pyinstaller whoisspy.spec（产物 dist/whoisspy-engine/）
# Electron main.js 在打包态下优先加载 resources/whoisspy-engine/whoisspy-engine.exe。

import os

block_cipher = None

a = Analysis(
    ["app/main.py"],
    pathex=[os.path.dirname(os.path.abspath(__file__))],
    binaries=[],
    datas=[],
    hiddenimports=["websockets"],
    hookspath=[],
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
    [],
    exclude_binaries=True,
    name="whoisspy-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # sidecar 需要 stdout 回打端口首行
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="whoisspy-engine",
)