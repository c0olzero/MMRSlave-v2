"""Review one match from the player's side: what they did and what they could have done.

Produces a JSON-ready dict with the win-chance curve, every death examined, the decisions
the player could have made differently (fights they missed, advantages not used, runes),
comparisons with high-Immortal players, and a ranked list of findings about the player.
The coach turns this into a written report.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch

from mmrslave.benchmarks import KEY_ITEMS, Benchmarks, first_item_times, player_stats
from mmrslave.config import Settings
from mmrslave.decisions import find_decisions
from mmrslave.extract import HF, MatchRecord, load_record
from mmrslave.features import GRID, HC, MatchArrays, build_arrays, cell_center, world_to_cell
from mmrslave.models import HeroContextNet, WinProbNet
from mmrslave.regions import describe

ANALYSIS_VERSION = 4   # 2: decisions, findings about the player only; 3: final items fixed; 4: Vietnamese decision texts
NEAR = 1500.0          # "nearby" radius in world units (a bit more than most spell ranges)
WARD_SIGHT = 1600.0    # observer ward vision radius
HIGH_RISK = 0.30       # death-risk level we call dangerous


def _name(npc: str | None) -> str:
    if not npc:
        return "unknown"
    try:
        import gem
        if npc.startswith("npc_dota_hero_"):
            return gem.constants.hero_display(npc)
    except Exception:  # noqa: BLE001
        pass
    for prefix in ("npc_dota_", "item_"):
        npc = npc.removeprefix(prefix)
    if "tower" in npc:
        return "a tower"
    if "creep" in npc and "neutral" not in npc:
        return "lane creeps"
    if "neutral" in npc or npc.startswith(("dark_troll", "satyr", "centaur", "ogre", "wolf", "harpy")):
        return "neutral creeps"
    if "roshan" in npc:
        return "Roshan"
    return npc.replace("_", " ").title()


def _ability(name: str | None) -> str | None:
    if not name or name == "null":
        return None
    try:
        import gem
        if name.startswith("item_"):
            return gem.catalog.items.item_display(name.removeprefix("item_"))
    except Exception:  # noqa: BLE001
        pass
    return name.split("_", 2)[-1].replace("_", " ").title() if "_" in name else name


def _clock(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(int(round(t)))
    return f"{sign}{t // 60}:{t % 60:02d}"


# --------------------------------------------------------------------------- model inference

class Models:
    def __init__(self, winprob: WinProbNet | None, context: HeroContextNet | None, device: str):
        self.winprob, self.context, self.device = winprob, context, device

    @classmethod
    def load(cls, s: Settings) -> "Models":
        from mmrslave.train import load_models
        device = "cuda" if torch.cuda.is_available() else "cpu"
        wp, ctx = load_models(s, device)
        return cls(wp, ctx, device)

    def _tensors(self, a: MatchArrays, rows: np.ndarray | None = None, hero: np.ndarray | None = None):
        rows = np.arange(len(a.t)) if rows is None else rows
        h = torch.from_numpy(hero if hero is not None else a.hero[rows]).float().to(self.device)
        g = torch.from_numpy(a.glob[rows]).float().to(self.device)
        n = len(rows)
        ids = torch.from_numpy(a.hero_ids).to(self.device).expand(n, 10)
        pos = torch.from_numpy(a.positions).to(self.device).expand(n, 10)
        return h, g, ids, pos

    @torch.no_grad()
    def radiant_wp(self, a: MatchArrays, rows: np.ndarray | None = None, hero: np.ndarray | None = None) -> np.ndarray:
        h, g, ids, pos = self._tensors(a, rows, hero)
        return torch.sigmoid(self.winprob(h, g, ids, pos).float()).cpu().numpy()

    @torch.no_grad()
    def risk_and_moves(self, a: MatchArrays, pid: int, rows: np.ndarray | None = None,
                       want_moves: bool = False) -> tuple[np.ndarray, np.ndarray | None]:
        h, g, ids, pos = self._tensors(a, rows)
        focus = torch.full((h.shape[0],), pid, device=self.device, dtype=torch.long)
        risk, move = self.context(h, g, ids, pos, focus)
        risk = torch.sigmoid(risk.float()).cpu().numpy()
        if not want_moves:
            return risk, None
        probs = torch.softmax(move.float(), dim=-1)
        if pid >= 5:                       # model works in the Radiant-corner frame: mirror back
            probs = probs.flip(-1)
        return risk, probs.cpu().numpy()


# --------------------------------------------------------------------------- helpers on the record

def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _team(pid: int) -> int:
    return 0 if pid < 5 else 1


def _missing_enemies(rec: MatchRecord, pid: int, t: float) -> list[dict[str, Any]]:
    """Enemies the player's team couldn't see at time t, and for how long."""
    out = []
    r = rec.row(t)
    enemies = range(5, 10) if pid < 5 else range(0, 5)
    for e in enemies:
        if rec.hero[r, e, HF["alive"]] == 0:
            continue
        vis = rec.hero[: r + 1, e, HF["visible_to_enemy"]]
        if vis[-1] != 0:
            continue
        seen = np.nonzero(vis != 0)[0]
        since = float(rec.t[r] - rec.t[seen[-1]]) if len(seen) else float(rec.t[r] - rec.t[0])
        out.append({"pid": e, "hero": rec.players[e]["hero_display"], "missing_s": round(since)})
    return out


def _wards_near(rec: MatchRecord, x: float, y: float, t: float, team: int, kind: str = "observer") -> int:
    return sum(1 for w in rec.events["wards"]
               if w["team"] == team and w["type"] == kind and w["t"] <= t < w["end"]
               and _dist(w["x"], w["y"], x, y) <= WARD_SIGHT)


def _fight_at(rec: MatchRecord, t: float) -> dict[str, Any] | None:
    for f in rec.events["fights"]:
        if f["start"] - 3 <= t <= f["end"] + 3:
            return f
    return None


def _row_at(a: MatchArrays, t: float) -> int:
    return int(np.clip(np.searchsorted(a.t, t, side="right") - 1, 0, len(a.t) - 1))


# --------------------------------------------------------------------------- deaths

def analyze_deaths(rec: MatchRecord, a: MatchArrays, models: Models, wp_rad: np.ndarray | None,
                   risk: dict[int, np.ndarray]) -> list[dict[str, Any]]:
    deaths = [d for d in rec.events["deaths"] if not d["reincarnated"] and d["t"] > 0]
    out = []

    # Win-chance cost of each death: compare the real game a few seconds later with the
    # same moment where only this hero is still alive.
    costs: list[float | None] = [None] * len(deaths)
    if models.winprob is not None and wp_rad is not None and deaths:
        rows = np.array([_row_at(a, d["t"] + 9) for d in deaths])
        hero = a.hero[rows].copy()
        for k, d in enumerate(deaths):
            v = d["victim"]
            hero[k, v, HC["alive"]] = 1
            hero[k, v, HC["hp_frac"]] = 0.6
            hero[k, v, HC["respawn"]] = 0
            hero[k, v, HC["deaths"]] = max(0.0, hero[k, v, HC["deaths"]] - 1 / 20)
        cf = models.radiant_wp(a, rows, hero)
        for k, d in enumerate(deaths):
            actual = wp_rad[rows[k]]
            team_cf = cf[k] if _team(d["victim"]) == 0 else 1 - cf[k]
            team_actual = actual if _team(d["victim"]) == 0 else 1 - actual
            costs[k] = float(team_cf - team_actual)
    # How much the team's win chance moved across the whole moment (the fight around the death).
    swings: list[float | None] = [None] * len(deaths)
    if wp_rad is not None:
        for k, d in enumerate(deaths):
            before, after = wp_rad[_row_at(a, d["t"] - 12)], wp_rad[_row_at(a, d["t"] + 9)]
            swings[k] = float(after - before) if _team(d["victim"]) == 0 else float(before - after)

    # Where a high-Immortal player would have been heading, 30 s before each death.
    moves: list[np.ndarray | None] = [None] * len(deaths)
    if models.context is not None:
        for k, d in enumerate(deaths):
            r = _row_at(a, d["t"] - 30)
            if a.hero[r, d["victim"], HC["alive"]] > 0.5:
                _, probs = models.risk_and_moves(a, d["victim"], np.array([r]), want_moves=True)
                moves[k] = probs[0]

    for k, d in enumerate(deaths):
        v, t = d["victim"], d["t"]
        team = _team(v)
        r_pre = rec.row(t - 3)
        vx, vy = d["x"], d["y"]
        allies = [p for p in range(10) if _team(p) == team and p != v
                  and rec.hero[r_pre, p, HF["alive"]] > 0
                  and _dist(rec.hero[r_pre, p, HF["x"]], rec.hero[r_pre, p, HF["y"]], vx, vy) <= NEAR]
        enemies_near = [p for p in range(10) if _team(p) != team
                        and rec.hero[rec.row(t - 1), p, HF["alive"]] > 0
                        and _dist(rec.hero[rec.row(t - 1), p, HF["x"]],
                                  rec.hero[rec.row(t - 1), p, HF["y"]], vx, vy) <= NEAR * 1.2]
        missing = _missing_enemies(rec, v, t - 8) if rec.meta.get("has_visibility") else None
        r10 = rec.row(t - 10)
        hp10 = float(rec.hero[r10, v, HF["hp"]] / max(rec.hero[r10, v, HF["max_hp"]], 1))
        # A jump of thousands of units in a second or two is a teleport (TP scroll, Shadow Step, Boots...).
        r_lo, r_hi = rec.row(t - 30), rec.row(t)
        xs, ys = rec.hero[r_lo:r_hi + 1, v, HF["x"]], rec.hero[r_lo:r_hi + 1, v, HF["y"]]
        jumps = np.hypot(np.diff(xs), np.diff(ys))
        teleported_s_before = None
        if len(jumps) and jumps.max() > 3500:
            j = int(np.argmax(jumps > 3500))
            teleported_s_before = round(float(t - rec.t[r_lo + j + 1]))
        fight = _fight_at(rec, t)
        info: dict[str, Any] = {
            "t": round(t, 1), "clock": _clock(t), "victim": v,
            "victim_hero": rec.players[v]["hero_display"],
            "killer": d["killer"], "killer_hero": _name(d["killer_name"]),
            "ability": _ability(d["inflictor"]),
            "where": describe(vx, vy, team), "x": vx, "y": vy,
            "allies_nearby": [rec.players[p]["hero_display"] for p in allies],
            "enemies_nearby": [rec.players[p]["hero_display"] for p in enemies_near],
            "hp_10s_before_pct": round(hp10 * 100),
            "own_observer_wards_covering": _wards_near(rec, vx, vy, t, team),
            "enemy_observer_wards_covering": _wards_near(rec, vx, vy, t, 1 - team),
            "net_worth": int(rec.hero[r_pre, v, HF["net_worth"]]),
            "level": int(rec.hero[r_pre, v, HF["level"]]),
        }
        if missing is not None:
            info["enemies_missing_8s_before"] = missing
        if teleported_s_before is not None:
            info["teleported_in_seconds_before_death"] = teleported_s_before
        if fight:
            my_k = fight["radiant_kills"] if team == 0 else fight["dire_kills"]
            their_k = fight["dire_kills"] if team == 0 else fight["radiant_kills"]
            info["fight"] = {"your_team_kills": my_k, "your_team_deaths": their_k,
                             "won": (fight["winner"] == ("radiant" if team == 0 else "dire"))}
        if costs[k] is not None:
            info["win_chance_cost_pct"] = round(costs[k] * 100, 1)
        if swings[k] is not None:
            info["team_win_chance_change_pct"] = round(swings[k] * 100, 1)
        if v in risk:
            rr = risk[v]
            lo, hi = _row_at(a, t - 30), _row_at(a, t - 3)
            window = rr[lo:hi + 1]
            if len(window):
                streak = 0
                for val in window[::-1]:
                    if val < HIGH_RISK:
                        break
                    streak += 1
                info["risk"] = {"max_30s_before": round(float(window.max()), 2),
                                "at_10s_before": round(float(rr[_row_at(a, t - 10)]), 2),
                                "seconds_in_danger_before_death": streak * 3}
        if moves[k] is not None:
            areas = area_probabilities(moves[k], team)
            mine = describe(vx, vy, team)
            info["immortal_would_be"] = [{"where": w, "probability": round(p, 2)} for w, p in areas[:3]]
            info["immortal_probability_of_your_area"] = round(dict(areas).get(mine, 0.0), 2)

        tags = []
        team_got_kills = bool(fight and info["fight"]["your_team_kills"] > 0)
        if not allies and len(enemies_near) >= 2 and not team_got_kills:
            tags.append("caught alone, outnumbered")
        elif len(enemies_near) > len(allies) + 1:
            tags.append("outnumbered")
        if missing is not None and len(missing) >= 3 and info["own_observer_wards_covering"] == 0:
            tags.append("several enemies missing and no ward nearby")
        if "enemy" in info["where"] or info["where"] == "the enemy base":
            tags.append("deep in enemy territory")
        if hp10 < 0.35:
            tags.append("stayed on low HP")
        if teleported_s_before is not None and teleported_s_before <= 20:
            tags.append(f"teleported in {teleported_s_before}s before dying")
        if "tower" in info["killer_hero"]:
            tags.append("killed by a tower")
        if fight and info["fight"]["your_team_kills"] >= info["fight"]["your_team_deaths"] >= 2:
            tags.append("traded in a fight your team didn't lose")
        if info.get("risk", {}).get("seconds_in_danger_before_death", 0) >= 9:
            tags.append("lingered in danger")
        if "immortal_probability_of_your_area" in info and info["immortal_probability_of_your_area"] < 0.08:
            tags.append("Immortal players rarely go there in this situation")
        info["tags"] = tags
        out.append(info)
    return out


_RELIABLE: dict[str, int] = {}


def reliable_until(s: Settings) -> int:
    """Game second after which fewer than 5% of the training games are still going.
    Past it the win-chance model has seen too few examples to be trusted."""
    if "v" not in _RELIABLE:
        from mmrslave.catalog import Catalog
        cat = Catalog(s.catalog_path)
        durs = [r[0] for r in cat.db.execute(
            "SELECT duration FROM matches WHERE source='immortal' AND status='parsed' AND duration > 0")]
        cat.close()
        _RELIABLE["v"] = int(np.percentile(durs, 95)) if len(durs) >= 50 else 45 * 60
    return _RELIABLE["v"]


_CELL_AREAS: dict[int, list[str]] = {}


def area_probabilities(probs: np.ndarray, team: int) -> list[tuple[str, float]]:
    """Sum the movement model's per-cell probabilities into named map areas, most likely first."""
    if team not in _CELL_AREAS:
        cells = np.arange(GRID * GRID)
        xs, ys = cell_center(cells)
        _CELL_AREAS[team] = [describe(float(x), float(y), team) for x, y in zip(xs, ys)]
    totals: dict[str, float] = {}
    for area, p in zip(_CELL_AREAS[team], probs):
        totals[area] = totals.get(area, 0.0) + float(p)
    return sorted(totals.items(), key=lambda kv: -kv[1])


