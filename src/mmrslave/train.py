"""Train the networks on collected high-Immortal games and record how well they do."""

from __future__ import annotations

import json
import math
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import torch
import torch.nn.functional as F

from mmrslave.catalog import Catalog
from mmrslave.config import Settings
from mmrslave.features import (GRID, MatchArrays, build_and_cache, load_cached, mirror_cell)
from mmrslave.models import HeroContextNet, WinProbNet, swap_teams

Log = Callable[[str], None]


def _is_val(match_id: int) -> bool:
    """Stable 10% hold-out: the same match is always in the same split."""
    return zlib.crc32(str(match_id).encode()) % 10 == 0


@dataclass
class Pack:
    """All sampled rows of many matches, stacked, on one device."""
    hero: torch.Tensor      # [N, 10, NH] float16
    glob: torch.Tensor      # [N, NG] float16
    ids: torch.Tensor       # [N, 10]
    pos: torch.Tensor       # [N, 10]
    win: torch.Tensor       # [N] float
    t: torch.Tensor         # [N] game seconds
    dies: torch.Tensor      # [N, 10] float
    cell: torch.Tensor      # [N, 10] int64, -1 invalid
    vis: torch.Tensor       # [N] bool, match has fog-of-war data
    n_matches: int

    def __len__(self) -> int:
        return self.hero.shape[0]


def make_pack(arrays: list[MatchArrays], device: str) -> Pack:
    def cat(f, dtype=None):
        x = torch.from_numpy(np.concatenate([f(a) for a in arrays]))
        return x.to(device=device, dtype=dtype) if dtype else x.to(device)
    rep = lambda a, v: np.repeat(v[None], len(a.t), 0)
    return Pack(
        hero=cat(lambda a: a.hero, torch.float16), glob=cat(lambda a: a.glob, torch.float16),
        ids=cat(lambda a: rep(a, a.hero_ids)), pos=cat(lambda a: rep(a, a.positions)),
        win=cat(lambda a: np.full(len(a.t), a.radiant_win, np.float32)), t=cat(lambda a: a.t),
        dies=cat(lambda a: a.dies_soon), cell=cat(lambda a: a.future_cell),
        vis=cat(lambda a: np.full(len(a.t), a.has_visibility)), n_matches=len(arrays),
    )


def load_training_data(s: Settings, log: Log, min_avg_mmr: float = 0.0, limit: int | None = None,
                       workers: int = 12) -> tuple[list[MatchArrays], list[MatchArrays]]:
    cat = Catalog(s.catalog_path)
    q = "SELECT match_id FROM matches WHERE source='immortal' AND status='parsed'"
    args: list = []
    if min_avg_mmr:
        q += " AND avg_mmr >= ?"
        args.append(min_avg_mmr)
    q += " ORDER BY match_id DESC"
    ids = [r[0] for r in cat.db.execute(q, args)]
    cat.close()
    if limit:
        ids = ids[:limit]
    cache_dir = s.models_dir / "cache"
    log(f"building features for {len(ids)} matches")
    with ProcessPoolExecutor(workers) as ex:
        paths = list(ex.map(build_and_cache, [s.matches_dir] * len(ids), [cache_dir] * len(ids), ids,
                            chunksize=8))
    arrays = [load_cached(p) for p in paths if p is not None]
    train = [a for a in arrays if not _is_val(a.match_id)]
    val = [a for a in arrays if _is_val(a.match_id)]
    log(f"loaded {len(train)} training and {len(val)} validation matches "
        f"({sum(len(a.t) for a in arrays):,} game moments)")
    return train, val


# --------------------------------------------------------------------------- shared loop

def _batches(n: int, bs: int, shuffle: bool, device: str):
    idx = torch.randperm(n, device=device) if shuffle else torch.arange(n, device=device)
    for i in range(0, n, bs):
        yield idx[i:i + bs]


def _schedule(opt: torch.optim.Optimizer, step: int, total: int, base_lr: float, warmup: int = 300) -> None:
    lr = base_lr * min(1.0, (step + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(step / max(total, 1), 1.0)))
    for g in opt.param_groups:
        g["lr"] = max(lr, base_lr * 0.02)


