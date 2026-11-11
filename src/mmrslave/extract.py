"""Convert a parsed replay into a compact match record.

A match record is two files in ``data_dir/matches``:

* ``<match_id>.npz``  per-second arrays (hero state, buildings, Roshan timer)
* ``<match_id>.json`` match info, players, and timestamped events

Every time is in game seconds (0 = the horn, negative = pre-game), pause-aware.
Player slots are 0-4 Radiant and 5-9 Dire. Team index 0 = Radiant, 1 = Dire.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 3       # 2: per-minute damage/assists, ward killers; 3: item inventory over time
TICKS_PER_SECOND = 30

HERO_FEATURES = (
    "x", "y", "alive", "hp", "max_hp", "mana", "max_mana", "level", "xp",
    "gold", "net_worth", "lh", "dn", "visible_to_enemy", "respawn_in", "kills", "deaths",
)
HF = {name: i for i, name in enumerate(HERO_FEATURES)}

LANES = ("top", "mid", "bot")
BUILDINGS = tuple(
    [f"tower{tier}_{lane}" for tier in (1, 2, 3) for lane in LANES]
    + ["tower4_a", "tower4_b"]
    + [f"{kind}_rax_{lane}" for lane in LANES for kind in ("melee", "range")]
)
BUILDING_INDEX = {name: i for i, name in enumerate(BUILDINGS)}

# Seconds a ward lives when nobody kills it.
WARD_LIFETIME_S = {"observer": 360, "sentry": 420}

# Lane role (1 safe, 2 mid, 3 off, 4 jungle/roam) each position normally plays.
_POSITION_LANE = {1: 1, 2: 2, 3: 3, 4: 3, 5: 1}


class ExtractError(Exception):
    """The replay can't be turned into a usable match record."""


@dataclass
class MatchRecord:
    """A parsed match, loaded back from disk."""

    meta: dict[str, Any]
    t: np.ndarray               # [T] game second of each row
    hero: np.ndarray            # [T, 10, len(HERO_FEATURES)]
    buildings: np.ndarray       # [T, 2, len(BUILDINGS)] 1 = standing
    rosh_since_kill: np.ndarray # [T] seconds since the last Roshan kill, -1 if none yet

    @property
    def match_id(self) -> int:
        return int(self.meta["match_id"])

    @property
    def events(self) -> dict[str, list[dict[str, Any]]]:
        return self.meta["events"]

    @property
    def players(self) -> list[dict[str, Any]]:
        return self.meta["players"]

    def row(self, game_second: float) -> int:
        """Index of the row at (or just before) a game second."""
        i = int(np.searchsorted(self.t, game_second, side="right")) - 1
        return max(0, min(i, len(self.t) - 1))

    def player_by_steam_id(self, steam_id: int) -> dict[str, Any] | None:
        return next((p for p in self.players if p["steam_id"] == steam_id), None)


# --------------------------------------------------------------------------- helpers

def _team_index(team: int | None) -> int | None:
    return {2: 0, 3: 1}.get(team) if team is not None else None


def _series(values: Any, n: int, fill: float = 0.0) -> np.ndarray:
    """A per-sample series as float64 with exactly n entries."""
    arr = np.asarray(values if values is not None else [], dtype=np.float64)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    if len(arr) >= n:
        return arr[:n]
    out = np.full(n, fill)
    out[: len(arr)] = arr
    if len(arr):
        out[len(arr):] = arr[-1]
    return out


def _building_slot(npc_name: str, taken: set[tuple[int, str]], team: int) -> str | None:
    """Map 'npc_dota_goodguys_tower1_bot' -> 'tower1_bot' (tower4s fill slots a then b)."""
    for prefix in ("npc_dota_goodguys_", "npc_dota_badguys_"):
        if npc_name.startswith(prefix):
            name = npc_name[len(prefix):]
            break
    else:
        return None
    if name == "tower4":
        for slot in ("tower4_a", "tower4_b"):
            if (team, slot) not in taken:
                return slot
        return None
    return name if name in BUILDING_INDEX else None


