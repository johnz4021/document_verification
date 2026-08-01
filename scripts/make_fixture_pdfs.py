"""Generate the HTML sources for the sample chart-export fixture PDFs.

Writes sample_export.html and sample_export_broken.html to /tmp; convert to
PDF with the gstack browse daemon:

    browse goto file:///tmp/sample_export.html
    browse pdf corpus/sample_export.pdf --format letter --print-background

The layout is deliberately NOT our committed corpus: a fake clinic identity
(Lakeshore Behavioral Health), running header/footer with page numbers, and a
different section-heading vocabulary ("Presenting Problem", "Clinical
Impressions", "Care Team Signatures"). Same clinical content shape and the
same four planted gaps as chart_clean.json:

  1. No strengths inventory anywhere        -> fail 482.61(c)(1)
  2. Admission reason in clinician voice    -> unclear 482.61(a)(3)
  3. 23-day gap between notes 2 and 3       -> fail 482.61(d)
  4. Signature block without responsibilities -> fail 482.61(c)(1)(iv)

The broken variant additionally drops the legal-status/consent line
-> 482.61(a)(1) flips green -> amber (unclear): the narrative still says the
patient "presented voluntarily", which hints at status without being the
required identification-data statement, so the auditor cautiously flags it
for human review rather than calling it an outright fail. Verified stable
across repeated runs.
"""

from __future__ import annotations

from pathlib import Path

LEGAL_STATUS_LINE = (
    "<p><b>Legal Status:</b> Voluntary admission; consent to treatment signed by "
    "the patient at registration.</p>"
)

STYLE = """
<style>
  @page { margin: 0.9in 0.8in; }
  body { font-family: "Times New Roman", serif; font-size: 11.5pt; line-height: 1.45;
         color: #111; margin: 0; }
  .clinic-header { display: flex; justify-content: space-between; align-items: baseline;
         border-bottom: 2.5px solid #14532d; padding: 10px 0 6px; }
  .clinic-name { font-family: Arial, sans-serif; font-weight: bold; font-size: 13pt;
         color: #14532d; letter-spacing: .02em; }
  .clinic-meta { font-family: Arial, sans-serif; font-size: 8pt; color: #555; text-align: right; }
  .patient-band { background: #eef4ef; font-family: Arial, sans-serif; font-size: 9pt;
         padding: 5px 10px; margin: 8px 0 14px; display: flex; gap: 22px; }
  h2 { font-family: Arial, sans-serif; font-size: 11pt; text-transform: uppercase;
       letter-spacing: .06em; color: #14532d; border-bottom: 1px solid #b9ccbc;
       padding-bottom: 2px; margin: 22px 0 8px; page-break-after: avoid; }
  h3 { font-family: Arial, sans-serif; font-size: 9.5pt; text-transform: uppercase;
       letter-spacing: .05em; color: #333; margin: 14px 0 4px; page-break-after: avoid; }
  p { margin: 5px 0; }
  .doc { page-break-before: always; }
  .doc:first-of-type { page-break-before: auto; }
  .footer { font-family: Arial, sans-serif; font-size: 7.5pt; color: #777;
       border-top: 1px solid #ccc; margin-top: 26px; padding-top: 4px;
       display: flex; justify-content: space-between; }
  table.sig { width: 100%; border-collapse: collapse; font-size: 10.5pt; }
  table.sig td { border-bottom: 1px solid #999; padding: 8px 6px 2px; }
</style>
"""


def clinic_header(page: int, total: int) -> str:
    return f"""
    <div class="clinic-header">
      <span class="clinic-name">LAKESHORE BEHAVIORAL HEALTH</span>
      <span class="clinic-meta">2140 N Harbor Dr, Chicago IL 60601<br>
      Confidential — Chart Export · Page {page} of {total}</span>
    </div>
    <div class="patient-band">
      <span><b>Patient:</b> RIVERA, MARCUS</span>
      <span><b>DOB:</b> 03/14/1987</span>
      <span><b>MRN:</b> LBH-40217</span>
      <span><b>Unit:</b> Adult Inpatient Psychiatry</span>
    </div>"""


