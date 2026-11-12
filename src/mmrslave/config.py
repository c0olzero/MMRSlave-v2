"""Settings loaded from mmrslave.toml, with API keys from environment variables.

Run from source, the settings file sits in the project folder. Run as the packaged MMRSlave.exe,
it sits in %LOCALAPPDATA%/MMRSlave, next to the downloaded games and code updates.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The folder that holds src/mmrslave and brain/: the project when run from source, or the
# bundled or updated copy of the code when run as MMRSlave.exe.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FROZEN = bool(getattr(sys, "frozen", False))
# Where the packaged app keeps settings, games and code updates (always writable).
APP_HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MMRSlave"
CONFIG_PATH = (APP_HOME if FROZEN else PROJECT_ROOT) / "mmrslave.toml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "mmrslave.example.toml"
# Trained networks and Immortal benchmarks published with the app, used when you haven't
# trained your own (see `mmrslave publish-brain`).
BRAIN_DIR = PROJECT_ROOT / "brain"
BRAIN_FILES = ("winprob.pt", "context.pt", "benchmarks.json", "benchmark_curves.json", "history.jsonl")

STEAM_ID64_BASE = 76561197960265728


@dataclass
class CollectSettings:
    min_immortal_players: int = 8
    min_avg_computed_mmr: float = 0.0
    min_duration_minutes: int = 20
    parse_workers: int = 16
    download_workers: int = 4
    api_delay_s: float = 1.1


@dataclass
class UpdateSettings:
    # Install new versions from GitHub by itself when the app starts.
    auto_update: bool = False


@dataclass
class Settings:
    steam_id: int = 0
    data_dir: Path = (APP_HOME / "data") if FROZEN else Path("D:/MMRSlaveData")
    local_replays: Path = Path("C:/Program Files (x86)/Steam/steamapps/common/dota 2 beta/game/dota/replays")
    # The game's `game/dota` folder, for the real minimap and hero icons. Found automatically when unset.
    dota_dir: Path | None = None
    collect: CollectSettings = field(default_factory=CollectSettings)
    coach_model: str = "claude-opus-5-5"
    updates: UpdateSettings = field(default_factory=UpdateSettings)

    @property
    def account_id(self) -> int:
        """32-bit account ID, as used by OpenDota and Dotabuff."""
        return self.steam_id - STEAM_ID64_BASE if self.steam_id else 0

    # Folders inside data_dir
    @property
    def matches_dir(self) -> Path:
        return self.data_dir / "matches"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.sqlite"

    def model_file(self, name: str) -> Path:
        """Your own trained file when you have one, otherwise the one published with the app."""
        own = self.models_dir / name
        if own.exists() or not (BRAIN_DIR / name).exists():
            return own
        return BRAIN_DIR / name

    def ensure_dirs(self) -> None:
        for d in (self.matches_dir, self.raw_dir, self.models_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)


def opendota_api_key() -> str | None:
    return os.environ.get("OPENDOTA_API_KEY") or None


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_PATH
    if not path.exists():
        path = EXAMPLE_CONFIG_PATH
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    s = Settings()
    s.steam_id = int(raw.get("player", {}).get("steam_id", 0) or 0)
    # The example's folders are the developer's; the packaged app uses its own until you set some.
    paths = {} if FROZEN and path == EXAMPLE_CONFIG_PATH else raw.get("paths", {})
    if "data_dir" in paths:
        s.data_dir = Path(paths["data_dir"])
    if "local_replays" in paths:
        s.local_replays = Path(paths["local_replays"])
    if paths.get("dota_dir"):
        s.dota_dir = Path(paths["dota_dir"])
    c = raw.get("collect", {})
    for name in CollectSettings.__dataclass_fields__:
        if name in c:
            setattr(s.collect, name, type(getattr(s.collect, name))(c[name]))
    s.coach_model = raw.get("coach", {}).get("model", s.coach_model)
    s.updates.auto_update = bool(raw.get("updates", {}).get("auto_update", False))
    return s


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "/").replace('"', '\\"') + '"'


def save_setting(section: str, key: str, value: object, path: Path | None = None) -> None:
    """Change one value in mmrslave.toml, keeping the rest of the file and its comments.
    The file is created from the example when it doesn't exist yet."""
    path = path or CONFIG_PATH
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8") if EXAMPLE_CONFIG_PATH.exists() else ""
        if FROZEN:
            # The example's paths are the developer's; the packaged app keeps data in APP_HOME.
            text = re.sub(r"(?m)^(data_dir|local_replays)\s*=.*\n?", "", text)
    line = f"{key} = {_toml_value(value)}"
    lines = text.splitlines()
    head = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if head is None:
        lines += ["", f"[{section}]", line]
    else:
        end = next((i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        at = next((i for i in range(head + 1, end) if re.match(rf"\s*{re.escape(key)}\s*=", lines[i])), None)
        if at is None:
            # after the section's last non-blank line
            at = end
            while at > head + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, line)
        else:
            lines[at] = line
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
