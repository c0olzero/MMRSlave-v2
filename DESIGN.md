---
name: MMRSlave
description: A Dota 2 coach's review of your own games, in the brand's Dire-crimson HUD.
colors:
  obsidian-ground: "#0a0a0c"
  obsidian-board: "#141418"
  obsidian-raise: "#1b1b22"
  obsidian-rule: "#2a2a35"
  steel-ink: "#f5f5f7"
  steel-dim: "#b9b9c3"
  steel-faint: "#858592"
  plate-dim: "#4a4a55"
  dire-crimson: "#e62e25"
  crimson-fill: "#d0261e"
  crimson-hi: "#ff4d42"
  crimson-lo: "#9e1b15"
  on-crimson: "#ffffff"
  moment-yellow: "#f2d65c"
  enemy-red: "#ef7a6e"
  team-green: "#8fd18a"
  water-blue: "#7fb7e6"
  you-curve: "#6cc98f"
  you-curve-deep: "#3f9466"
  you-curve-pale: "#b5e8c7"
  immortal-curve-deep: "#c49a2c"
  immortal-curve-pale: "#f7ebb0"
  hp-green: "#6fcf5a"
  hp-enemy: "#e0574a"
  mana-blue: "#4f8fe8"
  ash-ground: "#f1f1f4"
  ash-board: "#ffffff"
  ash-raise: "#e4e4ea"
  ash-rule: "#cfcfd6"
  ash-dim: "#474752"
  ash-faint: "#5f5f6b"
  deep-crimson: "#c4231b"
  deep-crimson-lo: "#7d140f"
  moment-amber: "#7a5300"
  enemy-red-ink: "#a82c22"
  team-green-ink: "#277536"
  water-blue-ink: "#1d5fbd"
  you-curve-ink: "#127a52"
  you-curve-ink-mid: "#4fa77a"
  you-curve-ink-deep: "#0b4a31"
  immortal-curve-ink: "#b87a00"
  immortal-curve-ink-mid: "#dcaa45"
  immortal-curve-ink-deep: "#6e4800"
typography:
  display:
    fontFamily: "Oxanium, Segoe UI, sans-serif"
    fontSize: "clamp(30px, 3.6vw, 44px)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.04em"
  headline:
    fontFamily: "Oxanium, Segoe UI, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "0.01em"
  stat:
    fontFamily: "Oxanium, Segoe UI, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.02em"
  title:
    fontFamily: "Rajdhani, Arial Narrow, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.14em"
  label:
    fontFamily: "Rajdhani, Arial Narrow, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.08em"
  body-heading:
    fontFamily: "Inter, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.4
  body:
    fontFamily: "Inter, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "JetBrains Mono, Consolas, monospace"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.45
    fontFeature: "tnum"
rounded:
  sm: "2px"
  md: "3px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
components:
  button-crimson:
    backgroundColor: "{colors.crimson-fill}"
    textColor: "{colors.on-crimson}"
    typography: "{typography.label}"
    padding: "0 16px"
    height: "40px"
  button-crimson-hover:
    backgroundColor: "{colors.crimson-lo}"
    textColor: "{colors.on-crimson}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.steel-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-outline-hover:
    backgroundColor: "{colors.steel-ink}"
    textColor: "{colors.obsidian-ground}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.steel-dim}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "34px"
  button-quiet-hover:
    backgroundColor: "{colors.obsidian-raise}"
    textColor: "{colors.steel-ink}"
  stat-pill:
    backgroundColor: "transparent"
    textColor: "{colors.steel-dim}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  stat-pill-selected:
    backgroundColor: "{colors.crimson-fill}"
    textColor: "{colors.on-crimson}"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.steel-dim}"
    typography: "{typography.label}"
    padding: "8px 0"
  tab-selected:
    textColor: "{colors.steel-ink}"
  verdict-plate:
    backgroundColor: "{colors.steel-ink}"
    textColor: "{colors.obsidian-ground}"
    typography: "{typography.headline}"
    padding: "16px 24px"
  game-row-current:
    backgroundColor: "{colors.obsidian-raise}"
    textColor: "{colors.crimson-hi}"
    rounded: "{rounded.md}"
    padding: "9px 8px"
  moment-row-selected:
    backgroundColor: "{colors.obsidian-raise}"
    textColor: "{colors.steel-ink}"
    padding: "11px 8px"
  stat-tile:
    backgroundColor: "{colors.obsidian-board}"
    textColor: "{colors.steel-ink}"
    typography: "{typography.stat}"
    rounded: "{rounded.md}"
    padding: "12px"
  board:
    backgroundColor: "{colors.obsidian-board}"
    rounded: "{rounded.md}"
