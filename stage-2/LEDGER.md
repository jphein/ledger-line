# LEDGER — pocketful stage 2

Sources: `/home/jp/band/dark-factory-wearedevs/pocketful/spec/stage-2.md` (adds to) and
`stage-1.md` (still applies). Stage 2 lines are numbered from 200 so they never collide with the
carried-forward stage 1 lines, which follow at the end of this file unchanged unless amended here.
Item tags: `[X1]` copy + stage-1 carry-over fix + authorizations API, `[X2]` UI shell, auth
screens, wallet home (balance, pay, request, feed, refresh, uncertainty), `[X3]` requests,
split and authorizations screens, product/visual quality, upgrade-in-browser.

## Stage 2 requirements

### Delivery [X1]
- R-200 (amends R-01: the Dockerfile, RUN.md and build command live in and build from `stage-2/`) `stage-2/` is a copy of `stage-1/` (no `.git`), extended; nothing under `stage-1/` changes. stage-2 still satisfies every carried-forward stage 1 line (R-00..R-101, I-01..I-08, S-01..S-24) except where amended below.
- R-201 Every UI asset (CSS, JS, fonts, icons) is served from the image; no CDNs, no external fonts or scripts.
- R-202 Carried-forward defect from stage 1, now required: S-23 "Large-fixture reset (1000 users) completes under 10 s" measured **in the 2 vCPU / 2 GiB container** (stage 1 measured 14–18 s there).

### Holds model and API changes [X1]
- R-203 "The sum of all wallet `total` values always equals the total seeded by the last reset. A hold moves no money; payments, settlements and captures transfer money between wallets."
- R-204 "`available = total − held` must never be negative. Held funds cannot fund new payments, authorizations or settlement net debits. Captures may spend the money reserved for them."
- R-205 "Cumulative captures must not exceed the authorized amount. Each idempotent capture moves money once. A closed hold cannot be captured again."
- R-206 `GET /me` -> `{user_id, display_name, handle, balance, total, available, held, currency, minor_units}`; "`balance` and `total` are always equal. `held` is the sum of open holds, and `available` is `total − held`, never negative." With no open holds "every earlier behaviour is unchanged".
- R-207 "`POST /payments` remains an immediate transfer. It must not leave an intermediate hold or require a separate capture."
- R-208 "Every `409 insufficient_funds` in stage 1 — on `POST /payments`, `POST /requests/{id}/pay` and settlements — is now evaluated against `available`." Settlement affordability: every wallet's `total + net − held ≥ 0`.
- R-209 "Paying a request remains immediate. Authorizing a request is out of scope." "`POST /splits` is unchanged."
- R-210 "There are now seven idempotent write paths: stage 1's five, authorizations and captures. The same replay rules apply independently to each."
- R-211 Every payment body carries `authorization_id` (null unless created by a capture); `request_id` semantics unchanged; `settlement_id` stays.

### Fixture [X1]
- R-212 `authorization_ttl_seconds` "applies to every authorisation created through the API. It defaults to 600 when omitted. If supplied, it must be a positive integer number of seconds." (else reset 422 `validation_failed`, change nothing)
- R-213 Fixture `authorizations` array: `{id, from_user_id, to_user_id, amount, note, visibility, status, expires_at}`; "Seeded authorisations carry their own absolute `expires_at`". "An earlier fixture may omit `authorizations` altogether; omission means an empty list."
- R-214 "A user's seeded `balance` is still `total`. **`available` is derived, never seeded**".
- R-215 "A sum of seeded unexpired open holds larger than that user's `balance` is a reset error: `422 validation_failed` from `POST /_test/reset`, changing nothing".
- R-216 "Seeded `status` is `open`, `captured`, `voided` or `expired`. Only `open` holds anything."

### Expiry [X1]
- R-217 "An authorization whose `expires_at` is at or before now is `expired` and holds no funds. Reads and writes must reflect expiry even if no request occurred at the deadline." `GET /authorizations` shows `status: "expired"`; `GET /me` includes the released remainder in `available`. A seeded open hold with past `expires_at` is expired from reset.
- R-218 "Void and expiry can close a partially captured authorization, release only the remainder, and preserve all capture records."

### `POST /authorizations` [X1]
- R-219 Idempotency-Key required; caller is payer; body `{to_handle, amount, note?, visibility?}`, same defaults as payments -> 201 `{authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount (0), remaining_amount, payment_ids ([]), currency, note, visibility, status ("open"), expires_at, payment_id (null), created_at}`. "`expires_at` is `created_at` plus `authorization_ttl_seconds`."
- R-220 Errors: available below amount -> 409 `insufficient_funds`; amount <1, >1000000000, non-integer -> 422; own handle -> 422 `self_payment`; note >200 or bad visibility -> 422; unknown handle -> 404.
- R-221 "An open authorisation is **not** a feed item and never appears in `GET /activity`."