# --------------------------------------------------------------------------- swings

def key_moments(rec: MatchRecord, a: MatchArrays, team_wp: np.ndarray, team: int, n: int = 5,
                window_rows: int = 15) -> dict[str, list[dict[str, Any]]]:
    """Biggest drops and rises in your team's win chance over ~45 s windows."""
    if len(team_wp) <= window_rows:
        return {"drops": [], "rises": []}
    delta = team_wp[window_rows:] - team_wp[:-window_rows]

    def pick(sign: int, threshold: float) -> list[dict[str, Any]]:
        d = delta * sign
        used = np.zeros(len(d), dtype=bool)
        out = []
        for i in np.argsort(d)[::-1]:
            if len(out) >= n or d[i] < threshold:
                break
            if used[max(0, i - window_rows): i + window_rows].any():
                continue
            used[i] = True
            t0, t1 = float(a.t[i]), float(a.t[i + window_rows])
            out.append({
                "start": round(t0), "end": round(t1), "clock": f"{_clock(t0)}-{_clock(t1)}",
                "win_chance_before_pct": round(float(team_wp[i]) * 100),
                "win_chance_after_pct": round(float(team_wp[i + window_rows]) * 100),
                "events": _events_between(rec, t0 - 5, t1 + 3, team),
                "summary": _moment_summary(rec, t0 - 5, t1 + 3, team),
            })
        return sorted(out, key=lambda m: m["start"])

    return {"drops": pick(-1, 0.06), "rises": pick(1, 0.06)}


