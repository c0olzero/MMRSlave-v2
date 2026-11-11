"""Neural networks.

WinProbNet      whole-game view -> P(Radiant wins). Used to measure how much each
                event (a death, a lost tower) changed the game.
HeroContextNet  one hero's view of the game, using only what their team could see ->
                  * risk: P(this hero dies in the next 15 s)
                  * move: where a high-Immortal player would be in 30 s (24x24 map grid)

Both treat each hero as a token in a small transformer, plus one token for
game-wide state (time, buildings, Roshan, wards).
"""

from __future__ import annotations

import torch
from torch import nn

from mmrslave.features import GC, GRID, HC, HERO_ID_VOCAB, NB, NG

# ---- index helpers for swapping teams in the global vector
_R_B = slice(GC["r_" + "tower1_top"], GC["r_" + "tower1_top"] + NB)
_D_B = slice(GC["d_" + "tower1_top"], GC["d_" + "tower1_top"] + NB)
_R_W = [GC["r_obs"], GC["r_sen"]]
_D_W = [GC["d_obs"], GC["d_sen"]]
_XY = [HC["x"], HC["y"], HC["seen_x"], HC["seen_y"]]

WP_HERO_COLS = [HC[c] for c in (
    "x", "y", "alive", "hp_frac", "max_hp", "mana_frac", "max_mana", "level", "net_worth", "gold",
    "lh", "dn", "respawn", "kills", "deaths", "vis_seen", "vis_hidden", "vis_unknown", "aegis")]


def swap_teams(hero: torch.Tensor, glob: torch.Tensor, ids: torch.Tensor, pos: torch.Tensor,
               mask: torch.Tensor) -> tuple[torch.Tensor, ...]:
    """For rows where mask is True: mirror the map and swap Radiant/Dire."""
    if not mask.any():
        return hero, glob, ids, pos
    m3 = mask.view(-1, 1, 1)
    h2 = torch.cat([hero[:, 5:], hero[:, :5]], dim=1).clone()
    h2[..., _XY] = -h2[..., _XY]
    g2 = glob.clone()
    g2[:, _R_B], g2[:, _D_B] = glob[:, _D_B], glob[:, _R_B]
    g2[:, _R_W], g2[:, _D_W] = glob[:, _D_W], glob[:, _R_W]
    ids2 = torch.cat([ids[:, 5:], ids[:, :5]], dim=1)
    pos2 = torch.cat([pos[:, 5:], pos[:, :5]], dim=1)
    m2 = mask.view(-1, 1)
    return (torch.where(m3, h2, hero), torch.where(m2, g2, glob),
            torch.where(m2, ids2, ids), torch.where(m2, pos2, pos))


class _Encoder(nn.Module):
    def __init__(self, d: int, layers: int, heads: int, dropout: float):
        super().__init__()
        layer = nn.TransformerEncoderLayer(d, heads, dim_feedforward=d * 4, dropout=dropout,
                                           batch_first=True, norm_first=True, activation="gelu")
        self.enc = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.norm(self.enc(x))


N_TEAM_SUMMARY = 9


def team_summary(hero: torch.Tensor) -> torch.Tensor:
    """Team-level totals the network would otherwise have to work out: heroes alive, levels,
    net worth (in units of 10k gold) and its gap, and seconds of respawn waiting. [B, 9]"""
    alive, lvl = hero[..., HC["alive"]], hero[..., HC["level"]]
    nw = torch.expm1(hero[..., HC["net_worth"]].clamp(0, 1.2) * 11) / 10000
    resp = hero[..., HC["respawn"]]
    r, d = slice(0, 5), slice(5, 10)
    return torch.stack([
        alive[:, r].mean(1), alive[:, d].mean(1), lvl[:, r].mean(1), lvl[:, d].mean(1),
        nw[:, r].mean(1), nw[:, d].mean(1), (nw[:, r].sum(1) - nw[:, d].sum(1)) / 5,
        resp[:, r].mean(1), resp[:, d].mean(1),
    ], dim=-1)


