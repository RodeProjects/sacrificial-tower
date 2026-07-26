from pathlib import Path


project_root = Path(SPECPATH)
source_root = project_root / "src"

a = Analysis(
    [str(project_root / "start_gui.pyw")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[
        (
            str(project_root / "config" / "default_settings.json"),
            "config",
        ),
        (
            str(source_root / "cooling_tower" / "gui" / "styles.qss"),
            "cooling_tower/gui",
        ),
        (
            str(source_root / "cooling_tower" / "gui" / "assets"),
            "cooling_tower/gui/assets",
        ),
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name="SacrificialTower",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SacrificialTower",
)
