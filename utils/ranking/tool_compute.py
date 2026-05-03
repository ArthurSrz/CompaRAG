"""
Tool ranking computation using Bradley-Terry model.

Isolated from the LLM ranking path (compute.py) per D-01.
Only shared primitive: bootstrap_confidence_intervals from bradley_terry.py.

Output shape mirrors the LLM pipeline (DatasetData + PreferencesData) so the
frontend leaderboard can reuse LLM ranking components.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from backend.config import ALL_PREFS, NEGATIVE_PREFS, POSITIVE_PREFS
from utils.ranking.bradley_terry import bootstrap_confidence_intervals
from utils.ranking.tool_queries import fetch_tool_votes
from utils.utils import configure_logger

logger = configure_logger(logging.getLogger("ranking.tool_compute"))

PROVISIONAL_THRESHOLD = 50


@dataclass
class ToolRankingEntry:
    tool_id: str
    elo: int
    score_p2_5: int
    score_p97_5: int
    rank: int
    rank_p2_5: int
    rank_p97_5: int
    n_match: int
    mean_win_prob: float
    win_rate: float
    provisional: bool


@dataclass
class ToolPreferencesData:
    positive_prefs_ratio: float
    total_prefs: int
    useful: int
    complete: int
    creative: int
    clear_formatting: int
    incorrect: int
    superficial: int
    instructions_not_followed: int


@dataclass
class ToolRankingResult:
    timestamp: float
    rankings: dict[str, ToolRankingEntry] = field(default_factory=dict)
    preferences: dict[str, ToolPreferencesData] = field(default_factory=dict)


def _tool_votes_to_battles(votes: list[dict]) -> list[tuple[str, str, str]]:
    """Convert tool vote records to battle tuples, filtering ties."""
    battles = []
    for v in votes:
        if v["chosen"] == "tie":
            continue
        winner = v["tool_a_id"] if v["chosen"] == "a" else v["tool_b_id"]
        battles.append((v["tool_a_id"], v["tool_b_id"], winner))
    return battles


def _aggregate_tool_preferences(
    votes: list[dict],
) -> dict[str, ToolPreferencesData]:
    """Aggregate per-side preference flags from tool_votes into per-tool counts.

    Mirrors compute._aggregate_preferences (vote-side branch only — there is no
    tool_reactions table). Each vote row contributes to BOTH tools' totals.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {f: 0 for f in ALL_PREFS})
    total: dict[str, int] = defaultdict(int)

    for v in votes:
        for side in ("a", "b"):
            tool = v[f"tool_{side}_id"]
            total[tool] += 1
            for pref_field in ALL_PREFS:
                if v.get(f"vote_{pref_field}_{side}"):
                    counts[tool][pref_field] += 1

    result: dict[str, ToolPreferencesData] = {}
    for tool in total:
        c = counts[tool]
        positive_count = sum(c[f] for f in POSITIVE_PREFS)
        negative_count = sum(c[f] for f in NEGATIVE_PREFS)
        all_prefs_count = positive_count + negative_count

        result[tool] = ToolPreferencesData(
            positive_prefs_ratio=(
                positive_count / all_prefs_count if all_prefs_count > 0 else -1
            ),
            total_prefs=total[tool],
            useful=c["useful"],
            complete=c["complete"],
            creative=c["creative"],
            clear_formatting=c["clear_formatting"],
            incorrect=c["incorrect"],
            superficial=c["superficial"],
            instructions_not_followed=c["instructions_not_followed"],
        )

    return result


def compute_tool_rankings() -> ToolRankingResult | None:
    """
    Main function for tool ranking computation.

    Fetches votes from DB, converts to battles, runs Bradley-Terry with
    bootstrap confidence intervals, computes rank bounds + mean win prob,
    and aggregates per-side preferences.

    Returns:
        ToolRankingResult with empty rankings/preferences if no battles exist.
        None only on unexpected failure.
    """
    try:
        votes = fetch_tool_votes()
    except Exception:
        logger.error("[ToolRanking] Failed to fetch tool votes", exc_info=True)
        return None

    battles = _tool_votes_to_battles(votes)

    if not battles:
        logger.warning("[ToolRanking] No tool battles found, returning empty result")
        return ToolRankingResult(timestamp=time.time())

    ci = bootstrap_confidence_intervals(battles, n_samples=100)

    match_counts: dict[str, int] = defaultdict(int)
    win_counts: dict[str, int] = defaultdict(int)
    for a, b, winner in battles:
        match_counts[a] += 1
        match_counts[b] += 1
        win_counts[winner] += 1

    # Sort by bootstrap median Elo descending (matches compute.py:146)
    sorted_tools = sorted(ci, key=lambda t: -ci[t][0])
    n_total = len(sorted_tools)

    rankings: dict[str, ToolRankingEntry] = {}
    for rank, tool_id in enumerate(sorted_tools, 1):
        elo_median, elo_lower, elo_upper = ci[tool_id]
        n_match = match_counts.get(tool_id, 0)
        wins = win_counts.get(tool_id, 0)

        # Rank bounds via CI overlap (compute.py:155-166):
        # rank_best  = 1 + tools whose lower CI > this tool's upper CI
        # rank_worst = N - tools whose upper CI < this tool's lower CI
        rank_best = 1
        rank_worst = n_total
        for other in sorted_tools:
            if other == tool_id:
                continue
            if ci[other][1] > elo_upper:
                rank_best += 1
            if elo_lower > ci[other][2]:
                rank_worst -= 1

        # Mean win probability (compute.py:168-176)
        strength_i = 10 ** ((elo_median - 1000) / 400)
        win_probs = []
        for other in sorted_tools:
            if other == tool_id:
                continue
            strength_j = 10 ** ((ci[other][0] - 1000) / 400)
            win_probs.append(strength_i / (strength_i + strength_j))
        mean_win_prob = sum(win_probs) / len(win_probs) if win_probs else 0.5

        rankings[tool_id] = ToolRankingEntry(
            tool_id=tool_id,
            elo=round(elo_median),
            score_p2_5=round(elo_lower),
            score_p97_5=round(elo_upper),
            rank=rank,
            rank_p2_5=rank_best,
            rank_p97_5=rank_worst,
            n_match=n_match,
            mean_win_prob=round(mean_win_prob, 4),
            win_rate=round(wins / n_match, 4) if n_match > 0 else 0.0,
            provisional=n_match < PROVISIONAL_THRESHOLD,
        )

    preferences = _aggregate_tool_preferences(votes)

    return ToolRankingResult(
        timestamp=time.time(),
        rankings=rankings,
        preferences=preferences,
    )
