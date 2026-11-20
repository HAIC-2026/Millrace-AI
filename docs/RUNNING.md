# Run, check and operate District Brief Builder

This guide holds the developer and operator detail for [District Brief Builder](../README.md). The README has the short path. Run every command from the repository root.

## Run the bundled snapshot

Use Python 3.11.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
HAIC_STATE_DIR="$HOME/.local/state/millrace-ai" HAIC_LOCAL_HTTP=1 PORT=8080 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8080 wsgi:application
```

Open [the local app](http://127.0.0.1:8080). Choose a district and run the visible plan. This guided run needs no API key or other credential, and the AI preview stays off.

| Setting | Effect |
| --- | --- |
| `HAIC_STATE_DIR` | Directory where the server writes bounded operational metrics. Keep it outside the repository. |
| `HAIC_LOCAL_HTTP=1` | Permits a development cookie over local HTTP. Omit it for an HTTPS deployment. |
| `PORT` | Port for the supplied Gunicorn configuration, which binds all interfaces. The local command's `--bind 127.0.0.1:8080` overrides that bind and keeps the server on loopback. |
| `HAIC_INPUT_PROFILE` | `public` (default) uses the bundled snapshot. `r2` replays historical cases and needs `HAIC_R2_INPUT_DIR`. See [the R2 replay guide](R2-REPLAY.md). |

The supplied Gunicorn configuration uses one worker, because pending requests and sessions live in process memory. The only Python dependencies are Gunicorn and `packaging`, pinned by hash in `requirements.txt`. The browser code uses no third-party libraries.

### Docker

The `Dockerfile` packages the same bundled snapshot. The container runs as a nonroot user. Mount a private writable directory at `/var/lib/haic`. Configure HTTPS at your hosting boundary.

### Hosted deployment

The hosted app runs a pinned build of this container on one AWS Lightsail instance in `us-east-2`. A Caddy reverse proxy serves it, and Cloudflare proxies the public hostname.

### Operator requirement

The supplied Gunicorn configuration runs a single synchronous worker. Bind Gunicorn to a loopback address, or publish the container's port on loopback only. Inside the container the supplied configuration binds all interfaces. Put a reverse proxy in front that buffers the whole request body before it passes the request on. The proxy's buffer must be larger than its body size limit, and the proxy must enforce a deadline for reading the body. Example bounds: a 65,536-byte body limit, a 65,537-byte buffer and a 5-second read deadline, or equivalent. Do not expose Gunicorn directly to the Internet. This requirement is not a security certification of the app.

## Check a checkout

```sh
.venv/bin/python tools/build_release_manifest.py --check
.venv/bin/python tools/build_candidate_metadata.py --check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_app_startup.cjs tests/test_case_state.cjs tests/test_language_state.cjs
```

| Command | What it checks |
| --- | --- |
| `build_release_manifest.py --check` | Every file in the checkout is an admitted publication member and matches `RELEASE-MANIFEST.json`. |
| `build_candidate_metadata.py --check` | The authored metadata matches `candidate-metadata/MANIFEST.json`. |
| `unittest discover` | All 76 districts, source inspection, claim bindings, case replay, HTTP sessions, packet tamper rejection and the AI preview's server rules. |
| `node --test` | Case state and staff-context protections, the question guards, and app startup, catalog Retry and pagination, in the browser code. |

The Python suite also runs Node for its recommended-selection test, so install Node before you run the full checks. The app itself does not need Node at run time. The Python suite needs the installed requirements, because one test starts Gunicorn. Case fixtures in `tests/fixtures/` are synthetic test material. They are separate from the runtime facts.

On November 15, 2026 (HST), both suites passed on the developer's macOS checkout of commit `aa8f0ab`: 401 Python tests and 38 Node tests, on Python 3.11.6. Earlier versions of two language-adoption test files could fail when run as the root user, because root bypasses a file-permission fault that the tests inject. The tests at that commit no longer rely on that fault.

## Release identity

Three manifests identify a build:

- `runtime-packet/PACKET-MANIFEST.json` identifies the bundled facts.
- `candidate-metadata/MANIFEST.json` identifies the authored metadata. The two together identify the analytical evidence.
- `RELEASE-MANIFEST.json` identifies the source build. It lists every publication member, including the documentation.

Any commit, including a documentation-only commit, regenerates `RELEASE-MANIFEST.json` and changes the release id that a checkout reports. The hosted app can therefore report a different release id from `main`. `/api/health` reports the running build's identity under `investigation.release_id`.

## Bundled facts and source inspection

The default `public` input profile includes 3,280 statistical observations (40 ACS measures for 82 geographies), 24 administrative records, five program records, four original geometry captures and authored recipe metadata. It combines the earlier public projection with 20 additional measures extracted from the same retained workbooks. The public and historical R2 profiles have separate evidence identities.

Source inspection verifies the bundled projection. It displays the historical origin hashes and locators of the original captures. It does not reread workbooks or pages that the projection omits. Program evidence uses authored references instead of copied passages. The four included geometry captures still receive original-byte verification. See [data provenance](../DATA-PROVENANCE.json), [the included-input inventory](PROJECTION-INPUTS.json) and [source notices](../DATA-NOTICES.md).

## Saved cases and replay

A case binds to an evidence snapshot and to semantic claim references. The app refuses a case from different evidence before any analytical step runs. It keeps the saved file and the current browser case unchanged. It does not relabel historical sources or attach old finding notes to new claims.

The browser holds the case in page memory. The app does not save the case on the server or in browser storage, so a reload discards unsaved work. The browser builds a downloaded case file itself. It reads an opened case file in the page without uploading the file. Running or reopening a case still sends its plan and selections to the server, because the server calculates the results. See [privacy and security behavior](../PRIVACY.md).

Cases from earlier releases:

- Cases from the first hosted release, called R2, reopen at [haic-r2.millrace.ai](https://haic-r2.millrace.ai). The app offers that link when it refuses such a case. [The R2 replay guide](R2-REPLAY.md) covers the local `r2` profile, which needs the complete retained historical inputs.
- Cases from the earlier public snapshot reopen from [the published e2f2cf0 checkout](https://github.com/HAIC-2026/Millrace-AI/tree/e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4). Follow [the public33af replay guide](PUBLIC33AF-REPLAY.md).
- Cases saved with the earlier 20-measure public evidence, combined evidence identity `sha256:b1f06a08f8d61f5a5a15bf1f02c3ebf71c2e70a48442fe9f702a3cc837a28479`, reopen only on that exact release, Git commit `ac065bd83632c69ef77d55763bfb524068485c21`. The app names this route when it refuses such a file. Run that commit in a separate checkout and state directory, then open the saved file there:

  ```sh
  git clone https://github.com/HAIC-2026/Millrace-AI.git /absolute/new-ac065bd-replay
  git -C /absolute/new-ac065bd-replay checkout --detach ac065bd83632c69ef77d55763bfb524068485c21
  cd /absolute/new-ac065bd-replay
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --require-hashes -r requirements.txt
  HAIC_STATE_DIR=/absolute/separate-ac065bd-state HAIC_LOCAL_HTTP=1 PORT=8084 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8084 wsgi:application
  ```

  Open `http://127.0.0.1:8084`, choose the saved case file, inspect its preview, then replay it. On that release `/api/health` reports `investigation.snapshot_id` `sha256:b1f06a08…a28479`. Imported staff work still needs review before a brief. The operator also keeps a private exact archive of that release for restoration.

