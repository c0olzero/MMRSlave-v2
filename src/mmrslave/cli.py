"""Command line: `python -m mmrslave <command>` (or `mmrslave <command>` once installed)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cmd_status(args, s) -> None:
    from mmrslave.catalog import Catalog
    cat = Catalog(s.catalog_path)
    print(f"Data folder: {s.data_dir}")
    print(f"Your Steam ID: {s.steam_id or '(not set)'}  account ID: {s.account_id or '-'}")
    rows = cat.summary()
    if not rows:
        print("No matches yet. Try:  python -m mmrslave mine   or   python -m mmrslave collect")
    for source, status, n in rows:
        print(f"  {source:9} {status:11} {n}")
    models = sorted(p.name for p in s.models_dir.glob("*.pt")) if s.models_dir.exists() else []
    print(f"Trained models: {', '.join(models) or 'none yet'}")


def cmd_collect(args, s) -> None:
    from mmrslave.collect import Collector
    if args.workers:
        s.collect.parse_workers = args.workers
    col = Collector(s, log=_log)
    # Leave some of the daily OpenDota allowance for fetching your own games.
    col.api.min_daily_remaining = 150
    try:
        col.run(max_parsed=args.max, hours=args.hours, sources=("mine", "immortal"))
    finally:
        col.close()


def cmd_mine(args, s) -> None:
    from mmrslave.collect import Collector
    col = Collector(s, log=_log)
    try:
        col.queue_mine(args.count)
        col.run(sources=("mine",), discover=False)
    finally:
        col.close()


def cmd_local(args, s) -> None:
    from mmrslave.collect import Collector
    if args.workers:
        s.collect.parse_workers = args.workers
    col = Collector(s, log=_log)
    try:
        col.queue_local(Path(args.folder) if args.folder else s.local_replays)
        col.run(sources=("local",), discover=False)
    finally:
        col.close()


def cmd_stats(args, s) -> None:
    from mmrslave.catalog import Catalog
    cat = Catalog(s.catalog_path)
    rows = cat.db.execute("SELECT avg_mmr, n_immortal, patch FROM matches WHERE source='immortal'"
                          " AND avg_mmr IS NOT NULL AND status IN ('url','downloaded','parsed')").fetchall()
    if not rows:
        print("No qualifying Immortal matches yet.")
        return
    mmrs = sorted(r[0] for r in rows)
    pct = lambda q: mmrs[min(len(mmrs) - 1, int(q * len(mmrs)))]
    print(f"{len(mmrs)} qualifying Immortal matches. OpenDota avg computed_mmr percentiles:")
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        print(f"  {int(q*100):3}%  {pct(q):.0f}")
    print("Set collect.min_avg_computed_mmr in mmrslave.toml to keep only the top slice.")
    reasons = cat.db.execute("SELECT reason, COUNT(*) FROM matches WHERE status='skipped' GROUP BY reason"
                             " ORDER BY 2 DESC LIMIT 8").fetchall()
    if reasons:
        print("Most common skip reasons:")
        for r, n in reasons:
            print(f"  {n:6}  {r}")


def cmd_train(args, s) -> None:
    from mmrslave.train import train_all
    which = tuple(args.only.split(",")) if args.only else ("winprob", "context")
    r = train_all(s, _log, epochs_wp=args.epochs_wp, epochs_ctx=args.epochs_ctx, limit=args.limit,
                  min_avg_mmr=args.min_mmr or s.collect.min_avg_computed_mmr, which=which)
    print()
    print(f"Trained on {r['train_matches']} games, checked on {r['val_matches']} held-out games.")
    if "winprob" in r:
        w = r["winprob"]
        print(f"  Win-probability: predicts the winner {w['accuracy']:.1%} of the time across all game moments")
        for k, v in w["by_minute"].items():
            print(f"      minute {k:>6}: {v['accuracy']:.1%}")
    if "context" in r:
        c = r["context"]
        print(f"  Death risk: AUC {c['risk_auc']:.3f} (0.5 = guessing, 1.0 = perfect)")
        print(f"  Next position: right cell {c['move_top1']:.1%}, in top 5 cells {c['move_top5']:.1%} "
              f"(\"stays put\" guess: {c['move_stay_baseline_top1']:.1%})")


def cmd_auto(args, s) -> None:
    """One self-improvement cycle: learn from new Immortal games, then review your new games."""
    from mmrslave.benchmarks import build_benchmarks
    from mmrslave.catalog import Catalog
    from mmrslave.collect import Collector
    from mmrslave.train import train_all

    col = Collector(s, log=_log)
    col.api.min_daily_remaining = 150
    try:
        _log("step 1/4: collecting new high-Immortal games")
        col.run(hours=args.hours, sources=("mine", "immortal"))
        _log("step 2/4: fetching your latest games")
        col.api.min_daily_remaining = 5
        col.queue_mine(20)
        col.run(sources=("mine",), discover=False)
    finally:
        col.close()

    cat = Catalog(s.catalog_path)
    n_now = cat.count("parsed", "immortal")
    n_last = int(cat.kv_get("last_train_count") or 0)
    if n_now - n_last >= args.retrain_every or not (s.models_dir / "winprob.pt").exists():
        _log(f"step 3/4: retraining on {n_now} Immortal games ({n_now - n_last} new since last time)")
        train_all(s, _log)
        build_benchmarks(s, _log)
        cat.kv_set("last_train_count", str(n_now))
        retrained = True
    else:
        _log(f"step 3/4: {n_now - n_last} new games since last training; retraining at {args.retrain_every}")
        retrained = False

    _log("step 4/4: reviewing your games")
    rows = cat.db.execute("SELECT match_id FROM matches WHERE source='mine' AND status='parsed'"
                          " ORDER BY match_id DESC LIMIT ?", (args.review,)).fetchall()
    cat.close()
    for (mid,) in rows:
        done = (s.reports_dir / f"{mid}.analysis.json").exists()
        if retrained or not done:
            analyze_and_coach(s, mid, coach=not (s.reports_dir / f"{mid}.report.json").exists())
    _log("cycle complete. Open the dashboard:  python -m mmrslave serve")


def cmd_serve(args, s) -> None:
    import uvicorn

    from mmrslave.web.server import create_app
    _refresh_game_assets(s)
    print(f"Dashboard: http://127.0.0.1:{args.port}   (Ctrl+C to stop)")
    uvicorn.run(create_app(s), host="127.0.0.1", port=args.port, log_level="warning")


def _refresh_game_assets(s, force: bool = False) -> None:
    """Copy the minimap and hero icons from the Dota 2 install if missing or the game updated."""
    from mmrslave.game_assets import extract
    try:
        extract(s, force=force, log=_log)
    except (OSError, ValueError, KeyError) as e:
        _log(f"couldn't read the Dota 2 game files ({e}); the board will use a drawn map")


def cmd_assets(args, s) -> None:
    _refresh_game_assets(s, force=True)


def cmd_benchmarks(args, s) -> None:
    from mmrslave.benchmarks import build_benchmarks
    build_benchmarks(s, _log)


def reparse_mine(s, log=_log) -> int:
    """Download your games again and parse them with the current parser, for games saved by an
    older one (they lack per-minute damage and assists). Games whose replay Valve has already
    deleted keep their old record. Returns how many were updated."""
    from concurrent.futures import ProcessPoolExecutor

    from mmrslave.catalog import Catalog
    from mmrslave.collect import ReplayExpired, download_replay, parse_job
    from mmrslave.extract import SCHEMA_VERSION, load_meta
    cat = Catalog(s.catalog_path)
    rows = cat.db.execute("SELECT match_id, replay_url FROM matches WHERE source='mine' AND status='parsed'"
                          " AND replay_url IS NOT NULL ORDER BY match_id DESC").fetchall()
    cat.close()
    old = [r for r in rows if load_meta(s.matches_dir, r["match_id"]).get("schema_version", 1) < SCHEMA_VERSION]
    log(f"reparse: {len(old)} of your games need the new format")
    done = 0
    with ProcessPoolExecutor(min(4, max(1, len(old)))) as pool:
        futures = []
        for r in old:
            try:
                dem = download_replay(r["match_id"], r["replay_url"], s.raw_dir)
            except ReplayExpired:
                log(f"reparse: {r['match_id']}: Valve no longer has this replay; keeping the old record")
                continue
            except Exception as e:  # noqa: BLE001
                log(f"reparse: {r['match_id']}: download failed ({e})")
                continue
            futures.append(pool.submit(parse_job, str(dem), str(s.matches_dir), "mine", {}, True))
        for f in futures:
            res = f.result()
            if res["ok"]:
                done += 1
                log(f"reparse: {res['match_id']} updated ({res['seconds']}s)")
            else:
                log(f"reparse: failed: {res['error']}")
    return done


def cmd_reparse(args, s) -> None:
    reparse_mine(s)


def _latest_mine(s) -> int | None:
    from mmrslave.catalog import Catalog
    cat = Catalog(s.catalog_path)
    row = cat.db.execute("SELECT match_id FROM matches WHERE source IN ('mine','local') AND status='parsed'"
                         " ORDER BY match_id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def analyze_and_coach(s, match_id: int, *, coach: bool = True, log=_log) -> dict:
    """Analyze one match, save it, and (if possible) write the Claude report. Returns the analysis."""
    from mmrslave.analyze import analyze_match, save_analysis
    from mmrslave.catalog import Catalog
    from mmrslave.coach import CoachError, rank_name, save_report, write_report
    an = analyze_match(s, match_id)
    save_analysis(s, an)
    log(f"analysis saved for match {match_id} ({len(an['findings'])} findings)")
    if coach:
        cat = Catalog(s.catalog_path)
        rank = rank_name(int(cat.kv_get("my_rank_tier") or 0))
        cat.close()
        try:
            report = write_report(s, an, rank)
            save_report(s, match_id, report)
            log(f"coaching report written ({report['_meta']['output_tokens']} tokens, "
                f"{report['_meta']['seconds']}s)")
            an["_report"] = report
        except CoachError as e:
            log(f"coach: {e}")
    return an


def cmd_analyze(args, s) -> None:
    match_id = args.match_id or _latest_mine(s)
    if not match_id:
        raise SystemExit("No games of yours parsed yet. Run:  python -m mmrslave mine")
    an = analyze_and_coach(s, match_id, coach=not args.no_coach)
    me = an["me"]
    if me is None:
        print("You're not in this match.")
        return
    p = an["players"][me]
    print()
    print(f"Match {match_id}: {p['hero']} (pos {p['position']}) {p['kills']}/{p['deaths']}/{p['assists']}, "
          f"{'WON' if an['won'] else 'LOST'} in {an['duration']}")
    r = an.get("_report")
    if r:
        print(f"\n{r['headline']}\n\n{r['summary']}\n")
        print("Your biggest mistakes:")
        for m in r["your_mistakes"]:
            print(f"  [{m['clock']}] {m['title']}\n      {m['what_happened']}\n      -> {m['do_instead']}")
        print("\nPractice next:")
        for h in r["practice_focus"]:
            print(f"  - {h['habit']}: {h['how_to_practice']}")
    else:
        print("\nTop findings:")
        for f in an["findings"][:12]:
            print(f"  - {f['title']}")
    print("\nOpen the dashboard for the full breakdown:  python -m mmrslave serve")


def main(argv: list[str] | None = None) -> None:
    from mmrslave.config import load_settings
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="mmrslave", description="AI Dota 2 coach.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show what's been collected and trained")

    p = sub.add_parser("collect", help="download and parse high-Immortal games (training data)")
    p.add_argument("--max", type=int, help="stop after parsing this many matches")
    p.add_argument("--hours", type=float, help="stop after this many hours")
    p.add_argument("--workers", type=int, help="parallel parsers (default from config)")

    p = sub.add_parser("mine", help="download and parse your own recent games")
    p.add_argument("--count", type=int, default=20)

    p = sub.add_parser("local", help="parse replays already on disk (your Dota replay folder by default)")
    p.add_argument("folder", nargs="?")
    p.add_argument("--workers", type=int)

    sub.add_parser("stats", help="skill spread of collected Immortal games")

    p = sub.add_parser("train", help="train the neural networks on collected Immortal games")
    p.add_argument("--epochs-wp", type=int, default=12)
    p.add_argument("--epochs-ctx", type=int, default=8)
    p.add_argument("--limit", type=int, help="use only the newest N matches")
    p.add_argument("--min-mmr", type=float, help="only matches with at least this avg computed_mmr")
    p.add_argument("--only", help="winprob or context")

    p = sub.add_parser("analyze", help="review one of your games (latest by default)")
    p.add_argument("match_id", nargs="?", type=int)
    p.add_argument("--no-coach", action="store_true", help="skip the written Claude report")

    sub.add_parser("benchmarks", help="rebuild Immortal benchmark stats from collected games")

    sub.add_parser("reparse", help="download your recent games again for the newest stats (damage, assists over time)")

    p = sub.add_parser("serve", help="open the local dashboard")
    p.add_argument("--port", type=int, default=8765)

    sub.add_parser("assets", help="copy the minimap and hero icons from your Dota 2 install again")

    p = sub.add_parser("auto", help="one self-improvement cycle: collect, retrain if needed, review your games")
    p.add_argument("--hours", type=float, default=3.0, help="max hours collecting Immortal games")
    p.add_argument("--retrain-every", type=int, default=300, help="retrain after this many new games")
    p.add_argument("--review", type=int, default=10, help="how many of your latest games to review")

    args = ap.parse_args(argv)
    s = load_settings()
    s.ensure_dirs()
    {"status": cmd_status, "collect": cmd_collect, "mine": cmd_mine, "local": cmd_local,
     "stats": cmd_stats, "train": cmd_train, "analyze": cmd_analyze, "benchmarks": cmd_benchmarks,
     "serve": cmd_serve, "assets": cmd_assets, "auto": cmd_auto, "reparse": cmd_reparse}[args.cmd](args, s)


if __name__ == "__main__":
    main()
