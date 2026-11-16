# Millrace AI · District Brief Builder

District Brief Builder is a web workbench that helps Hawaiʻi legislative staff turn a district question into a sourced, one-page agency verification brief.

**Try it:** [haic.millrace.ai](https://haic.millrace.ai). It needs no account, sign-in or setup. The checks below used Chrome.

Team **Millrace AI** built District Brief Builder for the HAIC 2026 Know Your District challenge. Millrace AI is the team. District Brief Builder is the product. This repository holds its working source.

You choose one of Hawaiʻi's 51 House or 25 Senate districts and an issue. The app runs a visible, editable plan on a bundled snapshot of public aggregate data. Each ACS figure shows its publisher, period, universe, margin of error and source location. Administrative figures show their publisher, period, coverage and sheet cell. Program references show their official page and checked date. You choose findings and an agency action, add labeled staff notes, and print a one-page brief. Agencies determine eligibility and current availability.

**Status:** working prototype. Guided controls, typed requests, sources, the brief and case files make no model call and need no credentials. **Ask a question** is an experimental AI preview on the hosted app. An OpenAI model proposes a plan, and staff review the proposal before it runs. Every number still comes from deterministic operations on the bundled snapshot. In developer checks the preview delivered no critical error, but it did not pass every preregistered quality gate. Read the [known issues](#known-issues-with-language-questions) before you rely on it. The hosted app runs the code at commit `aa8f0ab`. Later documentation-only commits on `main` are not redeployed. See [optional language questions](#optional-language-questions).

## Try the House 028 Care example

This path takes about five minutes. It follows the older-adult support-at-home issue in House District 28.

1. **Open the app.** [haic.millrace.ai](https://haic.millrace.ai) opens on House 028 with the issue **Older-adult support at home**. The plan has four steps: profile measures, a comparison with the State, the Kūpuna Care program reference and a reviewed outreach hypothesis. Its results already appear under **Findings and evidence**, led by a **Start here** summary.
2. **Edit the plan (optional).** Under **Investigation plan**, open **Change scope** on a step, or use **Add a supported step**. Choose **Apply plan** to run your edit. **Run again** repeats an unchanged plan.
3. **Inspect one estimate.** Find **Population age 65 and over, House 028: 6,463 persons (90% margin of error ±542 persons)**. Choose its **Inspect** source button. The source panel shows the publisher (Hawaiʻi DBEDT / U.S. Census Bureau ACS), the period (ACS 2020–2024 5-year), the universe (total population) and the location (sheet DP05, cell DF27, margin DG27). The source was retrieved October 30, 2026. Its address opens the publisher's file in a new tab. The app itself fetches nothing.
4. **Read the comparison.** The comparison step reports the age-65+ poverty rate: House 028 29.0% (±4.3) and State of Hawaiʻi 9.2% (±0.5). The app labels this a point difference of +19.8 percentage points. It performs no significance test.
5. **Review the agency route.** Under **Agency verification**, read the **Kūpuna Care** card. It starts with the **Official next step (recorded)** from the program record, with its link and phone number. It lists the facts the agency determines under **Questions to confirm with the agency**.
6. **Build the brief.** In the **Brief** panel, choose **Use recommended brief**. It selects the comparison and the Kūpuna Care agency action. The printed agency action carries the program's recorded referral link and phone, its open questions and its sources. These come from the program record checked October 30, 2026, not a live check. You can instead pick any findings with **Select for brief**, including the program reference, and choose **Use this agency action in the brief**. Extra findings may not fit one page. Choosing no action is also valid.
7. **Add a staff note.** Under **Staff notes**, enter a short title, a one-line summary and, if you like, one short next step. Choose **Mark staff notes reviewed**, then **Create one-page brief**. The status reads **Ready to print**. Staff text prints with the label *Staff edit — not a verified fact*.
8. **Print or save.** Choose **Print or save as PDF** to use your browser's print dialog.
9. **Save and reopen the case.** Under **Save or reopen the case**, choose **Download case file**. By default the file holds only the plan, versions and selected references. Select **Include staff notes (plain text, not encrypted)** to add your notes. Open a fresh tab, choose **Open a case file**, and review the preview. Reopened staff notes need a new review before a brief.

What the example does **not** establish:

- The map shows the 2026 boundary session. The statistics use 2024 district boundaries. House 028 has identical boundary geometry in both sessions, and the map says so.
- The age-65+ count is not Kūpuna Care's age-60+ population. It does not measure care need, eligibility, a participation gap or current capacity.
- The October 30, 2026 retrieval date does not confirm current program status.

The **SNAP outreach** issue follows the same workflow with its own three-step plan: a profile of the all-people poverty rate and median household income, the SNAP program reference and a reviewed outreach hypothesis. Its plan has no State comparison step. Its recommended brief selects two short district measures, the all-people poverty rate and median household income, plus the agency action. Verification routes to the DHS Benefit, Employment and Support Services Division (BESSD).

## What the release covers

| Area | Included in this release |
| --- | --- |
| Districts | All 51 House and 25 Senate districts. Statistics use 2024 district boundaries. The map can show the 2026 or 2024 session. |
| Measures | 20 American Community Survey (ACS) 2020–2024 five-year measures: age 65+, older householders living alone, income, Social Security receipt, poverty, employment, housing and rent burden. Each value keeps its published 90% margin of error. |
| Comparisons | Point differences against the State, any of the five counties or another district for the same measure. County choice supplies context. It does not establish that a district lies inside a county. |
| Program workflows | Two guided issues: **Older-adult support at home** (Kūpuna Care) and **SNAP outreach**. |
| Program references | SNAP, Med-QUEST, WIC, Kūpuna Care and the City and County of Honolulu Housing Choice Voucher program. Each record has an official link, agency, checked date and the facts the agency determines. |
| Administrative figures | 24 published participation figures: DHS monthly SNAP and Med-QUEST figures (statewide or island) and DBEDT county SNAP figures. They give context only and are never assigned to a district. |
| Map | The selected district's boundary, with a text alternative and selectable parts. Shading shows the district's all-people poverty class when its 2026 boundary matches the 2024 statistical boundary. |
| Brief and case | A printable one-page brief with numbered sources. A downloadable case file reopens only against the exact matching evidence. |

### Data sources and dates

| Source | Publisher | Used for | Retrieved |
| --- | --- | --- | --- |
| ACS 2020–2024 5-year workbooks for House, Senate, State and counties | Hawaiʻi DBEDT, republishing U.S. Census Bureau ACS | All 1,640 statistical values | 2026-10-30 |
| ACS profile group definitions (DP02–DP05) | U.S. Census Bureau Data API | Variable labels and definitions | 2026-10-30 |
| State legislative district boundaries, 2024 and 2026 sessions | U.S. Census Bureau TIGERweb | Map and boundary-session checks | 2026-10-30 |
| SNAP monthly participation summary, state fiscal year 2027 | Hawaiʻi DHS BESSD | Statewide SNAP context | 2026-10-30 |
| Medicaid enrollment report, 2026 | Hawaiʻi DHS Med-QUEST | Statewide and island Med-QUEST context | 2026-10-30 |
| County report, section H | Hawaiʻi DBEDT | County SNAP context | 2026-10-30 |
| Program pages and statutes (BESSD, Med-QUEST, DOH WIC, DOH Executive Office on Aging, HRS §§349-16 and 349-17, Honolulu Department of Community Services) | Each named agency | Program references and verification questions | 2026-10-30 |

These labels are descriptive. The app shows when an official title or publication date is not recorded. See [source notices](DATA-NOTICES.md) and the [included-input inventory](docs/PROJECTION-INPUTS.json).

This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.

## Challenge requirements

The table maps the Know Your District brief to this release. "Partly" means part of the requirement is met and the rest is stated.

| Requirement | Status | How this release handles it |
| --- | --- | --- |
| District summaries for all districts | Met | Every House and Senate district runs the same guided plan. |
| Age, income, poverty, employment and housing indicators | Met | 20 ACS measures. Tax, BLS, BEA and UHERO data are not included. |
| Compare with county and State | Met | Same-definition point differences with both margins shown. No significance test. |
| Every figure cites source, period and geography | Met | Each ACS finding and brief line links to publisher, period, universe, boundary session and cell location. Administrative figures show their source, period, coverage and cell. Program references show their official record and checked date. |
| State uncertainty and missing data | Met | Margins of error stay with values. Values the source has not published carry an unpublished status instead of a number. |
| Plain-language question interface | Partly | **Ask a question** is an experimental preview on the hosted app. It turns an ordinary question into a proposed plan, a clarifying choice or a refusal. Staff review and apply it. In developer checks of this build it delivered no critical error and no service failure. It did not pass every preregistered gate: handling of clarifications and unsupported requests fell short. No staff study has occurred. See [task results](#task-results), the [known issues](#known-issues-with-language-questions) and [optional language questions](#optional-language-questions). |
| Program information with official links; agency decides eligibility | Met | Five program references, two guided workflows and an agency action card with questions to confirm. |
| Potentially eligible populations and uptake gaps | Partly | The app offers a labeled outreach hypothesis and an agency verification route. It does not estimate eligible-but-unenrolled residents. The data do not support that estimate at district level. |
| District maps | Partly | Selected-district boundary and poverty shading with a text alternative. No statewide comparison map. |
| Export a sourced summary | Met | One-page brief through the browser's print dialog. See [task results](#task-results) for print status. |
| Public aggregate data only; no individual records | Met | The snapshot holds published aggregate values. The app has no resident lookup. |
| Accessible interface (WCAG 2.1 AA) | Not certified | Labeled controls, a skip link, a map text alternative and a 360-pixel layout were observed. Screen-reader use is unverified. |
| Keep program information current | Partly | Each record keeps a checked date. Refresh tools cover statistics and geometry. Program and administrative records need manual review. See [controlled source refresh](#controlled-source-refresh). |
| Validation of mapping and program results | Partly | Automated checks and developer task checks below. No staff or subject-matter-expert review has occurred. |

## Task results

These are developer checks, not a staff usability study or a measure of user accuracy. An AI browser agent operated the checks under developer direction. Each row is one observation on a named build. R12 is the guided release published November 14, 2026 (HST). This build adds a recommended brief and a Start here summary, and changes R12's language notice, agency cards, source links and printed wording. It keeps R12's data and calculations, and corrects the caveat shown with the all-people poverty rate. It also adds language questions as an experimental preview, which R12 had off. The preview is off by default in a source checkout. "This build" means the code at commit `aa8f0ab`. The hosted app has run this build with the preview on since November 16, 2026 (HST). "Hosted" means [haic.millrace.ai](https://haic.millrace.ai). "Local" means the same R12 release manifest served from a developer computer. Evidence kinds:

- **Reader check:** you can repeat it from [Try the House 028 Care example](#try-the-house-028-care-example) or [Check the checkout](#check-the-checkout).
- **Attested summary:** a public-safe summary of a private developer record.

| Task | Expected | Observed | Result | Build, date (HST), environment | Evidence |
| --- | --- | --- | --- | --- | --- |
| House 028 Care brief | Two findings, Kūpuna Care action and short staff notes produce a printable brief | Status **Ready to print**, Print enabled | Complete | R12, Nov 14, local Chrome | Reader check |
| House 013 Care brief and source | Source panel matches the finding | 5,488 ±511 persons at DP05 AX27/AY27. Brief reached **Ready to print** | Complete | R12, Nov 14, hosted Chrome | Reader check |
| Senate 025 Care brief | Multi-part district stays selectable | Map lists 10 parts. Brief reached **Ready to print** | Complete | R12, Nov 14, local Chrome | Reader check |
| House 028 SNAP outreach brief | Income and poverty findings with BESSD action | Brief reached **Ready to print** | Complete | R12, Nov 14, local Chrome | Reader check |
| Default and staff case files | Default file omits staff text. Opt-in file includes it. Reopen requires review | Default omitted staff fields. Opt-in held 3 staff fields. Fresh-tab reopen required review, then **Ready** | Complete | R12, Nov 14, hosted Chrome | Reader check |
| Case from an earlier release | Refused before replay, with a route to the matching release | Refused. The offered link opened the retained earlier release, which replayed the case unchanged | Complete | R12, Nov 14, hosted Chrome | Attested summary |
| Narrow screen | House 013 brief usable at 360 pixels wide | **Ready** and Print visible. No horizontal page overflow | Complete | R12, Nov 14, hosted Chrome | Reader check |
| Oversized staff summary | Brief refuses to overflow one page and keeps edits | Overflow refused, Print disabled, edits kept. A shorter summary restored **Ready** | Correct unsupported response | R12, Nov 14, local Chrome | Attested summary |
| Tab left open across the release update | Old tab blocks new briefs and keeps its case | Brief blocked and Print disabled. Case kept intact. Status text stayed on a pending message, and the source panel showed current data | Partial | R12, Nov 14, hosted Chrome | Attested summary |
| Hosted release checks | All districts, county comparisons, SNAP, indicator, secure cookie, no model call | All checks passed. Language reported off, zero model calls before and after | Complete | R12, Nov 14, hosted HTTP | Attested summary |
| Native Chrome Print, Cancel and Save as PDF | Cancel keeps edits. Saved PDF is readable | Not yet performed on R12 or this build | Unverified | — | — |
| Spoken VoiceOver journey | Hear and operate the full task | Not yet performed | Unverified | — | — |
| Walkthrough by the team captain, README only (not a first-time user) | Reach the House 028 brief using only these directions | Not yet performed | Unverified | — | — |
| Recommended brief, House 028 (this build) | **Use recommended brief** selects the comparison and agency action, and the brief reaches **Ready to print** | Not checked on the default Care plan. On a custom single-measure plan it selected that finding, and a brief with no staff text reached **Ready to print** | Partial | aa8f0ab, Nov 16, hosted browser | Attested summary |
| Plain-language questions, R12 | Interpret ordinary questions into supported steps | Off in R12. The question panel is hidden, a one-line notice says so, and guided steps remain available | Unsupported in R12 | R12, Nov 14, hosted Chrome | Reader check |
| Language qualification, this model setting on the earlier guard rules | Preregistered gate on 34 fresh held-out questions: at least 16 of 18 actionable, 3 of 4 source, 5 of 6 clarify and 5 of 6 unsupported correct, no critical error, 95th-percentile time at most 15 s | 16 of 18 actionable, 4 of 4 source, 5 of 6 clarify and 6 of 6 unsupported correct. An AI-agent audit found no critical error. 95th-percentile time 8.2 s | Gate met | `gpt-6.1-terra` medium, Nov 15, private developer evaluation | Attested summary |
| Confirmation, earlier build, `gpt-6.1-terra` medium | Preregistered: at least 114 of 119 scored questions, 76 of 79 supported actionable, 11 of 12 source, 15 of 16 clarify and 12 of 12 unsupported correct, no delivered critical error, no service failure, 95th-percentile time at most 15 s | 112 of 119, 73 of 79 supported actionable, 12 of 12 source, 15 of 16 clarify, 12 of 12 unsupported, 0 delivered critical errors, 0 service failures, 95th-percentile time 7.6 s over the 119 scored questions | Gate not met | e4bf7f3, Nov 15, private developer evaluation | Attested summary |
| Comparison, same earlier build and questions, `gpt-6.1-sol` low (test only) | Same questions and criteria | 110 of 119, 72 of 79 supported actionable, 12 of 12 source, 14 of 16 clarify, 12 of 12 unsupported, 0 delivered critical errors, 0 service failures, 95th-percentile time 5.0 s over the 119 scored questions | Gate not met | e4bf7f3, Nov 15, private developer evaluation | Attested summary |
| Development regression, this build, `terra-medium` | Same 119 scored questions and criteria as the earlier build. The questions were already used in development | 116 of 119 as delivered (115 of 119 on the model's own decisions), 79 of 79 supported actionable, 12 of 12 source, 13 of 16 clarify, 12 of 12 unsupported, 0 delivered critical errors, 0 service failures, 95th-percentile time 8.0 s over all 120 questions | Gate not met (clarify) | aa8f0ab, Nov 15, private developer evaluation | Attested summary |
| Reserve comparison, this build, `terra-medium` | Preregistered on 30 authored questions not run before: at least 29 of 30, 19 of 19 supported actionable, 3 of 3 source, 4 of 4 clarify and 4 of 4 unsupported correct, no delivered critical error, no service failure, 95th-percentile time at most 15 s | 28 of 30, 19 of 19 supported actionable, 3 of 3 source, 3 of 4 clarify, 3 of 4 unsupported, 0 delivered critical errors, 0 service failures, 95th-percentile time 7.9 s | Gate not met (overall, clarify, unsupported) | aa8f0ab, Nov 15, private developer evaluation | Attested summary |
| Reserve comparison, same questions, `terra-high` (comparison only, not hosted) | Same questions and criteria | 29 of 30, 19 of 19 supported actionable, 3 of 3 source, 3 of 4 clarify, 4 of 4 unsupported, 0 delivered critical errors, 0 service failures, 95th-percentile time 10.5 s | Gate not met (clarify) | aa8f0ab, Nov 15, private developer evaluation | Attested summary |
| Hosted language questions, this build | Ask a question, review the proposal and apply it on the hosted app | Two questions, one attempt each. A question about people age 65 and older in House 028 gave a single-measure plan. After review and a run it showed 6,463 persons (±542), ACS 2020–2024. A follow-up source question opened the same finding at DP05 DF27, margin DG27. The **Experimental AI preview** label was visible. Two automated clicks on **Apply plan** timed out as locator failures, and the header's **Review and apply these changes** control worked. No question was repeated | Complete | aa8f0ab, Nov 16, hosted browser | Attested summary |

Known limits from these checks:

- Native print on R12 and this build was not observed because the browser agent could not reach the native dialog. An earlier release printed an edited House 028 brief through native Chrome. Physical printers and other browsers are untested.
- Apple PDFKit text extraction, which macOS apps such as Preview use for search and copy, moves underscore characters in source URLs inside Chrome-saved PDFs. The PDF's stored text holds the exact URLs.
- One-page fit is measured when you create the brief. With an agency action, one page usually fits one comparison or about two short measure findings, plus a short title, summary and next step. Longer text or extra findings are refused, and your edits are kept. Fallback fonts are untested.
- Reload a tab that was open before a release update. Download work before you reload.
- The map does not follow a language question's measure. In the hosted check, the map kept its separately labeled all-people poverty shading after a question about people age 65 and older.

## Known limits

- The app supports published aggregate evidence and point differences for compatible measures. It does not estimate eligible-but-unenrolled residents, test statistical significance, rank districts, measure causal impact or establish current service capacity.
- The snapshot covers 76 districts, 51 House and 25 Senate, with public area aggregates only. An area aggregate cannot show whether a resident is eligible for a program, enrolled in it or missing from it. The app draws no such inference.
- County choice supplies comparison context. It does not establish district containment or program jurisdiction.
- The selected-district poverty shading uses fixed illustrative intervals. It shades 2026 geometry only when it matches the 2024 statistical boundary.
- Program records were checked October 30, 2026. Confirm current rules, contacts and availability with the agency.
- Accessibility is not certified. Screen-reader use is unverified.
- Language questions are an experimental preview. The preview did not pass every preregistered quality gate. See the [known issues](#known-issues-with-language-questions).
- The State portal terms leave a commercial-use limitation on State-derived data. See [scope and reuse](#scope-and-reuse).

## Run the bundled snapshot

Use Python 3.11. Run these commands from the repository root:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
HAIC_STATE_DIR="$HOME/.local/state/millrace-ai" HAIC_LOCAL_HTTP=1 PORT=8080 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8080 wsgi:application
```

Open [the local app](http://127.0.0.1:8080). Choose a district and run the visible plan. This guided run needs no API key or other credential, and language questions stay off. The server writes bounded operational metrics to `HAIC_STATE_DIR`. Keep that directory outside this repository. `HAIC_LOCAL_HTTP=1` permits a development cookie over local HTTP. For an HTTPS deployment, omit that setting. The supplied Gunicorn configuration uses one worker because pending requests and sessions live in process memory.

The Dockerfile packages the same bundled snapshot. Mount a private writable directory at `/var/lib/haic`. The container uses a nonroot user. Configure HTTPS at your hosting boundary.

The hosted app runs a pinned build of this container, from commit `aa8f0ab`, on one AWS Lightsail instance in `us-east-2`. A Caddy reverse proxy serves it, and Cloudflare proxies the public hostname. The only Python dependencies are Gunicorn and `packaging`, pinned by hash in `requirements.txt`. The browser code uses no third-party libraries.

## Check the checkout

```sh
.venv/bin/python tools/build_release_manifest.py --check
.venv/bin/python tools/build_candidate_metadata.py --check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_case_state.cjs
```

Python checks exercise all 76 districts, source inspection, claim bindings, case replay, HTTP sessions, and packet tamper rejection. Node checks exercise case state and staff-context protections. The Python suite also runs Node for its recommended-selection test, so install Node before running the full checks. The app itself does not need Node at run time. Case fixtures in `tests/fixtures/` are synthetic test material. They are separate from the runtime facts.

On November 15, 2026 (HST), both suites passed on the developer's macOS checkout of this build. Earlier versions of two language-adoption test files could fail when run as the root user, because root bypasses a file-permission fault the tests inject. This build's tests no longer rely on that fault. The developer checks used Python 3.11.6 and Node 22.22.0.

## Facts, references and verification

The default `public` input profile includes 1,640 statistical observations, 24 administrative observations, five program records, four original geometry captures, and authored recipe metadata. Source annotations remain explicit. Geometry provides district boundaries and cross-session compatibility. It does not establish program jurisdiction or access.

This is a smaller factual projection of the historical R2 archive. Its data and metadata have new identities. Source inspection verifies the bundled projection and displays historical origin hashes and locators. It does not claim to reread omitted workbooks or pages. Program evidence uses authored references instead of copied passages. The four included geometry captures still receive original-byte verification.

`runtime-packet/PACKET-MANIFEST.json` identifies the bundled facts. `candidate-metadata/MANIFEST.json` identifies the authored metadata. Their combination identifies analytical evidence. `RELEASE-MANIFEST.json` separately identifies the current source build and lists every publication member, including this README. A documentation-only commit therefore regenerates the manifest and changes the release id that a checkout reports. The hosted app runs the code at commit `aa8f0abc1ea4943dc500bfbe4f35d08beb8588b8`. Documentation-only commits are not redeployed, so the release id of `main` can differ from the hosted app's. Check out that commit to get the hosted code and its manifest. `/api/health` reports the running build's identity under `investigation.release_id`. See [data provenance](DATA-PROVENANCE.json), the [included-input inventory](docs/PROJECTION-INPUTS.json), and [source notices](DATA-NOTICES.md).

## Saved cases and historical R2 replay

Cases bind to an evidence snapshot and semantic claim references. The current app refuses a case from different evidence before analytical dispatch. It preserves the saved file and current browser case. It does not relabel historical sources or attach old finding notes to new claims.

The earlier hosted release is called R2. Cases saved from it reopen at [haic-r2.millrace.ai](https://haic-r2.millrace.ai). The current app offers that link when it refuses such a case. You can also use the explicit local `r2` profile, which requires the complete retained historical inputs. The [R2 replay guide](docs/R2-REPLAY.md) gives the exact inventory, installer and verification commands. Current source refresh cannot reconstruct that historical archive.

The browser holds the case in page memory. The app does not save the case on the server or in browser storage, so a reload discards unsaved work. The browser builds a downloaded case file itself, and it reads an opened case file in the page without uploading the file.

Parts of the case still reach the server when you act, because the server calculates results and renders the brief. Each run or replay sends the plan and your selections. A typed request sends its text. Creating a brief with staff notes sends those notes and checklist entries. The server renders the brief and does not store them. A language question, when the preview is on, sends the question and plan context to the server. The server forwards the question, the plans and value-free references to OpenAI. It does not forward staff notes, finding values, cookies or case identifiers.

Default downloads exclude staff work. Including staff text requires an explicit preview. Imported staff work needs contextual review before a brief. JSON downloads are unencrypted. Read [privacy and security behavior](PRIVACY.md) before entering information.

## Optional language questions

**Ask a question** is an experimental AI preview. The page labels it **Experimental AI preview** when it is on. The hosted app restored the preview on this build on November 16, 2026 (HST), after a short maintenance window. The preview is not gate-qualified. The results and the [known issues](#known-issues-with-language-questions) below say where it falls short.

When the preview is on, the app sends your question and limited public plan context to OpenAI's Responses API. The server selects the model through one named profile in `districtbrief/ia_language_profiles.json`. A question, cookie or browser setting cannot change the profile. That file fixes each profile's model, reasoning effort, service tier and token caps. It also fixes the per-token rates used for cost estimates. Each profile states the model, effort and tier that a response must report, and the server rejects a response that reports anything else. The hosted preview uses the `terra-medium` profile: `gpt-6.1-terra` at medium reasoning effort, on standard processing. `terra-high` exists for comparison only, and the hosted app does not use it. `sol-low` (`gpt-6.1-sol` at low effort) is for tests only.

The model only proposes. It returns a plan for the admitted operations, a clarifying choice or a refusal. It never states a figure. Staff review each proposal and choose **Use this proposal in the draft**. **Apply plan** then runs the same deterministic operations as the guided controls. Read [what is sent](PRIVACY.md#optional-language-questions) before you ask. Do not enter confidential or resident details.

A developer qualification of this model setting met its preregistered gate on 34 fresh held-out questions. An AI agent audited the results. This was not a staff usability study. That qualification used the earlier server guard rules. This build corrects several of those rules: a State comparison no longer blocks other named comparators, an unconfirmed draft's plan context is read the same way as a confirmed plan, the model's own inheritance labels no longer refuse an otherwise checked plan, and an unclear comparator gets typed choices when the model proposes a plan. One comparator pattern still fails (a bare district number), as the known issues describe.

On November 15, 2026 (HST), an earlier build (commit `e4bf7f3`) was checked on 120 authored questions, of which 119 are scored. `gpt-6.1-terra` at medium effort answered 112 of 119 correctly. `gpt-6.1-sol` at low effort answered 110 of 119 on the same questions. Neither met the preregistered threshold of 114, and neither delivered a critical error. Those figures describe that earlier build only. The questions were authored for that check and are not an untouched holdout, so the figures are not a population accuracy estimate.

On November 15, 2026 (HST), this build (commit `aa8f0ab`) had two developer checks. An independent AI reviewer audited the raw results and accepted the run's integrity and accounting. Neither setting passed every quality gate.

The first check reran the same 120 questions with `terra-medium`. These questions were already used in development, so the check measures regression, not accuracy on new questions. The delivered result was 116 of 119, and the clarify gate failed at 13 of 16. The server corrected one model decision, so the model's own decisions scored 115 of 119. The Housing Choice Voucher outreach question is reported separately, because the bundled data cannot run that outreach step. The model gave a safe partial proposal.

The second check ran 30 authored questions that had not been run before, once with `terra-medium` and once with `terra-high`. `terra-medium` answered 28 of 30 and `terra-high` answered 29 of 30. The gate allows one miss overall and none among the clarify or unsupported questions. `terra-medium` missed one clarify question and one unsupported question. `terra-high` missed the same clarify question. No run delivered a critical error or had a service failure.

Read these results narrowly. The two checks are separate, so do not add them together. The 30 questions are a small authored set with related question families. They are not a pristine holdout. An earlier entry gate consulted the earlier guard rules. A leak scan read the question bytes in memory. One question's wording appears verbatim in a source test. The results show no winner between the two settings, and they support no broad reliability claim.

On the 30 questions, server time per question averaged 4.2 s with `terra-medium` (2.3 to 8.9 s, 95th percentile 7.9 s). It averaged 5.0 s with `terra-high` (2.4 to 13.4 s, 95th percentile 10.5 s). That time includes the token count, generation, checks and accounting, so it is not model-only time. Estimated generation usage was 0.319877 USD with `terra-medium` and 0.328607 USD with `terra-high`. The 120-question rerun had a 95th-percentile time of 8.0 s and estimated usage of 1.292901 USD. These estimates apply documented rates to provider-reported usage. They are not invoices, and the input-count fee is unpublished. `terra-high` cost about 2.7% more and took about 19% longer on average, for one more correct answer. The hosted app stays on `terra-medium`.

Some correct questions may still end in a safe refusal or a clarifying choice. Guided steps, typed requests, sources, the brief and case files all work without language questions. **Typed request help** documents the literal request syntax. That parser runs on the server and calls no model.

When the preview is on, language use has fixed limits: 500 characters per question, 3 questions in any rolling 5-minute (300-second) window across the whole site, shared by all visitors, with no separate per-session limit. One question runs at a time. A finite spending budget covers all model use. When a limit or the budget is reached, the panel reports that language is unavailable and the guided controls keep working. If the hosted preview is turned off, the hosted app makes no model calls, and the spending record is kept as is.

In a source checkout, language questions are off by default. To run them, an operator sets `HAIC_LANGUAGE_ENABLED=1` and names one profile from `districtbrief/ia_language_profiles.json` in `HAIC_LANGUAGE_PROFILE`. The server refuses to start when the profile is missing or unknown. The operator also supplies their own OpenAI API key in a server secret file and a finite spending budget record. `districtbrief/ia_language_provider.py` and `districtbrief/ia_language_funding.py` define where the server reads them and how it checks them. The server checks both before it sends anything to OpenAI. This repository contains no API key and no budget record.

### Known issues with language questions

These issues are present in this build. Check every proposal before you choose **Use this proposal in the draft**.

- **A bare district number used as a comparator.** With a plan open, a question such as "compare this against district 10" can produce a choice for the primary district instead of the comparator. Name the chamber, for example "against House 10" or "against Senate 10". Inspect the district and the comparator in the proposal before you apply it.
- **Significance and hypothesis tests.** The app does not run them. The preview should refuse such a question. With `terra-medium` it may ask which measure you mean instead. Choosing a measure does not produce a significance test.
- **A place name without a district.** A question that names only a place gets a House or Senate choice first, then that chamber's district list. It does not get a list of nearby districts. One development question expects the nearby-district list, so the app fails it, and the score keeps that failure.
- **An empty clarifying choice.** When the model returns a clarifying question with an empty choice, the server rejects it and reports that it could not interpret the question. Nothing is applied. Rephrase the question or use guided controls.

This README does not claim that every language defect in this build is fixed or qualified. Fixes for these issues are proposed but not implemented, and no score was regraded. Every question used so far is now exposed, so any future fix needs validation on new questions.

## Cases from earlier public releases

The earlier public evidence remains available from [the exact published e2f2cf0 checkout](https://github.com/HAIC-2026/Millrace-AI/tree/e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4). Follow [the pinned replay instructions](docs/PUBLIC33AF-REPLAY.md). This release refuses old public33af and R2 cases before analytical dispatch. Start a blank case to use new evidence. No notes or selections migrate between evidence snapshots.

## Controlled source refresh

The app never follows user-provided source URLs or fetches live evidence during a query. [The separate source tools](tools/sources/README.md) can create an unreviewed statistical and geometry candidate. State workbooks require operator-supplied files. Only the fixed Census endpoints can be fetched automatically. The tools validate source identity, file hashes, table labels, geography, annotations and geometry structure. They refuse incomplete or malformed captures and never install outputs automatically.

Refreshing statistics and geometry leaves program and administrative dates unchanged. Those records need separate review. To refresh a program record, a reviewer rechecks the official page, updates the record and its checked date, and builds a new evidence snapshot. Review source changes, terms and analytical compatibility before creating a new admitted snapshot. Existing cases keep their original identities.

## Scope and reuse

Project-authored code is [MIT licensed](LICENSE). Outside source material has separate terms described in [license scope](LICENSE-SCOPE.md) and [data notices](DATA-NOTICES.md). State portal terms create an unresolved commercial-use limitation for State-derived information. This informational projection does not assert unrestricted commercial rights. Obtain applicable permission or independently replace affected sources before a covered commercial use.
