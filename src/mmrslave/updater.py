r"""Updates from GitHub (github.com/c0olzero/MMRSlave-v2, branch main).

Two ways the app can be running:

- "bundle": the packaged MMRSlave.exe. Python and the libraries are frozen into the .exe, but the
  app's own code and its trained brain are plain files, so an update downloads just those (a few
  MB) from the newest commit into %LOCALAPPDATA%\MMRSlave\app\<commit> and restarts on them.
  When a commit needs a new library (packaging/runtime.json's number goes up), the code alone
  can't run, so the app points to the newest full download on the Releases page instead.
- "git": run from a clone of the repository. An update is `git pull --ff-only`, plus
  `pip install -e .` when the dependencies changed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import httpx

from mmrslave.config import APP_HOME, FROZEN, PROJECT_ROOT

REPO = "c0olzero/MMRSlave-v2"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
HEADERS = {"User-Agent": "MMRSlave/0.1", "Accept": "application/vnd.github+json"}
# Updated copies of the code live here, one folder per commit; `current.txt` names the one to run.
APP_DIR = APP_HOME / "app"
CURRENT_FILE = APP_DIR / "current.txt"
VERSION_FILE = "VERSION.json"
RUNTIME_FILE = "packaging/runtime.json"
# What an update copies out of the repository.
UPDATE_PARTS = ("src/mmrslave/", "brain/", "pyproject.toml", "mmrslave.example.toml", RUNTIME_FILE)


class UpdateError(Exception):
    pass


def _git(*args: str, timeout: float = 60) -> str:
    r = subprocess.run(["git", "-C", str(PROJECT_ROOT), *args], capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise UpdateError((r.stderr or r.stdout).strip() or f"git {args[0]} failed")
    return r.stdout.strip()


def mode() -> str:
    if FROZEN:
        return "bundle"
    if (PROJECT_ROOT / ".git").exists() and shutil.which("git"):
        return "git"
    return "source"


def runtime_version(root: Path = PROJECT_ROOT) -> int:
    try:
        return int(json.loads((root / RUNTIME_FILE).read_text(encoding="utf-8"))["runtime"])
    except (OSError, ValueError, KeyError):
        return 0


def _dependency_names(pyproject_text: str) -> set[str]:
    deps = tomllib.loads(pyproject_text).get("project", {}).get("dependencies", [])
    out = set()
    for d in deps:
        name = d.split(";")[0]
        for stop in "<>=!~[ ":
            name = name.split(stop)[0]
        out.add(name.strip().lower().replace("_", "-"))
    return out


def installed() -> dict[str, Any]:
    """The commit this copy of the app was built from."""
    m = mode()
    info: dict[str, Any] = {"mode": m, "sha": None, "date": None, "runtime": runtime_version()}
    if m == "git":
        try:
            info["sha"] = _git("rev-parse", "HEAD")
            info["date"] = _git("log", "-1", "--format=%cI")
        except (UpdateError, OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            v = json.loads((PROJECT_ROOT / VERSION_FILE).read_text(encoding="utf-8"))
            info["sha"], info["date"] = v.get("sha"), v.get("date")
        except (OSError, ValueError):
            pass
    info["short"] = info["sha"][:7] if info["sha"] else None
    return info


def _get(client: httpx.Client, url: str) -> httpx.Response:
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        raise UpdateError(f"Couldn't reach GitHub ({e.__class__.__name__}). Check your internet connection.") from e
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        raise UpdateError("GitHub's limit for update checks is used up for this hour. Try again later.")
    return r


def check() -> dict[str, Any]:
    """Compare this copy with the newest commit on GitHub."""
    here = installed()
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = _get(c, f"{API}/commits/{BRANCH}")
        if r.status_code != 200:
            raise UpdateError(f"GitHub answered {r.status_code} for the newest version.")
        head = r.json()
        latest = {"sha": head["sha"], "short": head["sha"][:7], "date": head["commit"]["committer"]["date"]}
        out: dict[str, Any] = {"installed": here, "latest": latest, "checked_at": time.time(),
                               "available": here["sha"] != latest["sha"], "changes": [], "ahead_by": None,
                               "needs_full_download": False, "releases_url": RELEASES_URL, "can_install": False}
        if not out["available"]:
            return out
        if here["sha"]:
            r = _get(c, f"{API}/compare/{here['sha']}...{latest['sha']}")
            if r.status_code == 200:
                cmp = r.json()
                if cmp.get("status") == "behind":
                    # This copy is newer than GitHub (unpushed work): nothing to install.
                    out["available"] = False
                    return out
                out["ahead_by"] = cmp.get("ahead_by")
                out["changes"] = [{"sha": x["sha"][:7], "message": x["commit"]["message"].splitlines()[0],
                                   "date": x["commit"]["committer"]["date"]} for x in cmp.get("commits", [])][-15:][::-1]
        if out["installed"]["mode"] == "bundle":
            # New libraries need a new .exe; the code alone would fail to start.
            raw = f"https://raw.githubusercontent.com/{REPO}/{latest['sha']}"
            r = _get(c, f"{raw}/{RUNTIME_FILE}")
            remote_runtime = int(r.json().get("runtime", 0)) if r.status_code == 200 else 0
            r = _get(c, f"{raw}/pyproject.toml")
            new_libs = set()
            if r.status_code == 200:
                here_py = PROJECT_ROOT / "pyproject.toml"
                have = _dependency_names(here_py.read_text(encoding="utf-8")) if here_py.exists() else set()
                new_libs = _dependency_names(r.text) - have
            out["needs_full_download"] = remote_runtime != here["runtime"] or bool(new_libs)
        out["can_install"] = out["installed"]["mode"] in ("bundle", "git") and not out["needs_full_download"]
    return out


def _safe_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise UpdateError(f"refusing to write outside the update folder: {rel}")
    return target


def _install_bundle(sha: str, date: str | None, log: Callable[[str], None]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    final = APP_DIR / sha
    if not (final / "src" / "mmrslave" / "__init__.py").exists():
        tmp_zip = APP_DIR / f"{sha}.zip"
        log("Downloading the new version from GitHub…")
        try:
            with httpx.stream("GET", f"https://codeload.github.com/{REPO}/zip/{sha}", headers=HEADERS,
                              timeout=60, follow_redirects=True) as r:
                if r.status_code != 200:
                    raise UpdateError(f"GitHub answered {r.status_code} for the download.")
                with open(tmp_zip, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
        except httpx.HTTPError as e:
            raise UpdateError(f"The download failed ({e.__class__.__name__}).") from e
        log("Unpacking…")
        partial = APP_DIR / f"{sha}.partial"
        shutil.rmtree(partial, ignore_errors=True)
        try:
            with zipfile.ZipFile(tmp_zip) as z:
                for info in z.infolist():
                    parts = PurePosixPath(info.filename).parts
                    if len(parts) < 2 or info.is_dir():
                        continue
                    rel = "/".join(parts[1:])  # drop GitHub's "<repo>-<sha>/" top folder
                    if not any(rel == p or rel.startswith(p) for p in UPDATE_PARTS) or "__pycache__" in rel:
                        continue
                    target = _safe_target(partial, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as e:
            raise UpdateError("The download was damaged. Try again.") from e
        finally:
            tmp_zip.unlink(missing_ok=True)
        if not (partial / "src" / "mmrslave" / "__init__.py").exists():
            shutil.rmtree(partial, ignore_errors=True)
            raise UpdateError("The download didn't contain the app's code.")
        (partial / VERSION_FILE).write_text(json.dumps({"sha": sha, "date": date}), encoding="utf-8")
        shutil.rmtree(final, ignore_errors=True)
        partial.rename(final)
    CURRENT_FILE.write_text(sha, encoding="utf-8")
    log("Installed. Restarting…")


def _install_git(log: Callable[[str], None]) -> None:
    before = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("This folder has changes that aren't committed; commit or stash them, then update.")
    log("Pulling from GitHub…")
    _git("pull", "--ff-only", "origin", BRANCH, timeout=180)
    after = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if after != before:
        log("Installing new libraries…")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(PROJECT_ROOT)],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise UpdateError("Pulled the new code, but installing its libraries failed: "
                              + (r.stderr or r.stdout).strip().splitlines()[-1])
    log("Installed. Restarting…")


def install(log: Callable[[str], None] = print) -> dict[str, Any]:
    """Download and install the newest version. The app must restart afterwards to use it."""
    info = check()
    if not info["available"]:
        log("Already up to date.")
        return info
    if info["needs_full_download"]:
        raise UpdateError("This update adds new libraries, so it needs the full download from the Releases page.")
    m = info["installed"]["mode"]
    if m == "bundle":
        _install_bundle(info["latest"]["sha"], info["latest"]["date"], log)
    elif m == "git":
        _install_git(log)
    else:
        raise UpdateError("This copy wasn't installed from GitHub, so it can't update itself.")
    info["installed_now"] = info["latest"]
    return info


def clean_old_versions(keep: int = 2) -> None:
    """Remove downloaded versions except the one running and the newest few."""
    if not APP_DIR.exists():
        return
    current = CURRENT_FILE.read_text(encoding="utf-8").strip() if CURRENT_FILE.exists() else ""
    running = PROJECT_ROOT.resolve()
    dirs = sorted((d for d in APP_DIR.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    kept = 0
    for d in dirs:
        if d.name == current or d.resolve() == running:
            continue
        if d.name.endswith(".partial") or kept >= keep - 1:
            shutil.rmtree(d, ignore_errors=True)
        else:
            kept += 1