def build(include_legal_status: bool) -> str:
    legal = LEGAL_STATUS_LINE if include_legal_status else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">{STYLE}</head><body>

<div class="doc">
{clinic_header(1, 6)}
<h2>Initial Psychiatric Assessment — 06/14/2026</h2>
<h3>Registration &amp; Identifying Information</h3>
<p>Marcus Rivera is a 39-year-old married male admitted to the Adult Inpatient
Psychiatry unit on 06/14/2026 at 9:20 AM. Insurance: Blue Cross Blue Shield of
Illinois PPO. Emergency contact: Elena Rivera (spouse).</p>
{legal}
<h3>Admission Diagnoses</h3>
<p>Psychiatric: Alcohol use disorder, severe (F10.20); Major depressive disorder,
moderate, single episode (F32.1). Concurrent medical conditions: essential
hypertension (I10), untreated; elevated transaminases (R74.01) with AST 68 and
ALT 54 on outpatient labs obtained three months prior.</p>
<h3>Presenting Problem</h3>
<p>The patient was admitted for stabilization of escalating daily alcohol
consumption accompanied by worsening depressive symptoms and passive suicidal
ideation, occurring in the setting of marital and occupational stressors.
Inpatient admission was judged clinically appropriate for supervised withdrawal
management and initiation of structured treatment.</p>
<h3>Course of Illness</h3>
<p>Symptom onset traces to approximately three years ago, when drinking escalated
from social use to 8-12 standard drinks daily following a stressful job change.
Mood has declined progressively over the past six months with anhedonia, poor
sleep, and hopelessness. Two weeks before admission his wife stated she would
separate if he did not seek treatment; one week before admission his employer
issued a formal warning and placed him on a 30-day performance improvement plan.
Three days before admission, after a weekend binge, he experienced passive
suicidal ideation without plan or intent and presented voluntarily at the urging
of his wife and outpatient counselor.</p>
<h3>Mental Status Findings</h3>
<p>Adequately groomed male appearing stated age with mild bilateral hand tremor.
Cooperative, fair eye contact, normal speech. Mood "low" with constricted,
congruent affect. Thought process linear and goal-directed. Passive suicidal
ideation without plan or intent; no homicidal ideation, delusions, or
hallucinations. Alert and oriented x4; attention and memory grossly intact.
Insight fair, judgment fair. Estimated intellectual functioning average to above
average.</p>
<h3>Psychosocial Review</h3>
<p>Raised in Chicago, second of three children; father had alcohol use disorder.
Bachelor's degree in business; employed six years as a project manager at a
logistics firm. Married 11 years with two children ages 6 and 9. Discharge
housing plan is return to the family home, which is stable with no safety
concerns. Spouse was interviewed 06/15/2026: she supports treatment and will
attend family sessions, though she reports exhaustion and states the marriage
depends on his sobriety. Community resources: contact information provided for
the Lakeview Alcoholics Anonymous group and a referral initiated to the
Northside Intensive Outpatient Program; the outpatient counselor was contacted
with patient consent.</p>
<h3>Substance History</h3>
<p>Alcohol: 8-12 standard drinks daily for approximately three years; first use
at age 16. One prior withdrawal episode in 2023 (tremor, sweating, anxiety),
self-resolved. Morning tremor currently present. Completed a 12-week outpatient
program in 2023 with relapse within four months. Cannabis: occasional social
use. Tobacco and other substances: denied. DAST-10 score 6; AUDIT-C positive.</p>
<h3>Spiritual and Cultural Considerations</h3>
<p>Not addressed at intake.</p>
<h3>Evaluation Timing</h3>
<p>This psychiatric evaluation was completed 06/15/2026 at 2:30 PM by the
attending psychiatrist, within 60 hours of admission on 06/14/2026 at 9:20 AM.</p>
<div class="footer"><span>LBH Form 12-A rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