def _moment_summary(rec: MatchRecord, t0: float, t1: float, team: int) -> str:
    """One line on what happened in a window: '4 of your heroes died (1 enemy), mid barracks lost'."""
    deaths = [d for d in rec.events["deaths"] if t0 <= d["t"] <= t1 and not d["reincarnated"]]
    ours = sum(1 for d in deaths if _team(d["victim"]) == team)
    theirs = len(deaths) - ours
    parts = []
    if ours or theirs:
        if ours == 1:
            parts.append(f"{rec.players[next(d['victim'] for d in deaths if _team(d['victim']) == team)]['hero_display']} "
                         f"died ({theirs} enem{'y' if theirs == 1 else 'ies'} killed)")
        elif ours:
            parts.append(f"{ours} of your heroes died ({theirs} enem{'y' if theirs == 1 else 'ies'} killed)")
        else:
            parts.append(f"{theirs} enem{'y' if theirs == 1 else 'ies'} killed")
    lost = sorted({_building_words(b["name"]) for b in rec.events["buildings"] if t0 <= b["t"] <= t1 and b["team"] == team})
    taken = sorted({_building_words(b["name"]) for b in rec.events["buildings"] if t0 <= b["t"] <= t1 and b["team"] != team})
    if lost:
        parts.append(f"lost {', '.join(lost)}")
    if taken:
        parts.append(f"took their {', '.join(taken)}")
    for r in rec.events["roshans"]:
        if t0 <= r["t"] <= t1:
            parts.append("your team took Roshan" if r["team"] == team else "they took Roshan")
    return "; ".join(parts) or "no kills or buildings, the game state shifted"


