"""PDF intake: mechanical text extraction + LLM structuring.

Text extraction is mechanical (pypdf); turning raw text into our document
structure is judgment, so it goes through the same structured-output path as
everything else. The one hard constraint: the model must preserve source
wording EXACTLY, because downstream evidence verification does exact substring
matching against this text. Any failure degrades to a single unstructured
document — the audit can still run against it.
"""

from __future__ import annotations

import io
import re

from pydantic import BaseModel, Field
from pypdf import PdfReader

from engine.llm import AnthropicLLM

_MIN_TEXT_CHARS = 200


class ScannedPdfError(ValueError):
    """The PDF has no usable text layer."""


class ExtractedSection(BaseModel):
    heading: str
    text: str = Field(
        description=(
            "The section's text copied EXACTLY from the source, character for "
            "character. Empty string if the section heading is present but the "
            "section was left blank."
        )
    )


class ExtractedDocument(BaseModel):
    doc_type: str = Field(
        description="What this document is, e.g. 'Intake Assessment', 'Progress Note (SOAP)'."
    )
    date: str = Field(
        description="The document's date as YYYY-MM-DD if stated anywhere in it, else \"\"."
    )
    extraction_note: str = Field(
        description=(
            "One short sentence on extraction confidence for this document, e.g. "
            "'clean extraction' or 'table layout may have garbled the medication list'."
        )
    )
    sections: list[ExtractedSection]


class ExtractedChart(BaseModel):
    documents: list[ExtractedDocument]


_STRUCTURE_SYSTEM_PROMPT = """\
You segment raw text extracted from a clinical chart PDF export into its \
constituent documents (e.g. intake assessment, treatment plan, progress notes, \
discharge summary — whatever is actually present).

THE ONE UNBREAKABLE RULE: preserve the source wording EXACTLY, character for \
character. Do not clean up, normalize whitespace within sentences, fix typos, \
expand abbreviations, reorder, or summarize. Downstream software verifies \
audit evidence by exact substring matching against the text you return — any \
rewording silently breaks the audit. You may omit page headers/footers and \
page numbers that repeat on every page (they are export chrome, not chart \
content), and you may drop the line breaks a PDF inserts mid-sentence by \
joining with a single space, but every sentence's words must survive verbatim.

For each document: identify its type, its date (YYYY-MM-DD) if stated, and its \
sections as found — use the source's own section headings. If a heading is \
present but its body is blank or a bare placeholder, return that section with \
text set to the empty string. Give each document a one-sentence \
extraction_note on how confident/clean the extraction was.\
"""


def extract_text(pdf_bytes: bytes) -> str:
    """Pull the text layer out of a PDF. Raises ScannedPdfError if absent."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:  # malformed file, encryption, etc.
        raise ValueError(f"Could not read this file as a PDF ({type(exc).__name__}).") from exc
    raw = "\n\n--- page break ---\n\n".join(p for p in pages if p)
    if len(raw) < _MIN_TEXT_CHARS:
        raise ScannedPdfError(
            "This PDF appears to be scanned (no usable text layer). OCR is out of scope — "
            "please upload a text-based chart export."
        )
    return raw


async def structure_chart(raw_text: str, llm: AnthropicLLM) -> ExtractedChart:
    """One structured LLM call; never raises — falls back to a single
    unstructured document so a bad structuring call degrades the demo
    instead of killing it."""
    try:
        chart = await llm.structured(
            system_prompt=_STRUCTURE_SYSTEM_PROMPT,
            user_prompt=(
                "# Raw text extracted from the uploaded chart PDF\n\n"
                f"{raw_text}\n\n"
                "# Your task\n"
                "Segment this into its constituent documents per the rules in the "
                "system prompt and emit the structured result."
            ),
            response_model=ExtractedChart,
            max_tokens=16000,
        )
        if chart.documents:
            return chart
    except Exception:  # noqa: BLE001 — degrade, never die
        pass
    return ExtractedChart(
        documents=[
            ExtractedDocument(
                doc_type="Unstructured chart export",
                date="",
                extraction_note=(
                    "Automatic document segmentation failed; the raw extracted text is "
                    "presented as a single document. The audit can still run against it."
                ),
                sections=[ExtractedSection(heading="Extracted text", text=raw_text)],
            )
        ]
    )


def slugify_doc_id(doc_type: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", doc_type.lower()).strip("_") or "document"
    return f"upload_{index + 1}_{slug}"