class WinProbNet(nn.Module):
    def __init__(self, d: int = 160, layers: int = 4, heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.config = {"d": d, "layers": layers, "heads": heads, "dropout": dropout}
        self.hero_in = nn.Linear(len(WP_HERO_COLS), d)
        self.hero_emb = nn.Embedding(HERO_ID_VOCAB, d)
        self.pos_emb = nn.Embedding(6, d)
        self.team_emb = nn.Embedding(2, d)
        self.glob_in = nn.Linear(NG + N_TEAM_SUMMARY, d)
        self.enc = _Encoder(d, layers, heads, dropout)
        self.head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.register_buffer("team_idx", torch.tensor([0] * 5 + [1] * 5), persistent=False)
        # Fitted after training on held-out games so that "80%" really means about 8 in 10.
        self.register_buffer("temperature", torch.tensor(1.0))

    def forward(self, hero: torch.Tensor, glob: torch.Tensor, ids: torch.Tensor, pos: torch.Tensor) -> torch.Tensor:
        """Returns the calibrated logit of P(Radiant wins). hero [B,10,NH], glob [B,NG], ids/pos [B,10]."""
        return self.raw_logit(hero, glob, ids, pos) / self.temperature

    def raw_logit(self, hero: torch.Tensor, glob: torch.Tensor, ids: torch.Tensor, pos: torch.Tensor) -> torch.Tensor:
        tok = self.hero_in(hero[..., WP_HERO_COLS]) + self.hero_emb(ids) + self.pos_emb(pos.clamp(0, 5)) \
            + self.team_emb(self.team_idx)
        g = self.glob_in(torch.cat([glob, team_summary(hero)], dim=-1)).unsqueeze(1)
        x = self.enc(torch.cat([g, tok], dim=1))
        return self.head(x[:, 0]).squeeze(-1)


# --------------------------------------------------------------------------- hero perspective

CTX_IN = 26


def perspective(hero: torch.Tensor, glob: torch.Tensor, ids: torch.Tensor, pos: torch.Tensor,
                focus: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Build the view of the game from one hero's team.

    focus [B] is the hero slot (0-9). The result is canonical: the focus team always
    plays from the Radiant corner, token 0 is the focus hero, 1-4 allies, 5-9 enemies.
    Enemies that are hidden appear where they were last seen, with no HP/mana info.
    """
    B = hero.shape[0]
    dire = focus >= 5
    hero, glob, ids, pos = swap_teams(hero, glob, ids, pos, dire)
    local = torch.where(dire, focus - 5, focus)                       # focus index within team 0..4

    # order: focus first, then the other 4 allies, then enemies
    ar = torch.arange(5, device=hero.device).expand(B, 5)
    others = ar[ar != local.unsqueeze(1)].view(B, 4)
    order = torch.cat([local.unsqueeze(1), others, torch.arange(5, 10, device=hero.device).expand(B, 5)], 1)
    h = torch.gather(hero, 1, order.unsqueeze(-1).expand(-1, -1, hero.shape[-1]))
    ids = torch.gather(ids, 1, order)
    pos = torch.gather(pos, 1, order)

    enemy = torch.zeros(B, 10, 1, device=hero.device, dtype=torch.bool)
    enemy[:, 5:] = True
    hidden = (h[..., HC["vis_hidden"]:HC["vis_hidden"] + 1] > 0.5) & enemy
    x = torch.where(hidden, h[..., HC["seen_x"]:HC["seen_x"] + 1], h[..., HC["x"]:HC["x"] + 1])
    y = torch.where(hidden, h[..., HC["seen_y"]:HC["seen_y"] + 1], h[..., HC["y"]:HC["y"] + 1])
    dx, dy = (x - x[:, :1]) * 3, (y - y[:, :1]) * 3
    dist = torch.sqrt(dx * dx + dy * dy + 1e-6)
    unknown_stat = hidden.float()
    keep = 1 - unknown_stat

    def col(name: str) -> torch.Tensor:
        return h[..., HC[name]:HC[name] + 1]

    is_self = torch.zeros(B, 10, 1, device=hero.device)
    is_self[:, 0] = 1
    is_ally = torch.zeros(B, 10, 1, device=hero.device)
    is_ally[:, 1:5] = 1
    feats = torch.cat([
        x, y, dx, dy, dist.clamp(max=6),
        col("alive"), col("hp_frac") * keep, col("max_hp"), col("mana_frac") * keep, col("max_mana"),
        col("level"), col("net_worth"), col("gold") * (~enemy).float(), col("lh"), col("dn"), col("respawn"),
        col("kills"), col("deaths"), col("vis_seen"), col("vis_hidden"), col("vis_unknown"), col("aegis"),
        col("since_seen") * enemy.float(), is_self, is_ally, enemy.float(),
    ], dim=-1)
    return feats, glob, ids, pos


class HeroContextNet(nn.Module):
    def __init__(self, d: int = 192, layers: int = 4, heads: int = 6, dropout: float = 0.1):
        super().__init__()
        self.tok_in = nn.Linear(CTX_IN, d)
        self.hero_emb = nn.Embedding(HERO_ID_VOCAB, d)
        self.pos_emb = nn.Embedding(6, d)
        self.glob_in = nn.Linear(NG, d)
        self.enc = _Encoder(d, layers, heads, dropout)
        self.risk_head = nn.Sequential(nn.Linear(2 * d, d), nn.GELU(), nn.Linear(d, 1))
        self.move_head = nn.Sequential(nn.Linear(2 * d, d), nn.GELU(), nn.Linear(d, GRID * GRID))

    def forward(self, hero: torch.Tensor, glob: torch.Tensor, ids: torch.Tensor, pos: torch.Tensor,
                focus: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns (risk logit [B], move logits [B, GRID*GRID]) in the canonical (Radiant-corner) frame."""
        feats, g, ids, pos = perspective(hero, glob, ids, pos, focus)
        tok = self.tok_in(feats) + self.hero_emb(ids) + self.pos_emb(pos.clamp(0, 5))
        x = self.enc(torch.cat([self.glob_in(g).unsqueeze(1), tok], dim=1))
        z = torch.cat([x[:, 0], x[:, 1]], dim=-1)          # game token + focus hero token
        return self.risk_head(z).squeeze(-1), self.move_head(z)
