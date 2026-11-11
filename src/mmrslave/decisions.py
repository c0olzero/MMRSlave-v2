"""Decisions the player could have made differently, beyond their own deaths.

Each check looks at one kind of situation from the player's side only:

* fights_without_you   teammates fought (or were dived under a tower) while you were elsewhere,
                       and a TP or a walk would have got you there before the fight ended
* towers_lost_far_away your tower fell to several enemies while you were away and could have TPed
* advantage_unused     3+ enemies were dead but your team took no tower, Roshan or Tormentor
* rune_control         the enemy took most of the power runes early on

Each result has a pause time `t`, a title, what happened, what to do instead, the spot on
the map it's about, and a severity on the same scale as the other findings. The same three
texts in Vietnamese sit under "vi" (game terms such as TP, Roshan, last hits stay in English).
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from mmrslave.extract import BUILDING_INDEX, HF, MatchRecord
from mmrslave.landmarks import (BUILDING_XY, TOWER_RANGE, TP_CHANNEL_S, WALK_SPEED, building_words,
                                nearest_building)
from mmrslave.regions import describe, describe_vi

WinAt = Callable[[float], float] | None
REACTION_S = 2.0            # time to notice a fight and start the TP
POWER_RUNES = {0, 1, 2, 3, 4, 6, 9}
RUNE_NAMES = {0: "Double Damage", 1: "Haste", 2: "Illusion", 3: "Invisibility", 4: "Regeneration",
              5: "Bounty", 6: "Arcane", 7: "Water", 8: "Wisdom", 9: "Shield"}


def _clock(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(int(round(t)))
    return f"{sign}{t // 60}:{t % 60:02d}"


def _team(pid: int) -> int:
    return 0 if pid < 5 else 1


def _n(v: float) -> str:
    return f"{v:,.0f}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


class _View:
    """Small helpers over one match record."""

    def __init__(self, rec: MatchRecord, me: int, win_at: WinAt):
        self.rec, self.me, self.win_at = rec, me, win_at
        self.team = _team(me)
        self.enemy = 1 - self.team
        self.allies = [p for p in range(10) if _team(p) == self.team and p != me]
        self.enemies = [p for p in range(10) if _team(p) == self.enemy]

    def hero(self, pid: int) -> str:
        return self.rec.players[pid]["hero_display"]

    def pos(self, pid: int, t: float) -> tuple[float, float]:
        r = self.rec.row(t)
        return float(self.rec.hero[r, pid, HF["x"]]), float(self.rec.hero[r, pid, HF["y"]])

    def alive(self, pid: int, t: float) -> bool:
        return bool(self.rec.hero[self.rec.row(t), pid, HF["alive"]] > 0)

    def lh(self, pid: int, t: float) -> int:
        return int(self.rec.hero[self.rec.row(t), pid, HF["lh"]])

    def standing(self, team: int, t: float) -> set[str]:
        row = self.rec.buildings[self.rec.row(t), team]
        return {name for name, i in BUILDING_INDEX.items() if row[i] and name in BUILDING_XY[team]}

    def doing(self, t0: float, t1: float, lang: str = "en") -> str:
        """What the player was up to between two moments, in a few words."""
        gained = self.lh(self.me, t1) - self.lh(self.me, t0)
        x, y = self.pos(self.me, (t0 + t1) / 2)
        vi = lang == "vi"
        where = describe_vi(x, y, self.team) if vi else describe(x, y, self.team)
        if not self.alive(self.me, (t0 + t1) / 2):
            return "bạn đang chết" if vi else "you were dead"
        if gained >= 3:
            return f"bạn đang farm ở {where} (+{gained} last hits)" if vi else f"you were farming {where} (+{gained} last hits)"
        return f"bạn đang ở {where}" if vi else f"you were in {where}"

    def win_change(self, t0: float, t1: float) -> tuple[int, int] | None:
        if self.win_at is None:
            return None
        return round(self.win_at(t0) * 100), round(self.win_at(t1) * 100)

    def deaths(self, t0: float, t1: float) -> list[dict[str, Any]]:
        return [d for d in self.rec.events["deaths"] if t0 <= d["t"] <= t1 and not d["reincarnated"]]


def _route_to(v: _View, t: float, x: float, y: float) -> dict[str, Any]:
    """Fastest way for the player to reach a spot: walking, or a TP to the nearest own tower."""
    mx, my = v.pos(v.me, t)
    walk_s = math.hypot(mx - x, my - y) / WALK_SPEED
    best = {"how": "walk", "seconds": walk_s, "distance": math.hypot(mx - x, my - y)}
    tower = nearest_building(x, y, v.team, v.standing(v.team, t))
    if tower:
        name, d = tower
        tp_s = REACTION_S + TP_CHANNEL_S + d / WALK_SPEED
        if tp_s < walk_s:
            best = {"how": "tp", "seconds": tp_s, "tower": name, "tower_distance": d,
                    "distance": best["distance"]}
    return best


def _route_words(v: _View, route: dict[str, Any], lang: str = "en") -> str:
    if lang == "vi":
        if route["how"] == "tp":
            return (f"TP về {building_words(route['tower'], v.team, v.team, 'vi')} "
                    f"(cách đó {_n(route['tower_distance'])} units) sẽ tới nơi trong khoảng {route['seconds']:.0f}s")
        return f"Đi bộ tới đó mất khoảng {route['seconds']:.0f}s"
    if route["how"] == "tp":
        return (f"A TP to {building_words(route['tower'], v.team, v.team)} "
                f"({_n(route['tower_distance'])} units away from it) gets you there in about {route['seconds']:.0f}s")
    return f"Walking there takes about {route['seconds']:.0f}s"


# --------------------------------------------------------------------------- fights you weren't in

def fights_without_you(v: _View, keep: int = 5) -> list[dict[str, Any]]:
    out = []
    last_t = -999.0
    for f in v.rec.events["fights"]:
        start, end = f["start"], f["end"]
        if start < 90 or start - last_t < 45:
            continue
        involved = {fp["pid"] for fp in f["players"]
                    if fp.get("damage_dealt") or fp.get("damage_taken") or fp.get("deaths")}
        if v.me in involved:
            continue
        deaths = v.deaths(start - 1, end + 2)
        ours = [d for d in deaths if _team(d["victim"]) == v.team]
        theirs = [d for d in deaths if _team(d["victim"]) == v.enemy]
        if not ours or len(ours) < len(theirs):
            continue                                            # your team won it without you
        first_death = min(d["t"] for d in ours)
        # You must have been alive (and free to act) from the start until the first death.
        if not all(v.alive(v.me, t) for t in np.arange(start, first_death + 1, 2.0)):
            continue
        fx, fy = (f["x"], f["y"]) if f.get("x") is not None else (ours[0]["x"], ours[0]["y"])
        # A dive: a teammate died within range of your own standing tower.
        dive = None
        for d in ours:
            near = nearest_building(d["x"], d["y"], v.team, v.standing(v.team, d["t"] - 3))
            if near and near[1] <= TOWER_RANGE:
                dive = (d, near[0])
                break
        n_allies = len({p for p in involved if _team(p) == v.team})
        n_enemies = len({p for p in involved if _team(p) == v.enemy})
        if dive is None and (start < 600 or n_enemies < 2 or len(ours) < 2):
            continue                                            # a lane fight or a single pick-off
        if dive is not None and start < 300:
            continue                                            # too early to leave lane for it
        # gem pads fight windows; the part that matters is up to the first death.
        engage = max(start, first_death - 12)
        route = _route_to(v, engage, fx, fy)
        arrive = engage + route["seconds"]
        if arrive > first_death + 3 or route["distance"] < 1200:
            continue                                            # couldn't make it / you were there
        wc = v.win_change(engage - 5, end + 8)
        drop = (wc[0] - wc[1]) if wc else 0
        if dive:
            d, tower = dive
            title = f"{v.hero(d['victim'])} was dived under {building_words(tower, v.team, v.team)} while you were away"
        else:
            title = f"Your team fought {n_allies}v{n_enemies} in {describe(fx, fy, v.team)} without you"
        happened = [
            f"{v.doing(engage - 10, first_death).capitalize()}, {_n(route['distance'])} units from the fight.",
            f"Your team lost {len(ours)} hero{'es' if len(ours) != 1 else ''} and killed {len(theirs)}; "
            f"the first death came at {_clock(first_death)}."
            + (f" Win chance {wc[0]}% → {wc[1]}%." if wc and drop >= 2 else ""),
        ]
        in_time = arrive <= first_death
        instead = (f"{_route_words(v, route)}, {'before the first death' if in_time else 'just as the first hero fell'}"
                   f"{f', making it {n_allies + 1}v{n_enemies}' if n_allies and n_enemies else ''}. "
                   + (f"Under your own tower the fight is in your favour: {'TP' if route['how'] == 'tp' else 'go'} "
                      "in as soon as the dive starts." if dive
                      else "When your team starts a fight you can reach, join it; farm again after."))
        if dive:
            title_vi = f"{v.hero(d['victim'])} bị dive dưới {building_words(tower, v.team, v.team, 'vi')} khi bạn ở xa"
        else:
            title_vi = f"Đội bạn giao tranh {n_allies}v{n_enemies} ở {describe_vi(fx, fy, v.team)} mà không có bạn"
        happened_vi = [
            f"{_cap(v.doing(engage - 10, first_death, 'vi'))}, cách giao tranh {_n(route['distance'])} units.",
            f"Đội bạn mất {len(ours)} hero và hạ {len(theirs)}; người đầu tiên chết lúc {_clock(first_death)}."
            + (f" Tỉ lệ thắng {wc[0]}% → {wc[1]}%." if wc and drop >= 2 else ""),
        ]
        instead_vi = (f"{_route_words(v, route, 'vi')}, {'trước khi có người chết' if in_time else 'đúng lúc hero đầu tiên ngã xuống'}"
                      f"{f', thành {n_allies + 1}v{n_enemies}' if n_allies and n_enemies else ''}. "
                      + (f"Dưới trụ nhà, giao tranh có lợi cho bạn: {'TP' if route['how'] == 'tp' else 'đi'} "
                         "vào ngay khi bị dive." if dive
                         else "Khi đội bạn mở giao tranh mà bạn tới kịp, hãy tham gia; farm lại sau."))
        sev = (max(drop, 0) / 100 if wc else 0.03 * len(ours)) * (1.0 if in_time else 0.7) + 0.02
        last_t = start
        out.append({"kind": "missed_fight", "t": round(engage, 1), "clock": _clock(engage), "x": fx, "y": fy,
                    "title": title, "what_happened": happened, "do_instead": instead,
                    "vi": {"title": title_vi, "what_happened": happened_vi, "do_instead": instead_vi},
                    "severity": round(sev, 3),
                    "evidence": {"team_deaths": len(ours), "enemy_deaths": len(theirs),
                                 "you": v.doing(engage - 10, first_death),
                                 "route": {k: (round(val) if isinstance(val, float) else val)
                                           for k, val in route.items()},
                                 "win_chance": wc, "dive": bool(dive)}})
    out = sorted(out, key=lambda d: -d["severity"])[:keep]
    return sorted(out, key=lambda d: d["t"])


# --------------------------------------------------------------------------- towers lost while away

def towers_lost_far_away(v: _View, taken: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for b in v.rec.events["buildings"]:
        if b["team"] != v.team or b.get("denied") or b["t"] < 300 or b["name"] not in BUILDING_XY[v.team]:
            continue
        t = b["t"]
        if any(abs(x["t"] - t) < 40 for x in taken):
            continue                                            # already covered by a fight
        bx, by = BUILDING_XY[v.team][b["name"]]
        # How long 2+ enemy heroes stood at the building before it fell.
        siege = 0
        for s in range(1, 60):
            near = sum(1 for e in v.enemies if v.alive(e, t - s)
                       and math.dist(v.pos(e, t - s), (bx, by)) <= 1400)
            if near < 2:
                break
            siege = s
        if siege < 8 or not v.alive(v.me, t - siege):
            continue
        allies_there = sum(1 for a in v.allies if v.alive(a, t - 3) and math.dist(v.pos(a, t - 3), (bx, by)) <= 1400)
        enemies_there = sum(1 for e in v.enemies if v.alive(e, t - 3) and math.dist(v.pos(e, t - 3), (bx, by)) <= 1400)
        mx, my = v.pos(v.me, t - siege)
        dist = math.hypot(mx - bx, my - by)
        if dist < 2500:
            continue
        tier = 3 if "rax" in b["name"] else int(b["name"][5]) if b["name"][5].isdigit() else 3
        what = building_words(b["name"], v.team, v.team)
        what_vi = building_words(b["name"], v.team, v.team, "vi")
        out.append({
            "kind": "tower_lost", "t": round(t - siege, 1), "clock": _clock(t - siege), "x": bx, "y": by,
            "title": f"{what.capitalize()} fell to {enemies_there} enemies while you were away",
            "what_happened": [
                f"{enemies_there} enemies hit it for {siege}s before it fell at {_clock(t)}; "
                f"{allies_there} of your teammates were there.",
                f"{v.doing(t - siege, t).capitalize()}, {_n(dist)} units away.",
            ],
            "do_instead": (f"TP to {'the tower' if b['name'].startswith('tower') else 'the nearest tower'} "
                           "as soon as 2+ enemies start hitting it: with the tower's help, "
                           "you and the teammates nearby can hold it. If the fight looks lost, push the opposite "
                           "lane at the same time so they have to choose."),
            "vi": {
                "title": f"{_cap(what_vi)} bị {enemies_there} địch phá khi bạn ở xa",
                "what_happened": [
                    f"{enemies_there} địch đánh trong {siege}s trước khi nó vỡ lúc {_clock(t)}; "
                    f"có {allies_there} đồng đội ở đó.",
                    f"{_cap(v.doing(t - siege, t, 'vi'))}, cách {_n(dist)} units.",
                ],
                "do_instead": (f"TP về {'trụ đó' if b['name'].startswith('tower') else 'trụ gần nhất'} ngay khi 2+ địch "
                               "bắt đầu đánh: có trụ hỗ trợ, bạn và đồng đội gần đó có thể giữ được. Nếu giao tranh "
                               "có vẻ thua, hãy đẩy lane đối diện cùng lúc để địch phải chọn."),
            },
            "severity": round(0.02 + 0.015 * tier, 3),
            "evidence": {"siege_seconds": siege, "enemies": enemies_there, "allies": allies_there,
                         "your_distance": round(dist)},
        })
    return out


# --------------------------------------------------------------------------- advantages not used

def _objectives(v: _View, t0: float, t1: float, lang: str = "en") -> list[str]:
    got = [building_words(b["name"], b["team"], v.team, lang) for b in v.rec.events["buildings"]
           if t0 <= b["t"] <= t1 and b["team"] == v.enemy and not b.get("denied")]
    got += ["Roshan" for r in v.rec.events["roshans"] if t0 <= r["t"] <= t1 and r["team"] == v.team]
    got += ["Tormentor" for r in v.rec.events.get("tormentors", []) if t0 <= r["t"] <= t1 and r["team"] == v.team]
    return got


def advantage_unused(v: _View) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Windows with 3+ enemies dead. Returns (missed, converted)."""
    rec = v.rec
    dead = (rec.hero[:, v.enemies, HF["alive"]] == 0).sum(axis=1)
    rows = np.nonzero((dead >= 3) & (rec.t > 0))[0]
    windows: list[list[int]] = []
    for r in rows:
        if windows and r - windows[-1][1] <= 5:
            windows[-1][1] = r
        else:
            windows.append([r, r])
    missed, converted = [], []
    for r0, r1 in windows:
        ws, we = float(rec.t[r0]), float(rec.t[r1])
        if we - ws < 12 or rec.t[-1] - we < 30:
            continue                                            # too short, or the game ended (won)
        top = int(dead[r0:r1 + 1].max())
        got = _objectives(v, ws - 3, we + 25)
        if got:
            got_vi = _objectives(v, ws - 3, we + 25, "vi")
            converted.append({"kind": "converted", "t": round(ws, 1), "clock": _clock(ws),
                              "title": f"{top} enemies dead → your team took {', '.join(sorted(set(got)))}",
                              "vi": {"title": f"{top} địch chết → đội bạn lấy {', '.join(sorted(set(got_vi)))}"}})
            continue
        if not v.alive(v.me, ws + (we - ws) / 2):
            continue                                            # you were dead for it
        # Options: the closest enemy tower to your living team, Roshan, Tormentor.
        alive_team = [p for p in [v.me, *v.allies] if v.alive(p, ws)]
        cx = float(np.mean([v.pos(p, ws)[0] for p in alive_team]))
        cy = float(np.mean([v.pos(p, ws)[1] for p in alive_team]))
        options, options_vi = [], []
        tower = nearest_building(cx, cy, v.enemy, v.standing(v.enemy, ws), towers_only=False)
        if tower:
            options.append(f"{building_words(tower[0], v.enemy, v.team)} ({_n(tower[1])} units from your team)")
            options_vi.append(f"{building_words(tower[0], v.enemy, v.team, 'vi')} (cách đội bạn {_n(tower[1])} units)")
        since = float(rec.rosh_since_kill[r0])
        if since < 0 or since >= 660:
            options.append("Roshan (up)")
            options_vi.append("Roshan (đang sống)")
        elif since >= 480:
            options.append("Roshan (may be up)")
            options_vi.append("Roshan (có thể đã hồi)")
        last_torm = max((x["t"] for x in rec.events.get("tormentors", []) if x["team"] == v.team and x["t"] < ws),
                        default=None)
        if ws >= 20 * 60 and (last_torm is None or ws - last_torm >= 600):
            options.append("a Tormentor")
            options_vi.append("Tormentor")
        lost_b = [b for b in rec.events["buildings"] if ws <= b["t"] <= we + 25 and b["team"] == v.team]
        lost = [building_words(b["name"], b["team"], v.team) for b in lost_b]
        lost_vi = [building_words(b["name"], b["team"], v.team, "vi") for b in lost_b]
        sev = 0.04 * top * min(1.0, (we - ws) / 30) + (0.02 if v.lh(v.me, we) - v.lh(v.me, ws) >= 4 else 0)
        missed.append({
            "kind": "advantage_unused", "t": round(ws, 1), "clock": _clock(ws), "x": cx, "y": cy,
            "title": f"{top} enemies were dead for {we - ws:.0f}s, but your team took no objective",
            "what_happened": [
                f"From {_clock(ws)} to {_clock(we)} at least 3 of 5 enemies were dead, and your team didn't take a "
                f"tower, Roshan or Tormentor." + (f" They took {', '.join(lost)} instead." if lost else ""),
                f"{v.doing(ws, we).capitalize()}.",
            ],
            "do_instead": ("With 3+ enemies dead, group with your team and hit "
                           + (" or ".join(options) if options else "the nearest enemy tower")
                           + ". Farm after the objective; the dead enemies can't defend it."),
            "vi": {
                "title": f"{top} địch đã chết trong {we - ws:.0f}s, nhưng đội bạn không lấy mục tiêu nào",
                "what_happened": [
                    f"Từ {_clock(ws)} đến {_clock(we)} có ít nhất 3/5 địch đã chết, nhưng đội bạn không lấy "
                    f"trụ, Roshan hay Tormentor." + (f" Địch còn lấy {', '.join(lost_vi)}." if lost_vi else ""),
                    f"{_cap(v.doing(ws, we, 'vi'))}.",
                ],
                "do_instead": ("Khi 3+ địch đã chết, hãy gom cùng đội và đánh "
                               + (" hoặc ".join(options_vi) if options_vi else "trụ địch gần nhất")
                               + ". Farm sau khi lấy mục tiêu; địch đã chết không thể thủ."),
            },
            "severity": round(sev, 3),
            "evidence": {"enemies_dead": top, "seconds": round(we - ws), "options": options, "you": v.doing(ws, we)},
        })
    return missed, converted


