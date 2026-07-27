from pathlib import Path


project_root = Path(SPECPATH)
source_root = project_root / "src"

version_namespace = {}
exec(
    (source_root / "cooling_tower" / "version.py").read_text(encoding="utf-8"),
    {},
    version_namespace,
)
app_version = version_namespace["APP_VERSION"]
version_numbers = tuple(int(part) for part in app_version.split(".")) + (0,)
version_info_path = project_root / "build" / "windows_version_info.txt"
version_info_path.parent.mkdir(parents=True, exist_ok=True)
version_info_path.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_numbers!r},
    prodvers={version_numbers!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040704B0',
        [
          StringStruct(u'CompanyName', u'RodeProjects'),
          StringStruct(u'FileDescription', u'Sacrificial Tower'),
          StringStruct(u'FileVersion', u'{app_version}.0'),
          StringStruct(u'InternalName', u'SacrificialTower'),
          StringStruct(u'OriginalFilename', u'SacrificialTower.exe'),
          StringStruct(u'ProductName', u'Sacrificial Tower'),
          StringStruct(u'ProductVersion', u'{app_version}.0')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1031, 1200])])
  ]
)
""",
    encoding="utf-8",
)

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
            str(project_root / "config" / "distribution.json"),
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
    version=str(version_info_path),
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
