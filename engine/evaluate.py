"""Per-rule evaluation: prompt building, dispatch, and the fan-out runner.

Deliberately domain-neutral — nothing here knows about healthcare. Swapping
in a different rulebook (e.g. SOC 2) requires zero code changes; the rule's
`requirement_verbatim` and `evidence_required` carry all domain knowledge.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from engine import computed
from engine.llm import AnthropicLLM
from engine.schemas import DocumentIn, Finding, FindingDraft, Rule, Rulebook
from engine.verify import verify_finding

_CONCURRENCY = 5

_SYSTEM_PROMPT = """\
You are a meticulous compliance auditor. You judge whether ONE requirement \
from a rulebook is satisfied by a set of source documents.

Verdict vocabulary — pick exactly one:
- "pass" — the documents contain text that clearly satisfies the requirement.
- "fail" — the documents clearly do not satisfy it (the required content is \
absent or contradicted).
- "unclear" — something related exists but it does not clearly satisfy the \
requirement, or the evidence is ambiguous. When in genuine doubt between \
fail and unclear, choose unclear. Never stretch to a pass.

Evidence rules — these are strict:
- For a "pass" verdict you MUST copy a short verbatim span (one phrase to a \
few sentences) from a document, character for character, into `evidence`, and \
set `doc_id` to the document it came from. Your evidence will be mechanically \
checked against the source text; a span that does not appear exactly will \
cause your pass to be rejected. Do not paraphrase, do not fix typos, do not \
merge text from two places.
- For "fail", set `evidence` to null and explain in the rationale what you \
searched for and did not find.
- For "unclear", you may include the closest relevant verbatim span, or null.

Write a rationale of 2-4 sentences grounded only in the documents provided. \
Do not use outside knowledge about what the documents "probably" contain. \
Assign confidence: "high" (evidence directly settles it), "medium" \
(reasonable inference required), "low" (sparse or conflicting evidence).\
"""


def build_user_prompt(rule: Rule, docs: list[DocumentIn]) -> str:
    parts = [
        "# Requirement to audit\n",
        f"Rule ID: {rule.rule_id}\n",
        f"Requirement (verbatim from the rulebook source):\n{rule.requirement_verbatim}\n",
        f"\nWhat would satisfy it:\n{rule.evidence_required}\n",
        "\n# Source documents\n",
        "Each document below is identified by its doc_id. Cite evidence only "
        "from these documents, using exact verbatim spans.\n",
    ]
    for doc in docs:
        parts.append(
            f"\n<document doc_id=\"{doc.doc_id}\" type=\"{doc.doc_type}\" date=\"{doc.date}\">\n"
            f"{doc.text}\n</document>\n"
        )
    parts.append(
        "\n# Your task\n"
        "Judge this one requirement against these documents and emit the "
        "structured finding (verdict, evidence, doc_id, rationale, confidence)."
    )
    return "".join(parts)


async def evaluate_rule(
    rule: Rule, rulebook: Rulebook, documents: list[DocumentIn], llm: AnthropicLLM
) -> Finding:
    """Evaluate one rule. Never raises: any error degrades to an `unclear`
    finding so a single bad call mid-demo costs one amber row, not the run."""
    scoped = [d for d in documents if d.doc_id in rule.scope_docs] or documents
    docs_by_id = {d.doc_id: d for d in documents}
    meta = {"source": rulebook.source, "source_url": rulebook.source_url}

    try:
        if rule.rule_type == "computed":
            handler = computed.HANDLERS[rule.handler]
            return handler(rule, scoped).model_copy(update=meta)

        draft: FindingDraft = await llm.structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=build_user_prompt(rule, scoped),
            response_model=FindingDraft,
        )
        finding = Finding(
            rule_id=rule.rule_id,
            requirement_verbatim=rule.requirement_verbatim,
            verdict=draft.verdict,
            evidence=draft.evidence,
            doc_id=draft.doc_id,
            rationale=draft.rationale,
            confidence=draft.confidence,
            mode="semantic",
            **meta,
        )
        return verify_finding(finding, docs_by_id)
    except Exception as exc:  # noqa: BLE001 — per-rule isolation is the point
        return Finding(
            rule_id=rule.rule_id,
            requirement_verbatim=rule.requirement_verbatim,
            verdict="unclear",
            rationale=f"This rule could not be evaluated ({type(exc).__name__}: {exc}).",
            confidence="low",
            mode=rule.rule_type,
            **meta,
        )


async def run_audit(
    rulebook: Rulebook, documents: list[DocumentIn], llm: AnthropicLLM
) -> AsyncIterator[Finding]:
    """Fan out all rules under a semaphore; yield findings as each resolves."""
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    queue: asyncio.Queue[Finding | None] = asyncio.Queue()

    async def worker(rule: Rule) -> None:
        async with semaphore:
            await queue.put(await evaluate_rule(rule, rulebook, documents, llm))

    async def runner() -> None:
        await asyncio.gather(*(worker(r) for r in rulebook.rules))
        await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while (finding := await queue.get()) is not None:
            yield finding
    finally:
        task.cancel()
