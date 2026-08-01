"""Redline — audit a document set against a rulebook, streaming findings.

Endpoints:
    GET  /rulebooks            available rulebooks for the dropdown
    GET  /corpus/{rulebook_id} the rulebook's default corpus, flattened to
                               editable plain text per document
    POST /audit                SSE stream: one `finding` event per rule as it
                               resolves, then a `done` event with counts
Static UI is served at /.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from engine import intake, packet  # noqa: E402
from engine.evaluate import run_audit  # noqa: E402
from engine.llm import AnthropicLLM  # noqa: E402
from engine.schemas import DocumentIn, Finding, Rulebook  # noqa: E402

ROOT = Path(__file__).parent

app = FastAPI(title="Redline")

RULEBOOKS: dict[str, Rulebook] = {
    (rb := Rulebook.model_validate(json.loads(p.read_text()))).rulebook_id: rb
    for p in sorted((ROOT / "rules").glob("*.json"))
}

llm = AnthropicLLM()


def _flatten(doc: dict) -> DocumentIn:
    """Render structured sections into the plain text the judge edits.

    Three-state sections: text=None -> omitted entirely; text="" -> heading
    kept with an explicit '(left blank)' — present-but-skipped is a sharper
    finding than absent; text -> heading + text.
    """
    lines: list[str] = []
    for section in doc["sections"]:
        if section["text"] is None:
            continue
        lines.append(f"[{section['heading']}]")
        lines.append(section["text"] if section["text"] else "(left blank)")
        lines.append("")
    return DocumentIn(
        doc_id=doc["doc_id"],
        doc_type=doc["doc_type"],
        date=doc["date"],
        text="\n".join(lines).rstrip(),
    )


CORPORA: dict[str, list[DocumentIn]] = {
    (data := json.loads(p.read_text()))["corpus_id"]: [_flatten(d) for d in data["documents"]]
    for p in sorted((ROOT / "corpus").glob("*.json"))
}


class AuditRequest(BaseModel):
    rulebook_id: str
    documents: list[DocumentIn]


@app.get("/rulebooks")
def list_rulebooks() -> list[dict]:
    return [
        {
            "rulebook_id": rb.rulebook_id,
            "name": rb.name,
            "source": rb.source,
            "source_url": rb.source_url,
            "rule_count": len(rb.rules),
        }
        for rb in RULEBOOKS.values()
    ]


@app.get("/corpus/{rulebook_id}")
def get_corpus(rulebook_id: str) -> list[DocumentIn]:
    rb = RULEBOOKS.get(rulebook_id)
    if rb is None or rb.default_corpus not in CORPORA:
        raise HTTPException(404, f"No corpus for rulebook {rulebook_id!r}")
    return CORPORA[rb.default_corpus]


@app.post("/audit")
async def audit(request: AuditRequest) -> StreamingResponse:
    rulebook = RULEBOOKS.get(request.rulebook_id)
    if rulebook is None:
        raise HTTPException(404, f"Unknown rulebook {request.rulebook_id!r}")

    async def stream():
        started = time.monotonic()
        counts = {"pass": 0, "fail": 0, "unclear": 0}
        async for finding in run_audit(rulebook, request.documents, llm):
            counts[finding.verdict] += 1
            yield f"event: finding\ndata: {finding.model_dump_json()}\n\n"
        done = {"counts": counts, "elapsed_s": round(time.monotonic() - started, 1)}
        yield f"event: done\ndata: {json.dumps(done)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/intake/pdf")
async def intake_pdf(file: UploadFile) -> JSONResponse:
    """Extract a chart PDF into editable DocumentIn records. Does NOT run the
    audit — the user reviews the extraction in the left pane first."""
    pdf_bytes = await file.read()
    try:
        raw_text = intake.extract_text(pdf_bytes)
    except (intake.ScannedPdfError, ValueError) as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    chart = await intake.structure_chart(raw_text, llm)
    documents, notes = [], []
    for i, doc in enumerate(chart.documents):
        doc_id = intake.slugify_doc_id(doc.doc_type, i)
        documents.append(
            _flatten(
                {
                    "doc_id": doc_id,
                    "doc_type": doc.doc_type,
                    "date": doc.date,
                    "sections": [s.model_dump() for s in doc.sections],
                }
            )
        )
        notes.append({"doc_id": doc_id, "note": doc.extraction_note})
    return JSONResponse(
        content={
            "filename": file.filename,
            "documents": [d.model_dump() for d in documents],
            "notes": notes,
        }
    )


class PacketRequest(BaseModel):
    rulebook_id: str
    documents: list[DocumentIn]
    findings: list[Finding]
    counts: dict[str, int]
    elapsed_s: float


@app.post("/packet")
async def make_packet(request: PacketRequest) -> HTMLResponse:
    rulebook = RULEBOOKS.get(request.rulebook_id)
    if rulebook is None:
        raise HTTPException(404, f"Unknown rulebook {request.rulebook_id!r}")
    fails = [f for f in request.findings if f.verdict == "fail"]
    drafts = await packet.draft_fixes(fails, request.documents, llm)
    html_doc = packet.render_packet(
        rulebook, request.findings, request.counts, request.elapsed_s, drafts
    )
    return HTMLResponse(
        content=html_doc,
        headers={
            "Content-Disposition": 'attachment; filename="corrective_action_report.html"'
        },
    )


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
