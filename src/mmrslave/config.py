"""Settings loaded from mmrslave.toml, with API keys from environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "mmrslave.toml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "mmrslave.example.toml"

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
class Settings:
    steam_id: int = 0
    data_dir: Path = Path("D:/MMRSlaveData")
    local_replays: Path = Path("C:/Program Files (x86)/Steam/steamapps/common/dota 2 beta/game/dota/replays")
    # The game's `game/dota` folder, for the real minimap and hero icons. Found automatically when unset.
    dota_dir: Path | None = None
    collect: CollectSettings = field(default_factory=CollectSettings)
    coach_model: str = "claude-opus-5-5"

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
    paths = raw.get("paths", {})
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
    return s
