"""Issue status derivation, issue matching, and small helpers.

Verification labels follow one rule:
  * "verified"           - FixTrail itself witnessed the act (it received the
                           report, it sent the email, the landlord clicked a button).
  * "tenant_reported"    - the tenant describes something FixTrail didn't see
                           (a phone call, a conversation in the hallway).
  * "landlord_reported"  - same, from the landlord (e.g. "I couldn't get in").
"""

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

CATEGORIES = ["heat", "water", "electrical", "pest", "mold", "lock", "appliance", "other"]
URGENCIES = ["emergency", "urgent", "routine"]

# Events that change an issue's status. The latest one wins.
STATUS_BY_EVENT = {
    "issue_reported": "open",
    "landlord_acknowledged": "acknowledged",
    "landlord_scheduled": "scheduled",
    "landlord_marked_fixed": "landlord_marked_fixed",
    "tenant_confirmed_fixed": "closed",
    "tenant_disputed_fix": "disputed",
}

LANDLORD_EVENT_PHRASES = {
    "landlord_acknowledged": "acknowledged it",
    "landlord_scheduled": "scheduled a repair",
    "landlord_marked_fixed": "said it's fixed",
    "landlord_comment": "left a comment",
    "access_issue": "said they couldn't get in",
}

CATEGORY_KEYWORDS = {
    "heat": ["heat", "heater", "heating", "radiator", "furnace", "boiler", "cold"],
    "water": ["leak", "leaking", "sink", "toilet", "pipe", "faucet", "shower", "drain", "water", "flood"],
    "electrical": ["outlet", "light", "electric", "electrical", "power", "breaker", "wiring", "switch"],
    "pest": ["mice", "mouse", "rat", "roach", "cockroach", "bug", "bedbug", "pest", "ant"],
    "mold": ["mold", "mould", "mildew", "damp"],
    "lock": ["lock", "door", "key", "deadbolt", "window"],
    "appliance": ["fridge", "refrigerator", "stove", "oven", "dishwasher", "washer", "dryer", "microwave"],
}

STOPWORDS = {
    "the", "a", "an", "my", "our", "in", "on", "of", "is", "it", "issue", "problem",
    "one", "that", "this", "with", "about", "again", "still", "broken",
    # Words that appear in many titles ("Heater not working") and would
    # otherwise make unrelated phrases match ("nothing" starts with "not").
    "not", "working", "work", "doesn", "doesnt", "isn", "isnt", "t", "s", "fixed",
}


def derive_status(events: list[dict]) -> str:
    """Work out the current status from the events (the source of truth)."""
    status = "open"
    for event in events:
        status = STATUS_BY_EVENT.get(event["type"], status)
    return status


def guess_category(text: str) -> str:
    words = set(tokens(text))
    for category, keywords in CATEGORY_KEYWORDS.items():
        if words & set(keywords):
            return category
    return "other"


# ------------------------------------------------------------------ time

def days_since(iso_timestamp: str, now: datetime | None = None) -> int:
    then = datetime.fromisoformat(iso_timestamp)
    return ((now or datetime.now(timezone.utc)) - then).days


def describe_days(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    return f"{days} days"


def ago(days: int) -> str:
    """'today', 'yesterday', '3 days ago'."""
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


# -------------------------------------------------------------- matching

def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def _word_score(query_word: str, issue_words: list[str]) -> float:
    best = 0.0
    for word in issue_words:
        if word == query_word:
            return 1.0
        shorter, longer = sorted((word, query_word), key=len)
        if len(shorter) >= 4 and longer.startswith(shorter):  # heat / heater
            best = max(best, 0.8)
        elif len(shorter) >= 5 and difflib.SequenceMatcher(None, word, query_word).ratio() >= 0.82:
            best = max(best, 0.7)  # typos: haeter / heater (but not light / night)
    return best


@dataclass
class Match:
    issue: dict | None = None
    candidates: list[dict] = field(default_factory=list)  # set when ambiguous


def match_issue(query: str, issues: list[dict]) -> Match:
    """Find the issue a person means by "the heater" or "kitchen sink".

    Returns Match(issue=...) for one clear winner, Match(candidates=[...])
    when several issues tie, and Match() when nothing matches.
    """
    for issue in issues:
        if query.strip() == issue["id"]:
            return Match(issue=issue)

    query_words = tokens(query)
    if not query_words:
        return Match(issue=issues[0]) if len(issues) == 1 else Match(candidates=issues)

    scored = []
    for issue in issues:
        issue_words = tokens(f"{issue['title']} {issue['location']} {issue['category']}")
        score = sum(_word_score(w, issue_words) for w in query_words)
        if score > 0:
            scored.append((score, issue))
    if not scored:
        return Match()

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = scored[0][0]
    tied = [issue for score, issue in scored if score == best]
    return Match(issue=tied[0]) if len(tied) == 1 else Match(candidates=tied)
