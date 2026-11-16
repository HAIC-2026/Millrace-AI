# HAIC MCP connector

A small MCP server that puts the public HAIC district-evidence engine behind five read-only tools. It uses the official Python MCP SDK (`mcp` 2.3.0) over Streamable HTTP at `/mcp`. Every call is stateless and deterministic, and nothing a caller sends is kept between calls.

The connector does not interpret questions itself and calls no model. A client model (for example ChatGPT) reads the engine's own interpretation rules, proposes one structured decision, and the engine's guards accept, clarify or refuse it. Facts come only from the engine's verified public snapshot.

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

The largest measured run comes from an independent size search, which was not exhaustive: 80 claims and 395 KB of raw engine output, 204,827 B on the wire without selections. A typical eight-step run is 172,001 B. Other measured results: a first preparation is 37 KB, a full-context preparation 54 KB, the largest claim source lookup 51 KB and a brief 27 KB. These are the largest cases measured, not a proven maximum. A larger plan can still be refused as a whole with `result_too_large`, and the fix is a smaller plan.

A larger result is refused with `result_too_large` and is never clipped. All engine work runs under one lock, with at most two waiting calls. Beyond that, a call is refused at once with `busy` and a retry hint. There is no unbounded queue, distributed rate limit or wallet. Python work that has started is not cancelled by a proxy timeout.

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

- No ChatGPT account, custom connector, hosted endpoint, HTTPS tunnel or live-model run has been tested. This local proof is not ChatGPT proof.
- How well a model follows `interpretation_rules`, and how ChatGPT handles results of 170 to 210 KB, are both unmeasured.
- Exposing the server beyond loopback needs a separately authorized HTTPS endpoint and explicit `--allowed-host` and `--allowed-origin` values.
