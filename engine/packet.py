"""Corrective-action packet: LLM-drafted fixes + print-ready standalone HTML.

HTML, not PDF generation — browser print-to-PDF covers anyone who wants a PDF.
Every draft is grounded in the submitted chart text and carries the
clinician-review label; a failed draft call degrades that finding to a static
statement of what documentation is required (same isolation philosophy as the
audit itself: one bad call costs one section, not the packet).
"""

from __future__ import annotations

import asyncio
import html
from datetime import date

from pydantic import BaseModel, Field

from engine.llm import AnthropicLLM
from engine.schemas import DocumentIn, Finding, Rulebook

DRAFT_LABEL = (
    "DRAFT — for clinician review and signature. Not part of the medical record "
    "until reviewed, edited as needed, and signed."
)

_DRAFT_CONCURRENCY = 3


class FixDraft(BaseModel):
    draft_text: str = Field(
        description=(
            "The drafted documentation that would satisfy the failed requirement, "
            "written in clinical register, grounded only in facts present in the "
            "chart. Plain text; short paragraphs or a labeled list as appropriate."
        )
    )


_DRAFT_SYSTEM_PROMPT = """\
You draft missing clinical documentation to remediate a specific compliance \
finding. Rules:
- Ground every statement ONLY in facts already present in the chart provided. \
Do not invent clinical facts, dates, names, scores, or events.
- Write in concise clinical register, ready for a clinician to review, edit, \
and sign. No meta-commentary, no explanations of what you are doing.
- Draft exactly the documentation the requirement asks for — no more.\
"""


async def draft_fixes(
    fails: list[Finding], documents: list[DocumentIn], llm: AnthropicLLM
) -> dict[str, str | None]:
    """One draft per fail finding; None where the call failed (caller falls
    back to the static requirement statement)."""
    chart = "\n\n".join(
        f"<document type=\"{d.doc_type}\" date=\"{d.date}\">\n{d.text}\n</document>"
        for d in documents
    )
    semaphore = asyncio.Semaphore(_DRAFT_CONCURRENCY)

    async def one(f: Finding) -> tuple[str, str | None]:
        prompt = (
            f"# Failed requirement ({f.rule_id})\n{f.requirement_verbatim}\n\n"
            f"# Why it failed\n{f.rationale}\n\n"
            f"# The patient's chart\n{chart}\n\n"
            "# Your task\nDraft the documentation that would satisfy this "
            "requirement for this specific patient."
        )
        try:
            async with semaphore:
                draft = await llm.structured(
                    system_prompt=_DRAFT_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    response_model=FixDraft,
                    max_tokens=2048,
                )
            return f.rule_id, draft.draft_text
        except Exception:  # noqa: BLE001 — one bad draft costs one section
            return f.rule_id, None

    return dict(await asyncio.gather(*(one(f) for f in fails)))


# --- HTML rendering ----------------------------------------------------------

_CHIP_COLORS = {"pass": "#1a7f4b", "fail": "#c8102e", "unclear": "#b45309"}

_PACKET_CSS = """
  @page { margin: 1in 0.9in; }
  * { box-sizing: border-box; }
  body { font-family: Georgia, "Times New Roman", serif; color: #1c1917;
         font-size: 12pt; line-height: 1.5; max-width: 7.5in; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20pt; margin: 0 0 2px; letter-spacing: .01em; }
  .subtitle { color: #57534e; margin: 0 0 4px; }
  .meta { font-family: "Courier New", monospace; font-size: 9.5pt; color: #57534e;
          border-top: 2.5px solid #1c1917; border-bottom: 1px solid #d6d0c4;
          padding: 8px 0; margin: 14px 0 24px; }
  h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: .1em;
       border-bottom: 1px solid #1c1917; padding-bottom: 3px; margin: 30px 0 12px;
       page-break-after: avoid; }
  table { width: 100%; border-collapse: collapse; font-size: 10.5pt; }
  th { text-align: left; font-size: 9pt; text-transform: uppercase; letter-spacing: .08em;
       border-bottom: 1.5px solid #1c1917; padding: 4px 8px; }
  td { border-bottom: 1px solid #e2ddd3; padding: 5px 8px; vertical-align: top; }
  .chip { font-family: "Courier New", monospace; font-size: 8.5pt; font-weight: bold;
          text-transform: uppercase; letter-spacing: .08em; }
  .finding { page-break-inside: avoid; margin-bottom: 22px; }
  .finding h3 { font-size: 11.5pt; margin: 0 0 6px; }
  blockquote.reg { border-left: 3px solid #1c1917; margin: 8px 0; padding: 6px 14px;
                   background: #f7f4ee; font-style: italic; }
  .label { font-size: 8.5pt; text-transform: uppercase; letter-spacing: .1em;
           color: #57534e; margin: 10px 0 3px; font-family: Arial, sans-serif; }
  .draft-box { border: 1.5px solid #1c1917; padding: 12px 16px; margin: 8px 0;
               page-break-inside: avoid; }
  .draft-label { font-family: Arial, sans-serif; font-size: 8.5pt; font-weight: bold;
                 text-transform: uppercase; letter-spacing: .06em; color: #c8102e;
                 margin-bottom: 8px; }
  .signoff { margin-top: 36px; page-break-inside: avoid; }
  .signoff table td { border-bottom: 1px solid #1c1917; height: 34px; }
  .signoff .cap { font-size: 8.5pt; color: #57534e; border-bottom: none; height: auto;
                  padding-top: 2px; font-family: Arial, sans-serif; }
  @media print { body { padding: 0; } }
"""


def _e(s: str) -> str:
    return html.escape(s or "")


