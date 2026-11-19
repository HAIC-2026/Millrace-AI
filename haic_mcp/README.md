# HAIC MCP connector

A small MCP server that puts the public HAIC district-evidence engine behind five read-only tools. It uses the official Python MCP SDK (`mcp` 2.3.0) over Streamable HTTP at `/mcp`. Every call is stateless and deterministic, and nothing a caller sends is kept between calls.

The connector does not interpret questions itself and calls no model. A client model (for example ChatGPT) reads the engine's own interpretation rules, proposes one structured decision, and the engine's guards accept, clarify or refuse it. Facts come only from the engine's verified public snapshot.

## Hosted endpoint

```text
https://haic.millrace.ai/mcp
```

The endpoint needs no authentication and serves only public data. It runs connector source commit `2439110ac9523cdedbc35b9b55aeeb43607468c1` (build `sha256:b86b4e0a409766ab87b8f7624064ac1ad8f595135000e97674ec65501b043a9d`) over engine manifest `a3a8eb8d41504c7c05506c474df8dd82a493b4423df77905a99713d9d726bec3`. The `identity` that `prepare_question` returns shows these values. Later commits that change only documentation do not change what the endpoint runs.

The connector runs as a separate service on the AWS Lightsail host that serves District Brief Builder. Its public route moved from RunPod to this host on November 18, 2026 HST. Use the new URL when configuring a client. The [deployment notes](deploy/README.md) preserve the original RunPod procedure.

These checks passed against the AWS endpoint over public HTTPS on November 18, 2026 HST:

- `initialize` returned the server, and `tools/list` returned exactly the five tools.
- A prepared question ran through validation, a plan, source inspection and brief creation. An 80-claim run returned complete results.
- A fresh ChatGPT conversation used the AWS endpoint to build a Senate District 17 brief and show its workbook citations.

## Use it in ChatGPT