---

# Design System: MMRSlave

## Overview

**Creative North Star: "The Dire-Crimson War Room"**

MMRSlave reviews a Dota 2 game the way a coach breaks down tape, rendered in the player's own brand: an obsidian HUD cut like the MMRSlave logo, with the play that cost the game drawn on the real minimap. The brand is pinned by the user's stacked logo (`mmrslave-logo-stacked.svg`) and brand studio; the logo sits whole at the top of the rail, and its geometry (chamfered frame, crimson rivets) is the only ornament the interface borrows. Obsidian is the default, read at night next to the game client; ash is the light mode, white panels with obsidian ink and a deeper crimson. The rail stays obsidian in both themes so the logo always sits on the ground it was drawn for.

It is a working tool, so the world lends four things and stops: a HUD type voice (Oxanium display, Rajdhani labels), an obsidian palette with crimson reserved for brand chrome, a dense but calm layout, and one signature move, the selected moment played back on the game's own minimap. Navigation, tabs, tables, buttons and the range scrubber stay ordinary web controls. Crimson is a plate colour for actions and selection, never a glow on the interface and never a game meaning; the game keeps its own colours (yellow you, green your team, red the enemy).

**Key Characteristics:**
- Obsidian ground and slate panels with stark steel-white ink; ash-white panels and obsidian ink in light mode; the rail obsidian always.
- Dire crimson only on brand chrome: primary actions, selection, focus, section rivets, plate rivets, coach-brain accents.
- Game meanings in game colours on the board and charts, never crimson.
- Four type voices: Oxanium display, Rajdhani HUD labels, Inter prose, JetBrains Mono clocks and numbers.
- Filled plates take the logo's chamfered corner with a crimson rivet; everything else is squared (2-3px). No pills.
- The board is the real in-game minimap with hero icons, read from the player's own Dota 2 install at run time and never stored in the project; a map drawn from geometry is the fallback.

## Colors

An obsidian HUD with one brand colour for chrome and four game colours that each carry one meaning.

### Primary
- **Dire Crimson** (`dire-crimson`): the brand. Section-title and rail-heading rivets, the verdict and coach's-note corner rivets, the selected tab's underline, the coach-brain card tops and chart dots, the loading line. Its pressed shades: **Crimson Fill** (`crimson-fill`) fills the primary buttons (Fetch my latest games, Play), the selected stat pill, the checkbox accent and text selection; **Crimson Hi** (`crimson-hi`) is the focus ring, the caret and the current game's hero name; **Crimson Lo** (`crimson-lo`) is the hover/pressed fill of crimson buttons. **On Crimson** (`on-crimson`) is the white text on any crimson fill. In ash mode crimson deepens to **Deep Crimson** (`deep-crimson`) for brand and fill, with Crimson Lo as the hi step and **Deep Crimson Lo** (`deep-crimson-lo`) as the pressed step.

### Secondary (game meanings)
- **Moment Yellow** (`moment-yellow`) / **Moment Amber** (`moment-amber`, ash): you and the moment. Your hero's border on the board, game clocks, the chart cursor, the scrubber thumb and moment ticks, the death ring, spot ring and Immortal arrow on the board, the coin on team gold, your row in tables, and Immortal players' line on vs-Immortal curves.
- **Team Green** (`team-green`) / **Team Green Ink** (`team-green-ink`, ash): your teammates and what's good for your team. Teammates' borders, the chart area while your team is favoured, wins, enemy-death ticks.
- **Enemy Red** (`enemy-red`) / **Enemy Red Ink** (`enemy-red-ink`, ash): the enemy and what your side lost. Enemy borders, your team's death ticks, "Lost", win-chance costs, scrubber death ticks, error lines.
- **Water Blue** (`water-blue`) / **Water Blue Ink** (`water-blue-ink`, ash): water on the drawn fallback board, nothing else.