# --------------------------------------------------------------------------- runes

def rune_control(v: _View, position: int | None) -> list[dict[str, Any]]:
    runes = [r for r in v.rec.events.get("runes", [])
             if r["rune_type"] in POWER_RUNES and r["pid"] is not None and r["outcome"] != "not_taken"
             and 0 < r["t"] < 20 * 60]
    ours = [r for r in runes if _team(r["pid"]) == v.team]
    theirs = [r for r in runes if _team(r["pid"]) == v.enemy]
    if len(theirs) - len(ours) < 3:
        return []
    takers: dict[int, int] = {}
    for r in theirs:
        takers[r["pid"]] = takers.get(r["pid"], 0) + 1
    top = max(takers, key=takers.get)
    first = theirs[0]
    if position == 2:
        tip = ("Push your wave in before each even minute and stand at the rune 10s early; "
               "ask a support to rotate when the enemy mid is stronger.")
        tip_vi = ("Đẩy wave vào trước mỗi phút chẵn và đứng ở rune sớm 10s; "
                  "nhờ support xoay lên khi mid địch mạnh hơn.")
    elif position in (4, 5):
        tip = ("From 5:50, rotate to the river every 2 minutes to help your mid take the power rune; "
               "a ward over the rune spot makes it safe.")
        tip_vi = ("Từ 5:50, cứ 2 phút xoay ra sông một lần để giúp mid lấy power rune; "
                  "cắm ward ở chỗ rune sẽ an toàn hơn.")
    else:
        tip = ("When your wave is pushed and you'd only be waiting, check the nearest river rune at the even "
               "minute; ping your supports to help your mid with runes.")
        tip_vi = ("Khi wave đã đẩy xong và bạn chỉ đứng chờ, hãy ghé rune ở sông gần nhất vào phút chẵn; "
                  "ping support giúp mid lấy rune.")
    return [{
        "kind": "runes", "t": round(first["t"] - 5, 1), "clock": _clock(first["t"] - 5),
        "x": first["x"], "y": first["y"],
        "title": f"The enemy took {len(theirs)} of {len(runes)} power runes before 20:00",
        "what_happened": [
            f"{v.hero(top)} took {takers[top]} of them; your team took {len(ours)}.",
            "Power runes (Haste, Double Damage, Invisibility...) are how mid heroes gank and win lanes.",
        ],
        "do_instead": tip,
        "vi": {
            "title": f"Địch lấy {len(theirs)}/{len(runes)} power rune trước 20:00",
            "what_happened": [
                f"{v.hero(top)} lấy {takers[top]} cái; đội bạn lấy {len(ours)}.",
                "Power rune (Haste, Double Damage, Invisibility...) là cách các hero mid đi gank và thắng lane.",
            ],
            "do_instead": tip_vi,
        },
        "severity": round(0.012 * (len(theirs) - len(ours)) * (1.0 if position in (2, 4, 5) else 0.6), 3),
        "evidence": {"enemy_runes": len(theirs), "your_team_runes": len(ours),
                     "kinds": sorted({RUNE_NAMES.get(r["rune_type"], "?") for r in theirs})},
    }]


# --------------------------------------------------------------------------- all together

def find_decisions(rec: MatchRecord, me: int, win_at: WinAt = None) -> dict[str, list[dict[str, Any]]]:
    v = _View(rec, me, win_at)
    position = rec.players[me].get("position")
    missed_fights = fights_without_you(v)
    unused, converted = advantage_unused(v)
    found = missed_fights + towers_lost_far_away(v, missed_fights) + unused + rune_control(v, position)
    found.sort(key=lambda d: d["t"])
    return {"missed": found, "converted": converted}
