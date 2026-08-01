# Fire Yourselves — Build Plan

**Product working name:** Redline
**One-liner:** Reads a chart against a federal regulation and cites every place the regulation isn't satisfied — or the place the documentation should have been.
**Constraint:** 4 hours build, 3:00 live demo, one shot, judges supply/modify input.

---

## 0. The single most important decision

**Rulebook = 42 CFR §482.61, not ASAM and not TJC CTS.**

Your take-home README already establishes why: the ASAM 4th-edition PDF carries an explicit no-AI-input prohibition, and the TJC public portal signals `ai-train=no` plus AI-crawler `Disallow`. Every `requirement_text` in `app/intelligence/compliance/standards.py` is therefore an original paraphrase.

For a *demo*, a paraphrased rule is unverifiable. The judge reads a requirement they can't check against a source you can't show.

§482.61 is US federal regulation — public domain, no copyright, no robots restriction. Consequences:

- **Verbatim requirement text on screen.** The exact regulatory language, next to the chart excerpt.
- **A judge can verify on their phone** at ecfr.gov during the demo.
- **No IP disclosure section needed**, no paraphrase-quality risk, no awkward question.

It also keeps the healthcare-compliance story intact: TJC accreditation is used for *deemed status* against these same CMS Conditions of Participation. Say that once, move on.

**Action in hour 1:** pull §482.61 from https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-G/part-482/subpart-E/section-482.61 and commit the raw text to `rules/482_61_source.txt`. Verbatim. This is your source of truth and your on-screen citation.

---

## 1. What to port from `perspectives-take-home`, and what to cut

### Port (this is your head start — do not rebuild)

| From repo | Why |
|---|---|
| `app/intelligence/shared/` — `AnthropicLLM.structured()` via tool-use + forced `tool_choice` | Structured output already solved. No JSON-mode parsing, no regex. |
| Citation-grounding guard (`InvalidCitationError` at the evaluator boundary) | **This is your anti-hallucination story.** Extend it: verify the quoted span appears *verbatim* in the source text, not just that the doc id is real. |
| Three-state `Section.text` encoding (`None` / `""` / `"<text>"` → absent / empty / filled) | Your best original idea. Gives you a *sharper* verdict vocabulary than pass/fail. Keep it. |
| Deterministic-vs-LLM evaluation split | Maps directly to `rule_type: computed \| semantic`. Deterministic rules never hit the model — free speed, zero variance. |
| `asyncio.Semaphore(5)` fan-out pattern | Wall-time story. |
| `design/patient_spec.md` + the Marcus Rivera chart | **Biggest time save.** BPS intake + SOAP/DAP/DSAP notes already written and already have a designed gap. |
| Per-unit error isolation (one bad call → warning, not lost audit) | A single failed rule mid-demo degrades to amber instead of killing the run. |

### Cut ruthlessly

| Cut | Why |
|---|---|
| SimplePractice extraction / Playwright / auth cookie singleton | Invisible to judges, most fragile component, needs network + creds. Chart is a committed JSON file. |
| FHIR Bundle shaping | Ceremony. Judges don't see it. Plain documents with ids. |
| ASAM endpoint entirely | Unverifiable by a lay judge, and IP-blocked. |
| Applicability funnel (133 → 12 → 8) | Nice engineering, invisible payoff in 3 minutes. |
| pytest suite, VCR cassettes, mypy strict, Makefile | Four hours. |
| Any database | Dict. |

---

## 2. Repo layout (new, clean — do not fork the old one)

```
redline/
  main.py                 FastAPI app, SSE endpoint, static mount
  engine/
    llm.py                ported AnthropicLLM.structured()
    verify.py             verbatim-span verification + offset resolution
    evaluate.py           per-rule evaluation, semaphore fan-out
    computed.py           deterministic rule handlers (date math, presence)
  rules/
    482_61_source.txt     verbatim eCFR text (citation source)
    cms_psych.json        the rulebook the engine consumes
    soc2.json             second domain, built hour 4
  corpus/
    chart_clean.json      documents
    chart_broken.json     staged variant
  static/
    index.html            three-pane UI, vanilla JS, no build step
```

