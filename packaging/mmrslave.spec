# PyInstaller recipe for MMRSlave.exe. Run through packaging/build.py, which prepares
# build/stage/app (the app's code as plain files) and build/hidden_imports.json first.
import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "build"

hidden = json.loads((BUILD / "hidden_imports.json").read_text(encoding="utf-8"))
# Packages that pick their parts at run time.
for pkg in ("uvicorn", "gem", "anthropic", "httpx", "h11", "websockets", "watchfiles", "httptools"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:  # noqa: BLE001 - optional extras
        pass

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[],
    datas=[(str(BUILD / "stage" / "app"), "app"), *collect_data_files("gem")],
    hiddenimports=hidden,
    # The app's own code ships as plain files in app/ (see launcher.py), never frozen.
    excludes=["mmrslave", "tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MMRSlave",
    icon=str(ROOT / "packaging" / "mmrslave.ico"),
    console=False,
    version=None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MMRSlave", upx=False)