### Tertiary (charts and the in-game HUD)
- **vs-Immortal curves:** you in greens (`you-curve`, `you-curve-deep`, `you-curve-pale`; ash `you-curve-ink`, `you-curve-ink-mid`, `you-curve-ink-deep`), Immortal players in yellows (Moment Yellow, `immortal-curve-deep`, `immortal-curve-pale`; ash `immortal-curve-ink`, `immortal-curve-ink-mid`, `immortal-curve-ink-deep`).
- **Health and mana:** the game's own bar colours on the board, **HP Green** (`hp-green`), **HP Enemy** (`hp-enemy`) and **Mana Blue** (`mana-blue`). The hero card uses darker steps of the same three so its white numbers stay legible on the bar.

### Neutral
- **Obsidian Ground** (`obsidian-ground`) / **Ash Ground** (`ash-ground`): the page. Obsidian Ground is also the ink in ash mode, the board behind the real minimap in both themes, and the theme colour.
- **Obsidian Board** (`obsidian-board`) / **Ash Board** (`ash-board`): the rail, the board, stat tiles, selects.
- **Obsidian Raise** (`obsidian-raise`) / **Ash Raise** (`ash-raise`): hover and selected rows, the hero card, the curve tooltip, inline code.
- **Obsidian Rule** (`obsidian-rule`) / **Ash Rule** (`ash-rule`): hairline dividers, quiet borders, scrollbars.
- **Steel Ink** (`steel-ink`): primary text in obsidian; also the verdict and coach's-note plate fill (reversed). In ash the plate turns obsidian with steel ink.
- **Steel Dim** (`steel-dim`) / **Ash Dim** (`ash-dim`): secondary text, section titles, table heads.
- **Steel Faint** (`steel-faint`) / **Ash Faint** (`ash-faint`): axis labels, the 50% line, crosshairs, "not reviewed yet".
- **Plate Dim** (`plate-dim`): secondary text and tag borders on the light plate.

**The Chrome, Not Meaning Rule.** Crimson marks the brand's own controls: what you can press, what is selected, what has focus. It never marks a hero, a team, a death, a cost or a curve. If crimson is telling the player something about the game, it is wrong; use the game colour.

**The One Meaning Rule.** Each game colour means one thing everywhere: yellow is "you, at this moment", green is "your team and what's good for it", red is "the enemy and what your side lost", blue is only water on the fallback map. Never use them as decoration.

**The Own Ground Rule.** The rail is obsidian in both themes, and the board on the real minimap keeps obsidian and the obsidian-mode game colours in ash mode, because the logo and the map art were drawn for a dark ground.

## Typography

**Display Font:** Oxanium (self-hosted variable woff2; fallback Segoe UI)
**HUD Label Font:** Rajdhani 500/600/700 (self-hosted; fallback Arial Narrow)
**Body Font:** Inter (self-hosted variable woff2; fallback system-ui). Pinned by the user's brand studio, kept on purpose despite its ubiquity.
**Mono Font:** JetBrains Mono (self-hosted variable woff2; fallback Consolas)
**Logo and Vietnamese:** Chakra Petch 500/600/700, for the logo's tagline, and as the display and HUD face when the dashboard is in Vietnamese (Oxanium and Rajdhani have no Vietnamese letters; Inter and JetBrains Mono load their Vietnamese subsets).

**Character:** Oxanium's squared, cut terminals echo the logo's chamfers and carry what a HUD would shout; Rajdhani's narrow tracked capitals label the controls; Inter explains in plain sentences; JetBrains Mono keeps every clock and number in its column.

### Hierarchy
- **Display** (Oxanium 700, clamp(30px, 3.6vw, 44px), 1, 0.04em, uppercase): the hero and result at the top of a game review; the empty-state h1 at 28-38px.
- **Headline** (Oxanium 600, 24px, 1.25, sentence case): the coach's verdict on the plate; balanced, max 60ch; 20px under 820px.
- **Stat** (Oxanium 700, 26px, 1.1, uppercase where lettered): stat-tile values; the same voice sets team-gold totals (28px), coach-brain scores (36px), coach-brain model headings (19px, 0.06em, uppercase), the hero-card name (16px, 0.04em, uppercase) and fallback-board initials.
- **Title** (Rajdhani 700, 15px, 1.2, 0.14em, uppercase): section titles and rail headings, each led by a crimson rivet; table heads at 14px/0.12em; team names at 15px/0.1em.
- **Label** (Rajdhani 700, 15-17px, 0.06-0.1em, uppercase): buttons (16px), tabs (17px), stat pills (15px), kind tags (12px), game names in the rail (18px, no tracking, hero cells 17px). Playback controls (speed, the pause toggle) use Rajdhani 600 at 14.5px.
- **Body heading** (Inter 650, 16px, 1.4, sentence case): list headings; the coach's-note heading at 18px.
- **Body** (Inter 400, 15px, 1.5): explanations, death details, table cells; max 75-80ch. Meta lines 12.5-13.5px.
- **Mono** (JetBrains Mono 500-600, 12-17px, tabular figures): clocks, win-chance costs, the ±10s buttons, axis labels, hero-card and team-gold numbers, results, the speed select, chart values.

