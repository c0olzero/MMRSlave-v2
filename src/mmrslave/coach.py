"""Turn a match analysis into a written coaching report with Claude."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mmrslave.config import Settings, anthropic_api_key

SYSTEM_PROMPT = """You are a Dota 2 coach reviewing one ranked match for a player who wants to climb.

You coach ONLY this player. In public games they can't control their teammates, so teammates'
play is context, never the subject: don't grade or blame teammates. When a teammate made a
mistake, ask what the player could have done about it (TP to help, rotate, ward, join the fight,
take the objective, stay safe, farm elsewhere).

You receive a JSON analysis produced by software that parsed the replay and ran neural networks
trained on thousands of recent high-Immortal ranked games:
- win_chance: the player's team's estimated chance to win over time. A death's
  "win_chance_cost_pct" is how much lower that chance was than if the hero had survived.
- risk: estimated chance the hero dies within 15 seconds, using only what their team could see.
- immortal_would_be: where high-Immortal players in the same situation usually headed next.
- decisions: situations where the player could have acted differently, already checked against
  the replay: fights the player could have reached (by TP or on foot) before a teammate died,
  towers lost to several enemies while the player was away, windows with 3+ enemies dead where
  the team took no objective, and rune control. Each has what happened and a suggestion.
  "converted" lists the times the team did use such an advantage (good examples).
- vs_immortal: the player's numbers against Immortal players on the same hero and position,
  as "better_than_pct_of_immortals" (50 = typical Immortal; low = well behind).
- enemies_missing_8s_before: enemies the team couldn't see just before a death, and for how long.

How to coach:
- Go deeper than deaths. Cover the player's decisions over the whole map and game: where they
  farmed while fights happened, TPs they could have made when a teammate was dived under a tower,
  rotations for runes, using the time when enemies are dead to take towers, Roshan or Tormentor,
  and when to farm versus group. Use the decisions list as evidence and refine its suggestions
  for the player's hero and position (a farming carry shouldn't join every fight; say which ones
  were worth it and why).
- Be specific and concrete. Every mistake needs its game clock and the evidence from the data
  (who was missing, wards, HP, distance, how many enemies were dead, win chance lost). Never
  invent events or numbers that aren't in the analysis.
