"""Evidence-based work-mode and role priority for job processing."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any


_IDENTITY_PATTERN = re.compile(
    r"\b(?:iam|iga|ciamp?|identity|access management|identity governance|"
    r"privileged access|single sign[- ]on|sso|authentication|authorization|"
    r"okta|sailpoint|cyberark|ping identity|forgerock|entra id)\b",
    re.IGNORECASE,
)
_REMOTE_PATTERN = re.compile(
    r"\b(?:fully remote|remote[- ](?:first|only)|remote (?:work|position|role|job|"
    r"location|option|eligible|based)|work remotely|work from home|wfh|"
    r"fully distributed|distributed team)\b",
    re.IGNORECASE,
)
_REMOTE_NEGATION_PATTERN = re.compile(
    r"\b(?:not remote|no remote|remote work (?:is )?not available|"
    r"not a remote position|must work on[- ]site)\b",
    re.IGNORECASE,
)
_HYBRID_PATTERN = re.compile(
    r"\bhybrid\s+(?:work|schedule|role|position|workplace|arrangement)\b",
    re.IGNORECASE,
)
_ONSITE_PATTERN = re.compile(
    r"\b(?:on[- ]?site|in[- ]office|office[- ]based|in person)\b",
    re.IGNORECASE,
)

_TIER_LABELS = {
    0: "Remote IAM/identity",
    1: "Other remote",
    2: "Onsite/hybrid IAM/identity",
    3: "Other onsite/hybrid",
    4: "Unknown work arrangement (review)",
}


def classify_work_mode(title: str | None, description: str | None, location: str | None) -> str:
    """Classify only when listing text provides evidence; otherwise return unknown."""
    text = "\n".join(value or "" for value in (title, description, location))

    location_text = location or ""
    if _HYBRID_PATTERN.search(text) or re.search(r"\bhybrid\b", location_text, re.IGNORECASE):
        return "hybrid"

    title_or_location = f"{title or ''}\n{location_text}"
    explicitly_remote = bool(
        _REMOTE_PATTERN.search(text)
        or re.search(r"\bremote\b", title_or_location, re.IGNORECASE)
    )
    remote_is_negated = bool(_REMOTE_NEGATION_PATTERN.search(text))
    if explicitly_remote and not remote_is_negated:
        return "remote"

    if _ONSITE_PATTERN.search(text) or remote_is_negated:
        return "onsite"

    return "unknown"


def is_identity_role(title: str | None, description: str | None) -> bool:
    """Return whether the title or description contains identity/IAM evidence."""
    return bool(_IDENTITY_PATTERN.search(f"{title or ''}\n{description or ''}"))


def classify_priority_tier(
    title: str | None,
    description: str | None,
    location: str | None,
) -> tuple[int, str, str, bool]:
    """Return (tier, label, work_mode, identity_role) in the requested order.

    Tier 4 is deliberately a review bucket, not one of the four confirmed tiers.
    """
    work_mode = classify_work_mode(title, description, location)
    identity_role = is_identity_role(title, description)

    if work_mode == "unknown":
        tier = 4
    elif work_mode == "remote":
        tier = 0 if identity_role else 1
    else:
        tier = 2 if identity_role else 3

    return tier, _TIER_LABELS[tier], work_mode, identity_role


def _posted_timestamp(value: Any) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def job_priority_key(
    title: str | None,
    description: str | None,
    location: str | None = None,
    match_score: Any = None,
    date_posted: Any = None,
    stable_id: Any = "",
) -> tuple[Any, ...]:
    """Sort by requested tier, then fit score, freshness, and stable identity."""
    tier, _, _, _ = classify_priority_tier(title, description, location)
    try:
        score = float(match_score) if match_score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0

    return (
        tier,
        -score,
        -_posted_timestamp(date_posted),
        (title or "").casefold(),
        str(stable_id or "").casefold(),
    )


def select_pending_jobs(
    connection: sqlite3.Connection,
    limit: int = 10,
    include_unknown: bool = False,
) -> tuple[list[tuple[Any, ...]], int, int]:
    """Select a bounded, ranked PENDING batch without changing database state.

    Returns selected rows, the count of unknown-work-mode rows held for review,
    and the eligible count before applying the batch limit. Row fields are
    ``id, title, company, description, location, match_score, date_posted``.
    """
    if limit < 0:
        raise ValueError("limit must be zero or greater")

    cursor = connection.cursor()
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(jobs)").fetchall()}
    posted_select = "date_posted" if "date_posted" in columns else "NULL"
    cursor.execute(
        "SELECT id, title, company, description, location, match_score, "
        f"{posted_select} FROM jobs WHERE status = 'PENDING'"
    )

    eligible: list[tuple[Any, ...]] = []
    unknown_count = 0
    for row in cursor.fetchall():
        tier, _, _, _ = classify_priority_tier(row[1], row[3], row[4])
        if tier == 4 and not include_unknown:
            unknown_count += 1
            continue
        eligible.append(row)

    eligible.sort(
        key=lambda job: job_priority_key(
            job[1], job[3], job[4], job[5], job[6], job[0]
        )
    )
    eligible_count = len(eligible)
    return eligible[:limit], unknown_count, eligible_count