def estimate_positions(players: list[dict[str, Any]]) -> dict[int, int]:
    """Guess position 1-5 for each player on one team from lane and net worth.

    Picks the assignment that best matches each position's usual lane and
    net-worth rank (pos 1 richest ... pos 5 poorest).
    """
    by_nw = sorted(players, key=lambda p: -p["net_worth"])
    nw_rank = {p["player_id"]: i + 1 for i, p in enumerate(by_nw)}
    best: tuple[float, tuple[int, ...]] | None = None
    for perm in itertools.permutations(range(1, 6)):
        cost = 0.0
        for p, pos in zip(players, perm):
            lane = p.get("lane_role") or 0
            if lane != _POSITION_LANE[pos]:
                cost += 0.5 if (lane == 4 and pos in (4, 5)) else 1.0
            cost += 0.6 * abs(nw_rank[p["player_id"]] - pos)
        if best is None or cost < best[0]:
            best = (cost, perm)
    assert best is not None
    return {p["player_id"]: pos for p, pos in zip(players, best[1])}


# --------------------------------------------------------------------------- extraction

def parse_replay(path: str | Path) -> tuple[Any, list[Any]]:
    """Parse a replay with gem, also keeping the once-a-second player snapshots gem reads along
    the way (they hold each hero's inventory, which the finished ParsedMatch drops)."""
    import gem
    from gem.extractors import players as gem_players

    made: list[Any] = []
    original = gem_players.PlayerExtractor.__init__

    def keep(self: Any, *a: Any, **k: Any) -> None:
        original(self, *a, **k)
        made.append(self)

    gem_players.PlayerExtractor.__init__ = keep
    try:
        match = gem.parse(str(path))
    finally:
        gem_players.PlayerExtractor.__init__ = original
    return match, (list(made[0].snapshots) if made else [])


# Inventory slots in gem's snapshots: 0-5 main, 6-8 backpack, 15 teleport, 16 neutral item.
MAIN_SLOTS, BACKPACK_SLOTS, NEUTRAL_SLOT = range(6), range(6, 9), 16


def _item_timeline(snapshots: list[Any], gt: Any) -> list[dict[str, Any]]:
    """Each hero's items, one entry per change: {t, pid, main[6], backpack[3], neutral}.
    Empty slots are ""."""
    out: list[dict[str, Any]] = []
    last: dict[int, tuple] = {}
    for sn in sorted(snapshots, key=lambda x: x.tick):
        pid = sn.player_id
        if not 0 <= pid < 10:
            continue
        name = lambda k: (sn.items.get(k) or "").removeprefix("item_")  # noqa: E731
        main = [name(k) for k in MAIN_SLOTS]
        bp = [name(k) for k in BACKPACK_SLOTS]
        key = (*main, *bp, name(NEUTRAL_SLOT))
        if last.get(pid) == key:
            continue
        last[pid] = key
        out.append({"t": round(gt(sn.tick)), "pid": pid, "main": main, "backpack": bp, "neutral": key[-1]})
    return out