# --------------------------------------------------------------------------- win probability

def train_winprob(train: Pack, val: Pack, device: str, log: Log, epochs: int = 12, bs: int = 2048,
                  lr: float = 3e-4) -> tuple[WinProbNet, dict]:
    # Every moment of a game shares one label, so the network can "remember" games by their
    # hero line-ups instead of learning what wins. Smaller model, heavier regularization,
    # and randomly hidden hero identities push it to learn from the game state.
    small = train.n_matches < 2000
    model = WinProbNet(d=96 if small else 160, layers=3 if small else 4, dropout=0.2 if small else 0.1).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.1)
    # Neighbouring seconds of one game are near-copies, so each pass sees a fresh random quarter
    # of all moments: more passes, less memorising of individual games.
    frac = 0.25
    epochs = epochs * 2
    steps_per_epoch = math.ceil(len(train) * frac / bs)
    total, step = steps_per_epoch * epochs, 0
    best, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        model.train()
        t0, run = time.time(), 0.0
        subset = torch.randperm(len(train), device=device)[: int(len(train) * frac)]
        for b in (subset[i:i + bs] for i in range(0, len(subset), bs)):
            hero, glob = train.hero[b].float(), train.glob[b].float()
            ids, pos, y = train.ids[b], train.pos[b], train.win[b]
            flip = torch.rand(len(b), device=device) < 0.5
            hero, glob, ids, pos = swap_teams(hero, glob, ids, pos, flip)
            y = torch.where(flip, 1 - y, y)
            ids = torch.where(torch.rand(ids.shape, device=device) < 0.5, torch.zeros_like(ids), ids)
            hero = hero + torch.randn_like(hero) * 0.02
            _schedule(opt, step, total, lr)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
                logit = model(hero, glob, ids, pos)
            loss = F.binary_cross_entropy_with_logits(logit.float(), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            run += loss.item()
            step += 1
        m = eval_winprob(model, val, device)
        log(f"win-prob epoch {ep + 1}/{epochs}: train loss {run / steps_per_epoch:.4f} | "
            f"val loss {m['log_loss']:.4f} acc {m['accuracy']:.3f} | {time.time() - t0:.0f}s")
        if m["log_loss"] < best - 1e-4:
            best, bad = m["log_loss"], 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 4:
                log("win-prob: validation stopped improving, stopping early")
                break
    if best_state:
        model.load_state_dict(best_state)
    calibrate_winprob(model, val, device, log)
    return model, eval_winprob(model, val, device)


@torch.no_grad()
def calibrate_winprob(model: WinProbNet, val: Pack, device: str, log: Log, bs: int = 8192) -> None:
    """Temperature scaling: one number that makes the probabilities honest on held-out games."""
    model.eval()
    logits = []
    for b in _batches(len(val), bs, False, device):
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            logits.append(model.raw_logit(val.hero[b].float(), val.glob[b].float(), val.ids[b], val.pos[b]).float())
    z = torch.cat(logits)
    best_t, best_ll = 1.0, float("inf")
    for t in torch.arange(0.5, 4.01, 0.05).tolist():
        ll = F.binary_cross_entropy_with_logits(z / t, val.win).item()
        if ll < best_ll:
            best_t, best_ll = t, ll
    model.temperature.fill_(best_t)
    p = torch.sigmoid(z / best_t)
    hi = p > 0.9
    hi_acc = ((p[hi] > 0.5).float() == val.win[hi]).float().mean().item() if hi.any() else float("nan")
    log(f"win-prob calibration: temperature {best_t:.2f}; when it says >90%, it's right {hi_acc:.0%} of the time")


@torch.no_grad()
def eval_winprob(model: WinProbNet, val: Pack, device: str, bs: int = 8192) -> dict:
    model.eval()
    ps = []
    for b in _batches(len(val), bs, False, device):
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            ps.append(torch.sigmoid(model(val.hero[b].float(), val.glob[b].float(), val.ids[b], val.pos[b]).float()))
    p = torch.cat(ps).clamp(1e-5, 1 - 1e-5)
    y = val.win
    ll = -(y * p.log() + (1 - y) * (1 - p).log())
    acc = ((p > 0.5).float() == y).float()
    out = {"log_loss": ll.mean().item(), "accuracy": acc.mean().item(), "brier": ((p - y) ** 2).mean().item(),
           "by_minute": {}}
    for lo, hi in ((0, 10), (10, 20), (20, 30), (30, 45), (45, 200)):
        m = (val.t >= lo * 60) & (val.t < hi * 60)
        if m.any():
            out["by_minute"][f"{lo}-{hi}"] = {"accuracy": acc[m].mean().item(), "log_loss": ll[m].mean().item(),
                                             "n": int(m.sum())}
    return out


# --------------------------------------------------------------------------- hero context (risk + movement)

def _context_samples(pack: Pack) -> torch.Tensor:
    """(row, hero) pairs where the hero is alive, from matches with fog-of-war data."""
    from mmrslave.features import HC
    alive = pack.hero[..., HC["alive"]] > 0.5
    ok = alive & pack.vis.unsqueeze(1)
    return ok.nonzero()            # [M, 2] (row, hero)


def _context_batch(pack: Pack, pairs: torch.Tensor):
    rows, focus = pairs[:, 0], pairs[:, 1]
    cell = pack.cell[rows, focus]
    dire = focus >= 5
    cell = torch.where((cell >= 0) & dire, (GRID * GRID - 1) - cell, cell)   # mirror into canonical frame
    return (pack.hero[rows].float(), pack.glob[rows].float(), pack.ids[rows], pack.pos[rows], focus,
            pack.dies[rows, focus], cell)


def train_context(train: Pack, val: Pack, device: str, log: Log, epochs: int = 8, bs: int = 2048,
                  lr: float = 4e-4) -> tuple[HeroContextNet, dict]:
    model = HeroContextNet().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.05)
    pairs = _context_samples(train)
    vpairs = _context_samples(val)
    if len(pairs) == 0 or len(vpairs) == 0:
        raise RuntimeError("no matches with fog-of-war data to train the hero-context model on")
    steps_per_epoch = math.ceil(len(pairs) / bs)
    total, step = steps_per_epoch * epochs, 0
    best, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        model.train()
        t0, run_r, run_m = time.time(), 0.0, 0.0
        for b in _batches(len(pairs), bs, True, device):
            hero, glob, ids, pos, focus, dies, cell = _context_batch(train, pairs[b])
            _schedule(opt, step, total, lr)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
                risk, move = model(hero, glob, ids, pos, focus)
            loss_r = F.binary_cross_entropy_with_logits(risk.float(), dies)
            valid = cell >= 0
            loss_m = F.cross_entropy(move.float()[valid], cell[valid]) if valid.any() else risk.sum() * 0
            loss = loss_r * 4 + loss_m * 0.5
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            run_r += loss_r.item()
            run_m += loss_m.item()
            step += 1
        m = eval_context(model, val, vpairs, device)
        log(f"hero-context epoch {ep + 1}/{epochs}: risk loss {run_r / steps_per_epoch:.4f} "
            f"move loss {run_m / steps_per_epoch:.3f} | val risk AUC {m['risk_auc']:.3f} "
            f"move top-1 {m['move_top1']:.3f} top-5 {m['move_top5']:.3f} | {time.time() - t0:.0f}s")
        score = m["risk_log_loss"] * 4 + m["move_loss"] * 0.5
        if score < best - 1e-4:
            best, bad = score, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                log("hero-context: validation stopped improving, stopping early")
                break
    if best_state:
        model.load_state_dict(best_state)
    return model, eval_context(model, val, vpairs, device)


