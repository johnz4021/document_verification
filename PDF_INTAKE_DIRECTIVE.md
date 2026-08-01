# Redline — Final Extension: PDF Intake + Corrective-Action Packet

Directive for Claude Code. This document gives intent, contracts, and constraints.
Implementation specifics (libraries, parsing strategy, HTML details) are yours to
decide — but every contract and DO-NOT in here is binding.

## Context

Redline audits a document set against a rulebook (42 CFR §482.61) and streams
per-rule findings over SSE. Working today:

- `POST /audit` — SSE stream of findings, `done` event with counts + elapsed time
- `GET /rulebooks`, `GET /corpus/{rulebook_id}`
- `engine/` — `evaluate.py` (semaphore fan-out), `llm.py` (structured output via
  tool-use), `schemas.py` (`DocumentIn`, `Rulebook`, `Finding`)
- Three-state section encoding, flattened for display: absent sections omitted,
  empty sections rendered as `(left blank)`
- Verbatim-evidence verification: a `pass` requires a quoted span that appears
  exactly in the source text, or it downgrades to `unclear`

We are adding two features, in priority order. If time runs short, Feature 1
complete beats both features partial.

1. **PDF intake** — a judge hands us an EHR chart export we have never seen;
   we audit it.
2. **Corrective-action packet** — a downloadable report with findings, verbatim
   regulatory citations, drafted fixes, and sign-off lines.

Demo framing these serve: "Charts live in an EHR. Every EHR exports. Drop the
export here." The PDF path must therefore work on a *generic* chart export —
not one shaped like our committed corpus.

---

## Feature 1 — PDF intake

### New endpoint

`POST /intake/pdf` — accepts a PDF upload, returns `list[DocumentIn]` plus a
per-document extraction confidence note. It does NOT auto-run the audit: the
user sees the extraction in the editable left pane first, then triggers
`/audit` themselves. Two reasons this is load-bearing: the judge's
delete-and-re-run loop operates on extracted text, and eyeballing the
extraction before auditing is our defense against garbage-in.

### Extraction pipeline — use the LLM, not a parsing library, for structure

