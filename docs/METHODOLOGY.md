# How District Brief Builder maps, measures and checks its figures

This page describes how [District Brief Builder](../README.md) assigns figures to districts, what was checked, what the checks found and what has not been checked. The checks are developer checks. No agency, subject-matter expert or legislative staff member has reviewed the figures.

## 1. Mapping: how a district gets its numbers

- **Native district tables, no apportionment.** Every statistic is a value that the publisher already tabulated for that geography. The source is Hawaiʻi DBEDT's republication of the U.S. Census Bureau's American Community Survey (ACS) 2020–2024 five-year profile tables. The app never splits a tract, ZIP code or county total across districts. Each record carries `spatial_method: native published geography; no apportionment`.
- **Geographies covered:** 82. These are 51 House districts, 25 Senate districts, 5 counties and the State.
- **Administrative records stay where the agency published them.** The 24 DHS and DBEDT records are statewide, island or county totals. They hold 23 published values and one month (October 2026 SNAP) that the source had not yet published. Each record is marked as unusable for a district gap. No operation assigns one to a district.
- **County comparisons are context.** A county comparator does not assert that a district lies inside that county.

## 2. Measures

The app uses 40 ACS measures. Each measure binds to one Census variable and one workbook row. The original 20 are listed first. **Ask about this district** uses only those 20.

| Measure | ACS variable | Workbook sheet, row |
| --- | --- | --- |
| Total population | DP05_0001E | DP05, 4 |
| Median age | DP05_0018E | DP05, 21 |
| Population age 65 and over | DP05_0024E | DP05, 27 |
| Total households | DP02_0001E | DP02, 4 |
| Male householder 65+ living alone | DP02_0009E | DP02, 12 |
| Female householder 65+ living alone | DP02_0013E | DP02, 16 |
| Civilian labor force | DP03_0003E | DP03, 6 |
| Unemployed | DP03_0005E | DP03, 8 |
| Unemployment rate | DP03_0009PE | DP03, 12 |
| Education, health care and social assistance industry | DP03_0042E | DP03, 48 |
| Median household income | DP03_0062E | DP03, 70 |
| Households with Social Security income | DP03_0066E | DP03, 74 |
| Poverty rate, all people | DP03_0128PE | DP03, 138 |
| Poverty rate, age 65 and over | DP03_0135PE | DP03, 145 |
| Total housing units | DP04_0001E | DP04, 4 |
| Occupied housing units | DP04_0002E | DP04, 5 |
| Renter-occupied units | DP04_0047E | DP04, 55 |
| Median gross rent | DP04_0134E | DP04, 152 |
| Renter units with computable rent-to-income ratio | DP04_0136E | DP04, 155 |
| Renter units paying 35%+ of income for gross rent | DP04_0142E | DP04, 161 |

The 20 guided measures come from the same four DBEDT workbooks and cover the same 82 geographies. Counts and percentages of one concept are separate variables. Each percentage keeps the publisher's percent margin (`PM`) and its stated universe.

| Guided measure | ACS variable | Workbook sheet, row | Universe |
| --- | --- | --- | --- |
| Households reporting SNAP receipt in the past 12 months | DP03_0074E | DP03, 82 | All households. The ACS measures survey-reported SNAP receipt by a current household member in the past 12 months. Administrative enrollment and eligibility require separate evidence. |
| Households reporting SNAP receipt in the past 12 months, share | DP03_0074PE | DP03, 82 | All households. The ACS measures survey-reported SNAP receipt by a current household member in the past 12 months. Administrative enrollment and eligibility require separate evidence. |
| People with a disability, share | DP02_0072PE | DP02, 84 | Civilian noninstitutionalized population |
| Share of people age 65 and over who have a disability | DP02_0078PE | DP02, 90 | Civilian noninstitutionalized population age 65 years and over |
| People age 5 and over who speak English less than “very well,” share | DP02_0115PE | DP02, 133 | Population age 5 years and over |
| People without health insurance coverage, share | DP03_0099PE | DP03, 108 | Civilian noninstitutionalized population |
| Population age 60 to 64 | DP05_0014E | DP05, 17 | Total population |
| Households with someone age 65 and over | DP02_0015E | DP02, 18 | Households |
| Native Hawaiian alone (one race reported) | DP05_0071E | DP05, 75 | Total population. This category counts people reporting Native Hawaiian as their only race. |
| Occupied housing units with no vehicle available, share | DP04_0058PE | DP04, 68 | Occupied housing units |
| Gross rent at 30.0–34.9% of household income (share of computable ratios) | DP04_0141PE | DP04, 160 | Occupied units paying rent with computable gross rent as a percentage of household income |
| Households with a broadband Internet subscription, share | DP02_0154PE | DP02, 174 | Households |
| Gross rent at 35% or more of household income (share of computable ratios) | DP04_0142PE | DP04, 161 | Occupied units paying rent with computable gross rent as a percentage of household income |
| Native Hawaiian and Other Pacific Islander alone or in combination, share | DP05_0087PE | DP05, 92 | Total population; Native Hawaiian and Other Pacific Islander alone or in combination with other races |
| People age 25 and over with a bachelor’s degree or higher, share | DP02_0068PE | DP02, 78 | Population age 25 years and over |
| Households with retirement income, share | DP03_0068PE | DP03, 76 | Households; retirement income in the past 12 months |
| Per-capita income | DP03_0088E | DP03, 96 | Total population; income in the past 12 months |
| Population age 85 and over | DP05_0017E | DP05, 20 | Total population |
| Workers age 16 and over who worked from home, share | DP03_0024PE | DP03, 28 | Workers age 16 years and over |
| Owner-occupied share of occupied housing units | DP04_0046PE | DP04, 54 | Occupied housing units |

