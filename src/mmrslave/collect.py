"""Collect replays: find matches, check quality, download, and parse in parallel.

Sources
-------
immortal  high-Immortal public ranked games (training data)
mine      your own recent games, fetched by account ID
local     .dem files already on disk (your Dota replay folder)

Every match moves through the catalog: found -> url -> downloaded -> parsed.
The run can be stopped at any time and picks up where it left off.
"""

from __future__ import annotations

import bz2
import os
import shutil
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import httpx

from mmrslave.catalog import Catalog
from mmrslave.config import Settings
from mmrslave.opendota import ALL_PICK_RANKED, RANKED_LOBBY, BudgetExhausted, OpenDota, OpenDotaError, match_quality

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BZIP2_MAGIC = b"BZh"
# Valve keeps replays for a limited time; don't bother with older matches.
MAX_REPLAY_AGE_S = 10 * 24 * 3600

Log = Callable[[str], None]


class ReplayExpired(Exception):
    pass


# --------------------------------------------------------------------------- download

def _fetch(url: str, dest: Path, tries: int = 4) -> None:
    """Stream a URL to a file, retrying with backoff when Valve's servers drop the connection."""
    for attempt in range(tries):
        try:
            with httpx.stream("GET", url, timeout=60, follow_redirects=True,
                              headers={"User-Agent": "MMRSlave/0.1"}) as r:
                if r.status_code in (403, 404):
                    raise ReplayExpired(f"HTTP {r.status_code}")
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.TransportError(f"HTTP {r.status_code}")
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            return
        except (httpx.TransportError, OSError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(5 * 3 ** attempt)     # 5s, 15s, 45s


def download_replay(match_id: int, url: str, raw_dir: Path) -> Path:
    """Download a replay and decompress it to raw_dir/<match_id>.dem."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    packed = raw_dir / f"{match_id}.dem.part"
    dem = raw_dir / f"{match_id}.dem"
    try:
        _fetch(url, packed)
        with open(packed, "rb") as f:
            magic = f.read(4)
        tmp = dem.with_suffix(".dem.tmp")
        if magic.startswith(ZSTD_MAGIC):
            import zstandard
            with open(packed, "rb") as src, open(tmp, "wb") as dst:
                zstandard.ZstdDecompressor().copy_stream(src, dst)
        elif magic.startswith(BZIP2_MAGIC):
            with bz2.open(packed, "rb") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        else:
            raise ValueError(f"unknown replay archive format (magic {magic.hex()})")
        os.replace(tmp, dem)
        return dem
    finally:
        packed.unlink(missing_ok=True)


REPLAY_UPLOAD_DELAY_S = 12 * 60
RETRY_AFTER_S = 10 * 60


def _replay_ready(row: Any) -> bool:
    """Valve needs some minutes after a game ends to upload its replay."""
    now = time.time()
    ended = (row["start_time"] or 0) + (row["duration"] or 0)
    if ended > now - REPLAY_UPLOAD_DELAY_S:
        return False
    return not (row["attempts"] and row["updated_at"] > now - RETRY_AFTER_S)


# --------------------------------------------------------------------------- parse (runs in worker processes)

def parse_job(dem_path: str, matches_dir: str, source: str, extra_meta: dict[str, Any],
              delete_after: bool) -> dict[str, Any]:
    from mmrslave.extract import extract, parse_replay, save_record
    t0 = time.time()
    try:
        m, snapshots = parse_replay(dem_path)
        rec = extract(m, source=source, extra_meta=extra_meta, snapshots=snapshots)
        save_record(rec, Path(matches_dir))
        return {"ok": True, "match_id": rec.match_id, "path": dem_path, "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001 - reported back to the catalog
        return {"ok": False, "path": dem_path, "error": f"{type(e).__name__}: {e}"[:500]}
    finally:
        if delete_after:
            Path(dem_path).unlink(missing_ok=True)


# --------------------------------------------------------------------------- orchestrator

class Collector:
    def __init__(self, settings: Settings, log: Log = print):
        self.s = settings
        self.log = log
        settings.ensure_dirs()
        self.cat = Catalog(settings.catalog_path)
        self.api = OpenDota(delay_s=settings.collect.api_delay_s)
        # Give downloads that failed on a flaky connection in an earlier run another go.
        self.cat.db.execute("UPDATE matches SET status='url' WHERE status='failed' AND reason LIKE 'download:%'"
                            " AND replay_url IS NOT NULL AND attempts < 6")
        self.cat.db.commit()

    def close(self) -> None:
        self.cat.close()
        self.api.close()

    # ---- API steps
    def discover(self) -> int:
        """Add a page of recent top-bracket public matches. Returns how many were new."""
        c = self.s.collect
        cursor = self.cat.kv_get("discover_cursor")
        page = self.api.public_matches()
        fresh = self._add_public(page)
        if fresh < 20:
            # Few new games at the top: walk back in time from where we left off.
            page = self.api.public_matches(less_than_match_id=int(cursor) if cursor else None)
            fresh += self._add_public(page)
        if page:
            oldest = min(m["match_id"] for m in page)
            too_old = min(m.get("start_time") or 0 for m in page) < time.time() - MAX_REPLAY_AGE_S
            self.cat.kv_set("discover_cursor", "" if too_old else str(oldest))
        self.log(f"discover: +{fresh} new candidate matches (min duration {c.min_duration_minutes} min)")
        return fresh

    def _add_public(self, page: list[dict[str, Any]]) -> int:
        min_dur = self.s.collect.min_duration_minutes * 60
        keep = [m for m in page
                if m.get("lobby_type") == RANKED_LOBBY and m.get("game_mode") == ALL_PICK_RANKED
                and (m.get("duration") or 0) >= min_dur]
        return self.cat.add_found("immortal", keep)

    def resolve(self, row: Any) -> None:
        """Fetch match details, check skill level, and record the replay URL."""
        mid, source = row["match_id"], row["source"]
        detail = self.api.match(mid)
        if not detail:
            self.cat.set_status(mid, "skipped", reason="no match details")
            return
        q = match_quality(detail)
        fields = {k: q[k] for k in ("n_immortal", "avg_mmr", "patch", "start_time", "duration")}
        if source == "immortal":
            c = self.s.collect
            reason = None
            if q["lobby_type"] != RANKED_LOBBY or q["game_mode"] != ALL_PICK_RANKED:
                reason = "not ranked all pick"
            elif q["n_immortal"] < c.min_immortal_players:
                reason = f"only {q['n_immortal']} immortal players"
            elif c.min_avg_computed_mmr and (q["avg_mmr"] or 0) < c.min_avg_computed_mmr:
                reason = f"avg mmr {q['avg_mmr']} below {c.min_avg_computed_mmr}"
            elif q["abandons"]:
                reason = "abandon"
            elif (q["duration"] or 0) < c.min_duration_minutes * 60:
                reason = "too short"
            if reason:
                self.cat.set_status(mid, "skipped", reason=reason, **fields)
                return
        if not q["replay_url"]:
            self.cat.set_status(mid, "skipped", reason="no replay url yet", **fields)
            return
        self.cat.set_status(mid, "url", replay_url=q["replay_url"], **fields)

    # ---- source helpers
    def queue_mine(self, count: int) -> int:
        """Add your most recent matches to the queue."""
        if not self.s.account_id:
            raise RuntimeError("Connect your Steam account first (or set player.steam_id in mmrslave.toml).")
        profile = self.api.get(f"/players/{self.s.account_id}") or {}
        if profile.get("rank_tier"):
            self.cat.kv_set("my_rank_tier", str(profile["rank_tier"]))
        rows = self.api.player_matches(self.s.account_id, limit=count)
        new = 0
        for m in rows:
            existing = self.cat.get(m["match_id"])
            if existing and existing["status"] in ("parsed", "url", "downloaded"):
                continue
            self.cat.upsert(m["match_id"], "mine", "found", start_time=m.get("start_time"),
                            duration=m.get("duration"), reason=None)
            new += 1
        self.log(f"mine: queued {new} of your last {len(rows)} matches")
        return new

    def queue_local(self, folder: Path) -> int:
        """Register .dem files in a folder for parsing (files are kept)."""
        new = 0
        for path in sorted(folder.glob("*.dem")):
            if not path.stem.isdigit():
                continue
            mid = int(path.stem)
            existing = self.cat.get(mid)
            if existing and existing["status"] == "parsed":
                continue
            self.cat.upsert(mid, "local", "downloaded", raw_path=str(path),
                            start_time=int(path.stat().st_mtime), reason=None)
            new += 1
        self.log(f"local: queued {new} replays from {folder}")
        return new

    # ---- main loop
    def run(self, *, max_parsed: int | None = None, hours: float | None = None,
            sources: tuple[str, ...] = ("mine", "local", "immortal"), discover: bool = True) -> int:
        c = self.s.collect
        deadline = time.time() + hours * 3600 if hours else None
        parsed_now = 0
        api_ok = True
        downloads: dict[Future, int] = {}
        parses: dict[Future, int] = {}
        last_report = 0.0
        next_discover = 0.0

        with ThreadPoolExecutor(c.download_workers) as dl, \
                ProcessPoolExecutor(c.parse_workers, max_tasks_per_child=8) as pp:
            while True:
                # 1) finished downloads
                for fut in [f for f in downloads if f.done()]:
                    mid = downloads.pop(fut)
                    try:
                        path = fut.result()
                        self.cat.set_status(mid, "downloaded", raw_path=str(path))
                    except ReplayExpired as e:
                        row = self.cat.get(mid)
                        ended = (row["start_time"] or 0) + (row["duration"] or 0)
                        tries = self.cat.bump_attempts(mid)
                        if time.time() - ended < 90 * 60 and tries < 4:
                            # Valve uploads replays some minutes after the game; try again later.
                            self.cat.set_status(mid, "url", reason=f"not uploaded yet ({e})")
                        else:
                            self.cat.set_status(mid, "expired", reason=str(e))
                    except Exception as e:  # noqa: BLE001
                        tries = self.cat.bump_attempts(mid)
                        self.cat.set_status(mid, "url" if tries < 3 else "failed", reason=f"download: {e}"[:300])

                # 2) finished parses
                for fut in [f for f in parses if f.done()]:
                    mid = parses.pop(fut)
                    res = fut.result()
                    if res["ok"]:
                        self.cat.set_status(mid, "parsed", raw_path=None, reason=None)
                        parsed_now += 1
                    else:
                        self.cat.set_status(mid, "failed", reason=f"parse: {res['error']}"[:300])

                done = (max_parsed is not None and parsed_now >= max_parsed) or \
                       (deadline is not None and time.time() > deadline)

                if not done:
                    # 3) start parses (yours first)
                    busy = set(parses.values())
                    free = c.parse_workers - len(parses)
                    for src in sources:
                        if free <= 0:
                            break
                        for row in self.cat.with_status("downloaded", src, limit=free + len(busy)):
                            if free <= 0:
                                break
                            if row["match_id"] in busy:
                                continue
                            if not row["raw_path"] or not Path(row["raw_path"]).exists():
                                self.cat.set_status(row["match_id"], "url" if row["replay_url"] else "failed",
                                                    reason="raw file missing")
                                continue
                            delete = Path(row["raw_path"]).resolve().is_relative_to(self.s.raw_dir.resolve())
                            extra = {"source_info": {k: row[k] for k in ("n_immortal", "avg_mmr", "patch", "start_time")}}
                            fut = pp.submit(parse_job, row["raw_path"], str(self.s.matches_dir), src, extra, delete)
                            parses[fut] = row["match_id"]
                            free -= 1

                    # 4) start downloads, keeping the backlog of unparsed raw replays small
                    backlog = self.cat.count("downloaded") - len(parses)
                    room = min(c.download_workers - len(downloads), c.parse_workers * 2 - backlog - len(downloads))
                    if room > 0:
                        busy = set(downloads.values())
                        for src in sources:
                            for row in self.cat.with_status("url", src, limit=room + len(busy) + 60):
                                if room <= 0:
                                    break
                                if row["match_id"] in busy or not _replay_ready(row):
                                    continue
                                downloads[dl.submit(download_replay, row["match_id"], row["replay_url"],
                                                    self.s.raw_dir)] = row["match_id"]
                                room -= 1

                    # 5) one API step: resolve a found match, or discover more
                    if api_ok:
                        try:
                            row = next((r for src in sources if src != "local"
                                        for r in self.cat.with_status("found", src, limit=1)), None)
                            if row is not None and self.cat.count("url") < c.download_workers * 8:
                                self.resolve(row)
                            elif row is None and discover and "immortal" in sources \
                                    and time.time() >= next_discover:
                                if self.discover() == 0:
                                    next_discover = time.time() + 120  # nothing new yet; check back later
                        except BudgetExhausted as e:
                            self.log(f"api: {e}; finishing downloads and parses already queued")
                            api_ok = False
                        except OpenDotaError as e:
                            self.log(f"api error: {e}; pausing 60s")
                            time.sleep(60)

                idle = not downloads and not parses
                nothing_queued = all(self.cat.count(st, src) == 0 for st in ("url", "downloaded") for src in sources)
                no_api_work = not api_ok or not discover and all(self.cat.count("found", s) == 0 for s in sources)
                if idle and (done or (nothing_queued and no_api_work)):
                    break

                if time.time() - last_report > 30:
                    last_report = time.time()
                    self.log(f"progress: parsed this run {parsed_now} | downloading {len(downloads)} | "
                             f"parsing {len(parses)} | api calls {self.api.calls}, day left {self.api.remaining_day}")
                time.sleep(0.2)
        self.log(f"done: parsed {parsed_now} matches this run")
        return parsed_now