@torch.no_grad()
def eval_context(model: HeroContextNet, val: Pack, vpairs: torch.Tensor, device: str, bs: int = 8192) -> dict:
    model.eval()
    risks, ys, mloss, top1, top5, stay, nvalid = [], [], 0.0, 0, 0, 0, 0
    from mmrslave.features import HC, MAP_CX, MAP_CY, MAP_SCALE, world_to_cell
    for b in _batches(len(vpairs), bs, False, device):
        hero, glob, ids, pos, focus, dies, cell = _context_batch(val, vpairs[b])
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            risk, move = model(hero, glob, ids, pos, focus)
        risks.append(torch.sigmoid(risk.float()))
        ys.append(dies)
        v = cell >= 0
        if v.any():
            mv = move.float()[v]
            mloss += F.cross_entropy(mv, cell[v], reduction="sum").item()
            top = mv.topk(5, dim=-1).indices
            top1 += (top[:, 0] == cell[v]).sum().item()
            top5 += (top == cell[v].unsqueeze(1)).any(1).sum().item()
            # baseline: "stays where it is now"
            fx = hero[v, focus[v], HC["x"]].cpu().numpy() * MAP_SCALE + MAP_CX
            fy = hero[v, focus[v], HC["y"]].cpu().numpy() * MAP_SCALE + MAP_CY
            now = torch.from_numpy(world_to_cell(fx, fy)).to(device)
            now = torch.where(focus[v] >= 5, (GRID * GRID - 1) - now, now)
            stay += (now == cell[v]).sum().item()
            nvalid += int(v.sum())
    p = torch.cat(risks).clamp(1e-5, 1 - 1e-5)
    y = torch.cat(ys)
    return {
        "risk_auc": _auc(p, y), "risk_log_loss": (-(y * p.log() + (1 - y) * (1 - p).log())).mean().item(),
        "risk_base_rate": y.mean().item(),
        "move_loss": mloss / max(nvalid, 1), "move_top1": top1 / max(nvalid, 1), "move_top5": top5 / max(nvalid, 1),
        "move_stay_baseline_top1": stay / max(nvalid, 1),
    }