Getting raw text out of the PDF is mechanical (pick any standard Python text
extraction; if the PDF yields no text layer, return a clear error — "this PDF
appears to be scanned; OCR is out of scope" — do NOT attempt OCR).

Turning raw text into our document structure is judgment, so it goes through
`llm.py`'s structured-output path like everything else. One call: here is the
raw text of a clinical chart export, split it into documents (intake
assessment, progress notes, treatment plan, discharge summary — whatever is
actually present), and for each return `doc_type`, `date` if stated, and the
section headings + text as found. The model must preserve source wording
EXACTLY — no cleanup, no normalization, no summarizing. Say this explicitly in
the prompt and say why: downstream evidence verification does exact substring
matching against this text, so any rewording breaks the audit.

Map the result into `DocumentIn` via the existing flattening conventions.
Sections the model reports as present-but-empty use the `(left blank)`
rendering.

### Contract that must not break

`/audit` consumes the same `DocumentIn` list whether it came from the committed
corpus or a PDF. No `source_type` branching inside the engine. If you find
yourself adding an `if pdf` anywhere in `engine/`, stop — the shape is wrong.

### Offsets and display

All highlighting and all judge edits operate on the extracted text in the left
pane. The UI may show a small "from PDF: {filename}" provenance chip per
document. Do NOT attempt to render or highlight inside the PDF itself — the
extracted text IS the working document.

### Failure behavior

Extraction failures must be survivable on stage: a structured error with a
human-readable reason rendered as a dismissible banner, never a blank pane or
a raw traceback. If the LLM structuring call fails or returns unparseable
output, fall back to a single `DocumentIn` containing the raw extracted text
with `doc_type: "Unstructured chart export"` — the audit can still run against
it, which is a degraded demo but not a dead one.

### UI

Add an upload affordance to the left pane (button or drop zone — your call).
On success, the extracted documents replace the current corpus in the editable
pane, and the corpus dropdown gains a "From upload" state so the user can
switch back to the committed corpus without reloading.

---

## Feature 2 — Corrective-action packet

### New endpoint

`POST /packet` — accepts the audit results (findings + the documents they ran
against + rulebook id + elapsed/counts from the `done` event), returns a
standalone HTML file as a download. HTML, not PDF generation — print-ready HTML
is 20 minutes and zero dependencies; browser print-to-PDF covers anyone who
wants a PDF. Do not add a PDF generation library.

### Contents, in order

1. **Header** — "Corrective Action Report", rulebook name, source citation
   (42 CFR § 482.61 + eCFR URL), audit date, elapsed seconds and counts pulled
   from the `done` event (the audit's own numbers, not hardcoded).
2. **Summary table** — one row per rule: rule id, verdict chip, one-line
   status.
3. **Findings detail** — for every `fail` and `unclear`: the VERBATIM
   regulatory requirement text, the rationale, and the evidence status (what
   was searched, what was or wasn't found).
4. **Drafted corrective documentation** — for each fail, the auto-fix draft if
   one was generated this session. Every draft carries the label "DRAFT — for
   clinician review and signature. Not part of the medical record until
   reviewed, edited as needed, and signed." If the auto-fix feature didn't make
   it in, this section instead lists what documentation must be added, per
   finding, and the label requirement moves to that list's header.
5. **Sign-off block** — reviewer name / credential / date / signature lines.
   This is what makes it the artifact a compliance officer hands a program
   director rather than a printout of our UI.

### Frontend

"Download report" button, enabled when an audit has completed. Style the packet
like a document (print CSS, page margins, no app chrome) — it should look
right printed, because that is how it would actually be used.

---

## Sample data to create

One new fixture: `corpus/sample_export.pdf` — a realistic multi-page chart
export in a DIFFERENT visual layout than our committed corpus. Different
section heading names ("Presenting Problem" instead of "History of Present
Illness"), a header/footer with a fake clinic name and page numbers, the same
underlying clinical content shape: intake + 3 progress notes + treatment plan.
Plant the same four gaps as chart_clean.json so the audit outcome is known.

Generate it by writing an HTML file and converting to PDF however is most
convenient. The point of the different layout is honesty: the demo claim is
"a chart shaped like someone else's EHR export," so the fixture must not be
our own corpus wearing a PDF extension.

Also produce `corpus/sample_export_broken.pdf` — same document minus the
consent line, for a staged judge variant if the live-mangle flow isn't wanted.

## Do not build

- OCR / scanned-PDF handling (detect and error clearly instead)
- PDF rendering or in-PDF highlighting
- PDF *generation* libraries for the packet (HTML only)
- Any `source_type` branching in `engine/`
- SimplePractice or any EHR API integration
- Persistence of uploads beyond the session

## Order of work and timeboxes

1. `/intake/pdf` extraction + LLM structuring + UI upload — 35 min
2. `sample_export.pdf` fixture + end-to-end test that its audit flags the four
   planted gaps — 10 min
3. `/packet` + download button — 20 min
4. Broken-variant PDF — 5 min

If step 1 is not producing a correct audit against the fixture by its timebox,
cut Feature 2 to the fallback (packet without drafts) and spend the difference
on making extraction robust. A working PDF intake with a plain packet beats a
beautiful packet behind a flaky intake.

## Definition of done

Upload `sample_export.pdf` → extracted documents appear editable in the left
pane → run audit → the four planted gaps flag correctly with verified evidence
spans on the passes → delete a line in the extracted text, re-run, watch the
corresponding rule flip → download the packet → it opens standalone, contains
the verbatim 482.61 text for each failure, and prints cleanly.

That sequence, run twice without intervention, is the rehearsal bar.
