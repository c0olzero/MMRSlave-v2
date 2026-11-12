"""Build MMRSlave.exe (a folder app) and a zip to share.

    .venv-build\\Scripts\\python packaging\\build.py

(packaging\\build.ps1 sets up that environment.) Output:
    dist\\MMRSlave\\MMRSlave.exe            the app; keep the folder together
    dist\\MMRSlave-windows-<commit>.zip     the same folder, zipped for sharing / GitHub Releases

The app's code is copied in as plain files (not frozen), so it can update itself from GitHub;
see packaging/launcher.py and src/mmrslave/updater.py.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
STAGE = BUILD / "stage" / "app"
DIST = ROOT / "dist"
# Standard-library modules not worth bundling.
SKIP_STDLIB = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv",
               "pydoc_data", "curses", "_tkinter", "msilib", "nis", "spwd", "crypt", "ossaudiodev",
               "readline", "_curses", "_curses_panel", "antigravity", "this"}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def stage_app() -> dict[str, str]:
    """Copy the code, brain and version info into build/stage/app."""
    shutil.rmtree(STAGE.parent, ignore_errors=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "src" / "mmrslave", STAGE / "src" / "mmrslave", ignore=ignore)
    if (ROOT / "brain").exists():
        shutil.copytree(ROOT / "brain", STAGE / "brain")
    else:
        print("warning: no brain/ folder; friends' copies will have no trained models")
    for rel in ("pyproject.toml", "mmrslave.example.toml", "packaging/runtime.json"):
        (STAGE / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, STAGE / rel)
    sha, date = git("rev-parse", "HEAD"), git("log", "-1", "--format=%cI")
    if git("status", "--porcelain", "--untracked-files=no"):
        print("warning: building with uncommitted changes; the version shown is the last commit")
    version = {"sha": sha, "date": date}
    (STAGE / "VERSION.json").write_text(json.dumps(version), encoding="utf-8")
    return version


def hidden_imports() -> list[str]:
    """Everything the app's code imports (it isn't frozen, so PyInstaller can't see it), plus the
    whole standard library, so an update that starts using another stdlib module still runs."""
    names: set[str] = set()
    for py in (ROOT / "src" / "mmrslave").rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
    names = {n for n in names if n.split(".")[0] not in ("mmrslave", "__future__")}
    names |= {m for m in sys.stdlib_module_names if m not in SKIP_STDLIB and not m.startswith("_")}
    return sorted(names)


def main() -> None:
    version = stage_app()
    (BUILD / "hidden_imports.json").write_text(json.dumps(hidden_imports()), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
                    str(ROOT / "packaging" / "mmrslave.spec")], check=True, cwd=ROOT)
    app = DIST / "MMRSlave"
    shutil.copy2(ROOT / "packaging" / "READ ME FIRST.txt", app / "READ ME FIRST.txt")
    zip_base = DIST / f"MMRSlave-windows-{version['sha'][:7]}"
    print("zipping…")
    shutil.make_archive(str(zip_base), "zip", DIST, "MMRSlave")
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"done: {app / 'MMRSlave.exe'} ({size / 1e6:.0f} MB unpacked)\n      {zip_base}.zip "
          f"({Path(str(zip_base) + '.zip').stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