---

## 3. Inputs

### 3.1 Rulebook format

12–15 rules in `rules/cms_psych.json`. Every rule carries the **verbatim** regulatory text plus an engineering-written evidence description (the paraphrase is fine here — it's your instruction to the model, not the citation shown to the judge).

```json
{
  "rule_id": "482.61(c)(1)",
  "source": "42 CFR § 482.61",
  "source_url": "https://www.ecfr.gov/current/title-42/section-482.61",
  "requirement_verbatim": "Each patient must have an individual comprehensive treatment plan that must be based on an inventory of the patient's strengths and disabilities.",
  "evidence_required": "Explicit description of patient assets, capabilities, skills, supports, or protective factors. Absence of documented deficits does NOT satisfy this.",
  "rule_type": "semantic",
  "scope_docs": ["treatment_plan", "bps_intake"]
}
```

Computed rule example:

```json
{
  "rule_id": "482.61(d)",
  "requirement_verbatim": "The frequency of progress notes is determined by the condition of the patient but must be recorded at least weekly for the first 2 months and at least once a month thereafter...",
  "rule_type": "computed",
  "handler": "progress_note_cadence"
}
```

### 3.2 The four rules that carry the demo

| Rule | Why it's in the deck |
|---|---|
| **§482.61(c)(1)** — treatment plan based on inventory of strengths and disabilities | **The headline finding.** Real charts document deficits exhaustively, strengths never. Judge ctrl-Fs "strength", finds nothing, learns something. This is your unfakeable moment. |
| **§482.61(a)(3)** — reasons for admission as stated by the patient and/or others significantly involved | **Proves semantic matching.** Text exists but it's the clinician's framing, not the patient's words. Resolves `unclear` (amber), not `fail`. |
| **§482.61(d)** — progress note cadence | **Computed, not semantic.** Pure date arithmetic. One row that is undeniably, checkably correct. |
| **§482.61(c)(1)(iv)** — responsibilities of each member of the treatment team | Chart has a signature block. The reg wants documented responsibilities. Different things. |

### 3.3 Document corpus

Start from `design/patient_spec.md`. Regenerate the chart as plain JSON:

```json
{
  "doc_id": "bps_intake",
  "doc_type": "Biopsychosocial Assessment",
  "date": "2026-06-14",
  "author_role": "LCSW",
  "sections": [
    {"code": "hpi", "heading": "History of Present Illness", "text": "..."},
    {"code": "spiritual", "heading": "Spiritual/Religious", "text": ""}
  ]
}
```

Keep the three-state encoding: `null` = section absent, `""` = present but blank, text = filled. Blank-but-present is a *better* finding than absent — "the template asked and the clinician skipped it" is a sharper sentence than "it's missing."

**Contents:** BPS intake, treatment plan, three progress notes (SOAP / DAP / DSAP on different dates), discharge summary. Format inconsistency is deliberate — it's why a human can't skim.

**Planted gaps (4):**
1. No strengths inventory anywhere → `fail` on (c)(1)
2. Admission reason in clinician voice only → `unclear` on (a)(3)
3. 23-day gap between progress notes 2 and 3 → `fail` on (d)
4. Signature block with no responsibilities → `fail` on (c)(1)(iv)

Everything else passes cleanly. **Target the clean chart at ~10 green, 3 red, 1 amber.** All-red reads as broken; all-green reads as pointless.

Generate the prose with Claude, not by hand. Give it the spec and the planted-gap list and tell it to write realistic clinical documentation that satisfies the other rules naturally.

---

## 4. Output

### 4.1 Per-rule finding

```json
{
  "rule_id": "482.61(c)(1)",
  "verdict": "fail",
  "evidence": null,
  "doc_id": null,
  "char_start": null,
  "char_end": null,
  "rationale": "No documentation of patient strengths, assets, or protective factors appears in the treatment plan or intake. The plan documents diagnoses and functional impairments only.",
  "confidence": "high",
  "mode": "semantic"
}
```

A pass is identical but with `evidence` holding a **verbatim span** from the source and resolved offsets.

### 4.2 The verification rule (non-negotiable)

Server-side, before any finding reaches the client:

```
if verdict == "pass":
    if evidence is None or evidence not in corpus[doc_id].full_text:
        verdict = "unclear"
        rationale += " [evidence span could not be verified]"
```

This makes a hallucinated pass **structurally impossible**, and it gives you free highlighting via `str.find()`. It is also the single best sentence in your pitch: *the model cannot claim compliance without producing text that actually exists.*

### 4.3 Verdict vocabulary

- `pass` — green, verified span
- `fail` — red, no evidence found
- `unclear` — amber, evidence exists but doesn't clearly satisfy

**Amber matters more than you think.** A wrong red row in front of judges costs you far more than a cautious amber one. Tune toward amber on ambiguity.

---

## 5. What the judge sees

Three panes, `static/index.html`, vanilla JS, no build step.

**Left — Chart.** Editable `<textarea>` per document, section headings visible. Scrollable. This is what the judge touches.

**Middle — Findings.** One row per rule, streaming in via SSE as each resolves. Rule id, verbatim requirement text (truncated with expand), colored verdict chip.

**Right — Citation detail.** Click a row → for a pass, the source text with the verified span highlighted; for a fail, the rule's full verbatim regulatory text and the rationale explaining what was searched and not found; a link to the eCFR section.

**Design notes:**
- Rows must **stream**, not appear at once. Progressive fill reads as working; batch appearance reads as canned.
- Show a live counter: `14 rules · 10 pass · 3 fail · 1 unclear`.
- Show elapsed time on screen. It's your 40-minutes-to-90-seconds story, live.
- Re-run button must be one click and re-run only, not reload.

---

## 6. Hour by hour

Every step below is a Claude Code prompt. Run them roughly in order; hours 1 and 2 are strictly sequential.

### Hour 1 — Rulebook + corpus

1. `Fetch 42 CFR 482.61 from ecfr.gov and save the verbatim text to rules/482_61_source.txt. Preserve subsection lettering exactly.`
2. `From rules/482_61_source.txt, build rules/cms_psych.json with 14 rules. Each needs rule_id, requirement_verbatim (exact text from the source, no paraphrasing), evidence_required (your own words describing what would satisfy it), rule_type (semantic or computed), and scope_docs. Mark 482.61(d) as computed with handler progress_note_cadence.`
3. `Read design/patient_spec.md from <path to old repo>. Generate corpus/chart_clean.json: a BPS intake, treatment plan, three progress notes in SOAP, DAP and DSAP format on dates 2026-06-14, 06-21, 07-14, and a discharge summary. Use the section schema in section 3.3 of the plan. Plant exactly these four gaps: [list]. Everything else should naturally satisfy the other rules.`

**Checkpoint at 1:00:** you can `cat` the rulebook and the chart and manually confirm the four gaps are there and the other rules are satisfiable.

### Hour 2 — Engine

4. `Port AnthropicLLM.structured() from <old repo>/app/intelligence/shared/ into engine/llm.py. Keep the tool-use + forced tool_choice pattern. Strip FHIR and SimplePractice imports.`
5. `Write engine/evaluate.py: evaluate_rule(rule, corpus) -> Finding. For semantic rules, one LLM call with the rule's evidence_required and the scoped documents. The model must return verdict, evidence (a verbatim span or null), doc_id, rationale, confidence.`
6. `Write engine/verify.py: after each finding, if verdict is pass, confirm the evidence string appears exactly in corpus[doc_id] full text. If not, downgrade to unclear and append a note to the rationale. Resolve char_start/char_end via str.find.`
7. `Write engine/computed.py with progress_note_cadence: check gaps between consecutive progress note dates against the 482.61(d) requirement. Return the same Finding shape.`
8. `Wire main.py: POST /audit accepts {documents, rulebook_id}, fans out under asyncio.Semaphore(5), streams each Finding as an SSE event as it resolves.`

**Checkpoint at 2:00:** `curl -N localhost:8000/audit` streams 14 findings and the four planted gaps are correctly flagged. **If this isn't true at 2:00, stop adding rules and start debugging — you have no demo without it.**

### Hour 3 — UI

9. `Build static/index.html: three panes per section 5 of the plan. Consume the SSE stream, append rows as they arrive with colored verdict chips. Clicking a row populates the right pane. Editable textareas on the left; a Re-run button posts current textarea contents back to /audit.`
10. `Add a live counter and an elapsed-time display.`

**Checkpoint at 3:00:** edit the chart in the browser, hit re-run, watch a row change color. **Hard feature freeze here.**

### Hour 4 — Tuning, second rulebook, rehearsal

11. Run the audit 5×. Log any rule that flips verdict across runs. Tighten its `evidence_required` until it doesn't. **A flapping rule is a demo killer.**
12. `Build rules/soc2.json: 8 rules from SOC 2 Common Criteria (access review cadence, incident response documentation, vendor risk assessment, change management approval). Same schema.` Plus a short security-policy document in `corpus/`.
13. Add a rulebook dropdown. Verify the swap works with zero code changes — if it doesn't, healthcare vocabulary has leaked into your prompt. Fix that; it's the portability claim.
14. Rehearse 4×.

---

## 7. Demo script (3:00)

**0:00–0:40 — The job.**
> "A compliance auditor reads every patient chart against a federal regulation and writes up what's missing. About 40 minutes a chart. Every psychiatric facility taking Medicare pays someone to do this, and they're all behind. This is 42 CFR 482.61 — you can pull it up right now, it's public."

**0:40–1:20 — The run.**
Scroll the chart fast so the volume registers. Hit run. Rows stream. Click a green row: exact sentence highlighted. Click the strengths-inventory red row: verbatim regulation, and the rationale explaining nothing in the chart satisfies it.
> "Charts document what's wrong with a patient exhaustively. The regulation requires strengths. Almost nobody documents them."

**1:20–2:30 — Hand it over. This is the demo.**
> "Delete anything you want from this chart."

Judge deletes. Re-run. Row flips red, citing the hole they just made. Let them do it **three times**. Then have them *add* a line satisfying a currently-failing rule and watch it go green. An audience operating the thing beats an audience watching it, and it's the most direct possible answer to the fresh-input rule.

**2:30–2:50 — The swap.**
Change the dropdown to SOC 2. Same engine, different domain, live.
> "Same engine. Different rulebook. That's a JSON file."

**2:50–3:00 — Close.**
> "Forty minutes to ninety seconds. And the model can't claim compliance without quoting text that actually exists — we check every citation against the source before it hits your screen."

---

## 8. Failure modes and mitigations

| Risk | Mitigation |
|---|---|
| A rule flaps between runs | Hour 4 stability pass. Any rule that flips gets its `evidence_required` tightened or gets cut. |
| Judge deletes something that breaks nothing | Rehearse the ask: *"delete the consent line, or the whole progress note from June 21."* Guide without scripting. |
| API latency spikes on conference wifi | Semaphore 5, and rows stream so partial results are visible. Have a recorded run open in a second tab — **narrate it as a recording if you use it**, never pass it off as live. |
| Judge asks "does this only work for healthcare" | The SOC 2 swap. Don't answer — show them. |
| Judge asks "what if the regulation changes" | Honest answer: the rulebook is data, not code; updating means editing JSON. |
| Judge asks "would a hospital trust this" | Honest answer: it's a first-pass triage that puts a human on the 4 findings instead of all 14 rules. Don't overclaim autonomy — the citation-verification design is what makes it reviewable. |

---

## 9. What not to build

- Auth of any kind
- Multi-patient support
- Persistence
- A skill/learning layer (right idea, wrong clock — that's a 12-hour build)
- Anything touching a browser
- Anything touching SimplePractice
- Test coverage beyond eyeballing the four planted gaps