<div class="doc">
{clinic_header(2, 6)}
<h2>Individualized Plan of Care — 06/15/2026</h2>
<h3>Confirmed Diagnoses</h3>
<p>(1) Alcohol use disorder, severe (F10.20), supported by three years of daily
heavy use, a prior withdrawal episode, examination tremor, elevated
transaminases (AST 68, ALT 54), a failed outpatient treatment with early
relapse, and continued use despite marital and occupational consequences.
(2) Major depressive disorder, moderate (F32.1), supported by six months of
depressed mood, anhedonia, insomnia, hopelessness, and passive suicidal
ideation on mental status examination.</p>
<h3>Identified Problems</h3>
<p>Problem 1: Physiological alcohol dependence with morning tremor and prior
withdrawal. Problem 2: Depressed mood with passive suicidal ideation. Problem
3: Impaired occupational functioning under a 30-day performance improvement
plan. Problem 4: Marital discord secondary to substance use. Problem 5:
Untreated hypertension and alcohol-related transaminase elevation. Problem 6:
History of relapse within four months of completing prior treatment.</p>
<h3>Goals of Care</h3>
<p>During hospitalization: complete alcohol withdrawal management without
complication with CIWA-Ar below 8 for 48 consecutive hours; reduce PHQ-9 from
16 to below 10 by discharge; remain free of suicidal ideation for 72 hours
before discharge with a completed written safety plan. Following discharge:
sustained abstinence at 6 and 12 months supported by naltrexone adherence and
intensive outpatient participation; return to full occupational functioning;
re-engagement in the marital relationship through at least six couples-focused
aftercare sessions.</p>
<h3>Planned Interventions</h3>
<p>Supervised alcohol withdrawal per CIWA-Ar protocol with symptom-triggered
lorazepam. Naltrexone 50 mg by mouth daily beginning 06/16/2026 after liver
function review. Cognitive behavioral therapy group 60 minutes daily.
Motivational interviewing individually twice weekly. Relapse-prevention
psychoeducation group three times weekly. One structured family session with
the spouse before discharge. Lisinopril 10 mg daily for hypertension with a
repeat liver panel.</p>
<h3>Care Team Signatures</h3>
<table class="sig">
<tr><td>R. Okafor, MD — Attending Psychiatrist</td><td>06/15/2026</td></tr>
<tr><td>J. Lindqvist, RN — Charge Nurse</td><td>06/15/2026</td></tr>
<tr><td>D. Marsh, LCSW — Social Worker</td><td>06/15/2026</td></tr>
<tr><td>A. Chen, CADC — Addictions Counselor</td><td>06/15/2026</td></tr>
</table>
<div class="footer"><span>LBH Form 31-C rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

<div class="doc">
{clinic_header(3, 6)}
<h2>Nursing Progress Note — 06/14/2026</h2>
<h3>Observations</h3>
<p>Patient states he is "nervous but glad to be here." Last drink reported
approximately 14 hours before admission. Vital signs stable; mild bilateral
hand tremor; CIWA-Ar score 6. Oriented x4 and cooperative on the unit.</p>
<h3>Clinical Impressions</h3>
<p>Early mild alcohol withdrawal. Mood depressed but engaged with the admission
process; no suicidal ideation expressed this shift.</p>
<h3>Plan of Care</h3>
<p>Continue CIWA-Ar monitoring every 4 hours, encourage fluids, orient to unit
schedule; psychiatric evaluation scheduled with Dr. Okafor.</p>
<div class="footer"><span>LBH Form 22-N rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

