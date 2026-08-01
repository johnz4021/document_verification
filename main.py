"""Blueline — audit a document set against a rulebook, streaming findings.

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

from engine import authoring, intake, packet  # noqa: E402
from engine.evaluate import run_audit  # noqa: E402
from engine.llm import AnthropicLLM  # noqa: E402
from engine.schemas import DocumentIn, Finding, Rule, Rulebook  # noqa: E402

ROOT = Path(__file__).parent

app = FastAPI(title="Blueline")

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
    # Optional session working rulebook (judge-added/edited/disabled rules) and
    # an id filter for single-rule re-runs. Omitted -> the committed rulebook.
    rules: list[Rule] | None = None
    rule_ids: list[str] | None = None


def _effective_rulebook(base: Rulebook, request: AuditRequest) -> Rulebook:
    """Apply the request's rule overrides and stamp computed provenance.

    Provenance is derived by diffing each incoming rule against the pristine
    committed copy — the client can never assert it. An edited committed rule
    becomes `modified`; an unknown rule_id is `user` (and loses any claim to a
    regulatory source).
    """
    pristine = {r.rule_id: r for r in base.rules}
    effective = []
    for rule in request.rules if request.rules is not None else base.rules:
        committed = pristine.get(rule.rule_id)
        if committed is None:
            provenance = "user"
        elif committed.model_dump(exclude={"provenance"}) == rule.model_dump(
            exclude={"provenance"}
        ):
            provenance = "committed"
        else:
            provenance = "modified"
        effective.append(rule.model_copy(update={"provenance": provenance}))
    if request.rule_ids is not None:
        wanted = set(request.rule_ids)
        effective = [r for r in effective if r.rule_id in wanted]
    return base.model_copy(update={"rules": effective})


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
    base = RULEBOOKS.get(request.rulebook_id)
    if base is None:
        raise HTTPException(404, f"Unknown rulebook {request.rulebook_id!r}")
    rulebook = _effective_rulebook(base, request)

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


@app.get("/rulebook/{rulebook_id}")
def get_rulebook(rulebook_id: str) -> Rulebook:
    rb = RULEBOOKS.get(rulebook_id)
    if rb is None:
        raise HTTPException(404, f"Unknown rulebook {rulebook_id!r}")
    return rb


class CompileRequest(BaseModel):
    instruction: str
    current_rule: Rule | None = None


@app.post("/rules/compile")
async def compile_rule(request: CompileRequest) -> JSONResponse:
    """Compile a plain-English requirement into a rule — or refuse with a
    reason when it isn't checkable against documentation. Does NOT evaluate."""
    result = await authoring.compile_rule(
        request.instruction, llm, current_rule=request.current_rule
    )
    payload: dict = result.model_dump()
    if result.checkable:
        if request.current_rule is not None:
            rule = request.current_rule.model_copy(
                update={
                    "requirement_verbatim": result.requirement
                    or request.current_rule.requirement_verbatim,
                    "evidence_required": result.evidence_required,
                }
            )
        else:
            rule = Rule(
                rule_id=authoring.make_rule_id(result.requirement),
                requirement_verbatim=result.requirement,
                evidence_required=result.evidence_required,
                rule_type="semantic",
                scope_docs=[],
                provenance="user",
            )
        payload["rule"] = rule.model_dump()
    return JSONResponse(content=payload)


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
