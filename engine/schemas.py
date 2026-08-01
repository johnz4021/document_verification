"""Core types for the audit engine.

`FindingDraft` is what the LLM emits (via structured output); `Finding` is the
draft merged with rule metadata and citation-verified offsets — the shape the
UI consumes. Verdict vocabulary is deliberately three-state: a cautious
`unclear` (amber) is always preferred over a wrong `fail` (red).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["pass", "fail", "unclear"]
Confidence = Literal["high", "medium", "low"]
RuleType = Literal["semantic", "computed"]

# committed: byte-identical to the pristine rulebook on disk.
# modified: same rule_id as a committed rule, but the judge changed something.
# user: authored this session. Computed server-side by diff — never asserted
# by the client — so an edited rule can't wear verbatim-citation styling.
Provenance = Literal["committed", "modified", "user"]


class Rule(BaseModel):
    rule_id: str
    requirement_verbatim: str
    evidence_required: str
    rule_type: RuleType
    handler: str | None = None
    scope_docs: list[str]
    provenance: Provenance = "committed"


class Rulebook(BaseModel):
    rulebook_id: str
    name: str
    source: str
    source_url: str
    default_corpus: str
    rules: list[Rule]


class DocumentIn(BaseModel):
    """A document as the audit endpoint receives it: flattened plain text.

    The judge edits this text directly in the UI, so everything downstream
    (prompting, span verification, offsets) works on `text` alone.
    """

    doc_id: str
    doc_type: str
    date: str
    text: str


class FindingDraft(BaseModel):
    """What the model must emit for one rule."""

    verdict: Verdict
    evidence: str | None = Field(
        default=None,
        description=(
            "For pass: a short verbatim span copied EXACTLY from one document, "
            "character for character, that satisfies the requirement. "
            "For fail: null. For unclear: the closest relevant span, or null."
        ),
    )
    doc_id: str | None = Field(
        default=None, description="The doc_id the evidence span was copied from, or null."
    )
    rationale: str = Field(
        description="2-4 sentences explaining the verdict, grounded in the documents."
    )
    confidence: Confidence


class Finding(BaseModel):
    rule_id: str
    requirement_verbatim: str
    source: str
    source_url: str
    verdict: Verdict
    evidence: str | None = None
    doc_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    rationale: str
    confidence: Confidence
    mode: RuleType
    provenance: Provenance = "committed"
