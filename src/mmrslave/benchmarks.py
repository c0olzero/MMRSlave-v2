"""What high-Immortal players typically achieve, per hero and position.

Built from the collected Immortal matches. Each stat keeps a sorted sample of
values, so any of your numbers can be turned into a percentile.
"""

from __future__ import annotations

import bisect
import json
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np

from mmrslave.catalog import Catalog
from mmrslave.config import Settings
from mmrslave.extract import HF, load_record

# Core items worth tracking timings for (internal names; unknown names are simply never seen).
KEY_ITEMS = {
    "blink", "black_king_bar", "manta", "bfury", "radiance", "desolator", "butterfly", "satanic", "skadi",
    "abyssal_blade", "ultimate_scepter", "aghanims_shard", "assault", "heart", "monkey_king_bar",
    "greater_crit", "silver_edge", "diffusal_blade", "disperser", "eternal_shroud", "sphere", "lotus_orb",
    "pipe", "crimson_guard", "guardian_greaves", "glimmer_cape", "force_staff", "hurricane_pike", "ghost",
    "aether_lens", "cyclone", "wind_waker", "orchid", "bloodthorn", "nullifier", "sheepstick", "refresher",
    "octarine_core", "kaya", "sange", "yasha", "sange_and_yasha", "kaya_and_sange", "yasha_and_kaya",
    "maelstrom", "mjollnir", "gungir", "echo_sabre", "harpoon", "armlet", "mask_of_madness", "power_treads",
    "phase_boots", "arcane_boots", "travel_boots", "boots_of_bearing", "tranquil_boots", "hand_of_midas",
    "vladmir", "helm_of_the_overlord", "helm_of_the_dominator", "solar_crest", "spirit_vessel", "mekansm",
    "holy_locket", "invis_sword", "heavens_halberd", "bloodstone", "shivas_guard", "dagon", "rod_of_atos",
    "veil_of_discord", "witch_blade", "revenants_brooch", "angels_demise", "khanda", "devastator", "pavise",
    "phylactery", "basher", "mage_slayer", "falcon_blade", "overwhelming_blink", "swift_blink",
    "arcane_blink", "ethereal_blade", "meteor_hammer", "moon_shard", "parasma", "harpoon",
}
MAX_SAMPLE = 400
# Stats drawn over time on the "vs Immortal" tab. The last three exist only in records parsed
# with schema 2 or later (see extract._minute_series).
CURVE_STATS = ("nw", "lh", "dn", "level", "kills", "deaths", "assists", "hero_damage", "building_damage")
MINUTE_ONLY = ("assists", "hero_damage", "building_damage")
MAX_MINUTE = 70
MIN_CURVE_N = 8      # fewer games than this at a minute: no Immortal point there
MIN_N = 12           # below this many games, fall back to position-wide numbers

Log = Callable[[str], None]


def player_stats(rec, pid: int) -> dict[str, float]:
    """The numbers we compare against Immortal players (also used for your own games)."""
    p = rec.players[pid]
    dur_min = max(rec.meta["duration_s"] / 60, 1)
    out: dict[str, float] = {
        "gpm": p["gpm"], "xpm": p["xpm"],
        "deaths_per_30": p["deaths"] / dur_min * 30,
        "ka_per_30": (p["kills"] + p["assists"]) / dur_min * 30,
        "hero_damage_per_min": p["hero_damage"] / dur_min,
        "tower_damage_per_min": p["tower_damage"] / dur_min,
        "obs_per_30": p["obs_placed"] / dur_min * 30,
        "sen_per_30": p["sen_placed"] / dur_min * 30,
        "fight_participation": p["teamfight_participation"],
    }
    if "minute" in rec.meta:                     # ward killers are known from schema 2 on
        killed = sum(1 for w in rec.events["wards"] if w.get("killer_pid") == pid)
        out["wards_killed_per_30"] = killed / dur_min * 30
    alive = rec.hero[:, pid, HF["alive"]]
    after0 = rec.t >= 0
    out["dead_pct"] = float((alive[after0] == 0).mean() * 100) if after0.any() else 0.0
    for minute in (10, 20, 30):
        if rec.t[-1] >= minute * 60:
            r = rec.row(minute * 60)
            out[f"nw{minute}"] = float(rec.hero[r, pid, HF["net_worth"]])
            out[f"lh{minute}"] = float(rec.hero[r, pid, HF["lh"]])
            out[f"level{minute}"] = float(rec.hero[r, pid, HF["level"]])
            if minute == 10:
                out["dn10"] = float(rec.hero[r, pid, HF["dn"]])
    return out


