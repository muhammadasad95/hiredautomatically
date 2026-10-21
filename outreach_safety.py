"""Fail-closed controls for bounded, deduplicated outreach batches."""

from __future__ import annotations

import os
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_limit(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        limit = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if limit < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return limit


def get_outreach_settings(
    send_enabled: bool | None = None,
    dry_run: bool | None = None,
    max_per_run: int | None = None,
    max_per_day: int | None = None,
) -> dict[str, Any]:
    """Read safe defaults; live sending requires explicit enable and dry-run off."""
    settings = {
        "send_enabled": _env_bool("OUTREACH_SEND_ENABLED", False) if send_enabled is None else send_enabled,
        "dry_run": _env_bool("OUTREACH_DRY_RUN", True) if dry_run is None else dry_run,
        "max_per_run": _env_limit("OUTREACH_MAX_PER_RUN", 5) if max_per_run is None else max_per_run,
        "max_per_day": _env_limit("OUTREACH_MAX_PER_DAY", 5) if max_per_day is None else max_per_day,
    }
    for key in ("max_per_run", "max_per_day"):
        if not isinstance(settings[key], int) or isinstance(settings[key], bool) or settings[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    return settings


def select_unique_company_contacts(rows: list[tuple[Any, ...]], limit: int) -> list[tuple[Any, ...]]:
    """Keep first eligible NEW contact per company and email, respecting a cap.

    Rows start with ``contact_id, company, first_name, title, email``. Remaining
    row elements (for example tailored resume and cover letter) pass through.
    """
    if limit <= 0:
        return []
    selected = []
    seen_companies: set[str] = set()
    seen_emails: set[str] = set()
    for row in rows:
        company_key = str(row[1] or "").strip().casefold()
        email_key = str(row[4] or "").strip().casefold()
        if not company_key or not email_key or company_key in seen_companies or email_key in seen_emails:
            continue
        seen_companies.add(company_key)
        seen_emails.add(email_key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected