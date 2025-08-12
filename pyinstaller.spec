# Optional: you can build with `pyinstaller app.py` and ignore this.
# If you need fine control, edit this spec and run: pyinstaller app.spec
# (The workflow uses the CLI flags, not this spec, by default.)

# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app.png','assets'), ('assets/app.ico','assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='yt_mp4_to_audio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed
    icon='assets/app.ico' if os.path.exists('assets/app.ico') else None
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='yt_mp4_to_audio'
)