def player_curves(rec, pid: int) -> dict[str, list[float]]:
    """One value per minute (0:00, 1:00, ...) for each curve stat this record has."""
    last = min(int(rec.t[-1] // 60), MAX_MINUTE)
    rows = [rec.row(m * 60) for m in range(last + 1)]
    out = {}
    for key, field in (("nw", "net_worth"), ("lh", "lh"), ("dn", "dn"), ("level", "level"),
                       ("kills", "kills"), ("deaths", "deaths")):
        out[key] = [round(float(rec.hero[r, pid, HF[field]]), 1) for r in rows]
    minute = rec.meta.get("minute")
    if minute:
        for key in MINUTE_ONLY:
            vals = minute[key][pid][: last + 1]
            out[key] = vals + [vals[-1]] * (last + 1 - len(vals)) if vals else []
    return out


def first_item_times(rec, pid: int) -> dict[str, float]:
    times: dict[str, float] = {}
    for e in rec.events["purchases"]:
        if e["pid"] == pid and e["item"] in KEY_ITEMS and e["item"] not in times and e["t"] > 0:
            times[e["item"]] = e["t"]
    return times


def _one_match(matches_dir: Path, match_id: int) -> list[dict[str, Any]] | None:
    try:
        rec = load_record(matches_dir, match_id)
    except Exception:  # noqa: BLE001
        return None
    rows = []
    for p in rec.players:
        pid = p["player_id"]
        won = (p["team"] == 0) == bool(rec.meta["radiant_win"])
        rows.append({"hero_id": p["hero_id"], "pos": p.get("position", 0), "won": won,
                     "stats": player_stats(rec, pid), "items": first_item_times(rec, pid),
                     "curves": player_curves(rec, pid),
                     "duration": rec.meta["duration_s"]})
    return rows


def build_benchmarks(s: Settings, log: Log, workers: int = 12) -> dict[str, Any]:
    cat = Catalog(s.catalog_path)
    ids = cat.parsed_ids("immortal")
    cat.close()
    log(f"benchmarks: reading {len(ids)} Immortal matches")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with ProcessPoolExecutor(workers) as ex:
        for rows in ex.map(_one_match, [s.matches_dir] * len(ids), ids, chunksize=16):
            for r in rows or []:
                groups[f"{r['hero_id']}:{r['pos']}"].append(r)
                groups[f"pos:{r['pos']}"].append(r)
                groups[f"hero:{r['hero_id']}"].append(r)

    rng = np.random.default_rng(0)
    out: dict[str, Any] = {"built_at": time.strftime("%Y-%m-%d %H:%M"), "n_matches": len(ids), "groups": {}}
    curves_out: dict[str, Any] = {}
    for key, rows in groups.items():
        stats: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            for k, v in r["stats"].items():
                stats[k].append(v)
        item_times: dict[str, list[float]] = defaultdict(list)
        long_games = [r for r in rows if r["duration"] >= 30 * 60]
        for r in rows:
            for item, t in r["items"].items():
                item_times[item].append(t)
        g = {"n": len(rows), "win_rate": float(np.mean([r["won"] for r in rows])), "stats": {}, "items": {}}
        for k, vals in stats.items():
            v = np.asarray(vals)
            if len(v) > MAX_SAMPLE:
                v = rng.choice(v, MAX_SAMPLE, replace=False)
            g["stats"][k] = sorted(round(float(x), 2) for x in v)
        for item, times in item_times.items():
            rate = sum(1 for r in long_games if item in r["items"]) / max(len(long_games), 1)
            if len(times) >= 3:
                g["items"][item] = {"rate_30min_games": round(rate, 3), "median_s": float(np.median(times)),
                                    "times": sorted(round(t) for t in times)[:MAX_SAMPLE]}
        out["groups"][key] = g
        if not key.startswith("hero:"):
            curves_out[key] = _curve_bands(rows)
    path = s.models_dir / "benchmarks.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    cpath = s.models_dir / "benchmark_curves.json"
    cpath.write_text(json.dumps({"built_at": out["built_at"], "groups": curves_out}), encoding="utf-8")
    log(f"benchmarks: saved {len(out['groups'])} hero/position groups to {path}")
    return out


def _curve_bands(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per stat and minute: the middle half (p25-p75) and median of the games still going."""
    bands: dict[str, Any] = {"n": len(rows)}
    for stat in CURVE_STATS:
        cols: list[list[float]] = []
        for r in rows:
            for m, v in enumerate(r["curves"].get(stat) or []):
                if m >= len(cols):
                    cols.append([])
                cols[m].append(v)
        p25, p50, p75, ns = [], [], [], []
        for vals in cols:
            if len(vals) < MIN_CURVE_N:
                break
            q = np.percentile(vals, [25, 50, 75])
            p25.append(round(float(q[0]), 1)); p50.append(round(float(q[1]), 1)); p75.append(round(float(q[2]), 1))
            ns.append(len(vals))
        bands[stat] = {"p25": p25, "p50": p50, "p75": p75, "n": ns,
                       "games": sum(1 for r in rows if r["curves"].get(stat))}
    return bands


class Benchmarks:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.groups = data.get("groups", {})

    @classmethod
    def load(cls, s: Settings) -> "Benchmarks | None":
        path = s.model_file("benchmarks.json")
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def group(self, hero_id: int, pos: int) -> tuple[str, dict[str, Any]] | None:
        """Most specific group with enough games: hero+position, then position."""
        for key, label in ((f"{hero_id}:{pos}", "same hero and position"), (f"pos:{pos}", "same position")):
            g = self.groups.get(key)
            if g and g["n"] >= MIN_N:
                return label, g
        return None

    def percentile(self, hero_id: int, pos: int, stat: str, value: float) -> dict[str, Any] | None:
        found = self.group(hero_id, pos)
        if not found:
            return None
        label, g = found
        vals = g["stats"].get(stat)
        if not vals:
            return None
        pct = bisect.bisect_left(vals, value) / len(vals) * 100
        return {"value": round(value, 1), "percentile": round(pct), "immortal_median": vals[len(vals) // 2],
                "compared_with": label, "n": g["n"]}

    _curves: dict[str, Any] | None = None

    def curves(self, s: Settings, hero_id: int, pos: int) -> tuple[str, dict[str, Any]] | None:
        """Immortal curves for this hero and position, or for the position when the hero has few games."""
        if self._curves is None:
            path = s.model_file("benchmark_curves.json")
            self._curves = json.loads(path.read_text(encoding="utf-8"))["groups"] if path.exists() else {}
        hero, everyone = self._curves.get(f"{hero_id}:{pos}"), self._curves.get(f"pos:{pos}")
        if not (hero and hero["n"] >= MIN_N):
            return ("same position", {**everyone, "position_only": []}) if everyone and everyone["n"] >= MIN_N else None
        # Stats only recorded by newer parsers (damage, assists over time) can be missing for a
        # hero for a while; borrow those from every Immortal player in the position, and say so.
        out, borrowed = dict(hero), []
        for k in CURVE_STATS:
            if not (hero.get(k) or {}).get("p50") and everyone and (everyone.get(k) or {}).get("p50"):
                out[k] = everyone[k]
                borrowed.append(k)
        out["position_only"] = borrowed
        return "same hero and position", out

    def items(self, hero_id: int, pos: int) -> tuple[str, dict[str, Any]] | None:
        for key, label in ((f"{hero_id}:{pos}", "same hero and position"), (f"hero:{hero_id}", "same hero")):
            g = self.groups.get(key)
            if g and g["n"] >= MIN_N:
                return label, g["items"]
        return None