### `POST /authorizations/{id}/capture` [X1]
- R-222 Idempotency-Key required; "Only the receiver (the `to` party) may capture." Body `{amount?, final?}`; `amount` defaults to the remaining amount; "`{}` and `{"amount": 2000}` are different JSON values … reusing a key across the two is 409 `idempotency_key_reuse`".
- R-223 Returns 201 with the created payment in exactly the `POST /payments` shape, `authorization_id` set, `request_id: null`; amount = captured amount; note and visibility copied from the authorisation; appears in the feed by the ordinary rule.
- R-224 Default (final): authorisation becomes `captured`, carries `captured_amount` and `payment_id`, and "releases the uncaptured remainder immediately" in the same step. A second capture after a final capture -> 409 `authorization_not_open`.
- R-225 Extended mode `{"amount": 700, "final": false}`: `final` is boolean, default `true`; with an uncaptured remainder status stays `open`; further captures allowed up to the remainder; "Capturing the entire remainder closes it even with `final: false`." "A final capture closes it and releases any remainder."
- R-226 "`capture_exceeds_authorization` compares with the **remaining** amount; omitted amount defaults to that remainder. `captured_amount` is cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order. Every authorization response adds `remaining_amount`: the amount still held, zero when closed."
- R-227 "New fields do not change idempotency body equality." Request-body equality stays raw JSON-value equality: `{"amount":700}` vs `{"amount":700,"final":true}` -> 409 `idempotency_key_reuse` (like `{}` vs `{"amount":2000}`); "new fields" are the added response fields, which never change a stored replay body.
- R-228 Capture errors: not `open` -> 409 `authorization_not_open`; `expires_at` at or before now -> 409 `authorization_expired`; amount above remainder -> 422 `capture_exceeds_authorization`; amount <1 or non-integer -> 422 `validation_failed`; caller not receiver (incl. third parties) -> 403; unknown -> 404.

### `POST /authorizations/{id}/void` [X1]
- R-229 "Only the payer may void"; no idempotency key; 200 with the authorisation, `status: "voided"`, hold released; voiding a voided one -> 200 current state; `captured` or `expired` -> 409 `authorization_not_open`; non-payer (incl. third parties) -> 403; unknown -> 404.

### `GET /authorizations` [X1]
- R-230 Only authorisations where the caller is payer or receiver; newest first by `created_at`; `direction` `outgoing` (caller is payer) / `incoming` (caller is receiver) / absent; `status` one of four or absent ("An authorisation expired by the clock matches `expired`, never `open`"); unknown values 422; `limit`/`offset`/`has_more` exactly as `GET /requests`; response `{"authorizations": [...], "has_more": bool}`.

### Upgrade [X1 API, X3 browser]
- R-231 "A stage-2 service must accept an export produced by the same team's stage-1 service." Tokens, accounts, balances, pending requests, idempotency records survive; a stage-1 export has no authorizations (empty).
- R-232 "A browser signed in before that export/import upgrade must remain signed in afterwards. Existing pending requests remain payable through the request screen. A payment whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original payment and refresh the imported balance." "No page reload or new screen is required. The form and pending retry identity must survive the upgrade." [X3]
- R-233 Stage-2 export/import round-trips authorizations (status, captures, payment_ids, expires_at), ttl, and every stage-1 item.

### Concurrency [X1]
- R-234 "Concurrent requests must produce the same results as executing them one at a time in some order, and the requirements above hold at every read."

### Routes and negotiation [X2]
- R-235 Screens reachable by URL: `/` (balance, pay form, request form, activity feed), `/requests`, `/split`, `/signup`, `/login`; `/authorizations` added. Other screens reachable through the UI.
- R-236 "The browser and the API share `/requests`. Return the UI for `Accept: text/html`; API requests without that header receive JSON." Same for `/authorizations`. The UI's own API calls must not send `Accept: text/html`.
- R-237 Every element found by its exact `data-testid`.

