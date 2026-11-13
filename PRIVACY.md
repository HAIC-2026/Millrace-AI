# Privacy and security

District Brief Builder uses public aggregate evidence and deterministic operations. It makes no application model calls and sends no requests to a model provider.

The browser holds cases, selections, staff edits and checklist progress in memory. Reloading discards unsaved work. The application uses no implicit case storage or case-bearing URLs. Typed interpretation requests reach the server. A reviewed brief request also transmits active staff edits and checklist progress. The application does not persist those texts.

Default case downloads exclude staff-origin text, owners, dates, completion and tracking. Including staff work requires an explicit preview. The resulting JSON is unencrypted. Users control where downloads are saved and shared. Imports replay typed operations against the exact evidence snapshot and versions. They do not trust saved factual text or HTML.

Anonymous session cookies separate in-process requests and result references. They do not authenticate users. Production cookies use Secure, HttpOnly and SameSite=Strict. Request checks reject cross-origin submissions, duplicate keys, invalid Unicode and nonfinite numbers. JSON bodies are limited to 65,536 bytes. Static files use a fixed allowlist.

The server records bounded operational timing, status and operation metadata in rotated local metrics. Those records exclude typed requests, staff work, cookies, session identifiers and IP addresses. Gunicorn access logging is disabled. Hosting infrastructure may maintain separate logs. Operators must review those settings separately.

Do not enter confidential constituent information. This prototype provides evidence and agency verification questions. Agencies determine eligibility and current service availability. The actual spoken VoiceOver journey remains unverified.