No notes or selections migrate between evidence snapshots. Start a blank case to use new evidence, including the 20 guided measures.

When a brief reply would exceed 90% of the response limit, it returns the complete selected brief, validation reviews and citations. The `steps`, `claims` and `responses` arrays are empty in that reply. Use `mode: run` to get the full findings for the plan.

## Optional AI configuration

In a source checkout the AI preview is off by default. To run it, an operator supplies four things:

1. `HAIC_LANGUAGE_ENABLED=1`.
2. `HAIC_LANGUAGE_PROFILE`, naming one profile from `districtbrief/ia_language_profiles.json`. The server refuses to start when the profile is missing or unknown.
3. The operator's own OpenAI API key, in a server secret file.
4. A finite spending budget record.

`districtbrief/ia_language_provider.py` and `districtbrief/ia_language_funding.py` define where the server reads the key and the budget record, and how it checks them. The server checks both before it sends anything to OpenAI. This repository contains no API key and no budget record.

The profile file fixes each profile's model, reasoning effort, service tier and token caps. It also fixes the per-token rates that the server uses for cost estimates. Each profile states the model, effort and tier that a response must report. The server rejects a response that reports anything else.

| Profile | Model and effort | Use |
| --- | --- | --- |
| `terra-medium` | `gpt-6.1-terra`, medium | The hosted preview |
| `terra-high` | `gpt-6.1-terra`, high | Comparison only. The hosted app does not use it |
| `sol-low` | `gpt-6.1-sol`, low | Tests only |

The preview's value-free catalog lists only the original 20 measures, in their original order, so its digest stays `sha256:cc6467496100f8aff2f54096b4f4daf798f296fe6e1e75403200d66df4cb00eb`. A plan profile with no measure list means those 20. When the draft or confirmed plan, the focused step or a selected finding uses one of the 20 guided measures, the server refuses the question with `guided_only_measure` before it builds a provider request, takes a rate-limit slot, reserves budget or reads the key. The plan, findings and selections stay as they were.

Fixed limits apply when the preview is on: 500 characters per question, one question at a time, and 3 questions in any rolling 300-second window for the whole site. Each start counts against the finite budget. When a limit or the budget is reached, the server refuses new questions and the guided controls keep working. If the preview is turned off, the app makes no model calls and keeps the spending record as it is.

## Controlled source refresh

The app never follows user-provided source URLs and never fetches live evidence during a request. [The separate source tools](../tools/sources/README.md) can create an unreviewed candidate for statistics and geometry.

- State workbooks need operator-supplied files. Only the fixed Census addresses in the tool's allowlist are fetched automatically.
- The tools validate source identity, file hashes, table labels, geography, annotations and geometry structure.
- The tools refuse incomplete or malformed captures. They never install an output.

A statistics or geometry refresh leaves program and administrative records unchanged. To refresh a program record, a reviewer rechecks the official page, updates the record and its checked date, and builds a new evidence snapshot. Review source changes, terms and analytical compatibility before you admit a new snapshot. Existing cases keep their original identities.

A complete refresh, from capture to a reviewed release, has not been run end to end for the current data. [The methodology](METHODOLOGY.md#10-freshness-and-refresh) lists the owner, the review triggers and a proposed cadence.

## Scope and reuse

Project-authored code is [MIT licensed](../LICENSE). Outside source material has separate terms. See [license scope](../LICENSE-SCOPE.md) and [source notices](../DATA-NOTICES.md). State portal terms create an unresolved commercial-use limitation for State-derived information. Obtain permission or replace the affected sources before a covered commercial use.
