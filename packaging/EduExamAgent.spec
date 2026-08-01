from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


project_root = Path.cwd()
pypdfium_datas, pypdfium_binaries, pypdfium_hiddenimports = collect_all("pypdfium2")

analysis = Analysis(
    [str(project_root / "src" / "edu_exam_agent" / "app" / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=pypdfium_binaries,
    datas=[
        (str(project_root / "config.example.toml"), "."),
    ]
    + pypdfium_datas,
    hiddenimports=collect_submodules("sqlalchemy.dialects.sqlite") + pypdfium_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="EduExamAgent",
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
    icon=[str(project_root / "src" / "edu_exam_agent" / "assets" / "app_icon.ico")],
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EduExamAgent",
)
