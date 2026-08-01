"""Compile plain-English requirements into checkable rules.

The compile → card → add flow is two separate steps by design: the judge's
sentence becomes a legible, checkable contract before it executes. Refusal is
part of the schema, not an afterthought — a requirement that can't be checked
against documentation text gets `checkable: false` with a concrete reason
instead of a garbage rule.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from engine.llm import AnthropicLLM
from engine.schemas import Rule

_COMPILE_SYSTEM_PROMPT = """\
You compile a plain-English audit requirement into a machine-checkable rule \
for a documentation auditor. The auditor reads a set of documents and, per \
rule, returns pass (verbatim evidence found), fail (required content clearly \
absent), or unclear (something related exists but doesn't clearly satisfy).

First decide whether the requirement is CHECKABLE against documentation text. \
Not checkable: internal mental states, sincerity, intentions, effort, or \
quality judgments with no documentary criteria (e.g. "the clinician must \
genuinely care about the patient"). For these, set checkable=false and give a \
one-sentence reason naming what cannot be evidenced in a document — and, when \
possible, suggest a checkable documentation proxy in the reason.

If checkable, produce:
- requirement: the requirement essentially as the author wrote it, lightly \
tidied for grammar only. Do not expand its scope.
- evidence_required: your own concrete description of exactly what documented \
text would satisfy the requirement, what does NOT satisfy it, and when to \
prefer unclear over fail. This is the instruction an auditor model follows, so \
be specific about the discriminating details.

Calibration examples of good evidence_required from the existing rulebook:

Example A (requirement: reasons for admission stated by the patient): "The \
reason for admission recorded in the patient's own words (or those of \
family/others significantly involved) — direct quotes or clearly attributed \
first-person statements. A clinician's third-person summary is NOT sufficient \
on its own; if only clinician framing exists, the requirement is addressed \
but not clearly satisfied."

Example B (requirement: responsibilities of each treatment team member): "A \
documented statement of WHAT each treatment team member is responsible for — \
specific duties or interventions assigned to each role or person. A list of \
team member names, credentials, and signatures WITHOUT stated \
responsibilities does NOT satisfy this requirement."

Rules you compile are evaluated semantically by a model reading the \
documents; there is no date-arithmetic engine available, so express any \
frequency/timing requirement as something judged from the documents' text \
and dates as written.\
"""

_REFINE_ADDENDUM = """

REFINE MODE: you are amending an existing rule, not creating one. Apply the \
author's instruction to the rule below with the smallest change that honors \
it. Keep `requirement` unchanged unless the instruction explicitly targets \
the requirement's meaning; normally only `evidence_required` changes. Return \
the complete updated fields, not a diff.\
"""


class CompileResult(BaseModel):
    checkable: bool
    refusal_reason: str = Field(
        default="",
        description="When checkable is false: one sentence naming what cannot be "
        "evidenced in documentation (and a checkable proxy if one exists). "
        "Empty string when checkable.",
    )
    requirement: str = Field(
        default="", description="The requirement as authored, tidied for grammar only."
    )
    evidence_required: str = Field(
        default="", description="Concrete description of satisfying/non-satisfying evidence."
    )


def make_rule_id(requirement: str) -> str:
    words = re.findall(r"[a-z0-9]+", requirement.lower())
    slug = "-".join(words[:3]) or "rule"
    digest = hashlib.sha1(requirement.encode()).hexdigest()[:4]
    return f"user:{slug}-{digest}"


async def compile_rule(
    instruction: str, llm: AnthropicLLM, current_rule: Rule | None = None
) -> CompileResult:
    system = _COMPILE_SYSTEM_PROMPT + (_REFINE_ADDENDUM if current_rule else "")
    parts = []
    if current_rule:
        parts.append(
            "# Existing rule to refine\n"
            f"rule_id: {current_rule.rule_id}\n"
            f"requirement: {current_rule.requirement_verbatim}\n"
            f"evidence_required: {current_rule.evidence_required}\n\n"
            f"# Author's refinement instruction\n{instruction}"
        )
    else:
        parts.append(f"# Requirement as written by the author\n{instruction}")
    parts.append(
        "\n\n# Your task\nEmit the structured CompileResult (decide checkable first)."
    )
    return await llm.structured(
        system_prompt=system,
        user_prompt="".join(parts),
        response_model=CompileResult,
        max_tokens=2048,
    )
