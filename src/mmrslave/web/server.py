"""Local dashboard: `python -m mmrslave serve`, then open http://127.0.0.1:8765"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mmrslave import game_assets
from mmrslave.analyze import _clock
from mmrslave.catalog import Catalog
from mmrslave.coach import report_path
from mmrslave import steam, updater
from mmrslave.config import Settings, anthropic_api_key, load_settings, save_setting
from mmrslave.desktop import RESTART_EXIT, SUPERVISED_ENV
from mmrslave.extract import HF, load_meta, load_record

STATIC = Path(__file__).parent / "static"


def create_app(s: Settings | None = None) -> FastAPI:
    s = s or load_settings()
    s.ensure_dirs()
    app = FastAPI(title="MMRSlave")
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    jobs: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    supervised = os.environ.get(SUPERVISED_ENV) == "1"
    steam_login = steam.SteamLogin()
    update_state: dict[str, Any] = {"check": None, "error": None}

    def run_job(name: str, fn) -> dict[str, Any]:
        with lock:
            if jobs.get(name, {}).get("state") == "running":
                return jobs[name]
            jobs[name] = {"state": "running", "started": time.time(), "log": []}

        def log(msg: str) -> None:
            jobs[name]["log"] = (jobs[name]["log"] + [msg])[-50:]

        def target() -> None:
            try:
                fn(log)
                jobs[name]["state"] = "done"
            except BaseException as e:  # noqa: BLE001 - surfaced to the UI
                jobs[name]["state"] = "error"
                log(f"error: {e}")
        threading.Thread(target=target, daemon=True).start()
        return jobs[name]

    def restart_soon() -> None:
        """Exit with the restart code; the desktop supervisor starts the server again."""
        threading.Timer(0.8, lambda: os._exit(RESTART_EXIT)).start()

    def do_check() -> dict[str, Any]:
        try:
            update_state["check"], update_state["error"] = updater.check(), None
        except updater.UpdateError as e:
            update_state["error"] = str(e)
        return update_state

    def install_job(log) -> None:
        info = updater.install(log)
        update_state["check"], update_state["error"] = info, None
        if info.get("installed_now"):
            if supervised:
                restart_soon()
            else:
                log("Installed. Close and reopen MMRSlave to use the new version.")

    # Look for a new version once at startup; install it straight away when you chose that.
    if s.updates.auto_update and supervised and updater.mode() in ("bundle", "git"):
        run_job("update", install_job)
    else:
        threading.Thread(target=do_check, daemon=True).start()

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    # ------------------------------------------------------------------ app
    @app.get("/api/ping")
    def ping() -> dict[str, Any]:
        return {"app": "mmrslave", "version": updater.installed().get("sha")}

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"installed": updater.installed(), "check": update_state["check"], "error": update_state["error"],
                "auto_update": s.updates.auto_update, "can_restart": supervised,
                "releases_url": updater.RELEASES_URL, "job": jobs.get("update")}

    @app.post("/api/update/check")
    def update_check() -> dict[str, Any]:
        do_check()
        return version()

    @app.post("/api/update/install")
    def update_install() -> dict[str, Any]:
        return run_job("update", install_job)

    @app.post("/api/settings/updates")
    def update_settings(auto_update: bool = Body(..., embed=True)) -> dict[str, Any]:
        s.updates.auto_update = auto_update
        save_setting("updates", "auto_update", auto_update)
        return version()

    @app.post("/api/restart")
    def restart() -> dict[str, Any]:
        if not supervised:
            raise HTTPException(409, "Started without the app window; restart it yourself.")
        restart_soon()
        return {"restarting": True}

    # ------------------------------------------------------------------ Steam account
    def base_url(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def cached_profile() -> dict[str, Any] | None:
        if not s.steam_id:
            return None
        cat = Catalog(s.catalog_path)
        raw = cat.kv_get("steam_profile")
        cat.close()
        try:
            prof = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            prof = None
        if prof and prof.get("steam_id") == s.steam_id and time.time() - prof.get("fetched_at", 0) < 86400:
            return prof
        prof = {**steam.profile(s.steam_id), "fetched_at": time.time()}
        cat = Catalog(s.catalog_path)
        cat.kv_set("steam_profile", json.dumps(prof))
        if prof.get("rank_tier"):
            cat.kv_set("my_rank_tier", str(prof["rank_tier"]))
        cat.close()
        return prof

    @app.get("/api/account")
    def account() -> dict[str, Any]:
        return {"steam_id": s.steam_id or None, "account_id": s.account_id or None, "profile": cached_profile()}

    @app.get("/auth/steam/login")
    def steam_login_start(request: Request) -> RedirectResponse:
        return RedirectResponse(steam_login.login_url(base_url(request)), status_code=303)

    @app.get("/auth/steam/callback")
    def steam_login_done(request: Request) -> RedirectResponse:
        try:
            steam_id = steam_login.verify(dict(request.query_params), base_url(request))
        except steam.SteamLoginError as e:
            return RedirectResponse(f"/?steam_error={quote(str(e))}#/", status_code=303)
        changed = steam_id != s.steam_id
        s.steam_id = steam_id
        save_setting("player", "steam_id", steam_id)
        if changed:
            cat = Catalog(s.catalog_path)
            cat.kv_set("my_rank_tier", "")
            cat.kv_set("steam_profile", "")
            cat.close()
        return RedirectResponse("/?steam=connected#/", status_code=303)

    @app.post("/api/account/disconnect")
    def steam_disconnect() -> dict[str, Any]:
        s.steam_id = 0
        save_setting("player", "steam_id", 0)
        return {"steam_id": None}

    # ------------------------------------------------------------------ data
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        cat = Catalog(s.catalog_path)
        summary = [{"source": a, "status": b, "n": n} for a, b, n in cat.summary()]
        rank = cat.kv_get("my_rank_tier")
        cat.close()
        history = []
        hist = s.model_file("history.jsonl")
        if hist.exists():
            for line in hist.read_text(encoding="utf-8").splitlines():
                try:
                    h = json.loads(line)
                except json.JSONDecodeError:
                    continue
                history.append({
                    "trained_at": h.get("trained_at"), "train_matches": h.get("train_matches"),
                    "winprob_accuracy": (h.get("winprob") or {}).get("accuracy"),
                    "risk_auc": (h.get("context") or {}).get("risk_auc"),
                    "move_top5": (h.get("context") or {}).get("move_top5"),
                })
        from mmrslave.coach import rank_name
        return {"summary": summary, "history": history, "rank": rank_name(int(rank or 0)),
                "steam_id": s.steam_id, "coach_ready": bool(anthropic_api_key()),
                "models": {n: s.model_file(f"{n}.pt").exists() for n in ("winprob", "context")},
                "benchmarks": s.model_file("benchmarks.json").exists(), "jobs": jobs}

    @app.get("/api/matches")
    def matches() -> list[dict[str, Any]]:
        cat = Catalog(s.catalog_path)
        rows = cat.db.execute("SELECT match_id, source, start_time FROM matches WHERE source IN ('mine','local')"
                              " AND status='parsed' ORDER BY match_id DESC").fetchall()
        cat.close()
        out = []
        for r in rows:
            try:
                meta = load_meta(s.matches_dir, r["match_id"])
            except FileNotFoundError:
                continue
            me = next((p for p in meta["players"] if p["steam_id"] == s.steam_id), None)
            if me is None:
                continue
            won = (me["team"] == 0) == bool(meta["radiant_win"])
            out.append({
                "match_id": r["match_id"], "start_time": r["start_time"], "hero": me["hero_display"],
                "hero_id": me["hero_id"], "position": me.get("position"),
                "kda": f"{me['kills']}/{me['deaths']}/{me['assists']}", "won": won,
                "duration": _clock(meta["duration_s"]), "net_worth": me["net_worth"],
                "analyzed": (s.reports_dir / f"{r['match_id']}.analysis.json").exists(),
                "coached": report_path(s, r["match_id"]).exists(),
            })
        return out

    @app.get("/api/match/{match_id}")
    def match(match_id: int) -> dict[str, Any]:
        from mmrslave.analyze import ANALYSIS_VERSION, analyze_match, save_analysis
        a_path = s.reports_dir / f"{match_id}.analysis.json"
        an = json.loads(a_path.read_text(encoding="utf-8")) if a_path.exists() else None
        if an is None or an.get("analysis_version", 1) < ANALYSIS_VERSION:
            # New game, or reviewed by an older version: (re)build the review.
            if not (s.matches_dir / f"{match_id}.json").exists():
                raise HTTPException(404, "match not parsed")
            save_analysis(s, analyze_match(s, match_id))
            an = json.loads(a_path.read_text(encoding="utf-8"))
        rp = report_path(s, match_id)
        an["report"] = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None
        return an

    @app.get("/api/geometry")
    def geometry() -> dict[str, Any]:
        """Map shapes for drawing the board: the same geometry the coach uses to name areas."""
        import numpy as np

        from mmrslave import regions
        from mmrslave.features import GRID, GRID_HALF, MAP_CX, MAP_CY, cell_center
        try:
            import gem
            mc = json.loads((Path(gem.__file__).parent / "data" / "map_constants.json").read_text())
            river = mc["regions"]["river_outline"]
            fountains = mc["fountains"]
        except Exception:  # noqa: BLE001
            river, fountains = [], {}

        def world(line: list[tuple[float, float]]) -> list[list[float]]:
            return [[MAP_CX + u * regions._HALF, MAP_CY + v * regions._HALF] for u, v in line]

        cells = np.arange(GRID * GRID)
        xs, ys = cell_center(cells)
        areas: dict[int, dict[str, list[float]]] = {}
        for team in (0, 1):
            acc: dict[str, list[float]] = {}
            for x, y in zip(xs, ys):
                name = regions.describe(float(x), float(y), team)
                a = acc.setdefault(name, [0.0, 0.0, 0.0])
                a[0] += float(x)
                a[1] += float(y)
                a[2] += 1
            areas[team] = {k: [v[0] / v[2], v[1] / v[2]] for k, v in acc.items()}
        # The board's square: the game's own minimap when it was copied from the install,
        # otherwise the area the models' grid covers.
        man = game_assets.load_manifest(s)
        mm = man["minimap"] if man else None
        frame = ({k: mm[k] for k in ("x0", "y0", "size")} if mm
                 else {"x0": MAP_CX - GRID_HALF, "y0": MAP_CY - GRID_HALF, "size": 2 * GRID_HALF})
        return {
            "frame": frame,
            "minimap": {"url": f"/game-assets/{mm['file']}?v={int(man['source']['mtime'])}"} if mm else None,
            "center": [MAP_CX, MAP_CY], "half": GRID_HALF, "grid": GRID,
            "lanes": {"top": world(regions._TOP), "mid": world(regions._MID), "bot": world(regions._BOT)},
            "river": river, "fountains": fountains,
            "bases": {"radiant": world([(-1.0, -1.0), (-0.55, -0.55)]), "dire": world([(0.55, 0.55), (1.0, 1.0)])},
            "area_centers": areas,
        }

    @app.get("/api/match/{match_id}/replay")
    def replay(match_id: int) -> dict[str, Any]:
        """The whole game for the board's playback: every hero's position, health, mana, gold and
        whether the enemy could see them, once per game second, plus every ward."""
        import numpy as np
        rec = load_record(s.matches_dir, match_id)
        icons = game_assets.hero_icons(s)
        item_icons = game_assets.item_icons(s)
        man = game_assets.load_manifest(s)
        version = f"{int(man['source']['mtime'])}.{man['source'].get('format', 1)}" if man else "0"
        h = rec.hero
        hp = np.where(h[:, :, HF["alive"]] > 0,
                      np.clip(np.round(h[:, :, HF["hp"]] / np.maximum(h[:, :, HF["max_hp"]], 1) * 100), 1, 100), 0)
        whole = lambda f: np.round(h[:, :, HF[f]]).astype(int).T.tolist()  # noqa: E731
        # Inventory, one entry per change, per hero; None when the game was parsed before
        # schema 3 recorded items.
        timeline = rec.events.get("items")
        items = None
        if timeline:
            items = [[] for _ in range(10)]
            for e in timeline:
                items[e["pid"]].append([e["t"], e["main"], e["neutral"], e["backpack"]])
        used = {n for e in (timeline or []) for n in (*e["main"], *e["backpack"], e["neutral"]) if n}
        mp = np.clip(np.round(h[:, :, HF["mana"]] / np.maximum(h[:, :, HF["max_mana"]], 1) * 100), 0, 100)
        return {
            "t0": int(rec.t[0]), "n": int(len(rec.t)),
            "heroes": [{"pid": p["player_id"], "hero": p["hero_display"], "team": p["team"],
                        "icon": f"/game-assets/heroes/{p['hero']}.png?v={version}" if p["hero"] in icons else None}
                       for p in rec.players],
            "x": np.round(h[:, :, HF["x"]]).astype(int).T.tolist(),
            "y": np.round(h[:, :, HF["y"]]).astype(int).T.tolist(),
            "hp": hp.astype(int).T.tolist(),
            "mp": mp.astype(int).T.tolist(),
            "hpv": whole("hp"), "hpmax": whole("max_hp"), "mpv": whole("mana"), "mpmax": whole("max_mana"),
            "lh": whole("lh"), "dn": whole("dn"),
            "items": items,
            "item_icons": {n: f"/game-assets/items/{n}.png?v={version}" for n in sorted(used) if n in item_icons},
            # Unspent gold (reliable + unreliable) and net worth, as the game had them that second.
            "gold": whole("gold"), "nw": whole("net_worth"),
            "vis": h[:, :, HF["visible_to_enemy"]].astype(int).T.tolist(),
            "wards": [{"t": w["t"], "end": w["end"], "x": w["x"], "y": w["y"], "team": w["team"], "type": w["type"]}
                      for w in rec.events["wards"]],
        }

    @app.get("/api/match/{match_id}/curves")
    def curves(match_id: int) -> dict[str, Any]:
        """Your numbers minute by minute next to high-Immortal players on the same hero and position."""
        from mmrslave.benchmarks import CURVE_STATS, Benchmarks, player_curves
        rec = load_record(s.matches_dir, match_id)
        me = rec.player_by_steam_id(s.steam_id) if s.steam_id else None
        if me is None:
            raise HTTPException(404, "you're not in this match")
        bench = Benchmarks.load(s)
        found = bench.curves(s, me["hero_id"], me.get("position", 0)) if bench else None
        return {
            "you": player_curves(rec, me["player_id"]),
            "immortal": {k: found[1].get(k) for k in CURVE_STATS} if found else None,
            "compared_with": found[0] if found else None,
            "immortal_games": found[1]["n"] if found else 0,
            # stats compared with every Immortal player in the position, not just this hero
            "position_only": found[1].get("position_only", []) if found else [],
            "record_has_minutes": "minute" in rec.meta,
        }

    @app.post("/api/match/{match_id}/analyze")
    def reanalyze(match_id: int) -> dict[str, Any]:
        from mmrslave.cli import analyze_and_coach
        return run_job(f"analyze:{match_id}", lambda log: analyze_and_coach(s, match_id, log=log))

    @app.post("/api/fetch-mine")
    def fetch_mine() -> dict[str, Any]:
        def job(log):
            from mmrslave.collect import Collector
            col = Collector(s, log=log)
            try:
                col.queue_mine(20)
                col.run(sources=("mine",), discover=False)
            finally:
                col.close()
        return run_job("fetch-mine", job)

    @app.get("/api/jobs")
    def job_status() -> dict[str, Any]:
        return jobs

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    # Minimap and hero icons copied from the local Dota 2 install (see game_assets.py).
    game_assets.assets_dir(s).mkdir(parents=True, exist_ok=True)
    app.mount("/game-assets", StaticFiles(directory=game_assets.assets_dir(s)), name="game-assets")
    return app