def _auc(p: torch.Tensor, y: torch.Tensor) -> float:
    order = torch.argsort(p)
    y = y[order]
    n_pos, n_neg = y.sum().item(), (1 - y).sum().item()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = torch.arange(1, len(y) + 1, device=y.device, dtype=torch.float64)
    return ((ranks * y).sum().item() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


# --------------------------------------------------------------------------- entry point

def train_all(s: Settings, log: Log, *, epochs_wp: int = 12, epochs_ctx: int = 8, limit: int | None = None,
              min_avg_mmr: float = 0.0, which: tuple[str, ...] = ("winprob", "context")) -> dict:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.backends.cuda.matmul.allow_tf32 = True
    train_arr, val_arr = load_training_data(s, log, min_avg_mmr=min_avg_mmr, limit=limit)
    if len(train_arr) < 20 or len(val_arr) < 2:
        raise SystemExit(f"Only {len(train_arr) + len(val_arr)} Immortal matches parsed so far; "
                         "collect more first (python -m mmrslave collect).")
    train, val = make_pack(train_arr, device), make_pack(val_arr, device)
    del train_arr, val_arr
    s.models_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    results: dict = {"trained_at": stamp, "train_matches": train.n_matches, "val_matches": val.n_matches}

    if "winprob" in which:
        model, metrics = train_winprob(train, val, device, log, epochs=epochs_wp)
        torch.save({"state": model.state_dict(), "metrics": metrics, "config": model.config, **results},
                   s.models_dir / "winprob.pt")
        results["winprob"] = metrics
        log(f"win-prob saved: val accuracy {metrics['accuracy']:.3f}, log loss {metrics['log_loss']:.4f}")
    if "context" in which:
        model, metrics = train_context(train, val, device, log, epochs=epochs_ctx)
        torch.save({"state": model.state_dict(), "metrics": metrics, **results}, s.models_dir / "context.pt")
        results["context"] = metrics
        log(f"hero-context saved: death-risk AUC {metrics['risk_auc']:.3f}, "
            f"next-position top-5 {metrics['move_top5']:.3f}")

    with open(s.models_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(results) + "\n")
    return results


def load_models(s: Settings, device: str | None = None) -> tuple[WinProbNet | None, HeroContextNet | None]:
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    out = []
    for name, cls in (("winprob.pt", WinProbNet), ("context.pt", HeroContextNet)):
        path = s.models_dir / name
        if not path.exists():
            out.append(None)
            continue
        ck = torch.load(path, map_location=device, weights_only=False)
        m = cls(**ck.get("config", {})).to(device)
        m.load_state_dict(ck["state"])
        m.eval()
        out.append(m)
    return out[0], out[1]
