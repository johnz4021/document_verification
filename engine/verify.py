"""Citation-grounding guard.

A `pass` verdict may not reach the client unless its evidence span actually
exists, verbatim, in the cited document. This makes a hallucinated pass
structurally impossible and gives the UI free highlighting via the resolved
offsets. Exact match first; a whitespace-tolerant fallback catches spans the
model reflowed across line breaks. Anything unverifiable is downgraded to
`unclear`, never silently accepted.

Applies to semantic findings only — computed findings never touch the model.
"""

from __future__ import annotations

import re

from engine.schemas import DocumentIn, Finding

_UNVERIFIED_NOTE = " [Evidence span could not be verified against the source; downgraded.]"


def _locate(evidence: str, text: str) -> tuple[int, int] | None:
    start = text.find(evidence)
    if start != -1:
        return start, start + len(evidence)
    # Whitespace-tolerant fallback: match the same tokens across any whitespace.
    tokens = evidence.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(tok) for tok in tokens)
    m = re.search(pattern, text)
    if m:
        return m.start(), m.end()
    return None


def verify_finding(finding: Finding, docs_by_id: dict[str, DocumentIn]) -> Finding:
    if finding.mode != "semantic":
        return finding

    if finding.verdict == "pass":
        doc = docs_by_id.get(finding.doc_id) if finding.doc_id else None
        span = _locate(finding.evidence, doc.text) if (doc and finding.evidence) else None
        if span is None:
            return finding.model_copy(
                update={
                    "verdict": "unclear",
                    "char_start": None,
                    "char_end": None,
                    "rationale": finding.rationale + _UNVERIFIED_NOTE,
                }
            )
        return finding.model_copy(update={"char_start": span[0], "char_end": span[1]})

    # For fail/unclear, evidence is optional context — resolve offsets if it
    # checks out, otherwise drop the span rather than showing a bogus quote.
    if finding.evidence and finding.doc_id:
        doc = docs_by_id.get(finding.doc_id)
        span = _locate(finding.evidence, doc.text) if doc else None
        if span is not None:
            return finding.model_copy(update={"char_start": span[0], "char_end": span[1]})
        return finding.model_copy(update={"evidence": None, "doc_id": None})
    return finding