def extract(match: Any, *, source: str, extra_meta: dict[str, Any] | None = None,
            snapshots: list[Any] | None = None) -> MatchRecord:
    """Build a MatchRecord from a gem ``ParsedMatch`` (plus, from ``parse_replay``, gem's player
    snapshots for the item timeline)."""
    import gem

    players = sorted(match.players, key=lambda p: p.player_id)
    if len(players) != 10 or [p.player_id for p in players] != list(range(10)):
        raise ExtractError(f"expected 10 players in slots 0-9, got {[p.player_id for p in players]}")
    if match.parse_error:
        # Truncated replays still work if most of the game is there.
        if not players[0].times or len(players[0].times) < 600:
            raise ExtractError(f"replay too short or corrupt: {match.parse_error}")

    start_tick = match.game_start_tick or 0
    clock = match.game_clock

    def gt(tick: int) -> float:
        v = clock.game_time_at(tick) if clock is not None else None
        return float(v) if v is not None else (tick - start_tick) / TICKS_PER_SECOND

    # ---- uniform one-row-per-game-second grid
    ticks = np.asarray(players[0].times, dtype=np.int64)
    if len(ticks) < 60:
        raise ExtractError("too few samples in replay")
    sample_gt = np.array([gt(int(tk)) for tk in ticks])
    sample_gt = np.maximum.accumulate(sample_gt)  # guard against tiny clock jitter
    grid = np.arange(int(np.ceil(sample_gt[0])), int(np.floor(sample_gt[-1])) + 1, dtype=np.int64)
    pick = np.clip(np.searchsorted(sample_gt, grid, side="right") - 1, 0, len(ticks) - 1)
    T = len(grid)
    n = len(ticks)

    def second_index(game_s: float) -> int:
        """First grid row at or after a game time."""
        return int(np.clip(np.ceil(game_s) - grid[0], 0, T))

    hero = np.zeros((T, 10, len(HERO_FEATURES)), dtype=np.float32)
    xp_levels = np.asarray(json.loads((Path(gem.__file__).parent / "data" / "xp_level.json").read_text()))

    for p in players:
        i = p.player_id
        pos = np.asarray([(x, y) for _, x, y in p.position_log] or [(0.0, 0.0)], dtype=np.float64)
        if len(pos) != n:
            # Position samples are normally aligned with p.times; resample by tick if not.
            pt = np.asarray([tk for tk, _, _ in p.position_log], dtype=np.int64)
            j = np.clip(np.searchsorted(pt, ticks, side="right") - 1, 0, len(pt) - 1)
            pos = pos[j]
        hp = _series(p.hp_t, n)
        hero[:, i, HF["x"]] = pos[pick, 0]
        hero[:, i, HF["y"]] = pos[pick, 1]
        hero[:, i, HF["hp"]] = hp[pick]
        hero[:, i, HF["alive"]] = (hp[pick] > 0).astype(np.float32)
        hero[:, i, HF["max_hp"]] = _series(p.max_hp_t, n)[pick]
        hero[:, i, HF["mana"]] = _series(p.mana_t, n)[pick]
        hero[:, i, HF["max_mana"]] = _series(p.max_mana_t, n)[pick]
        xp = _series(p.xp_t, n)[pick]
        hero[:, i, HF["xp"]] = xp
        hero[:, i, HF["level"]] = np.clip(np.searchsorted(xp_levels, xp, side="right"), 1, 30)
        hero[:, i, HF["gold"]] = _series(p.gold_t, n)[pick]
        hero[:, i, HF["net_worth"]] = _series(p.net_worth_t, n)[pick]
        hero[:, i, HF["lh"]] = _series(p.lh_t, n)[pick]
        hero[:, i, HF["dn"]] = _series(p.dn_t, n)[pick]

        # Seconds until respawn while dead (scan backwards from each next alive row).
        alive = hero[:, i, HF["alive"]]
        respawn = np.zeros(T, dtype=np.float32)
        nxt = None
        for r in range(T - 1, -1, -1):
            if alive[r] > 0:
                nxt = r
            elif nxt is not None:
                respawn[r] = nxt - r
            else:
                respawn[r] = 0  # dead at the very end of the replay
        hero[:, i, HF["respawn_in"]] = respawn

    # ---- visibility to the enemy team (1 seen, 0 hidden, -1 unknown/older replays)
    vis_code = {"visible": 1.0, "hidden": 0.0}
    hero[:, :, HF["visible_to_enemy"]] = -1.0
    by_player: dict[int, list[tuple[float, float]]] = {}
    for e in match.hero_visibility_events:
        if e.player_id is None or not 0 <= e.player_id <= 9:
            continue
        enemy_state = e.dire_state if e.player_id < 5 else e.radiant_state
        by_player.setdefault(e.player_id, []).append((gt(e.tick), vis_code.get(str(enemy_state), -1.0)))
    for pid, evs in by_player.items():
        evs.sort(key=lambda x: x[0])
        et = np.array([x[0] for x in evs])
        ev = np.array([x[1] for x in evs], dtype=np.float32)
        j = np.searchsorted(et, grid, side="right") - 1
        hero[:, pid, HF["visible_to_enemy"]] = np.where(j >= 0, ev[np.clip(j, 0, None)], -1.0)

    # ---- events
    hero_pid = {p.hero_name: p.player_id for p in players}

    def pid_of(*names: str) -> int | None:
        for nm in names:
            if nm in hero_pid:
                return hero_pid[nm]
        return None

    def at_xy(pid: int, game_s: float) -> tuple[float, float]:
        r = max(0, min(second_index(game_s) - 1, T - 1))
        return float(hero[r, pid, HF["x"]]), float(hero[r, pid, HF["y"]])

    deaths = []
    for e in match.combat_log:
        if e.log_type.name != "DEATH" or not e.target_is_hero or e.target_is_illusion:
            continue
        victim = hero_pid.get(e.target_name)
        if victim is None:
            continue
        s = gt(e.tick)
        x, y = at_xy(victim, s)
        deaths.append({
            "t": round(s, 2),
            "victim": victim,
            "killer": pid_of(e.attacker_name, e.damage_source_name),
            "killer_name": e.attacker_name or e.damage_source_name,
            "inflictor": e.inflictor_name or None,
            "reincarnated": bool(getattr(e, "will_reincarnate", False)),
            "x": round(x, 1),
            "y": round(y, 1),
        })
    deaths.sort(key=lambda d: d["t"])

    # Cumulative kills/deaths per second (reincarnations don't count).
    for d in deaths:
        if d["reincarnated"]:
            continue
        r = min(second_index(d["t"]), T - 1)  # deaths in the final fraction of a second still count
        hero[r:, d["victim"], HF["deaths"]] += 1
        k = d["killer"]
        if k is not None and (k < 5) != (d["victim"] < 5):
            hero[r:, k, HF["kills"]] += 1

    purchases = []
    for p in players:
        for e in p.purchase_log:
            item = (e.value_name or "").removeprefix("item_")
            if item:
                purchases.append({"t": round(gt(e.tick), 2), "pid": p.player_id, "item": item})
    purchases.sort(key=lambda x: x["t"])

    wards = []
    for w in match.wards:
        s = gt(w.tick)
        if w.killed_tick is not None:
            end = gt(w.killed_tick)
        elif w.expires_tick is not None:
            end = gt(w.expires_tick)
        else:
            end = s + WARD_LIFETIME_S.get(w.ward_type, 360)
        wards.append({
            "t": round(s, 2), "end": round(end, 2), "pid": w.player_id,
            "team": _team_index(w.team), "type": w.ward_type,
            "x": round(w.x, 1), "y": round(w.y, 1),
            "dewarded": w.killed_tick is not None and (w.killer or "") not in ("", w.placer),
            "killer_pid": hero_pid.get(w.killer) if w.killed_tick is not None else None,
        })

    smokes = [{
        "t": round(gt(sm.tick), 2), "team": _team_index(sm.team),
        "pids": sorted({hero_pid[h] for h in sm.smoked if h in hero_pid}),
        "x": None if sm.x is None else round(sm.x, 1),
        "y": None if sm.y is None else round(sm.y, 1),
    } for sm in match.smoke_events]

    fights = []
    for f in match.fights:
        fights.append({
            "start": round(gt(f.start_tick), 2), "end": round(gt(f.end_tick), 2),
            "radiant_kills": f.radiant_kills, "dire_kills": f.dire_kills, "winner": f.winner,
            "x": None if f.centroid_x is None else round(f.centroid_x, 1),
            "y": None if f.centroid_y is None else round(f.centroid_y, 1),
            "players": [{
                "pid": fp.player_id,
                "deaths": getattr(fp, "deaths", 0),
                "damage_dealt": getattr(fp, "damage_dealt", 0),
                "damage_taken": getattr(fp, "damage_taken", 0),
                "healing": getattr(fp, "healing", 0),
                "gold_delta": getattr(fp, "gold_delta", 0),
            } for fp in f.players],
        })

    # Buildings standing per second, plus the kill events.
    buildings = np.ones((T, 2, len(BUILDINGS)), dtype=np.uint8)
    building_events = []
    taken: set[tuple[int, str]] = set()
    kills = [(k.tick, k.team, k.tower_name, k.killer, getattr(k, "killer_team", None)) for k in match.towers]
    kills += [(k.tick, k.team, k.barracks_name, k.killer, getattr(k, "killer_team", None)) for k in match.barracks]
    for tick, team, name, killer, killer_team in sorted(kills):
        ti = _team_index(team)
        if ti is None:
            continue
        slot = _building_slot(name, taken, ti)
        s = gt(tick)
        if slot is not None:
            taken.add((ti, slot))
            buildings[min(second_index(s), T - 1):, ti, BUILDING_INDEX[slot]] = 0
        building_events.append({
            "t": round(s, 2), "team": ti, "name": slot or name, "killer": killer,
            "killer_pid": hero_pid.get(killer), "denied": _team_index(killer_team) == ti,
        })

    roshans = [{
        "t": round(gt(r.tick), 2), "team": _team_index(r.killer_team),
        "killer_pid": hero_pid.get(r.killer), "kill_number": r.kill_number, "drops": list(r.drops),
    } for r in match.roshans]
    rosh_since = np.full(T, -1.0, dtype=np.float32)
    for r in roshans:
        i0 = second_index(r["t"])
        rosh_since[i0:] = grid[i0:] - r["t"]

    aegis = [{"t": round(gt(a.tick), 2), "pid": a.player_id, "type": a.event_type} for a in match.aegis_events]
    tormentors = [{"t": round(gt(k.tick), 2), "team": _team_index(k.killer_team), "pid": k.killer_player_id}
                  for k in match.tormentors]
    buybacks = [{"t": round(gt(e.tick), 2), "pid": p.player_id} for p in players for e in p.buyback_log]
    runes = [{
        "t": round(gt(r.end_tick if r.end_tick is not None else r.spawn_tick), 2),
        "pid": r.player_id, "rune_type": r.rune_type, "outcome": r.outcome,
        "x": round(r.x, 1), "y": round(r.y, 1),
    } for r in match.runes]

    # ---- players
    pinfo = []
    for p in players:
        pinfo.append({
            "player_id": p.player_id,
            "steam_id": int(p.steam_id or 0),
            "account_id": int(p.account_id or 0),
            "name": p.player_name,
            "hero_id": p.hero_id,
            "hero": p.hero_name,
            "hero_display": gem.constants.hero_display(p.hero_name),
            "team": 0 if p.is_radiant else 1,
            "lane_role": p.lane_role,
            "kills": p.kills, "deaths": p.deaths, "assists": p.assists,
            "last_hits": p.last_hits, "denies": p.denies,
            "gpm": p.gold_per_min, "xpm": p.xp_per_min,
            "net_worth": p.net_worth, "level": p.level,
            "hero_damage": p.hero_damage, "tower_damage": p.tower_damage, "hero_healing": p.hero_healing,
            "obs_placed": p.obs_placed, "sen_placed": p.sen_placed,
            "camps_stacked": p.camps_stacked, "stuns": round(float(p.stuns_dealt or 0), 1),
            "teamfight_participation": round(float(p.teamfight_participation or 0), 3),
            "lane_efficiency_pct": p.lane_efficiency_pct,
            "is_roaming": bool(p.is_roaming),
            # gem gives {slot: name} (older versions a list); keep the main six and the neutral item.
            "final_items": [str(i).removeprefix("item_") for i in (
                [v for k, v in sorted(p.final_items.items()) if int(k) in (*MAIN_SLOTS, NEUTRAL_SLOT)]
                if isinstance(p.final_items, dict) else (p.final_items or [])) if i],
            "abilities": dict(p.ability_uses or {}),
            "items_used": dict(p.item_uses or {}),
        })
    for team in (0, 1):
        positions = estimate_positions([p for p in pinfo if p["team"] == team])
        for p in pinfo:
            if p["player_id"] in positions:
                p["position"] = positions[p["player_id"]]

    minute = _minute_series(match, players, hero_pid, gt, int(grid[-1]))

    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gem_version": getattr(gem, "__version__", None) or _gem_version(),
        "source": source,
        "parsed_at": int(time.time()),
        "match_id": int(match.match_id),
        "game_mode": match.game_mode,
        "leagueid": match.leagueid,
        "radiant_win": bool(match.radiant_win) if match.radiant_win is not None else None,
        "duration_s": int(grid[-1]),
        "radiant_score": match.radiant_score,
        "dire_score": match.dire_score,
        "truncated": bool(match.parse_error),
        "has_visibility": bool(by_player),
        "players": pinfo,
        "events": {
            "deaths": deaths, "purchases": purchases, "wards": wards, "smokes": smokes,
            "fights": fights, "buildings": building_events, "roshans": roshans, "aegis": aegis,
            "tormentors": tormentors, "buybacks": buybacks, "runes": runes,
            "items": _item_timeline(snapshots or [], gt),
        },
        "minute": minute,
    }
    if extra_meta:
        meta.update(extra_meta)
    return MatchRecord(meta=meta, t=grid.astype(np.float32), hero=hero,
                       buildings=buildings, rosh_since_kill=rosh_since)