def _building_words(name: str) -> str:
    """'tower2_mid' -> 'mid tier-2 tower', 'range_rax_top' -> 'top barracks'."""
    if name.startswith("tower4"):
        return "tier-4 tower"
    if name.startswith("tower"):
        tier, lane = name[5], name.split("_")[-1]
        return f"{lane} tier-{tier} tower"
    if "rax" in name:
        return f"{name.split('_')[-1]} barracks"
    return name.replace("_", " ")


def _events_between(rec: MatchRecord, t0: float, t1: float, team: int) -> list[str]:
    ev = []
    for d in rec.events["deaths"]:
        if t0 <= d["t"] <= t1 and not d["reincarnated"]:
            side = "ally" if _team(d["victim"]) == team else "enemy"
            ev.append(f"{_clock(d['t'])} {side} {rec.players[d['victim']]['hero_display']} "
                      f"killed by {_name(d['killer_name'])}")
    for b in rec.events["buildings"]:
        if t0 <= b["t"] <= t1:
            ev.append(f"{_clock(b['t'])} {'your' if b['team'] == team else 'enemy'} {b['name'].replace('_', ' ')} destroyed")
    for r in rec.events["roshans"]:
        if t0 <= r["t"] <= t1:
            ev.append(f"{_clock(r['t'])} Roshan killed by {'your team' if r['team'] == team else 'the enemy'}")
    for b in rec.events["buybacks"]:
        if t0 <= b["t"] <= t1:
            ev.append(f"{_clock(b['t'])} {rec.players[b['pid']]['hero_display']} bought back")
    for sm in rec.events["smokes"]:
        if t0 <= sm["t"] <= t1:
            ev.append(f"{_clock(sm['t'])} {'your team' if sm['team'] == team else 'enemy'} smoked")
    return ev


