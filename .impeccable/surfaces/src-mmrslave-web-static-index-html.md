---
version: 1
slug: "src-mmrslave-web-static-index-html"
primary_target: "src/mmrslave/web/static/index.html"
related_targets: ["src/mmrslave/web/static/app.js","src/mmrslave/web/static/style.css"]
---

# Surface: coaching dashboard (src/mmrslave/web/static)

Mode: Operate. Desktop-first local web app (1280-1920 wide), usable down to phone width.

Audience and job: the player (Archon 5, mostly pos 1) checks a game right after it ends (verdict in under a minute) and also sits down for deeper reviews; party friends may read it. Task: pick a game → read the verdict → play the game back on the board, pausing at each of their own costly moments and decisions → read Immortal comparison (minute-by-minute curves), laning/items, practice plan. Only the player's own play is reviewed (user request, 2026-11-11). Secondary: fetch latest games, re-run analysis, see how well the "coach brain" is trained.

States that matter: no games yet; game parsed but not analysed (analyse on open); analysed without a written report (no API key: show the findings list as the coach, say how to enable the report); models missing or trained on few games (say so plainly); old replay without fog-of-war data; fetch/analyse job running and failed.

Constraints: plain HTML/CSS/JS served by FastAPI, no build step, no Valve art in the project (the board shows the real minimap and hero icons copied from the player's own Dota 2 install at run time; a geometry-drawn map is the fallback), only Google Fonts external.

Memorable moment: selecting a mistake draws the play on the board.

## Direction contract

Replaced 2026-11-11 at the user's request: the user's own MMRSlave logo and brand studio (mmrslave-logo-stacked.svg, mmrslave_svg_logo_brand_studio.html) pin the world; the chalkboard world is retired. Layout and features unchanged.

THESIS: The coach's review rendered as the brand's Dire-crimson HUD: the play that cost you is drawn on the real minimap, framed by obsidian chrome cut like the logo. Refuses neon-glow esports chrome: crimson is a plate colour for actions, never glow.

OWN-WORLD: Obsidian ground (#0a0a0c), slate panels (#141418 / #1b1b22), hairline rules (#2a2a35), stark-white ink; Dire crimson (#e62e25, fill #d0261e) only on brand chrome: primary actions (fetch, play), selected tab and stat pill, current game, focus, selection, section rivets. Game meanings unchanged on map and charts: yellow you/the moment, green your team, red the enemy, green vs yellow Immortal curves (user choice). Light mode is ash: white panels, obsidian ink, deep crimson; the rail stays obsidian in both themes so the logo sits on its own ground. Oxanium 700 uppercase for display, Rajdhani 700 tracked HUD labels, Inter for prose, JetBrains Mono for clocks and numbers. Filled plates (verdict, coach's note, primary buttons) have the logo's chamfered corners with crimson rivets; everything else is squared (2-3px).

STORY: The player opens a game and sees their brand's mark, a verdict plate, and the board; every claim still points to a moment on the map.

FIRST VIEWPORT: Rail: the full stacked logo (user choice), crimson "Fetch my latest games", games list, coach brain + theme switch at the foot. Main: game header, verdict plate, the board with team gold either side, playback bar, coach's note, chart + moments, tabs.

FORM: Brand HUD skin over the existing tactics-board layout (user-pinned; no concept roll). seed: none (concept-seed not run: the user pinned the direction with their own logo, palette and "Oxanium HUD" type, and asked to keep the current layout). Signature: the chamfered crimson-riveted plates echoing the logo frame, and the playback board.

FINISH: finish review, DESIGN.md rewritten from the built world, logo and fonts with provenance.