<div class="doc">
{clinic_header(4, 6)}
<h2>Clinical Progress Note — 06/21/2026</h2>
<h3>Interval Data</h3>
<p>Withdrawal management completed without complication; CIWA-Ar below 8 since
06/18/2026 and the protocol was discontinued. Attended all CBT groups this week
and both individual motivational interviewing sessions. Naltrexone tolerated
without side effects. PHQ-9 today 12, down from 16 at admission. Wife visited
06/20/2026; the interaction was observed to be warm.</p>
<h3>Clinical Impressions</h3>
<p>Meaningful early progress against short-term goals: the withdrawal goal is
met, depressive symptoms are improving, and engagement is strong. Ambivalence
about long-term abstinence persists; the patient stated in group that he
believes he "could probably drink normally someday."</p>
<h3>Plan of Care</h3>
<p>Continue current interventions. The team recommends adding a
relapse-prevention focus on workplace triggers in individual sessions. No
revision to plan goals at this time; PHQ-9 to be repeated in one week.</p>
<div class="footer"><span>LBH Form 22-N rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

<div class="doc">
{clinic_header(5, 6)}
<h2>Clinical Progress Note — 07/14/2026</h2>
<h3>Interval Data</h3>
<p>Patient remains abstinent on the unit; naltrexone continued at 50 mg daily.
PHQ-9 today 8. Attended a family session with his spouse on 07/11/2026,
described by both as productive. Patient states: "I told Elena everything. She
didn't blow up. I think that means something."</p>
<h3>Clinical Impressions</h3>
<p>Depressive symptoms are now below the short-term goal threshold; a safety
plan has been drafted and reviewed. The patient verbalizes commitment to
intensive outpatient step-down and AA attendance. Progress is consistent with
the plan of care; discharge planning is appropriate to begin.</p>
<h3>Plan of Care</h3>
<p>Recommend revising the plan of care to reflect the discharge preparation
phase: finalize the intensive outpatient intake date, complete the written
safety plan, and schedule discharge medication reconciliation.</p>
<div class="footer"><span>LBH Form 22-N rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

<div class="doc">
{clinic_header(6, 6)}
<h2>Discharge Summary — 07/18/2026</h2>
<h3>Hospital Course</h3>
<p>Mr. Rivera was admitted voluntarily on 06/14/2026 for severe alcohol use
disorder with early withdrawal and moderate major depressive disorder with
passive suicidal ideation. He completed symptom-triggered withdrawal management
by 06/18/2026 without complication. Naltrexone 50 mg daily was initiated and
tolerated. He participated consistently in daily CBT group, twice-weekly
motivational interviewing, and relapse-prevention psychoeducation, and
completed one family session with his spouse. Depressive symptoms improved
steadily (PHQ-9 16 at admission, 8 before discharge) and suicidal ideation
resolved by the second week. Hypertension was managed with lisinopril 10 mg
daily; a repeat liver panel on 07/10/2026 showed improving transaminases
(AST 51, ALT 44).</p>
<h3>Status at Discharge</h3>
<p>At discharge on 07/18/2026 the patient is medically stable, abstinent from
alcohol for the duration of the admission, and denies suicidal ideation, with a
completed written safety plan. Mood is euthymic with brighter affect; insight
and judgment are improved. He is motivated for continued treatment and has
family support at home.</p>
<h3>Aftercare Instructions</h3>
<p>Intake at the Northside Intensive Outpatient Program on 07/21/2026, three
evenings weekly. Continue naltrexone 50 mg daily with psychiatry follow-up in
two weeks. Continue lisinopril 10 mg daily with primary care follow-up within
30 days including a repeat liver panel. Attend Alcoholics Anonymous at least
twice weekly. Couples-focused family sessions through the intensive outpatient
program. Return to the emergency department if suicidal ideation recurs; the
crisis line number is on the written safety plan.</p>
<div class="footer"><span>LBH Form 44-D rev 3/2025</span><span>Printed 07/30/2026</span></div>
</div>

</body></html>"""


if __name__ == "__main__":
    out = Path("/tmp")
    (out / "sample_export.html").write_text(build(include_legal_status=True))
    (out / "sample_export_broken.html").write_text(build(include_legal_status=False))
    print("wrote /tmp/sample_export.html and /tmp/sample_export_broken.html")
