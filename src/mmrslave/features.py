"""Turn a match record into normalized arrays for the neural networks.

Everything is sampled every STEP_S game seconds. Per sampled row we keep:

hero    [R, 10, NH]  normalized hero state (see HERO_COLS)
glob    [R, NG]      game time, buildings, Roshan, wards (see GLOBAL_COLS)
labels  radiant_win, dies_soon [R, 10], future_cell [R, 10]

The "perspective" helpers then build what one team could actually know at that
moment: allies exactly, enemies only where last seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mmrslave.extract import BUILDINGS, HF, MatchRecord, load_record

FEATURE_VERSION = 1
STEP_S = 3
DEATH_HORIZON_S = 15
MOVE_HORIZON_S = 30

# Point the map is (nearly) symmetric around: midpoint of the two fountains.
MAP_CX, MAP_CY = 16360.0, 16339.0
MAP_SCALE = 9000.0
GRID = 24
# Movement grid, centred on the symmetry point so mirroring a cell is exact.
GRID_HALF = 9250.0
GRID_SIZE = 2 * GRID_HALF / GRID     # ~770 world units per cell

HERO_COLS = (
    "x", "y", "alive", "hp_frac", "max_hp", "mana_frac", "max_mana", "level", "net_worth", "gold",
    "lh", "dn", "respawn", "kills", "deaths", "vis_seen", "vis_hidden", "vis_unknown", "aegis",
    "seen_x", "seen_y", "since_seen",
)
HC = {n: i for i, n in enumerate(HERO_COLS)}
NH = len(HERO_COLS)
NB = len(BUILDINGS)
GLOBAL_COLS = (
    ("time", "night", "rosh_since", "rosh_up")
    + tuple(f"r_{b}" for b in BUILDINGS) + tuple(f"d_{b}" for b in BUILDINGS)
    + ("r_obs", "r_sen", "d_obs", "d_sen")
)
GC = {n: i for i, n in enumerate(GLOBAL_COLS)}
NG = len(GLOBAL_COLS)
HERO_ID_VOCAB = 160


@dataclass
class MatchArrays:
    match_id: int
    t: np.ndarray            # [R] game seconds
    hero: np.ndarray         # [R, 10, NH] float32
    glob: np.ndarray         # [R, NG] float32
    hero_ids: np.ndarray     # [10] int64
    positions: np.ndarray    # [10] int64, 1-5 (0 unknown)
    radiant_win: float
    dies_soon: np.ndarray    # [R, 10] float32 (1 = real death within DEATH_HORIZON_S)
    future_cell: np.ndarray  # [R, 10] int64, grid cell MOVE_HORIZON_S later, -1 if dead/unknown
    has_visibility: bool


def world_to_cell(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    gx = np.clip(np.floor((np.asarray(x) - (MAP_CX - GRID_HALF)) / GRID_SIZE).astype(np.int64), 0, GRID - 1)
    gy = np.clip(np.floor((np.asarray(y) - (MAP_CY - GRID_HALF)) / GRID_SIZE).astype(np.int64), 0, GRID - 1)
    return gy * GRID + gx


def cell_center(cell: np.ndarray | int) -> tuple[np.ndarray, np.ndarray]:
    cell = np.asarray(cell)
    return (MAP_CX - GRID_HALF + (cell % GRID + 0.5) * GRID_SIZE,
            MAP_CY - GRID_HALF + (cell // GRID + 0.5) * GRID_SIZE)


def mirror_cell(cell: np.ndarray) -> np.ndarray:
    """Cell index after reflecting the map through its centre (Radiant <-> Dire view)."""
    return (GRID * GRID - 1) - np.asarray(cell)


def _active_counts(events: list[dict[str, Any]], t: np.ndarray, team: int, kind: str) -> np.ndarray:
    out = np.zeros(len(t), dtype=np.float32)
    for w in events:
        if w["team"] == team and w["type"] == kind:
            out += (t >= w["t"]) & (t < w["end"])
    return out


def build_arrays(rec: MatchRecord, step: int = STEP_S, start_s: int = -60) -> MatchArrays:
    """Sample a match every `step` seconds and normalize it."""
    full_t = rec.t
    rows = np.nonzero((full_t >= start_s) & ((full_t - full_t[0]) % step == 0))[0]
    if len(rows) == 0:
        rows = np.arange(len(full_t))
    t = full_t[rows]
    h = rec.hero[rows]                                  # [R, 10, F]
    R = len(rows)

    out = np.zeros((R, 10, NH), dtype=np.float32)
    out[..., HC["x"]] = (h[..., HF["x"]] - MAP_CX) / MAP_SCALE
    out[..., HC["y"]] = (h[..., HF["y"]] - MAP_CY) / MAP_SCALE
    out[..., HC["alive"]] = h[..., HF["alive"]]
    out[..., HC["hp_frac"]] = h[..., HF["hp"]] / np.maximum(h[..., HF["max_hp"]], 1)
    out[..., HC["max_hp"]] = h[..., HF["max_hp"]] / 4000
    out[..., HC["mana_frac"]] = h[..., HF["mana"]] / np.maximum(h[..., HF["max_mana"]], 1)
    out[..., HC["max_mana"]] = h[..., HF["max_mana"]] / 3000
    out[..., HC["level"]] = h[..., HF["level"]] / 30
    out[..., HC["net_worth"]] = np.log1p(np.maximum(h[..., HF["net_worth"]], 0)) / 11
    out[..., HC["gold"]] = np.log1p(np.maximum(h[..., HF["gold"]], 0)) / 9
    out[..., HC["lh"]] = h[..., HF["lh"]] / 400
    out[..., HC["dn"]] = h[..., HF["dn"]] / 40
    out[..., HC["respawn"]] = np.minimum(h[..., HF["respawn_in"]], 120) / 90
    out[..., HC["kills"]] = h[..., HF["kills"]] / 20
    out[..., HC["deaths"]] = h[..., HF["deaths"]] / 20
    vis = h[..., HF["visible_to_enemy"]]
    out[..., HC["vis_seen"]] = vis == 1
    out[..., HC["vis_hidden"]] = vis == 0
    out[..., HC["vis_unknown"]] = vis < 0

    ev = rec.events
    # Aegis: held from pickup until it's used (reincarnation) or 5 minutes pass.
    for a in ev.get("aegis", []):
        if a["type"] not in ("pickup", "stolen") or not 0 <= a["pid"] <= 9:
            continue
        end = a["t"] + 300
        for d in ev["deaths"]:
            if d["victim"] == a["pid"] and a["t"] < d["t"] < end:
                end = d["t"]
                break
        out[(t >= a["t"]) & (t < end), a["pid"], HC["aegis"]] = 1

    # Last place each hero was seen by the enemy team, and for how long it's been missing.
    full_vis = rec.hero[:, :, HF["visible_to_enemy"]]
    for j in range(10):
        seen = full_vis[:, j] != 0          # unknown counts as seen: older replays have no visibility
        idx = np.where(seen, np.arange(len(full_t)), -1)
        last = np.maximum.accumulate(idx)[rows]
        known = last >= 0
        li = np.maximum(last, 0)
        out[:, j, HC["seen_x"]] = np.where(known, (rec.hero[li, j, HF["x"]] - MAP_CX) / MAP_SCALE, 0)
        out[:, j, HC["seen_y"]] = np.where(known, (rec.hero[li, j, HF["y"]] - MAP_CY) / MAP_SCALE, 0)
        out[:, j, HC["since_seen"]] = np.where(known, np.minimum(full_t[rows] - full_t[li], 180) / 60, 3)

    g = np.zeros((R, NG), dtype=np.float32)
    g[:, GC["time"]] = t / 3600
    g[:, GC["night"]] = (np.maximum(t, 0) % 600) >= 300
    rs = rec.rosh_since_kill[rows]
    g[:, GC["rosh_since"]] = np.where(rs < 0, 0, np.minimum(rs, 720) / 720)
    g[:, GC["rosh_up"]] = (rs < 0) | (rs >= 480)
    b = rec.buildings[rows].astype(np.float32)
    g[:, GC[f"r_{BUILDINGS[0]}"]:GC[f"r_{BUILDINGS[0]}"] + NB] = b[:, 0]
    g[:, GC[f"d_{BUILDINGS[0]}"]:GC[f"d_{BUILDINGS[0]}"] + NB] = b[:, 1]
    for team, prefix in ((0, "r"), (1, "d")):
        g[:, GC[f"{prefix}_obs"]] = _active_counts(ev["wards"], t, team, "observer") / 8
        g[:, GC[f"{prefix}_sen"]] = _active_counts(ev["wards"], t, team, "sentry") / 8

    # ---- labels
    dies = np.zeros((R, 10), dtype=np.float32)
    for d in ev["deaths"]:
        if d["reincarnated"]:
            continue
        dies[(t <= d["t"]) & (t > d["t"] - DEATH_HORIZON_S), d["victim"]] = 1

    fut_rows = np.clip(np.searchsorted(full_t, t + MOVE_HORIZON_S), 0, len(full_t) - 1)
    fx, fy = rec.hero[fut_rows, :, HF["x"]], rec.hero[fut_rows, :, HF["y"]]
    cell = world_to_cell(fx, fy)
    valid = (rec.hero[fut_rows, :, HF["alive"]] > 0) & (h[..., HF["alive"]] > 0) \
        & (full_t[fut_rows] >= (t + MOVE_HORIZON_S - 1))[:, None]
    future_cell = np.where(valid, cell, -1)

    return MatchArrays(
        match_id=rec.match_id, t=t.astype(np.float32), hero=out, glob=g,
        hero_ids=np.array([p["hero_id"] for p in rec.players], dtype=np.int64).clip(0, HERO_ID_VOCAB - 1),
        positions=np.array([p.get("position", 0) for p in rec.players], dtype=np.int64),
        radiant_win=float(bool(rec.meta["radiant_win"])), dies_soon=dies, future_cell=future_cell,
        has_visibility=bool(rec.meta.get("has_visibility")),
    )


# --------------------------------------------------------------------------- cache

def cache_path(cache_dir: Path, match_id: int) -> Path:
    return cache_dir / f"{match_id}.v{FEATURE_VERSION}.npz"


def build_and_cache(matches_dir: Path, cache_dir: Path, match_id: int) -> Path | None:
    path = cache_path(cache_dir, match_id)
    if path.exists():
        return path
    try:
        rec = load_record(matches_dir, match_id)
        if rec.meta.get("radiant_win") is None:
            return None
        a = build_arrays(rec)
    except Exception:  # noqa: BLE001 - a bad record shouldn't stop a training run
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, t=a.t, hero=a.hero.astype(np.float16), glob=a.glob.astype(np.float16),
             hero_ids=a.hero_ids, positions=a.positions, radiant_win=np.float32(a.radiant_win),
             dies_soon=a.dies_soon.astype(np.uint8), future_cell=a.future_cell.astype(np.int16),
             has_visibility=np.bool_(a.has_visibility))
    tmp.replace(path)
    return path


def load_cached(path: Path) -> MatchArrays:
    with np.load(path) as z:
        return MatchArrays(
            match_id=int(path.name.split(".")[0]), t=z["t"], hero=z["hero"].astype(np.float32),
            glob=z["glob"].astype(np.float32), hero_ids=z["hero_ids"], positions=z["positions"],
            radiant_win=float(z["radiant_win"]), dies_soon=z["dies_soon"].astype(np.float32),
            future_cell=z["future_cell"].astype(np.int64), has_visibility=bool(z["has_visibility"]),
        )
