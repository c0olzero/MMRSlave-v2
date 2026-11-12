"""Connecting a Steam account with "Sign in through Steam" (Steam's OpenID 2.0 login).

You sign in on steamcommunity.com itself; Steam then sends the browser back to the local
dashboard with your Steam ID, signed by Steam. We ask Steam to confirm that signature before
trusting it. The app never sees your password and gets no access to your account: it only
learns which Steam ID is yours, the same number that is public on your profile.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from mmrslave.config import STEAM_ID64_BASE

OPENID_URL = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
CLAIMED_ID = re.compile(r"^https://steamcommunity\.com/openid/id/(7656119\d{10})$")
HEADERS = {"User-Agent": "MMRSlave/0.1"}
# A sign-in has this long to come back before its one-time token expires.
STATE_TTL_S = 15 * 60


class SteamLoginError(Exception):
    pass


class SteamLogin:
    """One-time tokens for sign-ins in progress, so only a login this app started is accepted."""

    def __init__(self) -> None:
        self._pending: dict[str, float] = {}

    def login_url(self, base_url: str) -> str:
        """Steam's sign-in page; it sends the browser back to `base_url`/auth/steam/callback."""
        now = time.time()
        self._pending = {k: v for k, v in self._pending.items() if now - v < STATE_TTL_S}
        state = secrets.token_urlsafe(16)
        self._pending[state] = now
        base = base_url.rstrip("/")
        params = {
            "openid.ns": OPENID_NS,
            "openid.mode": "checkid_setup",
            "openid.return_to": f"{base}/auth/steam/callback?state={state}",
            "openid.realm": f"{base}/",
            "openid.identity": f"{OPENID_NS}/identifier_select",
            "openid.claimed_id": f"{OPENID_NS}/identifier_select",
        }
        return f"{OPENID_URL}?{urlencode(params)}"

    def verify(self, query: dict[str, str], base_url: str) -> int:
        """Check Steam's answer and return the 64-bit Steam ID it vouches for."""
        state = query.get("state", "")
        started = self._pending.pop(state, None)
        if started is None or time.time() - started > STATE_TTL_S:
            raise SteamLoginError("This sign-in link expired or wasn't started here. Try again.")
        if query.get("openid.mode") != "id_res":
            raise SteamLoginError("Steam sign-in was cancelled.")
        expected = f"{base_url.rstrip('/')}/auth/steam/callback?state={state}"
        if query.get("openid.return_to") != expected:
            raise SteamLoginError("Steam sent the sign-in back to a different address.")
        m = CLAIMED_ID.match(query.get("openid.claimed_id", ""))
        if not m or query.get("openid.identity") != query.get("openid.claimed_id"):
            raise SteamLoginError("Steam didn't return a Steam ID.")
        # Ask Steam whether it really signed this answer.
        check = {k: v for k, v in query.items() if k.startswith("openid.")}
        check["openid.mode"] = "check_authentication"
        try:
            r = httpx.post(OPENID_URL, data=check, headers=HEADERS, timeout=20)
        except httpx.HTTPError as e:
            raise SteamLoginError(f"Couldn't reach Steam to confirm the sign-in ({e}).") from e
        if r.status_code != 200 or "is_valid:true" not in r.text:
            raise SteamLoginError("Steam didn't confirm this sign-in.")
        return int(m.group(1))


def account_id(steam_id: int) -> int:
    return steam_id - STEAM_ID64_BASE


def profile(steam_id: int) -> dict[str, Any]:
    """Public name, avatar and rank from OpenDota. Empty fields when OpenDota doesn't know you
    yet (it picks players up once Dota's 'Expose Public Match Data' setting is on)."""
    out: dict[str, Any] = {"steam_id": steam_id, "account_id": account_id(steam_id),
                           "name": None, "avatar": None, "rank_tier": None, "known": False}
    try:
        r = httpx.get(f"https://api.opendota.com/api/players/{account_id(steam_id)}", headers=HEADERS, timeout=15)
        data = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return out
    p = data.get("profile") or {}
    avatar = p.get("avatarmedium") or p.get("avatar")
    if avatar:
        # The plain avatars.steamstatic.com host fails TLS on some networks; its Akamai mirror works.
        avatar = re.sub(r"^https://avatars\.steamstatic\.com/", "https://avatars.akamai.steamstatic.com/", avatar)
    out.update(name=p.get("personaname"), avatar=avatar,
               rank_tier=data.get("rank_tier"), known=bool(p))
    return out
