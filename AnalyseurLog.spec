# -*- mode: python ; coding: utf-8 -*-
# Spec PyInstaller multi-plateformes pour "Analyseur de fichiers .log".
# Usage :  pyinstaller AnalyseurLog.spec   (Windows / macOS / Linux)

import sys

block_cipher = None

# Sous Windows, embarque plink.exe/pscp.exe (PuTTY) s'ils ont ete deposes dans
# vendor/windows/ (la CI les telecharge avant le build). Permet le SSH bastion.
import os
_datas = [('ignore.txt', '.')]   # liste d'exclusion embarquee
_vendor = os.path.join('vendor', 'windows')
if sys.platform == 'win32' and os.path.isdir(_vendor):
    for _outil in ('plink.exe', 'pscp.exe'):
        _p = os.path.join(_vendor, _outil)
        if os.path.exists(_p):
            _datas.append((_p, os.path.join('vendor', 'windows')))

a = Analysis(
    ['analyseur.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
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
    upx=False,  # Desactiver upx pour eviter les soucis macOS
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
            'NSPrincipalClass': 'NSApplication',
        },
    )
    
    # Signature ad-hoc pour eviter blocage Gatekeeper macOS
    import subprocess
    try:
        subprocess.run(['codesign', '-s', '-', 'dist/AnalyseurLog.app', '--deep', '--force'],
                      check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # codesign indisponible, non grave
