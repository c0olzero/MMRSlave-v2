"""Fixed places on the map, in replay coordinates (the same frame as hero positions).

Read from the building entities of a current-patch replay. Names match extract.BUILDINGS.
The two barracks of a lane share one spot (which one is melee doesn't matter here).
"""

from __future__ import annotations

import math

# team 0 = Radiant, 1 = Dire
BUILDING_XY: dict[int, dict[str, tuple[float, float]]] = {
    0: {
        "tower1_top": (10048, 18240), "tower2_top": (9883, 15512), "tower3_top": (9792, 12976),
        "tower1_mid": (14840, 14976), "tower2_mid": (13194, 13458), "tower3_mid": (11744, 12240),
        "tower1_bot": (21244, 10005), "tower2_bot": (16024, 10128), "tower3_bot": (12432, 10272),
        "tower4_a": (10672, 11520), "tower4_b": (10992, 11192),
        "melee_rax_top": (9540, 12625), "range_rax_top": (10048, 12626),
        "melee_rax_mid": (11324, 12185), "range_rax_mid": (11712, 11832),
        "melee_rax_bot": (12104, 10024), "range_rax_bot": (12105, 10531),
    },
    1: {
        "tower1_top": (11109, 22420), "tower2_top": (16256, 22400), "tower3_top": (19936, 22160),
        "tower1_mid": (16908, 17036), "tower2_mid": (18880, 18496), "tower3_mid": (20656, 20143),
        "tower1_bot": (22653, 14144), "tower2_bot": (22784, 16768), "tower3_bot": (22720, 19416),
        "tower4_a": (21328, 21160), "tower4_b": (21664, 20816),
        "melee_rax_top": (20278, 22409), "range_rax_top": (20282, 21880),
        "melee_rax_mid": (20720, 20567), "range_rax_mid": (21086, 20208),
        "melee_rax_bot": (22448, 19760), "range_rax_bot": (22976, 19776),
    },
}
ANCIENT_XY = {0: (10464, 11032), 1: (21912, 21384)}

TOWER_RANGE = 850.0        # a hero this close to a tower is "under" it
TP_CHANNEL_S = 3.0         # Town Portal channel time
WALK_SPEED = 330.0         # typical hero move speed, units per second


def building_words(name: str, team: int, my_team: int, lang: str = "en") -> str:
    """'tower2_mid' -> 'your mid tier-2 tower' / 'their mid tier-2 tower' (or in Vietnamese)."""
    if lang == "vi":
        whose = "của bạn" if team == my_team else "của địch"
        if name.startswith("tower4"):
            return f"trụ tier-4 {whose}"
        if name.startswith("tower"):
            return f"trụ tier-{name[5]} {name.split('_')[-1]} {whose}"
        if "rax" in name:
            return f"nhà lính {name.split('_')[-1]} {whose}"
        return f"{'Ancient' if name == 'fort' else name.replace('_', ' ')} {whose}"
    whose = "your" if team == my_team else "their"
    if name.startswith("tower4"):
        return f"{whose} tier-4 tower"
    if name.startswith("tower"):
        return f"{whose} {name.split('_')[-1]} tier-{name[5]} tower"
    if "rax" in name:
        return f"{whose} {name.split('_')[-1]} barracks"
    return f"{whose} {name.replace('_', ' ')}"


def nearest_building(x: float, y: float, team: int, standing: set[str] | None = None,
                     towers_only: bool = True) -> tuple[str, float] | None:
    """The closest building of a team (optionally only ones still standing) and its distance."""
    best = None
    for name, (bx, by) in BUILDING_XY[team].items():
        if towers_only and not name.startswith("tower"):
            continue
        if standing is not None and name not in standing:
            continue
        d = math.hypot(x - bx, y - by)
        if best is None or d < best[1]:
            best = (name, d)
    return best
