"""The desktop app: runs the dashboard server and shows it in its own window.

The server runs as a child process so an update can restart it on the new code: the server
exits with RESTART_EXIT and this supervisor starts it again. The window is Microsoft Edge (or
Chrome) in app mode with its own profile, so it looks like a normal program window; closing it
closes the app. Without either browser, the dashboard opens in the default browser.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from mmrslave.config import APP_HOME, FROZEN

RESTART_EXIT = 3
SUPERVISED_ENV = "MMRSLAVE_SUPERVISED"
DEFAULT_PORT = 8765
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def message_box(text: str, title: str = "MMRSlave") -> None:
    """A Windows message box, for errors the packaged app (which has no console) must show."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    else:
        print(text, file=sys.stderr)


def server_command(port: int) -> list[str]:
    if FROZEN:
        return [sys.executable, "--server", "--port", str(port)]
    return [sys.executable, "-m", "mmrslave", "_server", "--port", str(port)]


def ping(port: int, timeout: float = 0.5) -> bool:
    """Whether an MMRSlave dashboard answers on this port."""
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/ping", timeout=timeout)
        return r.status_code == 200 and r.json().get("app") == "mmrslave"
    except (httpx.HTTPError, ValueError):
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_app_browser() -> str | None:
    """Edge (on every Windows 10/11 PC) or Chrome, which can show a page as an app window."""
    names = ("msedge.exe", "chrome.exe")
    if sys.platform == "win32":
        import winreg
        for name in names:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as k:
                        path = winreg.QueryValue(k, None)
                    if path and Path(path).exists():
                        return path
                except OSError:
                    continue
        roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            for root in filter(None, roots):
                if (Path(root) / rel).exists():
                    return str(Path(root) / rel)
        return None
    return next(filter(None, (shutil.which(n) for n in
                              ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"))), None)


def open_window(url: str) -> subprocess.Popen | None:
    """Show the dashboard in an app window. Returns the browser process when closing the window
    ends it (so the app can close with it), else None."""
    exe = find_app_browser()
    if not exe:
        webbrowser.open(url)
        return None
    profile = APP_HOME / "window"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1480,940",
        "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
        "--disable-features=msEdgeStartupBoost,Translate,msImplicitSignin",
    ])


def _start_server(port: int) -> subprocess.Popen:
    env = {**os.environ, SUPERVISED_ENV: "1"}
    return subprocess.Popen(server_command(port), env=env, creationflags=NO_WINDOW if FROZEN else 0)


def _wait_ready(child: subprocess.Popen, port: int, seconds: float = 120) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if child.poll() is not None:
            return False
        if ping(port):
            return True
        time.sleep(0.25)
    return False


def run(window: bool = True, port: int = DEFAULT_PORT) -> int:
    """Start the dashboard (and its window), restart it after updates, stop when the window closes."""
    if ping(port):
        # Already running: just show it.
        url = f"http://127.0.0.1:{port}/"
        if window:
            open_window(url)
        else:
            _log(f"MMRSlave is already running at {url}")
        return 0
    if not port_free(port):
        port = free_port()
    url = f"http://127.0.0.1:{port}/"
    if FROZEN:
        from mmrslave.updater import clean_old_versions
        try:
            clean_old_versions()
        except OSError:
            pass

    child = _start_server(port)
    if not _wait_ready(child, port):
        child.kill()
        message_box("MMRSlave couldn't start its dashboard.\n\n"
                    f"Details are in {APP_HOME / 'logs' / 'mmrslave.log'}." if FROZEN
                    else "The dashboard didn't start; see the error above.")
        return 1
    _log(f"Dashboard: {url}" + ("" if window else "   (Ctrl+C to stop)"))

    closed = threading.Event()
    if window:
        browser = open_window(url)
        if browser is not None:
            def watch() -> None:
                browser.wait()
                # Edge may hand the window to a process that was already running; then this one
                # exits at once and the window can't be watched, so keep running.
                if time.monotonic() - opened > 8:
                    closed.set()
            opened = time.monotonic()
            threading.Thread(target=watch, daemon=True).start()

    try:
        while True:
            while child.poll() is None and not closed.is_set():
                time.sleep(0.3)
            if closed.is_set():
                break
            if child.returncode != RESTART_EXIT:
                return child.returncode
            _log("restarting on the new version…")
            child = _start_server(port)
            if not _wait_ready(child, port):
                message_box("MMRSlave updated but the new version didn't start. "
                            "It will go back to the previous version next time you open it.")
                if FROZEN:
                    from mmrslave.updater import CURRENT_FILE
                    CURRENT_FILE.unlink(missing_ok=True)
                return 1
    except KeyboardInterrupt:
        pass
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0
