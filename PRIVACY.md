# Privacy and security

District Brief Builder uses public aggregate evidence and deterministic operations. It holds no resident or individual records and offers no resident lookup. Guided controls and Typed request make no model calls. The hosted app at haic.millrace.ai runs optional language questions as an experimental AI preview. They call an OpenAI model. See [optional language questions](#optional-language-questions).

## What stays in the browser

The browser holds cases, selections, staff edits and checklist progress in memory. Reloading discards unsaved work. The application uses no implicit case storage and no case-bearing URLs. Changing a plan that has already run opens a new context in the page and leaves the earlier context unchanged. Staff notes move to the new context only if you choose to copy them.

## What reaches the server

Each run, replay or brief sends the plan and your selected findings and agency action so the server can calculate results and render the brief; it does not store them. Typed requests reach the server for literal interpretation. Data catalog filters and search text reach the server in the request address so it can return matching rows. They are not sent to OpenAI. Creating or refreshing a brief sends active staff edits and checklist progress. The server renders the brief and does not persist those texts.

The server escapes staff text when it renders a brief. A Content Security Policy limits scripts, styles and connections to the app's own origin. Source addresses open the publisher's page in a new browser tab and send no referrer. The app itself never fetches them.

## Case files

Default case downloads exclude staff text, owners, dates, completion and tracking. Including staff work requires a preview. Downloads are unencrypted JSON. Users control saving and sharing. The app reads an opened case file in the page and does not upload it. Imports replay typed operations against matching evidence and versions. Saved factual text and HTML are not trusted. When a file holds staff notes, the app opens them only if you choose to. Reopened staff work needs review before a brief.

## Sessions and request limits

Anonymous session cookies separate requests without authenticating users. Production cookies use Secure, HttpOnly and SameSite=Strict and expire after 12 hours. Checks reject cross-origin submissions, duplicate keys, invalid Unicode and nonfinite numbers. JSON bodies have a 65,536-byte limit. Static files use a fixed allowlist.

## Logs

Rotated server metrics record bounded timing, status and operation metadata. Records exclude typed requests, catalog search text, staff work, cookies, session identifiers and IP addresses. Gunicorn access logging is disabled. The hosted app runs behind Cloudflare and a Caddy reverse proxy on AWS. Those layers can keep their own connection logs outside the application. Connection logs can include IP addresses and requested addresses, which can contain catalog filters and search text.

## Optional language questions

Language questions run on the hosted app as an experimental AI preview. The hosted app restored the preview on November 16, 2026 (HST). After a rollback to the earlier guided release they are off, and nothing is sent to OpenAI. They are off in a source checkout unless an operator enables them. Each question that the server admits is sent to OpenAI's Responses API, model `gpt-6.1-terra`, as raw text exactly as typed. The server refuses some questions locally and sends nothing, for example a question over 500 characters or one that arrives when a limit or the budget is reached. With an admitted question goes selected public context: the current and draft plan, the admitted district, measure, program and source identifiers and labels, and the selected findings as references without their values. The app does not add staff notes, finding values, source bodies, case files, cookies, case identifiers or earlier questions. Anything you type in the question is sent. The app cannot detect or remove sensitive text you type. Omit confidential or resident details.

Requests ask OpenAI not to store the response. OpenAI's own data policies still apply, and this app makes no zero-data-retention claim. The model only proposes a plan, a clarifying choice or a refusal. It never states a figure. The server checks each proposal against the allowed operations and sources before the app uses it. The app runs a clear, supported proposal at once on the bundled data and keeps earlier work. It shows a proposal for review first in these cases, among others:

- The proposal would change the district.
- The proposal adds a district comparison that the question did not name with House or Senate.
- The question says "my district".
- Running the proposal would affect unapplied plan edits, brief selections or staff notes.

You can edit or replace the plan afterwards. The app's deterministic operations compute every figure.

The app does not log question text, model responses or proposals. Server metrics keep only bounded timing and status metadata. Separate operator evaluation runs use authored test questions, never visitor questions, and can write private diagnostic files on the server. Language accounting keeps the model profile, token usage, a hash of each request, reservations and estimated costs. It excludes question text, prompts and provider bodies. Each start counts against a finite shared spending budget and fixed rate limits.

## Eligibility

Agencies determine eligibility and current availability. The prototype provides evidence and agency verification questions.