**The Four Voices Rule.** Oxanium shouts (headline numbers and names), Rajdhani labels (controls and section titles), Inter explains (any sentence), JetBrains Mono counts (any clock or number in a column). A sentence is never set in Oxanium caps or Rajdhani; a clock is never set in Inter.

**The Clock Column Rule.** Game clocks are always mono, tabular, right-aligned in their own column, and never wrap.

**The Vietnamese Face Rule.** Chakra Petch renders the logo's tagline, and replaces Oxanium and Rajdhani when `<html lang="vi">` (labels drop one size step, since it runs wider). Never mix faces inside a word: a face without the accented letters is not used for Vietnamese.

**The Two Languages Rule.** Every sentence exists in English and Vietnamese. Hero names and game terms (GPM, XPM, net worth, last hits, denies, K/D/A, TP, Roshan, Tormentor, rune, safe lane, mid, tier-2, units) stay in English in both; everyday words are translated (trụ, rừng, sông, base).

## Layout

A fixed left rail (264px, sticky, full height) holds the full stacked logo (up to 208px wide, centred), a "new version" notice when one is waiting, the Steam account card (or the crimson "Sign in through Steam" action when none is connected), the crimson fetch action and its status line, the player's games, and at the foot the coach-brain link beside a column of the EN | VI language switch and, side by side, the settings and theme icons. The main column scrolls with 24px/32px/48px padding and 24px between major blocks. A game review stacks header (hero icon and display h1 on the left; on the right a boxed fact strip, label over value, for result, position, K/D/A, duration, side and match, then the re-run action), verdict plate, then the stage: the board centred and as large as the window allows (up to 940px, about the viewport height minus 200px), each team's stats boxed on its own side (Radiant left and bottom-aligned, Dire right and top-aligned), the player and the coach's note under it. Below, the win-chance chart and the moments list sit side by side, then the tabs. Spacing steps by 4px (4, 8, 12, 16, 24, 32, 48).

Under 1240px the main padding tightens to 24px. Under 1080px the chart and the list stack, both team-gold panels move under the map side by side, and the coach-brain cards stack. Under 820px the rail becomes a top bar (logo 150px), the games list a horizontal snap strip of bordered rows, two-column tabs collapse to one, the board takes the full width, and tables scroll sideways inside themselves, never the page.

## Elevation & Depth

Flat by default, with tonal layering (ground, board, raise). One soft shadow, and only for things that float over the page: the board and the floating cards (the hero card and the curve tooltip). Chamfered plates are flat: their cut corner and rivet carry them, not a shadow. No hard offset shadows, and no glow on interface chrome; the only glow is inside the logo mark itself, which is the user's asset.

### Shadow Vocabulary
- **Float, obsidian** (`box-shadow: 0 12px 32px -14px rgba(0, 0, 0, 0.85)`): the board, the hero card, the curve tooltip.
- **Float, ash** (`box-shadow: 0 10px 30px -14px rgba(10, 10, 12, 0.3)`): the same three in light mode.
- **Map halo** (SVG drop shadow, 0 offset, 3px blur, black at 85%): trails, wards, rings and arrows on the real minimap, to stand off the terrain.

**The Floating Things Rule.** Only the board and cards that hover over it cast a shadow. Plates, tiles, rows and buttons sit flat.

## Shapes

Squared HUD geometry. Small marks (tags, code, item slots, bars, team swatches) at 2px; buttons, rows, inputs, tiles, the board and the tooltip at 3px; the hero card square. Filled plates take the logo's chamfer: a straight 45° cut on the top-left and bottom-right corners (`clip-path`), 16px on the verdict, 12px on the coach's note, 9px on crimson buttons. The verdict carries a 4px crimson rivet band along both cut edges; the coach's note along its top-left cut; crimson buttons are solid crimson and need none. Section titles and rail headings open with a 4×12px crimson rivet notched at its top-left corner. The only circle is the neutral item slot. On the board, hero tiles are 10-unit rounded squares and lines use round caps and joins.