SNAP receipt is household receipt reported in the survey for the past 12 months. It is not enrollment, a current caseload or eligibility, and it supports no participation gap. The Native Hawaiian count is the one-race category; the Native Hawaiian and Other Pacific Islander share counts people of that race alone or in combination with other races. The two are not interchangeable.

Each value keeps its universe and its period. It keeps the publisher's 90% margin of error where the source gives a number, which is 3,274 of the 3,280 values. For the other 6 the source prints `*****` in place of a margin. The app keeps that marker and shows no number.

A comparison is a point difference of two published estimates for the same measure. The app derives no margin for a difference and runs no significance test. It does not treat overlapping or non-overlapping margins as evidence.

## 3. Outreach hypotheses

The app drafts an outreach hypothesis for a program and a district. The text is labeled "Outreach hypothesis — not a measured gap or eligibility finding". It lists the district's published measures for that program, the agency route, and the facts that only the agency determines.

- The app drafts the same kind of hypothesis for every district where the program applies. The hypothesis is not a detected gap, a ranking or a signal. A district below the State on every listed measure receives one too.
- The two guided issues route to different agencies with different verification questions: the Executive Office on Aging for Kūpuna Care, and DHS BESSD for SNAP.
- The app does not estimate eligible-but-unenrolled residents. That estimate needs eligibility and participation measured for the same district, period and definition, with their error. No source reviewed here publishes either term for a legislative district.

## 4. What was checked, and the result

The team ran these checks on November 16, 2026 against its retained original captures of the publishers' files. This repository does not redistribute the State workbooks, PDFs or pages (see [source notices](../DATA-NOTICES.md)). To repeat a cell check, download a workbook from its address in [`tools/sources/allowlist.json`](../tools/sources/allowlist.json), compare its SHA-256 with that file, and read the cell that the app's source panel names. Addresses and SHA-256 values for every recorded source are in [`runtime-packet/SOURCE-CATALOG.json`](../runtime-packet/SOURCE-CATALOG.json).

