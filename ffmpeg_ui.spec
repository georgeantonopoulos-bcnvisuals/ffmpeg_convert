# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ffmpeg_ui.py'],
    pathex=[],
    binaries=[('/tmp/george_antonopoulos/openimageio/2.4.15.0/157a/a/bin/oiiotool', '.'), ('/usr/bin/ffmpeg', '.')],
    datas=[('dark_theme.tcl', '.'), ('rounded_buttons.tcl', '.'), ('ffmpeg_ui_icon.png', '.'), ('ffmpeg_settings.json', '.')],
    hiddenimports=['clique', 'tkinter'],
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
    a.binaries,
    a.datas,
    [],
    name='ffmpeg_ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
