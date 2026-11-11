"""Immortal curve bands and map landmarks used by the decision checks."""

from mmrslave.benchmarks import MIN_CURVE_N, _curve_bands
from mmrslave.landmarks import building_words, nearest_building


def test_curve_bands_stop_when_few_games_remain():
    # 10 games reach minute 2, only 3 reach minute 3: the band ends at minute 2.
    rows = [{"curves": {"nw": [0, 100 * i, 200 * i] + ([300 * i] if i < 3 else [])}} for i in range(10)]
    b = _curve_bands(rows)["nw"]
    assert len(b["p50"]) == 3 and b["n"] == [10, 10, 10]
    assert b["p25"][2] <= b["p50"][2] <= b["p75"][2]
    assert MIN_CURVE_N > 3


def test_building_words_and_nearest_tower():
    assert building_words("tower2_mid", 0, 0) == "your mid tier-2 tower"
    assert building_words("melee_rax_top", 1, 0) == "their top barracks"
    name, d = nearest_building(14840, 14976, 0)
    assert name == "tower1_mid" and d == 0
    name, _ = nearest_building(14840, 14976, 0, standing={"tower3_mid", "tower2_bot"})
    assert name == "tower3_mid"
