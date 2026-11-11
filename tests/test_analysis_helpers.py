"""Checks for the small helpers the coach's wording depends on."""
import numpy as np

from mmrslave.analyze import _building_words, _num, area_probabilities
from mmrslave.extract import estimate_positions
from mmrslave.features import GRID
from mmrslave.regions import describe, region_key


def test_regions_from_each_side():
    # Radiant fountain area, Dire fountain area, and the map centre.
    assert describe(8928, 9446, 0) == "your base"
    assert describe(8928, 9446, 1) == "the enemy base"
    assert region_key(16360, 16339) == "mid_lane"
    # Top lane is Dire's safe lane and Radiant's off lane.
    assert describe(10206, 19917, 1) == "your safe lane"
    assert describe(10206, 19917, 0) == "your off lane"


def test_building_words():
    assert _building_words("tower2_mid") == "mid tier-2 tower"
    assert _building_words("range_rax_top") == "top barracks"
    assert _building_words("tower4_b") == "tier-4 tower"


def test_number_formatting():
    assert _num(12506.0) == "12,506"
    assert _num(2.35) == "2.4"
    assert _num(14.0) == "14"


def test_area_probabilities_sum_to_one_and_rank():
    probs = np.full(GRID * GRID, 1.0 / (GRID * GRID))
    areas = area_probabilities(probs, 0)
    assert abs(sum(p for _, p in areas) - 1.0) < 1e-6
    assert [p for _, p in areas] == sorted((p for _, p in areas), reverse=True)


def test_position_estimate_prefers_lane_and_farm():
    team = [
        {"player_id": 0, "lane_role": 1, "net_worth": 30000},   # rich safe laner -> 1
        {"player_id": 1, "lane_role": 2, "net_worth": 25000},   # mid -> 2
        {"player_id": 2, "lane_role": 3, "net_worth": 20000},   # rich off laner -> 3
        {"player_id": 3, "lane_role": 3, "net_worth": 9000},    # poor off laner -> 4
        {"player_id": 4, "lane_role": 1, "net_worth": 7000},    # poor safe laner -> 5
    ]
    assert estimate_positions(team) == {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}
