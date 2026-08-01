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

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from engine.evaluate import run_audit  # noqa: E402
from engine.llm import AnthropicLLM  # noqa: E402
from engine.schemas import DocumentIn, Rulebook  # noqa: E402

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


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
