"""Name map areas in words a player uses ("your safe-lane jungle", "enemy base")."""

from __future__ import annotations

import math

from mmrslave.features import MAP_CX, MAP_CY

_HALF = 9250.0
_LANE_W = 0.13       # lane half-width in normalized map units (~1200 world units)


def _norm(x: float, y: float) -> tuple[float, float]:
    return (x - MAP_CX) / _HALF, (y - MAP_CY) / _HALF


def _seg_dist(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# Lanes in normalized coordinates (Radiant base bottom-left, Dire base top-right).
_TOP = [(-0.74, -0.45), (-0.74, 0.74), (0.45, 0.74)]
_BOT = [(-0.45, -0.74), (0.74, -0.74), (0.74, 0.45)]
_MID = [(-0.55, -0.55), (0.55, 0.55)]


def _near(u: float, v: float, line: list[tuple[float, float]]) -> bool:
    return any(_seg_dist(u, v, line[i], line[i + 1]) < _LANE_W for i in range(len(line) - 1))


def region_key(x: float, y: float) -> str:
    """Absolute area name: radiant_base, top_lane, mid_lane, bot_lane, river,
    radiant_top_jungle, radiant_bot_jungle, dire_top_jungle, dire_bot_jungle, dire_base."""
    u, v = _norm(x, y)
    if u < -0.55 and v < -0.55:
        return "radiant_base"
    if u > 0.55 and v > 0.55:
        return "dire_base"
    if _near(u, v, _MID):
        return "mid_lane"
    if _near(u, v, _TOP):
        return "top_lane"
    if _near(u, v, _BOT):
        return "bot_lane"
    try:
        import gem
        if gem.region_of(x, y) in ("river", "top_lotus", "bottom_lotus"):
            return "river"
    except Exception:  # noqa: BLE001
        if abs(u + v) < 0.1:
            return "river"
    side = "radiant" if u + v < 0 else "dire"
    half = "top" if v > u else "bot"
    return f"{side}_{half}_jungle"


def describe(x: float, y: float, team: int) -> str:
    """Area name from a player's point of view. team: 0 Radiant, 1 Dire."""
    key = region_key(x, y)
    own, enemy = ("radiant", "dire") if team == 0 else ("dire", "radiant")
    safe, off = ("bot", "top") if team == 0 else ("top", "bot")
    if key == f"{own}_base":
        return "your base"
    if key == f"{enemy}_base":
        return "the enemy base"
    if key == "mid_lane":
        return "mid lane"
    if key == "river":
        return "the river"
    if key.endswith("_lane"):
        lane = key.split("_")[0]
        return "your safe lane" if lane == safe else "your off lane"
    side, lane, _ = key.split("_")
    whose = "your" if side == own else "the enemy"
    # Each team's safe-lane jungle sits between its mid and safe lane.
    own_safe = safe
    enemy_safe = off
    lane_kind = "safe-lane" if lane == (own_safe if side == own else enemy_safe) else "off-lane"
    return f"{whose} {lane_kind} jungle"


# Area names in Vietnamese, keyed by the English names describe() returns.
AREA_VI = {
    "your base": "base của bạn",
    "the enemy base": "base địch",
    "mid lane": "đường mid",
    "the river": "sông",
    "your safe lane": "safe lane của bạn",
    "your off lane": "off lane của bạn",
    "your safe-lane jungle": "rừng safe lane của bạn",
    "your off-lane jungle": "rừng off lane của bạn",
    "the enemy safe-lane jungle": "rừng safe lane của địch",
    "the enemy off-lane jungle": "rừng off lane của địch",
}


def describe_vi(x: float, y: float, team: int) -> str:
    en = describe(x, y, team)
    return AREA_VI.get(en, en)

