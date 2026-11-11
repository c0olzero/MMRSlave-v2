"""Small OpenDota API client with rate limiting and retries.

Free tier: 60 calls/minute and 3,000 calls/day. The client spaces calls out and
stops cleanly when the daily budget is nearly used up.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from mmrslave.config import opendota_api_key

API = "https://api.opendota.com/api"
IMMORTAL_RANK_TIER = 80
RANKED_LOBBY = 7
ALL_PICK_RANKED = 22


class OpenDotaError(Exception):
    pass


class BudgetExhausted(OpenDotaError):
    """The daily API call allowance is used up."""


class OpenDota:
    def __init__(self, delay_s: float = 1.1, min_daily_remaining: int = 25):
        self.delay_s = delay_s
        self.min_daily_remaining = min_daily_remaining
        self.key = opendota_api_key()
        self.client = httpx.Client(timeout=30, headers={"User-Agent": "MMRSlave/0.1"}, follow_redirects=True)
        self._last_call = 0.0
        self.remaining_minute: int | None = None
        self.remaining_day: int | None = None
        self.calls = 0

    def close(self) -> None:
        self.client.close()

    def get(self, path: str, params: dict[str, Any] | None = None, method: str = "GET") -> Any:
        if self.remaining_day is not None and self.remaining_day <= self.min_daily_remaining:
            raise BudgetExhausted(f"OpenDota daily budget nearly used ({self.remaining_day} left)")
        params = dict(params or {})
        if self.key:
            params["api_key"] = self.key
        for attempt in range(5):
            wait = self.delay_s - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                r = self.client.request(method, f"{API}{path}", params=params)
            except httpx.HTTPError as e:
                if attempt == 4:
                    raise OpenDotaError(f"{path}: {e}") from e
                time.sleep(5 * (attempt + 1))
                continue
            self.calls += 1
            self._read_limits(r)
            if r.status_code == 429:
                time.sleep(30 if self.remaining_minute == 0 else 5)
                continue
            if r.status_code >= 500:
                # OpenDota and its Cloudflare front return 5xx during outages.
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                raise OpenDotaError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
            return r.json()
        raise OpenDotaError(f"{path}: gave up after retries (OpenDota may be down)")

    def _read_limits(self, r: httpx.Response) -> None:
        for header, attr in (("x-rate-limit-remaining-minute", "remaining_minute"),
                             ("x-rate-limit-remaining-day", "remaining_day")):
            v = r.headers.get(header)
            if v is not None and v.lstrip("-").isdigit():
                setattr(self, attr, int(v))

    # ---- endpoints
    def public_matches(self, less_than_match_id: int | None = None, min_rank: int = 75) -> list[dict[str, Any]]:
        """Recent public matches in the top bracket. The listed average rank is capped
        at 75, so Immortal games show up as 75 here and are checked per player later."""
        params: dict[str, Any] = {"min_rank": min_rank}
        if less_than_match_id:
            params["less_than_match_id"] = less_than_match_id
        return self.get("/publicMatches", params) or []

    def match(self, match_id: int) -> dict[str, Any] | None:
        return self.get(f"/matches/{match_id}")

    def player_matches(self, account_id: int, limit: int = 20, **filters: Any) -> list[dict[str, Any]]:
        return self.get(f"/players/{account_id}/matches", {"limit": limit, **filters}) or []

    def request_parse(self, match_id: int) -> Any:
        """Ask OpenDota to fetch a match's replay info (fills in replay_url for new matches)."""
        return self.get(f"/request/{match_id}", method="POST")


def match_quality(detail: dict[str, Any]) -> dict[str, Any]:
    """Skill summary of a match from its detail record."""
    players = detail.get("players") or []
    tiers = [p.get("rank_tier") for p in players]
    mmrs = [p["computed_mmr"] for p in players if isinstance(p.get("computed_mmr"), (int, float))]
    return {
        "n_immortal": sum(1 for t in tiers if isinstance(t, int) and t >= IMMORTAL_RANK_TIER),
        "avg_mmr": round(sum(mmrs) / len(mmrs), 1) if mmrs else None,
        "patch": detail.get("patch"),
        "start_time": detail.get("start_time"),
        "duration": detail.get("duration"),
        "replay_url": detail.get("replay_url"),
        "lobby_type": detail.get("lobby_type"),
        "game_mode": detail.get("game_mode"),
        "abandons": sum(1 for p in players if (p.get("leaver_status") or 0) > 1),
    }