See the [District Brief Builder user guide](https://haic.millrace.ai/docs#chatgpt) for the quickstart. Custom MCP servers depend on your ChatGPT plan and workspace settings. A workspace admin can block them. The plugin was tested on ChatGPT on the web with a Pro account.

1. Open `https://chatgpt.com/plugins`.
2. Select the plus button, then **Add custom MCP server**.
3. Enter the name `HAIC District Briefs` and a description such as “Public Hawaiʻi district data and briefs.”
4. Enter the server URL `https://haic.millrace.ai/mcp`.
5. Select **No authentication**.
6. Read the risk notice and acknowledge it.
7. Select **Create as a plugin**.
8. Install the plugin. Open a new chat and @-mention the plugin with a question, such as "Compare senior poverty in House 28 with the State."

This creates a private custom plugin in your own account. It is not a listing in a public plugin directory.

Where your data goes:

- ChatGPT handles your question and its tool calls under your own ChatGPT account. Normal ChatGPT usage limits and data terms apply. The connector calls no model, and the maintainers pay for no model use.
- Cloudflare, AWS and the website's Caddy proxy handle the connection and may keep connection logs.
- The connector logs tool name, status and duration. See [Results, sources and privacy limits](#results-sources-and-privacy-limits) for its handling of questions and results.
- The engine uses only public data. Do not put confidential or resident details in a question.
- The connector keeps no state between calls. ChatGPT itself can remember earlier chats, for example through account memory. The connector cannot make ChatGPT forget them.

### Tested in ChatGPT

One account ran these natural questions against the original RunPod deployment on 2026-11-16, with the model selector set to Pro. ChatGPT did not show the underlying model ID. No numbers or decisions were supplied to the model. The results were checked against the pinned engine run directly.

| Question | Observed result |
| --- | --- |
| Senate District 17: population age 65 and over and senior poverty, with sources and a brief | The plan was shown before running. 10,462 ±795 people and 6.2% ±1.3 percentage points, with correct universes and period. The brief equaled the engine's canonical brief: both entries, citation hash, locators and all seven limitations. |
| Follow-up: compare senior poverty with the State | Same district kept. 6.2% ±1.3 vs 9.2% ±0.5, a district-minus-State difference of −3.0 percentage points. No derived margin of error or significance claim. |
| "District 12" with no chamber, in a new chat | ChatGPT asked House or Senate and gave no figures. |
| Seniors eligible for Kūpuna Care but not enrolled | Reported as unsupported. No count was invented. |
| A statistical significance test | The connector reported it as unsupported. No test statistic or p-value was given. ChatGPT separately used web search to explain the Census method in general terms. |
| Senate District 17: all 20 measures compared with Senate District 23, five programs and a Med-QUEST lead | The first request, which said "all five available programs", was refused as an ungrounded program. ChatGPT ran nothing and asked for the names. A reply naming the five programs then ran an 8-step plan with 72 claims. All 20 values and margins of error equaled the engine. Six rates and medians were differenced; fourteen counts were not. |

ChatGPT took from 20 seconds to about 3 minutes per answer. These are observations from one account, not a benchmark of model quality.

Limits of this test:

- ChatGPT's tool panel showed summaries, not the raw MCP arguments or results. Separate protocol checks cover the raw tool input and output.
- ChatGPT can use its own features alongside the plugin, such as web search and account memory. The plugin does not make ChatGPT answer only from these sources.

## Setup

Use CPython 3.11, the engine's runtime version, and a virtual environment outside the repository:

```sh
python3.11 -m venv /path/outside/repo/venv
/path/outside/repo/venv/bin/pip install --require-hashes --no-deps -r haic_mcp/requirements.lock
```

The lock pins the exact installed versions with every file hash PyPI publishes for each version.

Run from the repository root:

```sh
/path/outside/repo/venv/bin/python -m haic_mcp --port 8765
```

The server binds to `127.0.0.1` by default. It refuses any non-loopback `--host`. Host and Origin headers must match the loopback address and port. A tunnel or proxy name has to be added explicitly with `--allowed-host` and `--allowed-origin`. Nothing is exposed publicly by default. Startup prints one JSON line to stderr: the URL and identity on success, or a fixed failure reason. Startup fails closed on any failure.

## Startup verification

Before serving, the connector:

1. Checks `RELEASE-MANIFEST.json` against the SHA-256 pinned in `engine-pin.json`.
2. Stream-hashes every file the manifest lists, without parsing fixtures. It also recomputes the manifest's declared `source_identity`. Extra files are allowed, including this package.
3. Imports `districtbrief` from the same checkout. It then checks that every loaded engine module is a listed file there. Provider, job, funding, accounting, profile and website modules are never imported.
4. Builds the public `PublicPacket`, metadata, `Core` and `Investigation` as the website's public profile does. The engine's loaders verify the packet and metadata hashes. The profile is fixed; no client or environment variable can choose it.
5. Reads the provider's `PROMPT` from the verified source text by AST, without importing or executing it. The literal's hash and the exact `<RECIPE_NAMES>` replacement expression are pinned, and any other shape fails startup. The connector adapts the rules in two ways only. It replaces the function-call sentence with an instruction to return one decision to `validate_proposal`. It also wraps the rules so they apply only to the interpretation phase; later narration of engine results is not restricted by them.

## Identity and pin

`identity.engine` holds:

- the manifest SHA-256 and declared `source_identity`;
- the data, metadata and combined evidence snapshot IDs;
- the schema, operation and recipe versions;
- the input profile `public`.

`identity.connector` holds the name, version and a build digest over this package's code, `engine-pin.json` and `requirements.lock`.

Every call after preparation must send back the exact `identity`. Any release change, including a documentation-only change, therefore requires a new question.

Current pin (`engine-pin.json`): source commit `ec1f45c369dd5d1f127ddb0af14bd1871b90c839`, manifest SHA-256 `a3a8eb8d41504c7c05506c474df8dd82a493b4423df77905a99713d9d726bec3` (146 listed files), source identity `sha256:832f4346b1f5130a436314a7a71ad4d340a26763a9b1a0f56b2a750694fc1cbd`. To repin to another release, change `engine-pin.json`. If that release changes the provider `PROMPT`, also update `prompt_literal_sha256`, then rerun the tests.

## Tool flow

| Tool | Purpose |
| --- | --- |
| `prepare_question` | The user's question, verbatim. A first call needs nothing else. A follow-up adds the latest `next_context` and `identity`. Returns the canonical request, `provider_context`, the request-specific `decision_schema` and `interpretation_rules`. Returns no facts. |
| `validate_proposal` | Re-prepares the exact request on the server and converts one complete decision with the engine. Returns the normalized plan and changes, a clarification, or a refusal, plus a `proposal_digest`. |
| `run_plan` | Repeats validation, requires the same digest, then runs only the server-derived plan. There is no way to submit a bare plan. |
| `inspect_source` | `mode=catalog` takes `source_id` only. `mode=claim` takes a validated runnable bundle and an exact current `claim_ref`. `mode=source_intent` takes a validated `inspect_source` bundle. Comparison and hypothesis references expand to their leaf sources. A wrong or partial bundle is an error, never a catalog lookup. |
| `build_brief` | A validated runnable bundle, 1 to 8 exact claim refs and an optional action ref. Returns the engine's brief, without HTML, and a readable text version with numbered citations. |

A first question starts with fresh IDs at revision 0, `recipe_version` `custom/1` (a neutral required token), and no plan or selections. Nothing defaults to House 28 or to "my district".

Every successful result except a catalog lookup returns `next_context`:

- **Preparation, validation and source intent:** the validated request context, unchanged.
- **Fully successful run:** the executed plan becomes both the confirmed and the draft plan, and `recipe_version` becomes `<issue>/1`. Focus is kept only if its step remains. Only selections the engine reviewed as `retained` are kept. New claims start unselected.
- **Partial, unsupported or error run:** not promoted. The previous confirmed plan and its selections stay, and the attempt becomes the draft.
- **Next `prepare_question`:** keeps the case and branch IDs, mints a new request ID and adds one to the revision.

A brief applies the run rule, with the brief's own selections as the selections reviewed.

The proposal digest is SHA-256 over canonical JSON (sorted keys, no spaces, UTF-8, no NaN) of the request, decision, validated result and identity. It only checks that the bundle was copied unchanged. It is not authentication, consent or proof that the user saw the preview. One boundary rule applies before validation and hashing: a whole-number float `map_session` (`2024.0`) becomes the integer `2024`. `validate_proposal` returns the canonical decision to copy.

### Labeled evaluation scenario (synthetic; not live-model proof)

The user asks "Run the Older-adult support at home recipe for House 28." Then they select the returned comparison and ask "Why that figure?". The interpreter should return `status=propose`, `intent=inspect_source` and `focus_alias=selected_1` with the sentinel plan. `inspect_source` in `source_intent` mode then returns the House 28 and State leaf statistics with locators.

If instead the user asks "What is the senior poverty rate?", the server returns a chamber clarification even when the decision guessed a district. The client should ask the user. It must not rewrite the question to get past the clarification. The tests run these scenarios with hand-written decisions. Whether a live model follows the rules is not tested here.

## Results, sources and privacy limits

- **Run results.** Each claim keeps its canonical engine text, `claim_ref`, values, margins of error, units, universe, period, geography, caveat IDs (`C1`, `C2`, ...) and source IDs. Program claims also keep the engine's related district observations, with their estimates and MOEs, and the program's criteria summary. Comparison operands and dependencies are given as finding IDs of claims in the same result. Full normalized findings and locators come from `inspect_source`.
- **Sources.** Source answers are the bundled normalized projection with its historical hashes and locators. Original source bytes are not bundled or re-read; every leaf says `normalized_projection` and `cell_verified: false`. URLs are never fetched. Source records report how many items cite them (a count) instead of the full `cited_by` lists.
- **Briefs.** Staff edits, checklist edits and tracking are not accepted as inputs. Internally they are always `{}`, `[]`, `null` and `null`, so no staff review is implied. The text version is not a PDF and makes no printing claim.
- **Logging and storage.** The server logs one `{"tool", "status", "ms"}` line per call. Transport messages from the MCP SDK below ERROR level are suppressed, so rejected Host or Origin values are not logged. Questions, contexts and results are not logged or stored. Error messages are fixed text with no stack traces or echoed input.
- **Network and credentials.** The engine tools use no network, secrets or credentials.

## Size and concurrency bounds

| Bound | Value | Largest legitimate case measured |
| --- | --- | --- |
| HTTP request body | 128 KiB | 6.3 KB (follow-up with a full context) |
| Canonical tool arguments | 64 KiB | 5.2 KB (largest context object) |
| Complete MCP result, both channels | 256 KiB | 210,169 B on the wire (largest measured eight-step run, with eight selections) |

The largest measured run comes from an independent size search, which was not exhaustive: 80 claims and 395 KB of raw engine output, 204,827 B on the wire without selections. A typical eight-step run is 172,001 B. Other measured results: a first preparation is 37 KB, a full-context preparation 54 KB, the largest claim source lookup 51 KB and a brief 27 KB. These are the largest cases measured, not a proven maximum.

A larger result is refused as a whole with `result_too_large` and is never clipped. A smaller plan then fits. All engine work runs under one lock, with at most two waiting calls. Beyond that, a call is refused at once with `busy` and a retry hint. There is no unbounded queue, distributed rate limit or wallet. Python work that has started is not cancelled by a proxy timeout.

## Tests

```sh
HAIC_MCP_TEST_TMP=/path/outside/repo/tmp \
/path/outside/repo/venv/bin/python -B -m unittest discover -s haic_mcp/tests -t .
```

The tests run against the real engine and need no credentials. They cover:

- startup integrity and tamper cases on private copies: byte drift, missing files, manifest edits, repinned documentation-only releases, source identity, PROMPT AST drift, other-checkout modules and post-start drift;
- a hostile language environment with networking blocked;
- interpretation-rule fidelity, checked against the provider's own `PROMPT` in a separate test process;
- guard cases written for this connector;
- digest and stale, foreign or tampered references;
- context continuation, partial runs and recovery;
- source leaves for comparisons and hypotheses, and brief parity with numbered citations;
- busy and interleaved calls;
- all 76 districts with both recipes, compared with direct engine runs and briefs;
- real loopback MCP initialize, list and call for all five tools with the SDK client, including errors, Host/Origin/body bounds and payload measurements.

## Not yet verified

- The ChatGPT test covers the six questions above from one account. It is not a broad accuracy or model-quality evaluation. Other questions, models and accounts are untested.
- ChatGPT's largest tested run had 72 claims. The 80-claim, 210 KB result is tested only at the protocol level, because ChatGPT does not show result sizes.
- `GET /mcp` still opens a server-sent event stream. Whether ChatGPT uses that stream is unknown.
- The original RunPod deployment went through a few restarts. The AWS endpoint has had functional checks. Long-running availability and load remain untested.

## License

The MIT license in [`LICENSE`](../LICENSE) covers project-authored code and documentation. It does not cover outside source data. Read [`LICENSE-SCOPE.md`](../LICENSE-SCOPE.md) and [`DATA-NOTICES.md`](../DATA-NOTICES.md) before reusing data. State-derived information has an unresolved commercial-use limitation.
