# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# PyInstaller sweeps up DLLs it finds on PATH. Qt 6 on Windows uses the system
# ICU forwarder, so if the build machine has another program's ICU DLLs on PATH
# (Poppler ships icuuc.dll and icudt78.dll, for instance) they get bundled under
# the same names and QtCore fails at startup on every other machine. Drop them:
# nothing here wants an ICU that is not Windows' own.
a.binaries = [
    item for item in a.binaries
    if item[0].lower() not in {'icuuc.dll', 'icudt78.dll'}
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='KeyPulse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['assets\\keypulse.ico'],
)

