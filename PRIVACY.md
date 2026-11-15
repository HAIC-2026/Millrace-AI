# Privacy and security

District Brief Builder uses public aggregate evidence and deterministic operations. It holds no resident or individual records and offers no resident lookup. Guided controls and Typed request make no model calls. The hosted app at haic.millrace.ai has language questions off and makes no model call.

## What stays in the browser

The browser holds cases, selections, staff edits and checklist progress in memory. Reloading discards unsaved work. The application uses no implicit case storage and no case-bearing URLs.

## What reaches the server

Typed requests reach the server for literal interpretation. Creating a reviewed brief sends active staff edits and checklist progress. The server renders the brief and does not persist those texts.

The server escapes staff text when it renders a brief. A Content Security Policy limits scripts, styles and connections to the app's own origin. Source addresses open the publisher's page in a new browser tab and send no referrer. The app itself never fetches them.

## Case files

Default case downloads exclude staff text, owners, dates, completion and tracking. Including staff work requires a preview. Downloads are unencrypted JSON. Users control saving and sharing. The app reads an opened case file in the page and does not upload it. Imports replay typed operations against matching evidence and versions. Saved factual text and HTML are not trusted. Reopened staff work needs review before a brief.

## Sessions and request limits

Anonymous session cookies separate requests without authenticating users. Production cookies use Secure, HttpOnly and SameSite=Strict and expire after 12 hours. Checks reject cross-origin submissions, duplicate keys, invalid Unicode and nonfinite numbers. JSON bodies have a 65,536-byte limit. Static files use a fixed allowlist.

## Logs

Rotated server metrics record bounded timing, status and operation metadata. Records exclude typed requests, staff work, cookies, session identifiers and IP addresses. Gunicorn access logging is disabled. The hosted app runs behind Cloudflare and a Caddy reverse proxy on AWS. Those layers can keep their own connection logs outside the application.

## Optional language questions

Language questions are disabled by default and off on the hosted app, which hides the question panel. If an operator admits and enables them, the **Ask a question** panel sends its bounded text and value-free plan/catalog context to OpenAI. It excludes staff notes, claim values, source bodies, case files and transcript history. Requests ask the provider not to store the response. The provider's own data policies still apply. Omit confidential or resident details. The application does not promise automatic removal of sensitive text. Staff review each proposal and choose **Use this proposal in the draft**. **Apply plan** runs it separately. Language accounting retains configuration, usage, reservations and settlements, and excludes prompts and provider bodies.

## Eligibility

Agencies determine eligibility and current availability. The prototype provides evidence and agency verification questions.
