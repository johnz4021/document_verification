"""Deterministic rule handlers. These never touch the model — free speed,
zero variance, and one demo row that is undeniably, checkably correct."""

from __future__ import annotations

import re
from datetime import date, timedelta

from engine.schemas import DocumentIn, Finding, Rule

_WEEKLY_WINDOW_DAYS = 61  # "at least weekly for the first 2 months"
_MAX_GAP_DAYS = 7


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


def progress_note_cadence(rule: Rule, documents: list[DocumentIn]) -> Finding:
    """Check 482.61(d)-style note frequency from document dates alone.

    Admission is taken as the earliest dated document; every consecutive gap
    between progress notes (and admission -> first note) within the first two
    months must be at most 7 days.
    """
    base = {
        "rule_id": rule.rule_id,
        "requirement_verbatim": rule.requirement_verbatim,
        "mode": "computed",
        "confidence": "high",
        "source": "",
        "source_url": "",
    }

    all_dates = [d for d in (_parse_date(doc.date) for doc in documents) if d]
    notes = sorted(
        (
            (_parse_date(doc.date), doc)
            for doc in documents
            if "progress note" in doc.doc_type.lower() and _parse_date(doc.date)
        ),
        key=lambda pair: pair[0],
    )

    if not all_dates or not notes:
        return Finding(
            **base,
            verdict="fail",
            rationale="No dated progress notes found in the chart, so the weekly "
            "progress-note requirement cannot be met.",
        )

    admission = min(all_dates)
    window_end = admission + timedelta(days=_WEEKLY_WINDOW_DAYS)

    checkpoints: list[tuple[date, str]] = [(admission, "admission")]
    checkpoints += [(d, f"progress note dated {d.isoformat()}") for d, _ in notes]

    violations = []
    for (prev_date, prev_label), (cur_date, cur_label) in zip(checkpoints, checkpoints[1:]):
        if prev_date > window_end:
            break
        gap = (cur_date - prev_date).days
        if gap > _MAX_GAP_DAYS:
            violations.append((gap, prev_label, cur_label))

    dates_str = ", ".join(d.isoformat() for d, _ in notes)
    if violations:
        gap, prev_label, cur_label = max(violations)
        return Finding(
            **base,
            verdict="fail",
            rationale=(
                f"Admission {admission.isoformat()}; progress notes dated {dates_str}. "
                f"The gap of {gap} days between {prev_label} and the {cur_label} exceeds "
                f"the required weekly cadence for the first 2 months (computed from "
                f"document dates; no model involved)."
            ),
        )
    return Finding(
        **base,
        verdict="pass",
        rationale=(
            f"Admission {admission.isoformat()}; progress notes dated {dates_str}. "
            f"Every interval within the first 2 months is 7 days or less, satisfying "
            f"the weekly cadence (computed from document dates; no model involved)."
        ),
    )


_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_QUARTER_MAX_GAP_DAYS = 92


def quarterly_review_cadence(rule: Rule, documents: list[DocumentIn]) -> Finding:
    """Check that dated entries in the scoped log occur at least quarterly.

    Extracts every ISO date from the scoped documents' text, sorts them, and
    requires each consecutive gap to be at most ~one quarter (92 days).
    """
    base = {
        "rule_id": rule.rule_id,
        "requirement_verbatim": rule.requirement_verbatim,
        "mode": "computed",
        "confidence": "high",
        "source": "",
        "source_url": "",
    }
    dates = sorted(
        {
            d
            for doc in documents
            for raw in _ISO_DATE_RE.findall(doc.text)
            if (d := _parse_date(raw))
        }
    )
    if len(dates) < 2:
        return Finding(
            **base,
            verdict="fail",
            rationale="Fewer than two dated entries found in the scoped log; a "
            "quarterly cadence cannot be demonstrated.",
        )
    dates_str = ", ".join(d.isoformat() for d in dates)
    gaps = [(int((b - a).days), a, b) for a, b in zip(dates, dates[1:])]
    worst = max(gaps)
    if worst[0] > _QUARTER_MAX_GAP_DAYS:
        gap, a, b = worst
        return Finding(
            **base,
            verdict="fail",
            rationale=(
                f"Entries dated {dates_str}. The gap of {gap} days between "
                f"{a.isoformat()} and {b.isoformat()} exceeds the quarterly cadence "
                f"(computed from dates in the log; no model involved)."
            ),
        )
    return Finding(
        **base,
        verdict="pass",
        rationale=(
            f"Entries dated {dates_str}. Every consecutive interval is 92 days or "
            f"less, consistent with a quarterly cadence (computed from dates in "
            f"the log; no model involved)."
        ),
    )


HANDLERS = {
    "progress_note_cadence": progress_note_cadence,
    "quarterly_review_cadence": quarterly_review_cadence,
}