# --------------------------------------------------------------------------- comparisons with Immortal players

_STAT_LABELS = {
    "nw10": "net worth at 10:00", "nw20": "net worth at 20:00", "nw30": "net worth at 30:00",
    "lh10": "last hits at 10:00", "lh20": "last hits at 20:00", "lh30": "last hits at 30:00",
    "dn10": "denies at 10:00", "level10": "level at 10:00", "level20": "level at 20:00",
    "level30": "level at 30:00", "gpm": "gold per minute", "xpm": "XP per minute",
    "deaths_per_30": "deaths per 30 minutes", "ka_per_30": "kills+assists per 30 minutes",
    "dead_pct": "% of game spent dead", "hero_damage_per_min": "hero damage per minute",
    "tower_damage_per_min": "tower damage per minute", "obs_per_30": "observer wards per 30 min",
    "sen_per_30": "sentry wards per 30 min", "fight_participation": "fight participation",
    "wards_killed_per_30": "enemy wards destroyed per 30 min",
}
_LOWER_IS_BETTER = {"deaths_per_30", "dead_pct"}
_SUPPORT_ONLY = {"obs_per_30", "sen_per_30"}


def compare_player(rec: MatchRecord, pid: int, bench: Benchmarks) -> dict[str, Any]:
    p = rec.players[pid]
    pos = p.get("position", 0)
    stats = player_stats(rec, pid)
    rows = {}
    for k, v in stats.items():
        if k in _SUPPORT_ONLY and pos not in (4, 5):
            continue
        c = bench.percentile(p["hero_id"], pos, k, v)
        if c:
            better = 100 - c["percentile"] if k in _LOWER_IS_BETTER else c["percentile"]
            rows[k] = {**c, "label": _STAT_LABELS.get(k, k), "better_than_pct_of_immortals": better}

    items_out: dict[str, Any] = {"timings": [], "commonly_built_but_skipped": []}
    found = bench.items(p["hero_id"], pos)
    mine = first_item_times(rec, pid)
    if found:
        label, ref = found
        items_out["compared_with"] = label
        import bisect
        for item, t in sorted(mine.items(), key=lambda x: x[1]):
            r = ref.get(item)
            if r:
                faster = 100 - bisect.bisect_left(r["times"], t) / len(r["times"]) * 100
                items_out["timings"].append({
                    "item": _item_name(item), "your_time": _clock(t), "immortal_median": _clock(r["median_s"]),
                    "minutes_behind": round((t - r["median_s"]) / 60, 1),
                    "faster_than_pct_of_immortals": round(faster)})
        dur = rec.meta["duration_s"]
        for item, r in sorted(ref.items(), key=lambda x: -x[1]["rate_30min_games"]):
            if r["rate_30min_games"] >= 0.5 and item not in mine and dur >= r["median_s"] + 300:
                items_out["commonly_built_but_skipped"].append({
                    "item": _item_name(item), "immortal_build_rate_pct": round(r["rate_30min_games"] * 100),
                    "immortal_median": _clock(r["median_s"])})
    return {"stats": rows, "items": items_out}


def _item_name(item: str) -> str:
    try:
        import gem
        return gem.catalog.items.item_display(item)
    except Exception:  # noqa: BLE001
        return item.replace("_", " ").title()


_LANE_OPPONENTS = {1: (3, 4), 2: (2,), 3: (1, 5), 4: (1, 5), 5: (3, 4)}


def laning(rec: MatchRecord, pid: int) -> dict[str, Any] | None:
    if rec.t[-1] < 600:
        return None
    p = rec.players[pid]
    pos = p.get("position", 0)
    r = rec.row(600)
    me = {"lh": int(rec.hero[r, pid, HF["lh"]]), "dn": int(rec.hero[r, pid, HF["dn"]]),
          "nw": int(rec.hero[r, pid, HF["net_worth"]]), "level": int(rec.hero[r, pid, HF["level"]])}
    opponents = []
    for q in rec.players:
        if q["team"] != p["team"] and q.get("position") in _LANE_OPPONENTS.get(pos, ()):
            j = q["player_id"]
            opponents.append({"hero": q["hero_display"], "position": q.get("position"),
                              "lh": int(rec.hero[r, j, HF["lh"]]), "nw": int(rec.hero[r, j, HF["net_worth"]]),
                              "level": int(rec.hero[r, j, HF["level"]])})
    early_deaths = [d for d in rec.events["deaths"] if d["victim"] == pid and 0 < d["t"] <= 600
                    and not d["reincarnated"]]
    early_kills = [d for d in rec.events["deaths"] if d["killer"] == pid and 0 < d["t"] <= 600]
    return {"at_10_min": me, "lane_opponents": opponents, "deaths_before_10": len(early_deaths),
            "kills_before_10": len(early_kills), "lane_efficiency_pct": p.get("lane_efficiency_pct")}


# --------------------------------------------------------------------------- whole match

