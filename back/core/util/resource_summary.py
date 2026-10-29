"""Pure rules shared by source-owned Document and Dataset summaries."""

from difflib import SequenceMatcher
import json
from typing import Literal

from .rich_text import visible_text


def _nearby_matches(previous: str, current: str) -> int:
    """A bounded-lookahead alignment also handles insertions in repetitive text."""
    old = new = matched = 0
    while old < len(previous) and new < len(current):
        block = min(256, len(previous) - old, len(current) - new)
        if previous[old:old + block] == current[new:new + block]:
            old += block
            new += block
            matched += block
            continue
        if previous[old] == current[new]:
            old += 1
            new += 1
            matched += 1
            continue
        anchor = min(8, len(previous) - old, len(current) - new)
        inserted = current.find(previous[old:old + anchor], new + 1, new + 257)
        deleted = previous.find(current[new:new + anchor], old + 1, old + 257)
        if inserted >= 0 and (deleted < 0 or inserted - new <= deleted - old):
            new = inserted
        elif deleted >= 0:
            old = deleted
        else:
            old += 1
            new += 1
    return matched


def normalize_source(content: str, kind: Literal["html", "json"]) -> str:
    """Ignore HTML presentation and JSON formatting, retaining actual values."""
    if kind == "json":
        return json.dumps(json.loads(content), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return " ".join(visible_text(content).split())


def change_percent(previous: str, current: str) -> float:
    """Changed share of the larger source; insertions and deletions count once."""
    size = max(len(previous), len(current))
    if not size or previous == current:
        return 0.0
    # Strip unchanged edges before matching: common long boilerplate should not
    # mask a local edit or dominate the matcher. Autojunk bounds repetitive input.
    prefix = 0
    while prefix < min(len(previous), len(current)) and previous[prefix] == current[prefix]:
        prefix += 1
    end_old, end_new = len(previous), len(current)
    while end_old > prefix and end_new > prefix and previous[end_old - 1] == current[end_new - 1]:
        end_old -= 1
        end_new -= 1
    unchanged = prefix + len(previous) - end_old
    unchanged += sum(match.size for match in SequenceMatcher(
        None, previous[prefix:end_old], current[prefix:end_new], autojunk=True,
    ).get_matching_blocks())
    if len(previous) == len(current):
        # Repetition can hide equal spans from autojunk. Aligned substitutions
        # are also a valid edit script, including sparse edits in boilerplate.
        unchanged = max(unchanged, sum(old == new for old, new in zip(previous, current, strict=True)))
    else:
        edges = prefix + len(previous) - end_old
        unchanged = max(unchanged, edges + _nearby_matches(previous[prefix:end_old], current[prefix:end_new]))
    return 100 * (size - unchanged) / size


def needs_summary(current: str, *, summary_present: bool, generated: bool,
                  baseline: str | None, min_chars: int, threshold: float) -> bool:
    if len(current) <= min_chars:
        return False
    if not summary_present:
        return True
    return generated and (baseline is None or change_percent(baseline, current) > threshold)