def _chip(verdict: str) -> str:
    return f'<span class="chip" style="color:{_CHIP_COLORS[verdict]}">{verdict}</span>'


_PROV_BADGES = {
    "user": '<span class="chip" style="color:#1d4ed8"> · USER RULE</span>',
    "modified": '<span class="chip" style="color:#b45309"> · MODIFIED — NOT VERBATIM REGULATION</span>',
}


def _prov_badge(finding: Finding) -> str:
    return _PROV_BADGES.get(finding.provenance, "")


def _status_line(f: Finding) -> str:
    first = f.rationale.split(". ")[0].rstrip(".")
    return first + "."


def render_packet(
    rulebook: Rulebook,
    findings: list[Finding],
    counts: dict[str, int],
    elapsed_s: float,
    drafts: dict[str, str | None],
) -> str:
    today = date.today().isoformat()
    order = {r.rule_id: i for i, r in enumerate(rulebook.rules)}
    findings = sorted(findings, key=lambda f: order.get(f.rule_id, 999))
    flagged = [f for f in findings if f.verdict in ("fail", "unclear")]
    fails = [f for f in findings if f.verdict == "fail"]

    parts = [
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Corrective Action Report — {_e(rulebook.name)}</title>"
        f"<style>{_PACKET_CSS}</style></head><body>",
        "<h1>Corrective Action Report</h1>",
        f"<p class='subtitle'>{_e(rulebook.name)}</p>",
        f"<div class='meta'>Source: {_e(rulebook.source)} &nbsp;·&nbsp; "
        f"{_e(rulebook.source_url)}<br>"
        f"Audit date: {today} &nbsp;·&nbsp; Completed in {elapsed_s}s &nbsp;·&nbsp; "
        f"{counts.get('pass', 0) + counts.get('fail', 0) + counts.get('unclear', 0)} rules — "
        f"{counts.get('pass', 0)} pass / {counts.get('fail', 0)} fail / "
        f"{counts.get('unclear', 0)} unclear</div>",
    ]

    # 2. Summary table
    parts.append("<h2>Summary of Findings</h2><table>")
    parts.append("<tr><th>Rule</th><th>Verdict</th><th>Status</th></tr>")
    for f in findings:
        parts.append(
            f"<tr><td style='white-space:nowrap'>§{_e(f.rule_id)}{_prov_badge(f)}</td>"
            f"<td>{_chip(f.verdict)}</td><td>{_e(_status_line(f))}</td></tr>"
        )
    parts.append("</table>")

    # 3. Findings detail (fail + unclear)
    parts.append("<h2>Findings Requiring Action</h2>")
    if not flagged:
        parts.append("<p>No failed or unclear findings — no corrective action required.</p>")
    for f in flagged:
        parts.append("<div class='finding'>")
        parts.append(f"<h3>§{_e(f.rule_id)} — {_chip(f.verdict)}{_prov_badge(f)}</h3>")
        if f.provenance == "committed":
            parts.append("<div class='label'>The regulation requires (verbatim)</div>")
            parts.append(f"<blockquote class='reg'>{_e(f.requirement_verbatim)}</blockquote>")
        else:
            label = (
                "The rule requires (user-defined this session)"
                if f.provenance == "user"
                else "The rule requires (modified this session — no longer verbatim regulation)"
            )
            parts.append(f"<div class='label'>{label}</div>")
            parts.append(
                f"<blockquote class='reg' style='font-style:normal;border-left-color:#a8a29e'>"
                f"{_e(f.requirement_verbatim)}</blockquote>"
            )
        parts.append("<div class='label'>Audit finding</div>")
        parts.append(f"<p>{_e(f.rationale)}</p>")
        parts.append("<div class='label'>Evidence status</div>")
        if f.evidence:
            parts.append(
                f"<p>Closest span located in <i>{_e(f.doc_id or '')}</i>: "
                f"&ldquo;{_e(f.evidence)}&rdquo; — judged not to satisfy the requirement.</p>"
            )
        else:
            parts.append(
                "<p>No text satisfying this requirement was found in the documents audited.</p>"
            )
        parts.append("</div>")

    # 4. Drafted corrective documentation
    parts.append("<h2>Drafted Corrective Documentation</h2>")
    if not fails:
        parts.append("<p>No failed findings — nothing to draft.</p>")
    for f in fails:
        draft = drafts.get(f.rule_id)
        parts.append("<div class='draft-box'>")
        parts.append(f"<div class='draft-label'>{_e(DRAFT_LABEL)}</div>")
        parts.append(f"<div class='label'>Remediates §{_e(f.rule_id)}</div>")
        if draft:
            body = "".join(
                f"<p>{_e(p).replace(chr(10), '<br>')}</p>"
                for p in draft.split("\n\n")
                if p.strip()
            )
            parts.append(body)
        else:
            parts.append(
                "<p><b>Documentation to be added by the treatment team:</b> "
                f"{_e(f.requirement_verbatim)}</p>"
            )
        parts.append("</div>")

    # 5. Sign-off block
    parts.append(
        "<div class='signoff'><h2>Review and Sign-off</h2><table>"
        "<tr><td style='width:34%'></td><td style='width:22%'></td>"
        "<td style='width:22%'></td><td style='width:22%'></td></tr>"
        "<tr><td class='cap'>Reviewer name</td><td class='cap'>Credential</td>"
        "<td class='cap'>Date</td><td class='cap'>Signature</td></tr>"
        "<tr><td></td><td></td><td></td><td></td></tr>"
        "<tr><td class='cap'>Program director</td><td class='cap'>Credential</td>"
        "<td class='cap'>Date</td><td class='cap'>Signature</td></tr>"
        "</table></div>",
    )
    parts.append("</body></html>")
    return "".join(parts)