def analyze_match(s: Settings, match_id: int, *, steam_id: int | None = None, models: Models | None = None,
                  bench: Benchmarks | None = None) -> dict[str, Any]:
    rec = load_record(s.matches_dir, match_id)
    models = models or Models.load(s)
    bench = bench if bench is not None else Benchmarks.load(s)
    steam_id = steam_id if steam_id is not None else s.steam_id
    me_p = rec.player_by_steam_id(steam_id) if steam_id else None
    me = me_p["player_id"] if me_p else None
    my_team = _team(me) if me is not None else 0

    a = build_arrays(rec, step=3, start_s=-60)
    wp_rad = models.radiant_wp(a) if models.winprob is not None else None
    risk: dict[int, np.ndarray] = {}
    if models.context is not None:
        for pid in range(10):
            risk[pid], _ = models.risk_and_moves(a, pid)

    deaths = analyze_deaths(rec, a, models, wp_rad, risk)
    out: dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "match_id": rec.match_id, "duration_s": rec.meta["duration_s"], "duration": _clock(rec.meta["duration_s"]),
        "radiant_win": rec.meta["radiant_win"], "me": me, "my_team": my_team,
        "won": None if me is None else (my_team == 0) == bool(rec.meta["radiant_win"]),
        "score": {"radiant": rec.meta["radiant_score"], "dire": rec.meta["dire_score"]},
        "has_visibility": rec.meta.get("has_visibility"),
        "models_used": {"win_probability": models.winprob is not None, "hero_context": models.context is not None,
                        "benchmark_matches": bench.data["n_matches"] if bench else 0},
        "players": [{
            "pid": p["player_id"], "hero": p["hero_display"], "hero_id": p["hero_id"], "name": p["name"],
            "team": p["team"], "position": p.get("position"), "is_me": p["player_id"] == me,
            "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"], "net_worth": p["net_worth"],
            "last_hits": p["last_hits"], "gpm": p["gpm"], "xpm": p["xpm"], "level": p["level"],
            "final_items": [_item_name(i) for i in p["final_items"]][:9],
            "denies": p.get("denies"), "hero_damage": p.get("hero_damage"), "tower_damage": p.get("tower_damage"),
            "obs_placed": p.get("obs_placed"), "sen_placed": p.get("sen_placed"),
            "wards_killed": (sum(1 for w in rec.events["wards"] if w.get("killer_pid") == p["player_id"])
                             if "minute" in rec.meta else None),
            "fight_participation": p.get("teamfight_participation"), "stuns": p.get("stuns"),
            "camps_stacked": p.get("camps_stacked"),
        } for p in rec.players],
        "deaths": deaths,
    }
    if wp_rad is not None:
        team_wp = wp_rad if my_team == 0 else 1 - wp_rad
        # Every 3 s sample, so the chart quotes exactly the numbers the swings and deaths use.
        out["win_chance"] = {"t": [int(x) for x in a.t],
                             "your_team": [round(float(x), 3) for x in team_wp],
                             "reliable_until_s": reliable_until(s)}
        out["key_moments"] = key_moments(rec, a, team_wp, my_team)
        after10 = a.t >= 600
        if after10.any():
            hi = int(np.argmax(np.where(after10, team_wp, -1)))
            lo = int(np.argmin(np.where(after10, team_wp, 2)))
            out["peak"] = {"best_clock": _clock(a.t[hi]), "best_pct": round(float(team_wp[hi]) * 100),
                           "worst_clock": _clock(a.t[lo]), "worst_pct": round(float(team_wp[lo]) * 100)}
    if me is not None and me in risk:
        out["my_risk"] = {"t": [int(x) for x in a.t[::2]], "risk": [round(float(x), 3) for x in risk[me][::2]]}

    # How much each player's deaths and kills moved the game: averages per death/kill and a count of
    # costly deaths, over the part of the game the win-chance model is reliable for.
    until = out.get("win_chance", {}).get("reliable_until_s")
    acc = {p: {"lost": [], "won": []} for p in range(10)}
    for d in deaths:
        c = d.get("win_chance_cost_pct")
        if c is None or (until is not None and d["t"] > until):
            continue
        acc[d["victim"]]["lost"].append(max(c, 0.0))
        if d["killer"] is not None and _team(d["killer"]) != _team(d["victim"]):
            acc[d["killer"]]["won"].append(max(c, 0.0))
    out["impact_until"] = None if until is None or rec.meta["duration_s"] <= until else _clock(until)
    out["impact"] = [{
        "pid": p, "hero": rec.players[p]["hero_display"],
        "deaths_priced": len(v["lost"]),
        "avg_cost_per_death_pct": round(float(np.mean(v["lost"])), 1) if v["lost"] else None,
        "costly_deaths": sum(1 for c in v["lost"] if c >= 10),
        "kills_priced": len(v["won"]),
        "avg_gain_per_kill_pct": round(float(np.mean(v["won"])), 1) if v["won"] else None,
    } for p, v in acc.items()]

    if me is not None:
        win_at = None
        if wp_rad is not None:
            team_wp_all = wp_rad if my_team == 0 else 1 - wp_rad
            win_at = lambda t: float(team_wp_all[_row_at(a, t)])  # noqa: E731
        out["decisions"] = find_decisions(rec, me, win_at)
    out["laning"] = [laning(rec, p) for p in range(10)]
    if bench:
        out["vs_immortal"] = [compare_player(rec, p, bench) for p in range(10)]
    out["findings"] = build_findings(out)
    return out


# --------------------------------------------------------------------------- ranked findings