ASSIST_WINDOW_S = 20.0


def _minute_series(match: Any, players: list[Any], hero_pid: dict[str, int], gt: Any,
                   duration_s: int) -> dict[str, Any]:
    """Cumulative hero damage, building damage and assists at each minute (0:00, 1:00, ...).

    Hero and building damage add up exactly to the scoreboard. The replay doesn't say when an
    assist happened, so assists are rebuilt from the combat log (enemy heroes who hurt or
    debuffed the victim in the 20 s before a kill) and scaled to end on the scoreboard count.
    """
    minutes = list(range(0, duration_s // 60 + 1))
    n = len(minutes)

    def source_pid(e: Any) -> int | None:
        for name in (e.damage_source_name, e.attacker_name):
            if name in hero_pid:
                return hero_pid[name]
        return None

    building = [[0.0] * n for _ in range(10)]
    assists = [[0.0] * n for _ in range(10)]
    touched: dict[int, list[tuple[float, int]]] = {pid: [] for pid in range(10)}

    def add(series: list[list[float]], pid: int, t: float, value: float) -> None:
        m = max(0, int(np.ceil(t / 60)))           # counts from the next minute mark on
        if m < n:
            series[pid][m] += value

    for e in match.combat_log:
        kind = e.log_type.name
        if kind not in ("DAMAGE", "MODIFIER_ADD", "DEATH"):
            continue
        target = e.target_name or ""
        if kind == "DEATH":
            if target not in hero_pid or e.target_is_illusion or getattr(e, "will_reincarnate", False):
                continue
            v, t = hero_pid[target], gt(e.tick)
            killer = source_pid(e)
            helpers = {p for tt, p in touched[v] if t - ASSIST_WINDOW_S <= tt <= t} - {killer}
            for p in helpers:
                add(assists, p, t, 1.0)
            continue
        src = source_pid(e)
        if src is None:
            continue
        if target in hero_pid:
            v = hero_pid[target]
            if not e.target_is_illusion and (v < 5) != (src < 5):
                touched[v].append((gt(e.tick), src))
        elif kind == "DAMAGE" and target.startswith(("npc_dota_goodguys_", "npc_dota_badguys_"))                 and "creep" not in target and "siege" not in target:
            if target.startswith("npc_dota_goodguys_") != (src < 5):        # enemy buildings only
                add(building, src, gt(e.tick), float(e.value or 0))

    def cumulative(rows: list[list[float]]) -> list[list[float]]:
        return [np.cumsum(r).round(1).tolist() for r in rows]

    building, assists = cumulative(building), cumulative(assists)
    for p in players:
        final = assists[p.player_id][-1] if n else 0
        if final > 0 and p.assists:
            scale = p.assists / final
            assists[p.player_id] = [round(a * scale, 2) for a in assists[p.player_id]]

    hero_damage = []
    for p in players:
        times = list(getattr(p, "game_times_min", None) or [])
        vals = list(getattr(p, "total_hero_damage_t_min", None) or [])
        by_min = {int(round(t / 60)): v for t, v in zip(times, vals)}
        row, last = [], 0.0
        for m in minutes:
            last = float(by_min.get(m, last))
            row.append(last)
        hero_damage.append(row)
    return {"t": [m * 60 for m in minutes], "hero_damage": hero_damage,
            "building_damage": building, "assists": assists}


def _gem_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("gem-dota")
    except Exception:
        return None


# --------------------------------------------------------------------------- disk I/O

def record_paths(matches_dir: Path, match_id: int) -> tuple[Path, Path]:
    return matches_dir / f"{match_id}.npz", matches_dir / f"{match_id}.json"


def save_record(rec: MatchRecord, matches_dir: Path) -> Path:
    matches_dir.mkdir(parents=True, exist_ok=True)
    npz_path, json_path = record_paths(matches_dir, rec.match_id)
    tmp_npz = npz_path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp_npz, t=rec.t, hero=rec.hero, buildings=rec.buildings,
                        rosh_since_kill=rec.rosh_since_kill)
    tmp_json = json_path.with_suffix(".tmp.json")
    tmp_json.write_text(json.dumps(rec.meta, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_npz, npz_path)
    os.replace(tmp_json, json_path)  # json last: its presence marks a complete record
    return json_path


def load_record(matches_dir: Path, match_id: int) -> MatchRecord:
    npz_path, json_path = record_paths(matches_dir, match_id)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    with np.load(npz_path) as z:
        return MatchRecord(meta=meta, t=z["t"], hero=z["hero"], buildings=z["buildings"],
                           rosh_since_kill=z["rosh_since_kill"])


def load_meta(matches_dir: Path, match_id: int) -> dict[str, Any]:
    return json.loads(record_paths(matches_dir, match_id)[1].read_text(encoding="utf-8"))
