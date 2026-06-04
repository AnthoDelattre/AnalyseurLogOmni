# -*- mode: python ; coding: utf-8 -*-
# Spec PyInstaller multi-plateformes pour "Analyseur de fichiers .log".
# Usage :  pyinstaller AnalyseurLog.spec   (Windows / macOS / Linux)

import sys

block_cipher = None

a = Analysis(
    ['analyseur.py'],
    pathex=[],
    binaries=[],
    datas=[('ignore.txt', '.')],   # liste d'exclusion embarquee
    hiddenimports=['parseur'],
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
    name='AnalyseurLog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='AnalyseurLog.app',
        icon=None,
        bundle_identifier='com.exemple.analyseurlog',
        info_plist={
            'CFBundleName': 'Analyseur de fichiers .log',
            'CFBundleDisplayName': 'Analyseur de fichiers .log',
            'NSHighResolutionCapable': True,
        },
    )