def build_findings(an: dict[str, Any]) -> list[dict[str, Any]]:
    me, my_team = an["me"], an["my_team"]
    players = an["players"]
    f: list[dict[str, Any]] = []

    def who(pid: int) -> str:
        if pid == me:
            return "you"
        p = players[pid]
        return f"{p['hero']} (pos {p['position']})"

    for d in an["deaths"]:
        v = d["victim"]
        if v != me:
            continue                                           # findings are about the player only
        cost = d.get("win_chance_cost_pct")
        swing = d.get("team_win_chance_change_pct")
        impact = max(cost or 0.0, -(swing or 0.0) * 0.5)      # the death itself, or its share of the fight
        if reliable_late := (an.get("win_chance") or {}).get("reliable_until_s"):
            if d["t"] > reliable_late:
                impact *= 0.4                                  # the model has seen few games this long
        sev = (impact / 100 if cost is not None or swing is not None else 0.03) + 0.02 * len(d["tags"])
        if cost is not None and cost >= 1:
            cost_txt = f" (-{cost:.0f}% win chance)"
        elif swing is not None and swing <= -3:
            cost_txt = f" (team win chance {swing:+.0f}% in this fight)"
        else:
            cost_txt = ""
        f.append({"t": d["t"], "clock": d["clock"], "pid": v, "about": who(v), "kind": "death",
                  "severity": round(sev, 3),
                  "title": f"{d['clock']} {_cap(who(v))} died to {d['killer_hero']} in {d['where']}{cost_txt}",
                  "tags": d["tags"]})

    reliable = (an.get("win_chance") or {}).get("reliable_until_s")
    for m in an.get("key_moments", {}).get("drops", []):
        drop = m["win_chance_before_pct"] - m["win_chance_after_pct"]
        summary = m.get("summary")
        late = reliable is not None and m["start"] > reliable
        if late:
            summary = (summary + "; " if summary else "") + "rough estimate: few Immortal games last this long"
        f.append({"t": m["start"], "clock": m["clock"], "pid": None, "about": "your team", "kind": "swing",
                  "severity": round((drop / 100 + 0.02) * (0.4 if late else 1.0), 3),
                  "before_pct": m["win_chance_before_pct"], "after_pct": m["win_chance_after_pct"],
                  "title": f"{m['clock']} Win chance {m['win_chance_before_pct']}% → {m['win_chance_after_pct']}%"
                           + (f": {summary}" if summary else ""), "events": m["events"]})

    for dec in (an.get("decisions") or {}).get("missed", []):
        f.append({"t": dec["t"], "clock": dec["clock"], "pid": me, "about": "you", "kind": dec["kind"],
                  "severity": dec["severity"], "title": f"{dec['clock']} {dec['title']}",
                  "what_happened": dec["what_happened"], "do_instead": dec["do_instead"],
                  "x": dec.get("x"), "y": dec.get("y")})

    peak = an.get("peak")
    if peak and an.get("won") is False and peak["best_pct"] >= 70:
        f.append({"t": None, "clock": peak["best_clock"], "pid": None, "about": "your team", "kind": "throw",
                  "severity": 0.25,
                  "title": f"Your team had a {peak['best_pct']}% win chance at {peak['best_clock']} and lost"})

    for pid, comp in enumerate(an.get("vs_immortal") or []):
        if pid != me:
            continue
        for k, row in comp["stats"].items():
            b = row["better_than_pct_of_immortals"]
            if b <= 15 and (pid == me or k in ("nw20", "deaths_per_30", "dead_pct", "obs_per_30")):
                f.append({"t": None, "pid": pid, "about": who(pid), "kind": "benchmark",
                          "severity": round((20 - b) / 100 * (1.0 if pid == me else 0.6), 3),
                          "title": f"{_cap(who(pid))}: {row['label']} {_num(row['value'])} "
                                   f"(Immortal median {_num(row['immortal_median'])}; "
                                   f"better than only {b}% of them)"})
        if pid == me:
            for it in comp["items"]["timings"]:
                if it["minutes_behind"] >= 4:
                    f.append({"t": None, "pid": pid, "about": "you", "kind": "items",
                              "severity": round(min(it["minutes_behind"], 15) / 60, 3),
                              "title": f"{it['item']} at {it['your_time']}, {it['minutes_behind']:.0f} min later "
                                       f"than the Immortal median ({it['immortal_median']})"})

    lane = an["laning"][me] if me is not None and an.get("laning") else None
    if lane and lane["deaths_before_10"] >= 2:
        f.append({"t": 600, "pid": me, "about": "you", "kind": "laning", "severity": 0.06 * lane["deaths_before_10"],
                  "title": f"Died {lane['deaths_before_10']} times before 10:00"})

    f.sort(key=lambda x: -x["severity"])
    return f


def save_analysis(s: Settings, an: dict[str, Any]) -> Path:
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    path = s.reports_dir / f"{an['match_id']}.analysis.json"
    path.write_text(json.dumps(an, default=_json_default), encoding="utf-8")
    return path


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(type(o))


def _num(v: float) -> str:
    """12506.0 -> '12,506'; 2.35 -> '2.4'."""
    return f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.1f}"


def _cap(text: str) -> str:
    """Capitalize the first letter only ("you" -> "You", hero names untouched)."""
    return text[:1].upper() + text[1:]
