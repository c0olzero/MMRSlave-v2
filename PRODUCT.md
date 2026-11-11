# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: plain static HTML/CSS/JS (no build step, no Node), served by the project's FastAPI backend from `src/mmrslave/web/static/`. Chosen because the user isn't a frontend developer and it keeps the tool runnable with one Python command.

## Users

One Dota 2 player (Archon 5 per OpenDota rank tier 45, plays mostly safe-lane carry: Phantom Assassin, Anti-Mage, Slark, Spectre; sometimes support) reviewing their own ranked games to climb. They use it both right after a game (a quick verdict on what cost them the match) and in dedicated review sessions going through games in depth. Friends they queue with may also look at the reviews. The review is about the player only: in pub games they can't control teammates (user request, 2026-11-11).

## Product Purpose

MMRSlave reads the player's replays and tells them what they could have done better: their deaths and their decisions across the map (fights they could have reached by TP, towers lost while away, enemies dead but no objective taken, rune control), with game clocks, evidence and what to do instead. Success is the player recognising a concrete habit to fix after each game and seeing it change over time.

## Positioning

The judgement comes from neural networks trained on the user's own continuously collected set of recent high-Immortal ranked games (not pro games), so "what good looks like" matches the solo-queue game they actually play and tracks the current patch. Every death is priced in win chance lost, and the death-risk model only uses what the player's team could actually see.

## Operating Context

Runs locally on the player's Windows PC (RTX 4090). Data lives in `D:/MMRSlaveData`. Typical flow: play a game → fetch latest games → open the match → read the verdict and top mistakes → optionally scrub the timeline and minimap to see the moment. The collector and trainer run in the background over days, so the "coach brain" improves as data grows.

## Capabilities and Constraints

- Per match: win-chance curve, every death analysed (cost, enemies missing, wards, allies nearby, death-risk lead-up, where an Immortal player would have been), biggest swings, laning, item timings and stats as percentiles against Immortal players on the same hero/position, a written report from Claude (requires `ANTHROPIC_API_KEY`; the analysis works without it).
- The whole game's positions and wards, played back on the minimap at 0.5x-8x, pausing at each coach moment if the player wants.
- Minute-by-minute curves (net worth, last hits/denies, level, K/D/A, hero and building damage) against Immortal players on the same hero and position. Damage and assists over time exist only for games parsed with the schema-2 parser.
- Older replays (pre-2025) lack fog-of-war data; models are weaker there.
- No Valve art is bundled in the project. The board shows the real minimap and in-game hero icons, copied from the player's own Dota 2 install at run time; a map drawn from geometry is the fallback.
- Terminology: positions 1-5, safe lane / off lane, net worth, last hits, Immortal, win chance.

## Evidence on Hand

Real data only: the player's parsed games and the collected Immortal games. No invented stats, ranks, or testimonials.

## Product Principles

1. Verdict first, evidence one click away: the post-game check must take under a minute.
2. Every claim points to a moment in the game the player can inspect.
3. About the player only: teammates are context ("what could you have done when your mid was dived?"), never graded.
4. Show what good looks like (Immortal benchmarks) rather than just scoring.
5. Be honest about confidence: say when models or fog-of-war data are missing.
