# Millrace AI · District Brief Builder

District Brief Builder is a deterministic evidence workbench for Hawaiʻi legislative staff.

Choose a House or Senate district, inspect aggregate measures, compare compatible estimates, and prepare an agency verification brief. The aging-at-home and SNAP outreach recipes connect published aggregate indicators with dated program references. Agencies determine eligibility and current availability.

This prototype serves 51 House districts, 25 Senate districts, 20 measures, State and all five county comparators, and complete district boundaries. Guided controls and Typed request make no model calls. Optional Language questions stay disabled until provider, accounting and quality admission passes. This candidate bundles the factual snapshot needed to run locally without credentials or a private archive.

This source is an isolated completion candidate. The hosted main application retains R2 evidence. New county, recipe, indicator and language work remains candidate-only until its release gates pass.

## Run the bundled snapshot

Use Python 3.11 or later. Run these commands from the repository root:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
HAIC_STATE_DIR="$HOME/.local/state/millrace-ai" HAIC_LOCAL_HTTP=1 PORT=8080 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8080 wsgi:application
```

Open [the local app](http://127.0.0.1:8080). Choose a district and run the visible plan. The server writes bounded operational metrics to `HAIC_STATE_DIR`. Keep that directory outside this repository. `HAIC_LOCAL_HTTP=1` permits a development cookie over local HTTP. For an HTTPS deployment, omit that setting. The supplied Gunicorn configuration uses one worker because pending requests and sessions live in process memory.

The Dockerfile packages the same bundled snapshot. Mount a private writable directory at `/var/lib/haic`. The container uses a nonroot user. Configure HTTPS at your hosting boundary.

## Facts, references and verification

The default `public` input profile includes 1,640 statistical observations, 24 administrative observations, five program records, four original geometry captures, and authored recipe metadata. The original 1,560 observations retain their R2 analytical meaning. Eighty observations add four county profiles from the same retained workbook. Source annotations remain explicit. Geometry provides district boundaries and cross-session compatibility. It does not establish program jurisdiction or access.

This is a smaller factual projection of the historical R2 archive. Its data and metadata have new identities. Source inspection verifies the bundled projection and displays historical origin hashes and locators. It does not claim to reread omitted workbooks or pages. Program evidence uses authored references instead of copied passages. The four included geometry captures still receive original-byte verification.

`runtime-packet/PACKET-MANIFEST.json` identifies the bundled facts. `candidate-metadata/MANIFEST.json` identifies the authored metadata. Their combination identifies analytical evidence. `RELEASE-MANIFEST.json` separately identifies the current source build and lists every publication member. See [data provenance](DATA-PROVENANCE.json), the [included-input inventory](docs/PROJECTION-INPUTS.json), and [source notices](DATA-NOTICES.md).

This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.

## Saved cases and historical R2 replay

Cases bind to an evidence snapshot and semantic claim references. The default public profile refuses historical R2 cases before analytical dispatch. It preserves the saved file and current browser case. It does not relabel historical sources or attach old finding notes to new claims.

Use the matching live R2 application or the explicit local `r2` profile to reopen those cases. The local profile requires your complete retained historical inputs. The [R2 replay guide](docs/R2-REPLAY.md) gives the exact inventory, installer and verification commands. Current source refresh cannot reconstruct that historical archive. The source build ID can change while the imported branch retains its historical release provenance.

Case state stays in browser memory until you download a file. Default downloads exclude staff work. Including staff text requires an explicit preview. Imported staff work needs contextual review before a brief. JSON downloads are unencrypted. Read [privacy and security behavior](PRIVACY.md) before entering information.

## Optional language questions

The separate Question control can propose a bounded plan or source-inspection request through OpenAI. It sends the question and value-free plan/catalog context. It excludes notes, claim values, source bodies and case files. Omit confidential or resident details. Interpret remains a separate zero-model literal parser.

A proposal changes no confirmed plan or result. Review the typed diff, apply it to the draft, then apply the plan and Run separately. Changes to context invalidate pending proposals. Guided controls remain available when language is disabled or fails.

Production enablement requires the approved shared two-bucket ledger, Linux secret mount, exact provider configuration and independent quality acceptance. The operator harness is included in the image. HTTP uses the demonstration bucket. Operator evaluation uses the testing bucket. Reservations are liability ceilings, not billed spend.

## Public33af case replay

The earlier public evidence remains available from [the exact published e2f2cf0 checkout](https://github.com/HAIC-2026/Millrace-AI/tree/e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4). Follow [the pinned replay instructions](docs/PUBLIC33AF-REPLAY.md). This candidate refuses old public33af and R2 cases before analytical dispatch. Start a blank case to use new evidence. No notes or selections migrate between evidence snapshots.

## Controlled source refresh

The app never follows user-provided source URLs or fetches live evidence during a query. [The separate source tools](tools/sources/README.md) can create an unreviewed statistical and geometry candidate. State workbooks require operator-supplied files. Only the fixed Census endpoints can be fetched automatically. The tools validate source identity, file hashes, table labels, geography, annotations and geometry structure. They refuse incomplete or malformed captures and never install outputs automatically.

Refreshing statistics and geometry leaves program and administrative dates unchanged. Those records need separate review. Review source changes, terms and analytical compatibility before creating a new admitted snapshot. Existing cases keep their original identities.

## Check the checkout

```sh
.venv/bin/python tools/build_release_manifest.py --check
.venv/bin/python tools/build_candidate_metadata.py --check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_case_state.cjs
```

Python checks exercise all 76 districts, source inspection, claim bindings, case replay, HTTP sessions, and packet tamper rejection. Node checks exercise case state and staff-context protections. Case fixtures in `tests/fixtures/` are synthetic test material. They are separate from the runtime facts.

## Scope and reuse

The workbench supports published aggregate evidence and bounded point differences for compatible measures. It does not estimate eligible-but-unenrolled residents, test statistical significance, rank districts, measure causal impact, or establish current service capacity. County choice supplies comparison context. It does not establish district containment or program jurisdiction. The selected-district poverty indicator uses fixed illustrative intervals. It shades 2026 geometry only when it matches the 2024 statistical boundary.

Project-authored code is [MIT licensed](LICENSE). Outside source material has separate terms described in [license scope](LICENSE-SCOPE.md) and [data notices](DATA-NOTICES.md). State portal terms create an unresolved commercial-use limitation for State-derived information. This informational projection does not assert unrestricted commercial rights. Obtain applicable permission or independently replace affected sources before a covered commercial use.
