"""Checks for the map mirroring and team-perspective code the models depend on."""
import numpy as np
import torch

from mmrslave.features import (GRID, HC, MAP_CX, MAP_CY, MAP_SCALE, NG, NH, cell_center,
                               mirror_cell, world_to_cell)
from mmrslave.models import HeroContextNet, WinProbNet, perspective, swap_teams


def _batch(B=6, seed=0):
    g = torch.Generator().manual_seed(seed)
    hero = torch.rand(B, 10, NH, generator=g) * 2 - 1
    glob = torch.rand(B, NG, generator=g)
    ids = torch.randint(1, 150, (B, 10), generator=g)
    pos = torch.randint(1, 6, (B, 10), generator=g)
    return hero, glob, ids, pos


def test_swap_twice_is_identity():
    hero, glob, ids, pos = _batch()
    mask = torch.tensor([True, False, True, True, False, True])
    h2, g2, i2, p2 = swap_teams(*swap_teams(hero, glob, ids, pos, mask), mask)
    assert torch.allclose(h2, hero) and torch.allclose(g2, glob)
    assert torch.equal(i2, ids) and torch.equal(p2, pos)


def test_mirror_cell_matches_coordinate_reflection():
    rng = np.random.default_rng(1)
    x = rng.uniform(MAP_CX - 9000, MAP_CX + 9000, 1000)
    y = rng.uniform(MAP_CY - 9000, MAP_CY + 9000, 1000)
    # reflect through the map centre, as swap_teams does for normalized coords
    xr, yr = 2 * MAP_CX - x, 2 * MAP_CY - y
    same = mirror_cell(world_to_cell(x, y)) == world_to_cell(xr, yr)
    assert same.mean() > 0.995          # only exact cell-boundary points may differ
    cx, cy = cell_center(world_to_cell(x, y))
    assert np.all(np.abs(cx - x) <= 9250 / GRID * 1.01) and np.all(np.abs(cy - y) <= 9250 / GRID * 1.01)


def test_perspective_puts_focus_first_and_hides_unseen_enemies():
    hero, glob, ids, pos = _batch(B=2)
    hero[..., HC["vis_hidden"]] = 0
    hero[..., HC["vis_seen"]] = 1
    hero[0, 7, HC["vis_hidden"]] = 1          # Dire slot 7 hidden from Radiant
    hero[0, 7, HC["vis_seen"]] = 0
    focus = torch.tensor([2, 8])
    feats, g, i, p = perspective(hero, glob, ids, pos, focus)
    assert i[0, 0] == ids[0, 2] and i[1, 0] == ids[1, 8]
    assert set(i[1, 1:5].tolist()) == set(ids[1, [5, 6, 7, 9]].tolist())   # Dire allies of slot 8
    assert set(i[1, 5:].tolist()) == set(ids[1, :5].tolist())               # Radiant are the enemies
    # hidden enemy: shown at last-seen spot, no HP info
    k = (i[0] == ids[0, 7]).nonzero()[0, 0]
    assert torch.isclose(feats[0, k, 0], hero[0, 7, HC["seen_x"]])
    assert feats[0, k, 6] == 0
    # Dire focus is mirrored: its own x is the negated raw x
    assert torch.isclose(feats[1, 0, 0], -hero[1, 8, HC["x"]])


def test_models_run_and_winprob_is_side_symmetric_shape():
    hero, glob, ids, pos = _batch(B=4)
    wp = WinProbNet().eval()
    assert wp(hero, glob, ids, pos).shape == (4,)
    ctx = HeroContextNet().eval()
    r, m = ctx(hero, glob, ids, pos, torch.tensor([0, 4, 5, 9]))
    assert r.shape == (4,) and m.shape == (4, GRID * GRID)