**The Cut Corner Rule.** The chamfer belongs to filled plates (verdict, coach's note, crimson buttons). Outlined and quiet controls, rows, tiles and cards stay squared; nothing is a pill.

## Components

### Buttons
- **Shape:** squared (3px), crimson buttons chamfered (9px cut).
- **Crimson:** Crimson Fill with white Rajdhani label, 40px min height. Only the primary actions: "Sign in through Steam", "Fetch my latest games", "Install and restart" and Play/Pause (52×44px). Hover deepens to Crimson Lo; focus is an inset white ring inside a Crimson Lo ring (the clip would cut an outline).
- **Outline:** transparent with a 1.5px steel outline; fills steel (text turns obsidian) on hover. Used on the coach's note ("Keep playing"), where it takes the plate's ink.
- **Quiet:** 1px rule outline, dim label, 34px; fills Raise on hover. "Re-run review" and Close.
- **Player control:** 40px squared outline, mono label, filled SVG icon; rewind/fast-forward and the 36px speed steps.
- **Language switch:** two-cell squared segment (EN | VI) in Rajdhani; the active cell fills Crimson Fill.
- **Icon:** 36px squared outline (settings and theme), 19px stroked SVG. The settings icon takes Raise and Crimson Hi while its page is open.
- **Busy / disabled:** 55% opacity and a progress cursor; the status line under the button narrates the background job. Colour transitions 160ms ease-out, off under reduced motion.

### Chips (stat pills and tags)
- **Stat pills:** a radio group of squared (3px) outlined Rajdhani labels picking one vs-Immortal stat; selected fills Crimson Fill with white text.
- **Tags:** 2px hairline-bordered, 12.5px Inter evidence tags; kind tags are 12px Rajdhani caps beside a moment's title.

### Cards / Containers
- **Verdict plate:** the reversed plate (Steel Ink fill and obsidian text; obsidian fill in ash), 16px chamfer, two crimson rivet corners, Oxanium headline verdict and an Inter summary. It always says what decided the game, in words.
- **Hero card:** Raise panel, 1px rule border, 3px top edge in the hero's side colour (yellow/green/red), floating shadow. See the Board.
- **Stat tiles:** Board fill, 1px rule, 3px radius, 12px padding: Inter label, Oxanium value, the Immortal typical value, and the better-than bar.
- **Coach-brain cards:** a 3px crimson top rule (rule colour when the model is off), Oxanium caps heading and score.
- **Steam account card (rail):** 1px rule box, 40px square avatar (a "?" tile when it can't load), Rajdhani name and rank under it; the whole card links to Settings.
- **New-version notice (rail):** 1px Crimson Lo outline on a faint Crimson Deep wash, Rajdhani caps with a small crimson diamond; the diamond pulses while an update installs (no pulse under reduced motion).
- **Settings page:** a 760px column of sections under the usual section titles: the account (Board panel, 72px avatar, Oxanium name, Steam ID) with quiet Switch account / Disconnect actions; then the version (mono), a status box (Board panel; Crimson Lo border when a new version is waiting, listing its commit messages) and the auto-install checkbox.

### Inputs / Fields
- **Style:** the timeline is a restyled native range (see the Board); the speed is a mono value between − and + steps; the pause toggle a native checkbox with a crimson accent.
- **Focus:** a 2px Crimson Hi outline, 2px offset, everywhere.

### Navigation
The rail's game rows show hero (Rajdhani 18px), position, K/D/A, day, result (mono, green W / red L) and duration; hover and the current game get Raise, and the current game's hero name turns Crimson Hi. Tabs are Rajdhani caps on a hairline; the selected tab gets steel ink and a 3px crimson underline; arrow keys move between them.

### Moments List
Only about the player: their deaths and decisions (fight you missed, tower lost, no objective, runes), in game order, each with a kind tag. Rows of clock (mono, yellow, right-aligned), what happened, and the win-chance cost (mono, red). Rows are separated by hairlines; selecting one tints it Raise, expands the evidence (tags, allies and enemies nearby, missing enemies, wards, death risk, where Immortal players went), and draws the moment on the board.

### The Board (signature)
The game's own minimap (copied from the player's Dota 2 install by `mmrslave assets`, placed with the game's overview coordinates), on obsidian in both themes. Every hero is their in-game icon on a dark tile with a border for their side: yellow for you (slightly heavier), green for teammates, red for enemies. Enemies your team couldn't see are faded with a dashed border; dead heroes turn grey and lose their bars. Icons that stand on each other in a fight are nudged apart, with a hairline back to the true spot; the hero the moment is about never moves. Without the game files, the board falls back to Board fill with faint grid lines, lanes, river and bases drawn from the analysis geometry, and Oxanium initials on the tiles. The board plays the game back: heroes glide between once-a-second positions, your last 20s trail behind you in white (broken at teleports), wards appear and expire. Each portrait carries a health bar (green, red for enemies) over a thinner blue mana bar.

Beside the board, each team's stats sit in a box on its own side (Board fill, 1px rule, 16px padding, up to 280px): team name with a side swatch, the 34px Oxanium total with a yellow coin, each hero's gold in 16px mono with a 28px icon between hairlines, and team net worth. Hovering, focusing or tapping a portrait opens the hero card beside it (kept inside the map, following the hero during playback): icon, name and clock, health and mana bars with exact numbers, last hits/denies, net worth, unspent gold, then the six item slots (3×2, empty slots dashed) with the neutral item as a circle and any backpack items small and dimmed. In the 30s before one of your deaths it rings the death spot in yellow and arcs a dashed yellow arrow to where high-Immortal players went, with the share in a label; at a decision moment a dashed yellow ring marks the place.

The player works like a video's: a timeline exactly as wide as the map (6px track, 8px on hover, the played part in crimson, a steel thumb ringed crimson, yellow moment and red death ticks above it), and under it the controls: rewind 10s and fast-forward 10s (outlined, double-triangle icons with "10s"), the crimson Play, the yellow mono clock; on the right the speed as − value + steps (0,5x to 8x, steps disable at the ends) and the "Pause at coach moments" toggle. There is no legend: Dota players read the colours already. Pausing at a moment opens the coach's note under the map: a plate in the verdict's colours with a 12px chamfer and a crimson rivet, mono clock, Inter heading, kind tag, cost, the evidence, and "Keep playing" / Close.

### vs Immortal Curves
One stat at a time, chosen with the stat pills: your line in green shades, Immortal players' typical line in yellow shades with the middle half as a faint yellow band (single-stat views only). Stats with two or three lines (last hits & denies, K/D/A) use shades plus solid/dashed/dotted strokes, never colour alone, and always a legend. Hairline grid, mono axis labels, Rajdhani end labels, a crosshair with one floating tooltip listing every line, and a "Show as a table" view. General stats sit below as stat tiles.

### Win-Chance Chart
The team's chance as a steel line over a 50% dashed rule, tinted green above and red below. Death ticks along the bottom: your deaths solid red, teammates' dashed red, enemies' hairline green. The stretch where the model has seen too few games is drawn dashed and labelled "rough". A yellow cursor marks the selected moment.

## Do's and Don'ts

### Do:
- **Do** keep obsidian the default and ash the light mode, with the rail obsidian in both.
- **Do** keep crimson on brand chrome only: primary actions, selected tab and stat pill, current game name, focus ring, text selection, rivets, checkbox accent, loading line, coach-brain accents.
- **Do** give every claim a clock the player can click to see on the board.
- **Do** carry state by line form (solid / dashed / hairline / faded) as well as colour.
- **Do** cut the corners of filled plates with the logo's chamfer and leave everything else squared at 2-3px.
- **Do** show the full stacked logo at the top of the rail, with its construction guides hidden and the tagline fitted to the MMR width.
- **Do** keep controls standard: buttons, tabs, tables, a range input.

### Don't:
- **Don't** use crimson for a game meaning (a hero, a team, a death, a cost, a curve).
- **Don't** put glow on interface chrome; crimson is a plate colour, not a light source.
- **Don't** round anything into a pill.
- **Don't** add a shadow to a plate, tile, row or button.
- **Don't** use Chakra Petch outside the logo.
- **Don't** copy Valve's map or hero art into the project; read it from the player's own install at run time.
- **Don't** show selection with a coloured stripe on the side of a row or card; use the Raise tint.