- Prioritise. The 4-7 mistakes that cost the most win chance or repeat a pattern matter more than
  a long list. Group repeated mistakes into one pattern ("3 times your team fought mid while you
  farmed the off lane, and a TP to mid tier-2 would have arrived in time").
- "do_instead" must be an action the player can take next game: where to stand, when to TP, when
  to back, what to buy, when to ward or smoke. Tie it to their hero and position.
- Compare with Immortal players to show what good looks like, not to belittle. Account for the
  player's rank when it is given: a player below Ancient needs fundamentals before advanced tricks.
- Plain language a Dota player uses. No filler, no generic advice like "communicate more" unless
  the data shows it.
- Wrap hero names, items and clocks in plain text (no markdown)."""

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence: why the game was won or lost."},
        "summary": {"type": "string", "description": "3-5 sentences on how the game went for the player."},
        "your_mistakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clock": {"type": "string", "description": "Game clock like 14:32, or a range, or 'whole game'."},
                    "title": {"type": "string"},
                    "what_happened": {"type": "string"},
                    "why_it_mattered": {"type": "string"},
                    "do_instead": {"type": "string"},
                },
                "required": ["clock", "title", "what_happened", "why_it_mattered", "do_instead"],
                "additionalProperties": False,
            },
        },
        "what_you_did_well": {"type": "array", "items": {"type": "string"}},
        "practice_focus": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "habit": {"type": "string"},
                    "how_to_practice": {"type": "string"},
                },
                "required": ["habit", "how_to_practice"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "summary", "your_mistakes", "what_you_did_well", "practice_focus"],
    "additionalProperties": False,
}


class CoachError(Exception):
    pass


def condense(an: dict[str, Any], rank: str | None = None) -> dict[str, Any]:
    """The parts of the analysis worth sending: the player's own detail, the rest as context."""
    me, my_team = an["me"], an["my_team"]
    brief = ("clock", "victim_hero", "killer_hero", "where", "win_chance_cost_pct")
    deaths_mine = [d for d in an["deaths"] if d["victim"] == me]
    deaths_context = [{k: d[k] for k in brief if k in d} | {"side": "your team" if (d["victim"] < 5) == (my_team == 0)
                                                            else "enemy"}
                      for d in an["deaths"] if d["victim"] != me]
    out = {
        "player": None if me is None else {
            "hero": an["players"][me]["hero"], "position": an["players"][me]["position"], "rank": rank},
        "result": "won" if an["won"] else "lost" if an["won"] is False else "unknown",
        "duration": an["duration"], "score": an["score"],
        "fog_of_war_data": an.get("has_visibility"),
        "models_used": an["models_used"],
        "players": [{k: p[k] for k in ("hero", "position", "is_me", "kills", "deaths", "assists",
                                       "net_worth", "last_hits", "level", "final_items")}
                    | {"side": "your team" if p["team"] == my_team else "enemy"} for p in an["players"]],
        "your_deaths": deaths_mine,
        "other_deaths_for_context": deaths_context,
        "decisions": an.get("decisions"),
        "win_chance_peak": an.get("peak"),
        "win_chance_rough_after": None if not an.get("win_chance") else
            f"{an['win_chance']['reliable_until_s'] // 60}:{an['win_chance']['reliable_until_s'] % 60:02d} "
            "(fewer than 5% of training games last longer; treat later win-chance numbers as rough)",
        "key_moments": an.get("key_moments"),
        "your_impact": next((i for i in an.get("impact") or [] if i["pid"] == me), None),
        "your_laning": an["laning"][me] if an.get("laning") and me is not None else None,
        "your_vs_immortal": an["vs_immortal"][me] if an.get("vs_immortal") and me is not None else None,
        "top_findings": an["findings"][:30],
    }
    return out


def write_report(s: Settings, an: dict[str, Any], rank: str | None = None) -> dict[str, Any]:
    if an.get("me") is None:
        raise CoachError("You're not in this match, so there's no one to coach. Check player.steam_id.")
    try:
        import anthropic
    except ImportError as e:
        raise CoachError("The anthropic package isn't installed: pip install anthropic") from e
    if not anthropic_api_key():
        raise CoachError("Set the ANTHROPIC_API_KEY environment variable to get written coaching reports. "
                         "The analysis itself is saved and shown without it.")

    client = anthropic.Anthropic()
    payload = json.dumps(condense(an, rank), separators=(",", ":"), default=str)
    t0 = time.time()
    try:
        # Streaming keeps long generations clear of HTTP timeouts. fallbacks="default" re-runs the
        # request on a fallback model if a safety classifier wrongly declines a gaming question.
        with client.beta.messages.stream(
            model=s.coach_model,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
            messages=[{"role": "user", "content": "Here is the match analysis. Write the coaching report.\n\n"
                                                  + payload}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise CoachError("Anthropic rejected the API key (ANTHROPIC_API_KEY).") from e
    except anthropic.RateLimitError as e:
        raise CoachError("Anthropic rate limit reached; try again in a minute.") from e
    except anthropic.APIConnectionError as e:
        raise CoachError(f"Couldn't reach the Anthropic API: {e}") from e
    except anthropic.APIStatusError as e:
        raise CoachError(f"Anthropic API error {e.status_code}: {e.message}") from e

    if msg.stop_reason == "refusal":
        raise CoachError("The model declined to write this report.")
    if msg.stop_reason == "max_tokens":
        raise CoachError("The report was cut off (too long).")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if not text:
        raise CoachError("The model returned no report text.")
    report = json.loads(text)
    report["_meta"] = {"model": msg.model, "seconds": round(time.time() - t0, 1),
                       "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
                       "written_at": time.strftime("%Y-%m-%d %H:%M")}
    return report


def report_path(s: Settings, match_id: int) -> Path:
    return s.reports_dir / f"{match_id}.report.json"


def save_report(s: Settings, match_id: int, report: dict[str, Any]) -> Path:
    path = report_path(s, match_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return path


RANK_NAMES = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon", 5: "Legend", 6: "Ancient", 7: "Divine",
              8: "Immortal"}


def rank_name(rank_tier: int | None) -> str | None:
    if not rank_tier:
        return None
    medal, star = divmod(int(rank_tier), 10)
    name = RANK_NAMES.get(medal)
    return None if not name else (name if medal == 8 or not star else f"{name} {star}")