### Signup / login [X2]
- R-238 testids `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; `login-email`, `login-password`, `login-submit`; `auth-error` "Present only when there is one"; `current-user` "Visible on every screen when signed in. Text contains the display name"; `current-handle` "Text is exactly the caller's handle, with no `@` and no surrounding words"; `logout-button`.

### Wallet home `/` [X2]
- R-239 `wallet-balance` "Text is exactly the formatted amount. Carries `data-amount="{minor units}"`" (formatted `total`).
- R-240 `pay-handle`, `pay-amount` (decimal string, e.g. `15.00`), `pay-note`, `pay-visibility` (select, option values `public`/`private`), `pay-submit`, `pay-error` "when the payment is refused — including insufficient funds".
- R-241 `request-handle`, `request-amount`, `request-note`, `request-submit`, `request-error` "when the request is refused".
- R-242 "Keep the pay form's values after success. Submitting it again without changing a field must not send another payment: `wallet-balance` falls once, the feed contains one payment and `pay-error` is absent. Changing a field makes the next submission a new payment request. Retries follow §7."
- R-243 Formatted amount: "the decimal with exactly `minor_units` decimal places, a single space, then the currency code: `100.00 EUR`. For a `minor_units` of `0` there is no decimal point at all: `1200 JPY`." (BHD: `1.250 BHD`; `5` minor units at 2 -> `0.05 EUR`.) No grouping separators, no sign, no locale formatting (`Intl.NumberFormat`/`toLocaleString` forbidden for money); format from the integer with string arithmetic, never floats.
- R-244 Decimal input: "`15.00` and `15` both submit `1500`; `15.5` submits `1550`. Nonnumeric input or more than `minor_units` decimal places must show the form's error element without sending a request. For example, `15.005` is rejected rather than rounded." Applies to pay, request, split, authorize and capture inputs.

### Activity feed [X2]
- R-245 `activity-list` children newest first in the DOM; `activity-item-{payment_id}` per visible payment with `data-visibility`; `activity-parties-{id}` contains both handles; `activity-amount-{id}` exactly the formatted amount; `activity-note-{id}` exactly the note, "Present even when the note is empty"; `empty-activity` "Shown instead of the list when nothing is visible". Equal timestamps may be in either order.

### Refresh and competing clients [X2]
- R-246 "After any successful action, the balance, the feed and the request lists on the same page must show the new state without a manual reload. Navigation must wait for the write to succeed before it refreshes the data."
- R-247 `wallet-refresh` button on `/` refreshes balance and feed "without clearing the pay form. **Latest refresh wins:** a delayed earlier read must not overwrite a later refresh, including when responses arrive out of order." Applies to available and held too.
- R-248 "A refused payment shows `pay-error`, refreshes the balance/feed, and preserves all pay inputs."
- R-249 "If a payment response is lost, including after `POST /payments` commits, show `pay-uncertain` (nonempty text), not `pay-error`. Keep the unchanged form retryable with the **same key and body**. Successful retry removes both error/uncertainty elements, refreshes the balance and feed, and moves money exactly once. Unknown outcomes are not confirmed rejections."
- R-250 "No background polling, live synchronization, or recovery across page reloads is required."

### Requests screen [X3]
- R-251 `incoming-list`, `outgoing-list`; `request-item-{id}` with `data-status`; `request-amount-{id}` exactly formatted; `request-pay-{id}` and `request-decline-{id}` only on a pending incoming request; `request-cancel-{id}` only on a pending outgoing request; `request-error` when a pay/decline/cancel is refused; `empty-requests` when both lists are empty.
- R-252 "A request cancelled elsewhere while its pay button is visible must show `request-error` when payment is refused and refresh the request list so the stale pay button disappears."

### Split screen [X3]
- R-253 `split-amount` (decimal, pay-amount rule), `split-handles` (comma-separated, in order), `split-note`, `split-submit`, `split-preview` with one `split-share-{handle}` per participant (exactly formatted share), `split-error`.
- R-254 "`split-preview` must show the shares the server would compute, by the rule in `stage-1.md` §9, before anything is posted. The preview and submitted split must have identical shares."

### Authorizations UI [X3]
- R-255 `wallet-balance` = formatted `total` with `data-amount`; `wallet-available` formatted `available` with `data-amount`, "Present this as the headline number"; `wallet-held` formatted `held` with `data-amount`, "Absent when `held` is zero".
- R-256 Authorise form on `/`: `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` ("Same input rules as the pay form"); `authorize-error` when refused, including insufficient available funds.
- R-257 `/authorizations`: `authorization-list` children newest first; `authorization-item-{id}` with `data-status`; `authorization-amount-{id}` exactly formatted authorised amount; `authorization-captured-{id}` "Present only when `status` is `captured`"; `authorization-expires-{id}` "Text is the RFC 3339 `expires_at`"; `authorization-capture-amount-{id}` decimal input "pre-filled with the remaining amount. Present only on an incoming `open` authorisation"; `authorization-capture-{id}` only on incoming open; `authorization-void-{id}` only on outgoing open; `authorization-error` when a capture or void is refused; `empty-authorizations` when the list is empty.
- R-258 "The UI must reflect seeded and newly created holds. Show available funds as the user's spending balance, including immediately after reset with open holds."

### Product and visual direction [X3, applies to all screens]
- R-259 "coherent, presentation-ready consumer finance product, not a test harness with controls attached"; "calm, trustworthy character".
- R-260 "Available funds must be the clearest monetary value once holds exist, with total and held funds visibly secondary."
- R-261 "Payments, requests, splits and authorisations should be easy to scan, and status, direction, privacy and money movement should be understandable without interpreting raw API data."
- R-262 "consistent visual system for typography, spacing, colour, controls and feedback. Primary actions must be easy to identify."
- R-263 "Available, held, pending, loading, successful, refused and uncertain states must be visually distinct as well as satisfying the behavioural requirements below".
- R-264 "Format people, amounts and timestamps for people first; expose technical identifiers only where they help the user." (display names / handles, formatted money, human dates; `authorization-expires` keeps RFC 3339 text per R-257)
- R-265 "clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling."
- R-266 "Inputs need visible labels, keyboard focus must be apparent, and text and controls need sufficient contrast." (WCAG AA 4.5:1 for text)
- R-267 "Provide considered empty, loading and error states, and keep navigation consistent across the required routes."

## Stage 2 invariants (black-box observable)
- I-200 Σ `total` over all users == Σ seeded balances after any storm including authorize/capture/void/expiry.
- I-201 `available ≥ 0` and `available == total − held` at every read, including during storms of payments, authorisations, captures and settlements against one wallet.
- I-202 Σ captures of one authorisation ≤ its amount; concurrent captures with different keys never over-capture; concurrent identical captures -> one 201, rest 200, one payment.
- I-203 Concurrent capture vs void on one open authorisation: outcomes match some serial order (either the capture succeeds and void then 409/voids the remainder, or void wins and capture 409).
- I-204 After expiry, `held` drops and `available` rises without any write request.
- I-205 UI: double-submitting the unchanged pay form moves money once (one payment in feed, balance falls once).

## Stage 2 silent requirements
- S-200 The UI's fetches to `/requests` and `/authorizations` must request JSON (no `Accept: text/html`), or they get HTML.
- S-201 Browser `Accept` for navigation includes `text/html` among others (`text/html,application/xhtml+xml,...`): negotiate on "contains text/html", not equality.
- S-202 Pay form idempotency key is kept per unchanged form contents; changing any field (handle, amount, note, visibility) mints a new key; a refused (4xx) payment's key may be reused (§7) but a changed field still mints a new one.
- S-203 Lost response = network error or no response (fetch rejects, timeout, 5xx-like); a 4xx with an error body is a confirmed refusal (pay-error), anything else is uncertain (pay-uncertain).
- S-204 Retry of an uncertain payment after import returns 200 with the original payment (idempotency record survived import) and the UI treats 200 as success.
- S-205 `authorization-expires-{id}` text is the raw RFC 3339 string exactly as the API returns it.
- S-206 Capture default amount pre-fill is the remaining amount formatted as a decimal input (e.g. `20.00`).
- S-207 `wallet-held` absent (not just hidden or zero) when held is 0; `auth-error`, `pay-error`, `pay-uncertain` absent when there is none.
- S-208 `current-handle` text has no `@`; `current-user` on every signed-in screen, including `/requests`, `/split`, `/authorizations`.
- S-209 Capture `final` of wrong type (e.g. `"false"`) -> 400 `malformed_request`; `amount: null`? -> 422 (amount rule).
- S-210 Expiry boundary: `expires_at == now` is expired; ttl of 1–2 s in a fixture expires on time on reads with no writes.
- S-211 Seeded expired-by-clock open holds are excluded from the R-215 sum ("unexpired open holds").
- S-212 After logout, protected screens send the user to login (no stale `current-user`).
- S-213 Unauthenticated visit to `/`, `/requests`, `/split`, `/authorizations` shows or redirects to login, never a raw JSON 401.
- S-215 A 1000-user fixture with all-distinct passwords resets in < 10 s in the 2 vCPU container (over HTTP).
- S-216 ttl=1 in the fixture: authorise then capture immediately -> 201; capture after 1.5 s -> 409 `authorization_expired`.
- S-217 Fixture authorisation validation: unknown from/to user, from == to, amount outside 1..1000000000 or non-integral, bad visibility/status, non-RFC 3339 `expires_at`, duplicate id, non-positive/non-integral `authorization_ttl_seconds` -> 422 `validation_failed`, nothing changed. Seeded `captured` without `captured_amount` defaults per D-206.
- S-214 A stale request pay button (request cancelled elsewhere) -> `request-error` and the list refreshes (R-252); same pattern for a stale capture/void button -> `authorization-error` and refresh.

## Stage 2 boundary
- Stage 3 anything. Authorising a request. Background polling, live sync, recovery across page reloads. Migration during an in-flight request. Custom illustration or brand assets.

## Stage 2 decisions
- D-200 UI: server-served static HTML shells plus one same-origin JS file per screen (or one shared), plain CSS, no build step; the JS calls the JSON API with the bearer token kept in `localStorage`, so a stage-1 token stays valid in the browser across import (R-232). HTML shells need no auth; JS redirects to `/login` when no/invalid token.
- D-201 Content negotiation: a GET whose `Accept` contains `text/html` on `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` serves HTML; otherwise the API (JSON). `/`, `/split`, `/signup`, `/login` have no JSON API — non-HTML requests to them keep stage 1 behaviour (404 JSON).
- D-202 Expiry is evaluated lazily on every read and write under the lock using the current clock; an open authorisation with `expires_at ≤ now` is treated as `expired` everywhere (and may be persisted as expired). Held = Σ remaining of effectively-open authorisations.
- D-203 Capture order: auth 401 -> body JSON object 400 -> key 400/422 -> claimed-key resolution -> field rules (`amount` 422 rules, `final` non-bool 400) -> 404 -> 403 -> status: voided/captured 409 `authorization_not_open`, expired (clock or seeded) 409 `authorization_expired` -> 422 `capture_exceeds_authorization` -> effect. The capture amount is checked for type, integral value and ≥ 1 only (spec row: "below 1, or not an integer"); anything above the remainder, including > 1000000000, is `capture_exceeds_authorization`, and that check comes after the status checks.
- D-204 Void order: 404 -> 403 -> voided 200 current -> captured/expired 409 `authorization_not_open` (spec: "A `captured` or `expired` one is `409 authorization_not_open`") -> void. Capture on expired gives `authorization_expired` (D-203); these two are intentionally different.
- D-205 (revised) Authorisation `created_at`/`expires_at` are emitted as RFC 3339 with milliseconds (e.g. `2026-09-24T13:10:00.123+00:00`); `expires_at = created_at + ttl` exactly and the real lifetime equals the ttl (no truncation).
- D-206 Authorisation responses always include `captured_amount`, `remaining_amount`, `payment_id`, `payment_ids`. Seeded authorisations may omit `captured_amount` (0), `payment_id`/`payment_ids` (null/[]).
- D-207 Export keeps `format_version: 1`; import accepts a stage-1 state (no authorizations, no ttl) and fills defaults (empty, 600).
- D-208 S-23 fix (revised after challenge): (a) measure the cause in the 2 vCPU container first (does hashlib.scrypt on python:3.12-alpine run in parallel / release the GIL; per-hash cost); (b) choose cost parameters so **1000 distinct passwords** reset in < 10 s in the container over HTTP; (c) keep per-user salts. Dedup of identical passwords is allowed only as an optimisation, stored per user as `sha256(user_salt ‖ scrypt(pw, shared_salt))` so records never reveal equal passwords.
- D-209 Pay form: the JS keeps `{key, body}` for the current form contents; it reuses the key while the canonical body is unchanged (including after success, so a resubmit is a 200 replay and moves nothing) and mints a new key (`crypto.randomUUID`, fallback random) when any field changes.
- D-211 Imported stage-1 payments carry `authorization_id: null` on every read (feed, capture shapes); stored stage-1 idempotency responses replay exactly as stored (§7 "body identical to the original response"), never rewritten.
- D-212 `GET /authorizations` envelope key is `"authorizations"` (our choice, by analogy with `requests`/`payments`).
- D-213 Decimal inputs: trim surrounding whitespace; accept only `^\d+(\.\d{1,mu})?$` (no dot at all when mu=0); so `15.`, `.5`, `1e3`, `-1`, `1,5`, `+1` and empty are rejected with the form's error element and no request. Parse with integer/string arithmetic; never `parseFloat`.
- D-214 Visual proxies (measured by the prover, judged with auditor screenshot review): R-265 `document.documentElement.scrollWidth <= innerWidth` on every required route at 375 px and 1280 px; R-266 every input has an associated `<label>`, `:focus-visible` has a visible outline, palette text contrast ≥ 4.5:1; R-260 `wallet-available` has the largest font size of any money on `/` when holds exist; R-263 each listed state maps to a distinct CSS class documented once in the stylesheet.
- D-210 Refresh: each refresh carries a monotonically increasing sequence number; a response is applied only if its sequence is the latest issued (latest refresh wins).

## Stage 2 work items (every stage-2 line belongs to exactly one)
- X1 Copy + S-23 fix + holds/authorizations API + upgrade import: R-200..R-234 (R-232 browser half goes with X3), I-200..I-204, S-209..S-211, S-215..S-217, D-202..D-208, D-211, D-212. Also re-proves all carried-forward stage 1 lines on stage-2/.
- X2 UI shell, auth screens, wallet home, feed, refresh, uncertainty: R-235..R-250, S-200..S-203, S-207, S-208, S-212, S-213, I-205, D-200, D-201, D-209, D-210, D-213.
- X3 Requests, split, authorizations screens, product/visual quality, upgrade in browser: R-232 (browser), R-251..R-267, S-204..S-206, S-214, D-214.

## Decision log (stage 2)
- 17:36 Auditor challenge merged (13 points): D-208 rewritten (distinct passwords, per-user salts, measured in container), D-205 milliseconds, D-203 capture amount rule, D-204 quote, D-211..D-214, S-215..S-217, R-200 amends R-01, R-227/R-243/R-263 sharpened.
- 17:35 Ledger written; stage 1 ledger carried forward below. Stage 1 judged revision d0b69b4 passed 440/441 of the prover suite; S-23 failed in the container (14–18 s) → R-202 makes it a stage 2 requirement, fix D-208.

---

# Carried forward: stage 1 ledger (unchanged; amended only where a stage 2 line says so)

Quoted words come from the spec. Item tags: `[W1]` runtime/reset/auth/me/errors,
`[W2]` payments/requests/idempotency/activity, `[W3]` splits/settlements/export-import.

## Requirements

### Delivery and runtime (§2, §3) [W1]
- R-00 "Source code, API documentation and schemas from existing products in this domain must not be used."
- R-01 Deliver "an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup", all inside `stage-1/`.
- R-02 "The image must run on its own with `-e PORT=<port>` and a port mapping." No outbound network at run time; every runtime dependency is in the image.
- R-03 "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`."
- R-04 `GET /health -> 200 {"status": "ok"}` within 60 s of container start (2 vCPU, 2 GiB).
- R-05 Up to 50 requests in flight; each answered within 5 s (10 s for `POST /_test/reset`, `GET /_test/export` and `POST /_test/import`: "Test control calls have a 10-second timeout.").
- R-06 `POST /_test/reset` with a fixture body -> `204 No Content`; "Replace all service state with the fixture". "When reset returns 204, subsequent requests must see only that fixture. Repeated resets are supported." No authentication.
- R-07 Requests and responses are `application/json; charset=utf-8`.
- R-08 "Timestamps in responses are RFC 3339 with an explicit offset."
- R-09 "Unknown fields in a request body are ignored, never an error." "Unknown query parameters are ignored."
- R-10 "IDs are opaque strings of at most 64 characters."

