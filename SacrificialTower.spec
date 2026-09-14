from pathlib import Path
import sys
import json


project_root = Path(SPECPATH)
source_root = project_root / "src"
sys.path.insert(0, str(project_root / "scripts"))
from distribution_compliance import (
    keep_qt_binary, prepare_legal_material, isolate_binary_search_path, binary_origins,
)
isolate_binary_search_path()
legal_root = project_root / "build" / "legal"
prepare_legal_material(legal_root)

version_namespace = {}
exec(
    (source_root / "cooling_tower" / "version.py").read_text(encoding="utf-8"),
    {},
    version_namespace,
)
app_version = version_namespace["APP_VERSION"]
native_timing_extensions = list(
    (source_root / "cooling_tower").glob("_native_timing*.pyd")
)
if len(native_timing_extensions) != 1:
    raise RuntimeError(
        "Die native G-Code-Analyse muss vor PyInstaller genau einmal gebaut werden."
    )
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
    binaries=[(str(native_timing_extensions[0]), "cooling_tower")],
    datas=[
        (str(legal_root), "legal"),
        (str(project_root / "config" / "legal_profile.json"), "config"),
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
    hiddenimports=["cooling_tower._native_timing"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtVirtualKeyboard", "PySide6.QtPdf", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
    optimize=0,
)
# Qt hooks collect optional plugins even without a Python import.
a.binaries = [entry for entry in a.binaries if keep_qt_binary(entry[0])]
origins_path = project_root / "build" / "binary-origins.json"
origins_path.write_text(json.dumps(binary_origins(a.binaries), indent=2) + "\n", encoding="utf-8")
a.datas.append(("legal/binary-origins.json", str(origins_path), "DATA"))
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
    icon=str(
        source_root / "cooling_tower" / "gui" / "assets" / "app.ico"
    ),
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
