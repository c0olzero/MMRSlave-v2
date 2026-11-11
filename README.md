# MMRSlave

An AI Dota 2 coach. It learns what good play looks like from thousands of recent
**high-Immortal ranked games**, then reviews your replays and tells you what went wrong:
your deaths and your decisions (fights you could have TPed to, towers lost while you farmed,
enemies dead but no objective taken, runes), and what to do instead, with game clocks and evidence.

## How it works

1. **Collect.** Finds recent ranked games where at least 8 of 10 players are Immortal
   (via the OpenDota API), downloads the replays from Valve, and parses them with
   [gem-dota](https://github.com/whanyu1212/gem-dota) into compact per-second match records.
2. **Learn.** Trains neural networks on your GPU:
   - **Win probability**: your team's chance to win at every moment. Used to price each
     death and find the moments that swung the game.
   - **Hero context**: from one hero's point of view, using only what their team could see:
     the chance they die in the next 15 s, and where a high-Immortal player would be 30 s later.
   - **Benchmarks**: net worth, last hits, deaths, wards and item timings of Immortal players
     on each hero and position.
3. **Review.** For each of your games: every death examined (enemies missing, wards, allies
   nearby, teleports, danger before the death, win chance lost), biggest swings, laning,
   items, and a written report from Claude.
4. **Improve.** Valve keeps replays for about 10 days, so collection keeps running, and the
   models are retrained as new games arrive. They keep up with the current patch on their own.

## Setup (once)

```powershell
cd "E:\My Coding Journey\MMRSlave"
.\.venv\Scripts\Activate.ps1          # the project's Python environment
copy mmrslave.example.toml mmrslave.toml   # already done; edit paths/Steam ID if needed
```

For the written coaching report, set your Anthropic API key (get one at console.anthropic.com):

```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."   # then open a new terminal
```

In Dota 2, keep **Settings → Social → Expose Public Match Data** on, so your games can be fetched.

## Everyday use

| Command | What it does |
|---|---|
| `python -m mmrslave mine` | Download and parse your last 20 games |
| `python -m mmrslave analyze` | Review your latest game (or `analyze <match_id>`) |
| `python -m mmrslave serve` | Open the dashboard at http://127.0.0.1:8765 |
| `python -m mmrslave auto` | One full cycle: collect Immortal games, retrain when 300+ are new, fetch and review your games |
| `python -m mmrslave status` | What's collected and trained |
| `python -m mmrslave assets` | Copy the minimap and hero icons from your Dota 2 install again |
| `python -m mmrslave reparse` | Download your recent games again so they get the newest stats (damage and assists over time) |

The dashboard's map is the game's own minimap with the in-game hero icons (yellow border:
you, green: teammates, red: enemies). They're copied from your Dota 2 install into
`data_dir/game_assets` when the dashboard starts, and again after a game update; nothing
from Valve is stored in this project. If the install can't be found, set `paths.dota_dir`
in `mmrslave.toml`; until then the board shows a drawn map.

The board plays the game back (play/pause, ±10 s, 0.5x to 8x). Every hero shows health and mana bars,
and each team's unspent gold is listed beside the map on its own side.

The dashboard is in English or Vietnamese (switch at the bottom of the sidebar). Hero names and game
terms (GPM, net worth, last hits, TP, Roshan, rune...) stay in English in both. The written Claude
report is in English. Hover (or tap) a hero for that moment's
last hits/denies, health, mana, net worth, unspent gold and items. With **Pause at coach moments**
on, it stops at each of your deaths and decisions and shows the coach's note under the map.

The **vs Immortal** tab draws your numbers minute by minute (green) against Immortal players on
the same hero and position (yellow). Hero damage, building damage and assists over time are only
in games parsed by the current version: the Immortal lines for them fill in as `collect` runs and
`benchmarks` is rebuilt.

## Building up the training data

| Command | What it does |
|---|---|
| `python -m mmrslave collect` | Collect Immortal games until the daily API allowance runs out (~1,000 games/day) |
| `python -m mmrslave train` | Retrain the networks on everything collected |
| `python -m mmrslave benchmarks` | Rebuild the Immortal benchmark stats |
| `python -m mmrslave stats` | Skill spread of the collected games (to raise the bar for "high" Immortal) |
| `python -m mmrslave local` | Parse the replays already in your Dota replay folder |

Run one collecting command at a time (`collect`, `mine` and `auto` share the download queue).

The free OpenDota tier allows 3,000 API calls a day (about 1,000 qualifying games). An
OpenDota API key (`setx OPENDOTA_API_KEY ...`) lifts that limit for a small per-call fee.

## Honest limits

- The models are only as good as the data. With a few hundred games they are rough; they
  get much better past a few thousand. `python -m mmrslave status` and the dashboard show
  how many games they were trained on and how accurate they are.
- Replays before 2025 don't record what each team could see, so death-risk reads are weaker
  on old games.
- The coach compares you with high-Immortal solo-queue players, not pros, so the advice fits
  the game you actually play.

## Where things are

- Data (replays, parsed matches, models, reports): `D:/MMRSlaveData` (set in `mmrslave.toml`)
- Code: `src/mmrslave/` (`collect.py`, `extract.py`, `features.py`, `models.py`, `train.py`,
  `analyze.py`, `coach.py`, `web/`)