### Model and fixture (§4) [W1]
- R-11 One currency, declared in the fixture (`currency`, `minor_units` ∈ {0,2,3}); every amount is an integer count of minor units.
- R-12 "JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount. Booleans and strings are not numbers here." (non-integral e.g. `10.5` -> 422)
- R-13 Handles unique, `^[a-z0-9_]{1,20}$`, "never changing once set".
- R-14 Signup handle derived: "take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters."
- R-15 "New users start with a balance of `0`. They can receive money and be asked for money immediately."
- R-16 "Seeded users must be able to log in with the given password immediately."
- R-17 Fixture `balance` is the balance after seeded payments; "you do not replay seeded payments against balances". Seeded payments and requests are returned by the API with the fixture's ids, amounts, notes, visibility, status.
- R-18 "A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from `POST /_test/reset` and change nothing."
- R-19 Fixture `settlement_operator_ids`: array of user ids, "default []".
- R-20 "`amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³." Exact integer arithmetic, no floats in money.

### Errors (§5) [W1, applied by every item]
- R-21 Every 4xx/5xx body is `{"error": {"code": "...", "message": "..."}}`.
- R-22 400 `malformed_request`: "Unparseable body, or a field of the wrong JSON type" (body that is not a JSON object is unparseable for our purposes).
- R-23 400 `missing_idempotency_key`: "Required `Idempotency-Key` header absent or empty".
- R-24 401 `unauthenticated`: "Missing, malformed or unknown bearer token".
- R-25 403 `forbidden`, 404 `not_found` ("No such resource, or not visible to this caller"), 409 `idempotency_key_reuse`.
- R-26 422 `validation_failed`: "A required field or query parameter is missing, or a stated rule is violated with no more specific code"; correct type but invalid format / out of range -> 422 ("invalid dates, negative counts and values exceeding a stated maximum or length").
- R-27 "invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`. Omission alone selects the optional-field defaults." (`visibility: null` -> 422.)
- R-28 Integer query parameters are plain decimal digits: "`1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value."
- R-29 `Idempotency-Key` 1..255 chars, else 422 (empty -> 400 per R-23); `limit` integer 1..200, else 422; `offset` integer ≥0, else 422.
- R-30 "Requests must not produce 5xx responses, including under concurrent load." Unknown paths -> 404 `not_found` with the error body.