| Check | Scope | Result |
| --- | --- | --- |
| Snapshot integrity | Every bundled data file against the pinned manifest, at each start | The app refuses to start on a mismatch. See `districtbrief/public_packet.py` and `tests/test_public_profile.py` |
| Retained originals | All 55 recorded sources: the retained original capture and its SHA-256 against the recorded hash | 55 of 55 present and equal |
| Cell binding | All 1,640 statistical values against the cited cell of the original DBEDT workbook: estimate, margin, geography header and row label | 1,640 estimates, row labels and geography headers match. 1,634 margins match numerically. The other 6 are `*****` in the source and carry that marker in the snapshot |
| Guided measures (November 19, 2026) | The 1,640 added values: independent re-extraction of estimate, margin, cell, geography and label from the retained workbooks, with the original 1,640 rows compared in full | 1,640 added numeric estimates and 1,640 numeric margins; no added `*****` margin. The original 1,640 rows are unchanged in value, margin, citation and serialization. 1,148 percentage denominator checks agree within 0.05 percentage points |
| Variable definitions | All 1,640 original values: Census variable id and official label against the Census API variable lists; workbook row label against the label's last segment | 1,640 of 1,640 match. Each of the 20 measures maps to one variable and one row. The 20 guided measures were reviewed against their parent headings and universes in the same way |
| County SNAP records | 5 DBEDT county report values against the cited workbook cells | 5 of 5 match |
| Med-QUEST enrollment records | 12 values read by eye against page 1 of the original report (report date June 5, 2026) | 12 of 12 match. One reader |
| DHS SNAP monthly records | 7 records in a legacy `.xls` workbook: 6 published monthly values and 1 unpublished month | **Not replayed.** The source locations were recorded when the snapshot was compiled |
| Referral contacts | Executive Office on Aging and county office-on-aging numbers; DHS public assistance line and application address, against captures of the official pages | Present on the pages as captured on October 30, 2026 |
| Boundary sessions | 2024 statistical boundaries against 2026 map boundaries, all 76 districts | The bundled 2026 geometry equals the 2024 geometry for all 76 districts. The four boundary captures are bundled, so a reader can repeat this comparison. See `districtbrief/geography.py` |
| Recorded source addresses | One anonymous request to each of the 55 recorded addresses. One normal Chrome visit to each of the 5 Med-QUEST addresses that bundled program and enrollment records cite | 48 answered. 7, all on `medquest.hawaii.gov`, refused the automated client (HTTP 403). All 5 cited Med-QUEST addresses loaded in Chrome with no access challenge. This shows only that they load, not that their content is current. The other 2 refused addresses are Med-QUEST report index pages, not opened in a browser. A refusal is unverified access, not a confirmed broken link |
| Automated suites | The commands in [the run guide](RUNNING.md#check-a-checkout) | On November 15, 2026 both suites passed on the developer's checkout of commit `aa8f0ab`: 401 Python tests and 38 Node tests |

How the recorded sources are used:

- 21 of the 55 are cited explicitly by a bundled figure, program record or boundary. That number counts explicit claim references only.
- The Census variable lists (DP02–DP05) supplied the official variable label that every statistical value carries. The app reads the DP03 list at run time for one displayed definition, SNAP receipt.
- Map-layer descriptions, index pages and Census guidance documents record how the cited files were located and defined.
- The remainder are earlier captures kept for provenance.

Publisher names in the app's recorded sources follow the agency site that served each file when it was retrieved, or the document's masthead. The app does not record official titles, authors or publication dates. For example, a USDA file retrieved from the Food and Nutrition Administration's site names the Food and Nutrition Service in its own 2025 text.

## 5. AI preview evaluation

The AI preview sends a question to an OpenAI model. The model returns a proposed plan, a clarifying choice or a refusal. The server checks the reply against a schema of admitted operations, identifiers and steps, then validates the plan (`districtbrief/ia_language.py`; tests in `tests/test_ia_language_*.py`). The model never supplies a figure.

All results below are developer evaluations on **commit `aa8f0ab` or earlier**, run on November 15, 2026 (HST). They do not describe any later build. Question sets and raw responses are private developer records, so a reader cannot rerun these evaluations from this repository. The server rules they exercised are public.

| Evaluation | Build and setting | Result | Gate |
| --- | --- | --- | --- |
| 34 held-out questions, earlier server guard rules | `gpt-6.1-terra` medium | 16 of 18 actionable, 4 of 4 source, 5 of 6 clarify, 6 of 6 unsupported | Met |
| 119 scored authored questions | `e4bf7f3`, `terra-medium` | 112 of 119; 73 of 79 supported; 15 of 16 clarify | Not met (needed 114) |
| Same questions | `e4bf7f3`, `sol-low` (test only) | 110 of 119; 72 of 79 supported; 14 of 16 clarify | Not met |
| Development regression, same 119 questions, already used in development | `aa8f0ab`, `terra-medium` | 116 of 119 delivered; 115 of 119 on the model's own decisions; 79 of 79 supported; 12 of 12 source; 13 of 16 clarify; 12 of 12 unsupported | Not met (clarify needed 15 of 16) |
| 30 authored questions not run before | `aa8f0ab`, `terra-medium` | 28 of 30; 19 of 19 supported; 3 of 3 source; 3 of 4 clarify; 3 of 4 unsupported | Not met |
| Same 30 questions | `aa8f0ab`, `terra-high` (comparison only) | 29 of 30; 19 of 19 supported; 3 of 3 source; 3 of 4 clarify; 4 of 4 unsupported | Not met (clarify) |

No run delivered a critical error or had a service failure. In the development regression the server corrected one model decision, which accounts for the difference between 116 and 115. One Housing Choice Voucher outreach question is reported separately, because the bundled data cannot run that step.

On the 30 questions, the 95th-percentile server time per question was 7.9 s with `terra-medium` and 10.5 s with `terra-high`. Estimated generation usage was 0.319877 USD and 0.328607 USD. These estimates apply documented rates to provider-reported usage. They are not invoices.

Read these results narrowly:

- The developer wrote every question. The 119 questions were already exposed to development. The 30 questions come from related question families.
- One of the 30 questions appears word for word in a source test. An earlier entry gate consulted the earlier guard rules.
- The two `aa8f0ab` evaluations are separate. Do not add them together.
- The results show no winner between the two settings. They are not a population accuracy estimate, a staff study or a qualification of any later build.

In a hosted check of `aa8f0ab` on November 16, 2026, two questions ran once each. A question about people age 65 and older in House 028 produced the 6,463 (±542) finding, and a source follow-up opened DP05 DF27.

Known issues found on `aa8f0ab`:

- **A bare district number as a comparator.** "Compare this against district 10" can produce a choice for the primary district instead of the comparator. Name the chamber: "against House 10".
- **Significance tests.** The app does not run them. The preview should refuse such a question, and `terra-medium` sometimes asked which measure was meant instead.
- **A place name without a district.** The app asks for House or Senate first, then offers that chamber's districts. It does not list nearby districts.
- **An empty clarifying choice.** The server rejects it and reports that it could not interpret the question. Nothing is applied.

Fixes for these issues need validation on new questions, because every question used so far is exposed.

On November 16, 2026 (HST) a server-rule revision changed the first two issues: a district number in comparator position, including in a list, now stays a comparator, and significance-test wording is refused on clarifications and proposals alike. The revision also keeps zero-padded district numbers in a list intact and handles a typed request to add a program to a district before any plan exists. The model, prompt, response schema, profile and data are unchanged.

On the same date the interface changed how a proposal runs. A clear, supported proposal runs at once and keeps earlier work. A proposal waits for review when it would change the district, add a district comparison that the question did not name with House or Senate, or affect unapplied plan edits, brief selections or staff notes, and when the question says "my district". When the proposal does not single out one finding, the page labels the results as related findings and not as an answer.

Both changes are engineering changes covered by developer regression tests on already exposed patterns. They are not a new evaluation, and the results above describe `aa8f0ab`.

## 6. Task checks on named builds

A browser agent operated these checks under developer direction. Each row is one observation on a named build. R12 is the guided release published on November 14, 2026 (HST). "Hosted" means haic.millrace.ai. "Local" means the same release served from a developer computer. These rows are not a staff usability study.

| Task | Observed | Result | Build and environment |
| --- | --- | --- | --- |
| House 028 Care brief | Status **Ready to print**; Print enabled | Complete | R12, local Chrome |
| House 013 Care brief and source | 5,488 ±511 persons at DP05 AX27/AY27; brief reached Ready | Complete | R12, hosted Chrome |
| Senate 025 Care brief | Map lists 10 parts; brief reached Ready | Complete | R12, local Chrome |
| House 028 SNAP outreach brief | Brief reached Ready | Complete | R12, local Chrome |
| Default and staff case files | Default file omitted staff fields; opt-in file held them; reopening required review | Complete | R12, hosted Chrome |
| Case from an earlier release | Refused before replay; the offered link opened the retained release, which replayed the case | Complete | R12, hosted Chrome |
| Narrow screen, 360 pixels | Brief Ready and Print visible; no horizontal overflow | Complete | R12, hosted Chrome |
| Oversized staff summary | Overflow refused; edits kept; a shorter summary restored Ready | Correct refusal | R12, local Chrome |
| Tab left open across a release update | Brief blocked and case kept; status text stayed on a pending message | Partial | R12, hosted Chrome |
| Hosted release checks | All districts, county comparisons, SNAP, secure cookie; zero model calls with the preview off | Complete | R12, hosted HTTP |
| Recommended brief, House 028 | Not checked on the default Care plan. On a custom single-measure plan the brief reached Ready | Partial | `aa8f0ab`, hosted browser |
| Native print, Cancel and Save as PDF | Not performed | Unverified | None |
| Spoken screen-reader journey | Not performed | Unverified | None |
| Walkthrough from the README alone | Not performed | Unverified | None |

The interface changed on November 16, 2026 (HST), after the checks in this table. Developers reviewed and tested the new interface's code on that date. Those are component checks. This table records no hosted check of the released build, so the recommended-brief, print and screen-reader rows keep their status.

Limits from these checks:

- One-page fit is measured when the brief is created. With an agency action, one page usually fits one comparison or about two short measure findings. The app refuses longer content and keeps your edits.
- Physical printers, other browsers and fallback fonts are untested. The saved PDF has not been checked for accessibility tagging.
- On `aa8f0ab` the map did not follow a question's measure. It kept its separately labeled all-people poverty shading.

## 7. What has not been checked

- **No independent value comparison against the Census Bureau.** The figures are DBEDT's republication. On November 16, 2026 one unauthenticated request for the same variables to the Census Data API was redirected to a required-key page. No further attempt was made, so the comparison was not performed. That one request says nothing about the API's general access rules. The Census variable lists confirm definitions, not values.
- **No full independent upstream audit.** The checks compare the snapshot with captures of the publishers' files. They do not re-derive DBEDT's republished figures from Census Bureau data. Program records were written from the official pages on October 30, 2026 and were not re-read against the live pages.
- **No subject-matter or agency review, and no staff study.**
- **No evaluation of any build after `aa8f0ab`.** Later server rules or interface changes are not covered until they are checked on the build that ships them.
- **Accessibility conformance, native printing and screen-reader use.**
- **The refresh process end to end.** See section 10.

## 8. Dates, vintages and boundaries

| Item | Vintage | Note |
| --- | --- | --- |
| Statistics | ACS 2020–2024 five-year estimates | A five-year period estimate, not a single year. Dollar values are 2024 inflation-adjusted |
| Statistical district boundaries | The 2024 legislative districts that ACS 2024 tabulated | Statistics always use this session |
| Map boundaries | The 2024 or 2026 session | The map setting changes the boundary drawn. It does not change the statistics or load newer ACS values |
| Boundary match | Both sessions | In this snapshot the geometry is identical for all 76 districts. The app shades 2026 geometry only when it equals the 2024 statistical boundary |
| Administrative records | SNAP: state fiscal year 2027 months, and a 2024 county table whose period basis the source does not state. Med-QUEST: January–March 2026 | Not aligned with the ACS period. Shown as context only |
| Program records | Checked October 30, 2026 | Not a live check |
| All sources | Retrieved October 30, 2026 | The app never fetches a source at run time |

The boundary session and the statistical period are separate facts. The app names both and changes neither to match the other.

## 9. Coverage, sources and licensing limits

Included: 40 ACS measures (the original 20 also used by Ask about this district); five program references (SNAP, Med-QUEST, WIC, Kūpuna Care, City and County of Honolulu Housing Choice Voucher); two guided issues; 24 administrative records; district boundaries for two sessions.

Not included:

- Department of Taxation statistics, UHERO, Bureau of Labor Statistics and Bureau of Economic Analysis data, all named in the challenge brief.
- District-level program participation or eligibility data.
- Guided issues for Med-QUEST, WIC and Housing Choice Voucher. The voucher record covers the Honolulu agency only.
- Other programs, other ACS measures, sub-district geography, time series, a statewide comparison map, significance testing and rankings.

Source and licensing limits:

- The MIT license covers project-authored code and documentation only. See [license scope](../LICENSE-SCOPE.md).
- The repository bundles a normalized factual projection and four boundary captures. [Source notices](../DATA-NOTICES.md) list each included input and its origin.
- State portal terms restrict commercial use of State-derived data and prohibit automated access. This limitation is unresolved. The release is prepared for informational review.
- Census API terms apply to the Census variable lists. This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.

## 10. Freshness and refresh

**Owner.** Team Millrace AI maintains this competition prototype. No State agency has accepted ownership, staffing or a service level.

**What is dated.** Every source shows its retrieval date. Every program record shows its checked date, October 30, 2026.

**How a refresh works.** [The run guide](RUNNING.md#controlled-source-refresh) describes the manual, reviewed steps. Tools exist for statistics and geometry only. Program and administrative records have no tool. A new snapshot has a new identity, and saved cases keep theirs.

**Not verified.** A complete refresh, from capture to a reviewed release, has not been run end to end for this data. Treat the process as documented, not proven.

The triggers and cadence below are a proposal. They have not been tested as a routine.

| Data | Review trigger | Proposed cadence |
| --- | --- | --- |
| ACS statistics | DBEDT posts the next ACS five-year workbooks | Yearly, when published |
| District boundaries | A reapportionment, or a change to a TIGERweb session layer | On the event; check yearly |
| Program records | An agency page changes, a link stops answering, a program is renamed, or a rule's effective date passes | Quarterly, and before each legislative session |
| Administrative records | The agency posts a new period | When posted; check quarterly |
| Recorded source addresses | An address returns an error to a person | Monthly link check. A refusal to an automated client needs a browser check before any conclusion |
| AI preview | A model retirement or price change, or any change to the prompt, the server rules or the catalog | On the event, with a new evaluation on unseen questions |
