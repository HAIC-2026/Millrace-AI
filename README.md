# Millrace AI · District Brief Builder

District Brief Builder is a web app that helps Hawaiʻi legislative staff turn a district question into a sourced, one-page brief for agency follow-up.

Team **Millrace AI** built it for the HAIC 2026 Know Your District challenge. Millrace AI is the team. District Brief Builder is the product.

**Try it:** [haic.millrace.ai](https://haic.millrace.ai). It needs no account, sign-in or setup.

**Status:** working prototype. Every figure comes from deterministic operations on a bundled snapshot of published aggregate data. Guided controls, sources, the brief and case files call no AI model. **Ask about this district** is an **experimental AI preview**: an OpenAI model proposes a plan and never supplies a number. In developer checks the preview delivered no critical error, but it did not pass every preregistered quality gate.

## From a question to a brief

This path takes about five minutes. It follows older-adult support at home in House District 28.

1. **Open the app.** It opens on House District 28 with the issue **Older-adult support at home**. Its plan has already run, so findings are on the page.
2. **Ask or browse.** With the AI preview on, type a question under **Ask about this district** and choose **Ask**, for example "How many adults 65 and older live in House 28?" Or skip it: the opening plan's findings are under **Findings and evidence**.
3. **Check the figure.** One finding reads **Population age 65 and over, House 028: 6,463 persons (90% margin of error ±542 persons)**. Choose **Inspect source** on that finding. The source panel names the publisher (Hawaiʻi DBEDT, republishing U.S. Census Bureau ACS data), the period (2020–2024), the universe (total population) and the location (sheet DP05, cell DF27, margin DG27).
4. **Read the comparison.** The age-65+ poverty rate is 29.0% (±4.3) in House 028 and 9.2% (±0.5) statewide. The app labels this a point difference of +19.8 percentage points. It runs no significance test.
5. **Review the agency route.** Under **Agency verification**, the Kūpuna Care card gives the program's recorded next step, link and phone number. It lists the facts only the agency can confirm.
6. **Create the brief.** Choose **Create recommended brief**. For this plan it selects the comparison and the Kūpuna Care agency action and builds a one-page brief with numbered sources. To add a staff note, write it under **Staff notes**, choose **Mark staff notes reviewed** and create the brief again. Staff text prints with the label *Staff edit — not a verified fact*. **Print or save as PDF** opens your browser's print dialog.
7. **Save and reopen the case.** Choose **Download case file**. The file leaves out staff notes unless you select **Include staff notes (plain text, not encrypted)**. To reopen, choose **Open a case file**, then **Replay and open this case**. Reopened staff notes need review before any brief.

What this path does **not** establish:

- The age-65+ count is not Kūpuna Care's age-60+ population. It does not measure need, eligibility, enrollment or capacity.
- The program record was checked on October 30, 2026. That date does not confirm current program status.
- The app drafts an outreach hypothesis for every district. A hypothesis is not a detected gap, a ranking or a signal. Read the figures.

The **SNAP outreach** issue follows the same path and routes to the DHS Benefit, Employment and Support Services Division (BESSD).

## What the release covers

| Area | Included |
| --- | --- |
| Districts | All 51 House and 25 Senate districts |
| Measures | 20 American Community Survey (ACS) 2020–2024 five-year measures: age 65+, older householders living alone, income, Social Security receipt, poverty, employment, housing and rent burden |
| Comparisons | Point differences against the State, a county or another district for the same measure |
| Programs | References for SNAP, Med-QUEST, WIC, Kūpuna Care and the City and County of Honolulu Housing Choice Voucher program. Two guided issues: older-adult support at home and SNAP outreach |
| Administrative context | 24 DHS and DBEDT participation records (23 published values and one month the source had not yet published) at state, island or county level. The app never assigns them to a district |
| Map | The selected district's boundary with a text alternative |
| Brief and case | A printable one-page brief with numbered sources, and a case file that reopens only against matching evidence |

Each ACS estimate shows its period, universe and 90% margin of error. Administrative counts show their period, coverage and source location. Program references show their source and checked date. All sources were retrieved on October 30, 2026. The app never fetches a source while you use it.

Statistics use the 2024 legislative districts that the ACS tabulated. The map's 2024 or 2026 setting changes only the boundary drawn. In this snapshot the two boundary sets match for all 76 districts.

This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.

## Challenge requirements

| Requirement | Status | How this release handles it |
| --- | --- | --- |
| District summaries for all districts | Met | Every House and Senate district runs the same plans |
| Age, income, poverty, employment and housing indicators | Met | 20 ACS measures. Tax, BLS, BEA and UHERO data are not included |
| Compare with county and State | Met | Same-measure point differences with both margins shown |
| Every figure cites source, period and geography | Met | Each figure links to its source record and location |
| State uncertainty and missing data | Met | Margins stay with values. Unpublished values show a status, not a number |
| Plain-language questions | Partly | Experimental AI preview; not every quality gate passed |
| Program information; agency decides eligibility | Met | Five program references and agency action cards |
| Potentially eligible populations and uptake gaps | Partly | A labeled outreach hypothesis and an agency route. No eligible-but-unenrolled estimate: no reviewed source publishes eligibility and participation for a district |
| District maps | Partly | Selected-district boundary. No statewide map |
| Export a sourced summary | Met | One-page brief through the browser's print dialog |
| Public aggregate data only | Met | No resident records and no resident lookup |
| Accessible interface (WCAG 2.1 AA) | Not certified | Labeled controls, a skip link and a map text alternative exist. Screen-reader use is unverified |
| Keep program information current | Partly | Each record keeps a checked date. Refresh is a reviewed manual step |
| Validation of mapping and results | Partly | Developer checks only. See [the methodology](docs/METHODOLOGY.md) |

## The experimental AI preview

The preview turns an ordinary question into a proposed plan, a clarifying choice or a refusal. The model never states a figure. The server checks each proposal against the allowed operations and sources before the app uses it. The same deterministic operations that serve the guided controls then compute the result.

A clear, supported proposal runs at once and keeps earlier work. The app asks for your review first when a proposal would change the district. It does the same for a district comparison that the question did not name with House or Senate. It also asks when a proposal would affect unapplied plan edits, brief selections or staff notes, and when the question says "my district".

When the proposal does not single out one finding, the page lists **Related findings**, says that they are not a completed answer, and lets you select the one you mean. Check the district, comparator and measure in every result.

**Create brief from this answer** or **Create brief from my selection** then builds the brief. **Advanced investigation** holds the plan's steps.

The hosted app uses one server-selected profile, `terra-medium`: OpenAI `gpt-6.1-terra` at medium reasoning effort.

Limits when the preview is on:

- 500 characters per question, and one question at a time.
- 3 questions in any rolling 5-minute (300-second) window across the whole site. All visitors share this limit. There is no separate per-session limit.
- A finite spending budget covers all model use.

When a limit or the budget is reached, the app reports that questions are unavailable. Every other feature keeps working.

Your question goes to OpenAI exactly as typed. Do not enter confidential or resident details. Read [what is sent](PRIVACY.md#optional-language-questions) first.

Developer evaluations ran on an earlier build, commit `aa8f0ab`. On 119 scored development questions the app delivered 116 correct results, including 79 of 79 supported tasks. It missed the clarifying-question gate at 13 of 16. On 30 further authored questions the hosted setting answered 28. No run delivered a critical error.

The developer wrote these questions, and many of them share a pattern. The results are not a staff study, a population accuracy estimate or a qualification of later builds. On November 16, 2026 (HST) the server's comparator and significance rules and the interface's proposal flow changed. Regression tests cover those engineering changes. No new evaluation has been run. [The methodology](docs/METHODOLOGY.md#5-ai-preview-evaluation) gives the full results and the known issues.

## Run it locally

Use Python 3.11. Run these commands from the repository root:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
HAIC_STATE_DIR="$HOME/.local/state/millrace-ai" HAIC_LOCAL_HTTP=1 PORT=8080 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8080 wsgi:application
```

Open [the local app](http://127.0.0.1:8080). This guided run needs no API key, database or other credential. The AI preview stays off in a source checkout unless an operator configures it.

To check a checkout:

```sh
.venv/bin/python tools/build_release_manifest.py --check
.venv/bin/python tools/build_candidate_metadata.py --check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_app_startup.cjs tests/test_case_state.cjs tests/test_language_state.cjs
```

[The run guide](docs/RUNNING.md) covers settings, Docker, the checks, AI configuration, release identity and source refresh.

## Known limits

- The app reports published aggregate evidence and point differences. It does not estimate eligible-but-unenrolled residents, test statistical significance, rank districts or establish current service capacity.
- Accessibility is not certified, and screen-reader use is unverified.
- State portal terms leave a commercial-use limitation on State-derived data. See [license scope](LICENSE-SCOPE.md).

## Data, license and privacy

- **License:** project-authored code is [MIT licensed](LICENSE). Outside source material has separate terms. See [license scope](LICENSE-SCOPE.md) and [source notices](DATA-NOTICES.md).
- **Data:** [data provenance](DATA-PROVENANCE.json) and [the included-input inventory](docs/PROJECTION-INPUTS.json) identify the bundled facts.
- **Privacy:** [privacy and security behavior](PRIVACY.md) says what reaches the app server and what reaches OpenAI.
- **Saved cases from earlier releases:** cases from the first hosted release reopen at [haic-r2.millrace.ai](https://haic-r2.millrace.ai). See [the R2 replay guide](docs/R2-REPLAY.md) and [the public33af replay guide](docs/PUBLIC33AF-REPLAY.md).

## Contact

Open an issue at [github.com/HAIC-2026/Millrace-AI/issues](https://github.com/HAIC-2026/Millrace-AI/issues). Posting requires a GitHub sign-in. Do not include resident or confidential details.

Team Millrace AI maintains this competition prototype. No agency ownership or service level is claimed.