### Authentication (§6) [W1]
- R-31 `POST /auth/signup {email,password,display_name}` -> `201 {"user_id","display_name","token"}`.
- R-32 `POST /auth/login {email,password}` -> `200 {"user_id","display_name","token"}`.
- R-33 Signup "Email already registered" -> 409 `email_taken`.
- R-34 "Password shorter than 8 characters" -> 422 `validation_failed`.
- R-35 "`email` not of the form `local@domain`" -> 422 `validation_failed`.
- R-36 "Wrong password or unknown email on login" -> 401 `unauthenticated`.
- R-37 "The handle derived from the email (§4) is already taken" -> 409 `handle_taken`, "and no account is created".
- R-38 Every other endpoint requires `Authorization: Bearer <token>` except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, signup, login.
- R-39 "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." (each login issues a new token; old ones stay valid)
- R-40 Passwords stored with scrypt (or equivalent); "Plaintext password storage is not permitted." (Our choice, stricter than §10 which allows credentials in exports: exports carry only hashes, so fixture passwords are hashed at reset — see S-02.)

### Idempotency (§7) [W2; W3 applies it to splits and settlements]
- R-41 Five paths require a key: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`.
- R-42 "The key is scoped to **the authenticated user**." Two users with the same key do not interact.
- R-43 Replay = same user, "same method, the same path and the same body". "The same key with the same body on a different path is a different request, not a replay, and must succeed normally."
- R-44 First use -> 201 normal response.
- R-45 Replay -> **200**, "body identical to the original response as a JSON value".
- R-46 Same key, different body -> 409 `idempotency_key_reuse`.
- R-47 "Key reused after the original request failed with 4xx" -> treated as first use.
- R-48 "Same body" = same JSON value after parsing; "key order and whitespace do not matter". (Comparison rule: D-11.)
- R-49 "For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once."
- R-50 "A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes."
- R-51 "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks." (successful key + now-invalid body -> 409 `idempotency_key_reuse`)

### API (§8) [W2]
- R-52 `GET /me` -> `{"user_id","display_name","handle","balance","currency","minor_units"}`.
- R-53 `POST /payments {to_handle, amount, note?, visibility?}` -> 201 payment: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), settlement_id (null), created_at`.
- R-54 `note` default `""`; `visibility` default `"public"`.
- R-55 Caller balance below `amount` -> 409 `insufficient_funds`.
- R-56 `amount` below 1, above 1000000000, or not an integer -> 422 `validation_failed`.
- R-57 `to_handle` is the caller's own -> 422 `self_payment`.
- R-58 `note` longer than 200 characters -> 422 (200 is valid; count Unicode code points).
- R-59 `visibility` not `public`/`private` -> 422.
- R-60 No user with that handle -> 404 `not_found`.
- R-61 "The debit and the credit are one atomic step." "a failed payment leaves no trace in either."
- R-62 `note` "stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and emoji survive a round trip byte for byte."
- R-63 `POST /requests {payer_handle, amount, note?}` -> 201 request: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status ("pending"), payment_id (null), created_at`. Caller is requester.
- R-64 `/requests` errors: amount rules 422; `payer_handle` own -> 422 `self_request`; note >200 -> 422; unknown handle -> 404.
- R-65 "The payer's balance is not checked here."
- R-66 `POST /requests/{id}/pay {visibility?}` -> 201 payment (as R-53) with `request_id` set; request becomes `paid` with `payment_id`.
- R-67 Pay: `{}` and `{"visibility":"public"}` are different bodies -> reusing a key across them is 409 `idempotency_key_reuse`.
- R-68 Pay errors: not pending -> 409 `request_not_pending`; payer short -> 409 `insufficient_funds` (changes nothing; request stays pending and is payable later); caller not payer -> 403; unknown -> 404.
- R-69 "Replaying a successful payment returns 200 with its original payment body, including when the request is already `paid`. It moves no additional money and must not return `409 request_not_pending`."
- R-70 `POST /requests/{id}/decline`: payer only, no key; 200 with request `status: "declined"`; declining a declined request -> 200 current state; paid/cancelled -> 409 `request_not_pending`; not payer -> 403; unknown -> 404.
- R-71 `POST /requests/{id}/cancel`: requester only, no key; 200 `status: "cancelled"`; cancelling a cancelled one -> 200; paid/declined -> 409 `request_not_pending`; not requester -> 403; unknown -> 404.
- R-72 `GET /requests?direction&status&limit&offset`: only requests where caller is requester or payer, newest first by `created_at`; `direction` ∈ {incoming (caller is payer), outgoing (caller is requester)} or absent; `status` ∈ four statuses or absent; unknown values -> 422; limit default 50 (1..200), offset default 0; response `{"requests": [...], "has_more": bool}`; `has_more` true when items exist beyond the last returned.
- R-73 `GET /activity?limit&offset` -> `{"payments": [...], "has_more": bool}`, newest first, same limit/offset rules.
- R-74 Feed contract: a payment appears for a caller "if and only if its `visibility` is `public`, **or** the caller is its sender or its receiver." Requests never appear in activity. A private payment is visible to its own receiver.
- R-75 A request never appears in anyone else's `GET /requests`; non-party access to a request id (pay/decline/cancel) — see decision D-05.

### Splits and rounding (§8, §9) [W3]
- R-76 `POST /splits {amount, participant_handles, note?}` -> 201 `{split_id, amount, currency, note, shares:[{handle,amount}], requests:[...], created_at}`.
- R-77 Caller may be in `participant_handles` or omitted. One `pending` request per participant except the caller, each for that participant's share, caller as requester.
- R-78 `shares` covers every participant including the caller, in given order, sums to `amount`; `requests` covers all but the caller, same order.
- R-79 Split errors: amount rules 422; `participant_handles` empty or containing a duplicate -> 422; note >200 -> 422; any unknown handle -> 404.
- R-80 Caller-only split is valid: one share, zero requests, `"requests": []`. "Nothing about a split checks anyone's balance."
- R-81 Shares whole units, sum exactly, differ by at most one; extra units to the first participants. Table: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333,333,333; 5/5 -> 1,1,1,1,1.
- R-82 "A share of `0` is legal and still produces a request for that participant." (a 0-amount request: decision D-06)
- R-83 Different order gives the extra unit to a different person; each split independent of previous splits.

### Export / import (§10) [W3]
- R-84 `GET /_test/export` (unauthenticated) -> 200 `{"track":"pocketful","format_version":1,"state":{...}}`.
- R-85 `POST /_test/import` with that entire object -> 204, atomically replaces all state; accepts an unchanged export of this service; "No dependency on the source process, files, volume, port or network address is allowed."
- R-86 Import is replacement, not merge; repeating it restores the state without duplicating anything.
- R-87 Invalid JSON -> 400 `malformed_request`; missing fields, wrong `track`/`format_version`, or invalid state -> 422 `validation_failed` "without changing the destination".
- R-88 Export "is an atomic, read-only snapshot; subsequent source writes do not change it."
- R-89 Preserve: accounts and hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits, settlement operator permissions, settlement membership, every completed idempotency record (body + original response). IDs and timestamps not regenerated; nothing replayed against balances. Failed keys stay reusable.
- R-90 After import, ID generation continues without colliding with imported ids.
- R-91 "Import removes all previous destination data and credentials." "Reset clears all state, including imported state."

### Settlements (§11) [W3]
- R-92 `POST /settlements` requires an operator and an idempotency key. No token -> 401; non-operator -> 403 `forbidden`.
- R-93 Body `{"transfers":[{from_handle,to_handle,amount,note?,visibility?}]}`; 1..32 transfers; each uses ordinary payment amount/note/visibility rules (defaults `""`, `public`).
- R-94 Unknown handle -> 404; self-transfer -> 422 `self_payment`; malformed batch shape (transfers missing / not an array / 0 or >32 entries / entry not an object) -> 422 `validation_failed`. Unknown fields ignored.
- R-95 "Entry errors take precedence in input order, before insufficient funds."
- R-96 Affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative (net, not sequential); else 409 `insufficient_funds`.
- R-97 All movements commit together or none do; "failed validation claims no idempotency key and creates no payment or revision."
- R-98 201 `{settlement_id, committed_at, payments:[...]}` in input order; each member is an ordinary payment with `settlement_id`; `request_id` null; every member's `created_at` == `committed_at`.
- R-99 Non-member payments expose `settlement_id: null` (every payment body carries the field).
- R-100 Members follow ordinary feed visibility; operator status grants no access to others' requests or private activity.
- R-101 Replays -> 200 with the original complete response.

## Invariants (black-box observable)
- I-01 Σ balances (sum of `GET /me` over all users) == Σ fixture balances (+0 for signups), after any sequence including concurrent storms. Observe: log in all users after a storm and sum.
- I-02 No balance negative, ever. Observe: concurrent storm of payments/pays/settlements draining one wallet; `/me` never negative and number of 201s × amount ≤ starting balance.
- I-03 A request moves money at most once. Observe: N concurrent pays of one request with different keys -> exactly one 201, the rest 409 `request_not_pending`; payer debited once.
- I-04 Concurrent identical idempotent requests -> exactly one 201, rest 200 same body, one effect (one payment in activity, one debit).
- I-05 A payment is either in both parties' activity with matching balance changes or in neither.
- I-06 Request status is a one-way transition from `pending` to exactly one terminal state; concurrent pay/decline/cancel -> exactly one wins.
- I-07 Export -> import -> export yields an equivalent state; balances, ids, tokens unchanged.
- I-08 No response is 5xx and none exceeds 5 s at 50 in flight.

## Silent requirements (stated once, not sampled)
- S-01 Listen backlog must absorb 50 concurrent connects (ThreadingHTTPServer default `request_queue_size` is 5 -> raise it, e.g. 128).
- S-02 scrypt cost must keep 50 concurrent logins/signups under 5 s on 2 vCPU and a large-fixture reset under 10 s; hash outside the global lock.
- S-03 Amount `1e3`/`1000.0` accepted and returned as integer `1000` in responses; amount `true` is 422 not 400.
- S-04 `note: null` -> 422; `visibility: null` -> 422; non-string `to_handle` -> 400.
- S-05 Key length 256 -> 422; empty key -> 400.
- S-06 Replay body is identical even after the request was later cancelled/paid, and after export/import.
- S-07 Same key + same body on a different path succeeds as a new request (201).
- S-08 4xx-failed key is reusable — including after import.
- S-09 Insufficient-funds pay leaves the request pending; after the payer receives money, the same request pays.
- S-10 `has_more` correct at exact boundaries (total == offset+limit -> false).
- S-11 Feed private payment visible to receiver; settlement members carry visibility per transfer.
- S-12 Reset with a negative balance leaves the previous state fully intact (tokens included).
- S-13 Unicode/emoji note round trip; 200 code-point note accepted, 201 rejected.
- S-14 Signup email `A.B-c@x.com` -> handle `a_b_c`; local part longer than 20 truncated; derived handle collision -> 409 `handle_taken` and the email is still free afterwards.
- S-15 Malformed/unknown bearer token -> 401 even on endpoints that would otherwise 404/422.
- S-16 Responses carry `Content-Type: application/json; charset=utf-8`; 204 has no body.
- S-17 Import of invalid state leaves destination intact (tokens still work).
- S-18 Settlement net affordability: A->B 100 and B->C 100 with B at 0 is affordable.
- S-19 Signup precedence: an already-registered email gives 409 `email_taken`, not `handle_taken`; check email before handle. `Ada@x.com` after `ada@x.com` -> 409 `handle_taken` (D-07).
- S-20 Non-JSON constants `NaN`, `Infinity`, `-Infinity` -> 400 `malformed_request`; `1e400` (inf) amount -> 422, never 5xx; integer literal over 4300 digits -> 400, never 5xx.
- S-21 Lone surrogate in a note (`"\ud800"`) must never 5xx: response encoder falls back to `ensure_ascii` (same JSON value) — D-12.
- S-22 Reset and import bodies must be JSON objects; non-object or unparseable -> 400; parses but malformed fixture (missing `users`, non-integer balance, bad handle, duplicate id/handle/email, payment/request referencing unknown user) -> 422 `validation_failed`, change nothing.
- S-23 Large-fixture reset (1000 users) completes under 10 s (target < 6 s) on 2 vCPU.
- S-24 Split with 1000 unknown participant handles -> 404/422 promptly, never 5xx or timeout.

## Boundary (out of scope for stage 1)
- Stage 2 anything. Deposits, top-ups, withdrawals, cards, bank integrations.
- Directory/user search, admin balance endpoint, `GET /requests/{id}`, `GET /payments/{id}`, email verification, password reset, refresh tokens, role management, follow graph, mute list.
- Persistence across container restarts.

## Decisions
- D-01 Stack: Python 3.12 stdlib, `python:3.12-alpine`, ThreadingHTTPServer. **Deviation:** state kept in plain in-memory Python structures behind one global `threading.Lock` rather than sqlite3 — makes atomic export snapshot / import replacement trivial and removes a failure mode. One lock acquisition spans read+write of every state-changing request.
- D-02 Check order for authenticated writes: auth (401) -> body parses as JSON object (400) -> operator check for settlements (403) -> key header (400/422) -> claimed-key resolution (200 replay / 409 reuse / wait if in flight) -> field validation (400 type / 422) -> resource checks (404, 403, 409) -> effect.
- D-03 Field precedence inside one body: missing required -> 422; wrong JSON type -> 400 except amount/note/visibility (422).
- D-04 Pay/decline/cancel order: unknown id -> 404; then role -> 403; then status -> 409; then funds -> 409.
- D-05 A request id that exists but the caller is neither party: 403 `forbidden` for pay/decline/cancel? Spec table gives 403 for "not the payer"; we return 403 for any non-payer (pay/decline) and non-requester (cancel), including third parties.
- D-06 A 0-share produces a pending request of amount 0 (legal per §9).
- D-07 Emails compared case-sensitively as given, after no transformation, for uniqueness and login (spec states no folding).
- D-08 Settlement entry check order per entry: amount/note/visibility/types -> unknown handle 404 -> self 422 `self_payment`; first failing entry in input order wins.
- D-09 Wrong method on a known path -> 404 `not_found` with error body (never 5xx).
- D-10 Idempotency records are keyed by (user, method, path, key): the same key on `/requests/rq_1/pay` and `/requests/rq_2/pay` is independent (R-43).
- D-11 Body comparison for replay is type-aware: a bool never equals a number; an int equals an integral float (`1000` == `1000.0`); key order and whitespace ignored; applied recursively (`[1]` vs `[true]` differ).
- D-12 Response encoding: UTF-8; if encoding fails (lone surrogate), fall back to `ensure_ascii=True` (same JSON value). Notes are not rejected for surrogates.
- D-13 scrypt parameters chosen so a 1000-user reset finishes < 6 s on 2 vCPU (likely n=2^11..2^12, r=8, p=1); same parameters for signup; hashing outside the global lock, and signup re-checks email and handle inside the lock.
- D-14 Fixture payments/requests get `created_at` = reset time, plus a monotonic sequence number for deterministic newest-first ordering; ties broken by sequence descending; a later fixture array index counts as newer.
- D-15 Decline and cancel ignore the request body entirely (absent, empty or anything). Pay with an absent/empty body is treated as `{}` (so it is the same body as `{}` for replays); a non-empty body that does not parse is 400.
- D-16 Third-party pay/decline/cancel gives 403 (D-05) chosen over §5's 404 "not visible to this caller" because the endpoint tables say "Not the payer is 403".
- D-17 Settlement entry fields of the wrong JSON type (e.g. numeric `from_handle`) follow D-03 (400); only amount/note/visibility give 422; batch shape gives 422 per §11.

## Decision log (changes)
- 15:35 Auditor challenge merged: R-00 added; R-05, R-85, R-97 restored to spec wording; R-48 decision moved to D-11; R-40 marked as our choice; S-19..S-24 and D-10..D-17 added (builder points 1-7 merged as D-11..D-15).

## Work items (every line belongs to exactly one)
- W1 Skeleton, runtime contract, reset/fixture, errors, auth, /me: R-00..R-40, S-01, S-02, S-12, S-14, S-15, S-16, S-19..S-23, I-08.
- W2 Idempotency, payments, requests, activity: R-41..R-75, I-01..I-06, S-03..S-11, S-13.
- W3 Splits, export/import, settlements: R-76..R-101, I-07, S-17, S-18, S-24.
- W3 re-proves I-01, I-02, I-04 and I-06-style races for splits and settlements (concurrent identical keys, net-funds storms).
- D-lines apply to every item.
