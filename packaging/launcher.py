"""MMRSlave.exe's entry point.

Python and the libraries are frozen into the .exe, but the app's own code is kept as plain files
so updates can replace it without a new .exe:

- the copy built into the .exe:      <exe folder>/_internal/app/src/mmrslave
- a newer copy downloaded by updates: %LOCALAPPDATA%/MMRSlave/app/<commit>/src/mmrslave
  (named in %LOCALAPPDATA%/MMRSlave/app/current.txt)

The newest copy that imports cleanly is put on sys.path, then:
    MMRSlave.exe                  opens the app window
    MMRSlave.exe --server ...     the dashboard server (started by the window process)
    MMRSlave.exe <command> ...    any `python -m mmrslave` command, e.g. `status`
"""

import multiprocessing
import os
import sys
from pathlib import Path

APP_HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MMRSlave"
BUNDLED = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "app"
LOG_LIMIT = 5_000_000


def _log_to_file() -> None:
    """The windowed .exe has no console; send prints and errors to a log file instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    logs = APP_HOME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "mmrslave.log"
    try:
        if path.exists() and path.stat().st_size > LOG_LIMIT:
            path.replace(logs / "mmrslave.old.log")
    except OSError:
        pass
    f = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def _updated_root() -> Path | None:
    current = APP_HOME / "app" / "current.txt"
    try:
        sha = current.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    root = APP_HOME / "app" / sha
    return root if sha and (root / "src" / "mmrslave" / "__init__.py").exists() else None


def _use(root: Path) -> None:
    sys.path.insert(0, str(root / "src"))
    import mmrslave.cli  # noqa: F401 - fails here, not later, when the copy is broken


def _load_code() -> None:
    root = _updated_root()
    if root is not None:
        try:
            _use(root)
            return
        except Exception as e:  # noqa: BLE001 - any failure means: go back to the built-in copy
            print(f"The downloaded version in {root} didn't load ({e!r}); using the built-in one.", file=sys.stderr)
            sys.path.remove(str(root / "src"))
            for name in [m for m in sys.modules if m == "mmrslave" or m.startswith("mmrslave.")]:
                del sys.modules[name]
            try:
                (APP_HOME / "app" / "current.txt").unlink()
            except OSError:
                pass
    _use(BUNDLED)


def main() -> None:
    _log_to_file()
    _load_code()
    # Parse workers are this .exe started again; this runs their job and exits.
    multiprocessing.freeze_support()
    from mmrslave.cli import main as cli

    args = sys.argv[1:]
    if args[:1] == ["--server"]:
        cli(["_server", *args[1:]])
    elif args:
        cli(args)
    else:
        from mmrslave.desktop import run
        sys.exit(run(window=True))


if __name__ == "__main__":
    main()
