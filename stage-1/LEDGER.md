# LEDGER — pocketful stage 1

Source: `/home/jp/band/dark-factory-wearedevs/pocketful/spec/stage-1.md` (the contract).
Quoted words come from the spec. Item tags: `[W1]` runtime/reset/auth/me/errors,
`[W2]` payments/requests/idempotency/activity, `[W3]` splits/settlements/export-import.

## Requirements

### Delivery and runtime (§2, §3) [W1]
- R-01 Deliver "an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup", all inside `stage-1/`.
- R-02 "The image must run on its own with `-e PORT=<port>` and a port mapping." No outbound network at run time; every runtime dependency is in the image.
- R-03 "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`."
- R-04 `GET /health -> 200 {"status": "ok"}` within 60 s of container start (2 vCPU, 2 GiB).
- R-05 Up to 50 requests in flight; each answered within 5 s (10 s for `POST /_test/reset`).
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
- R-40 Passwords stored with scrypt (or equivalent); "Plaintext password storage is not permitted." (export must not reveal plaintext)

### Idempotency (§7) [W2; W3 applies it to splits and settlements]
- R-41 Five paths require a key: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`.
- R-42 "The key is scoped to **the authenticated user**." Two users with the same key do not interact.
- R-43 Replay = same user, "same method, the same path and the same body". "The same key with the same body on a different path is a different request, not a replay, and must succeed normally."
- R-44 First use -> 201 normal response.
- R-45 Replay -> **200**, "body identical to the original response as a JSON value".
- R-46 Same key, different body -> 409 `idempotency_key_reuse`.
- R-47 "Key reused after the original request failed with 4xx" -> treated as first use.
- R-48 "Same body" = same JSON value after parsing; key order and whitespace do not matter (and `1000` vs `1e3`? -> compare parsed JSON values; `1000` and `1000.0` parse to equal numbers in Python and count as the same value).
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
- R-85 `POST /_test/import` with that entire object -> 204, atomically replaces all state; accepts an unchanged export of this service; no dependency on source process/files/port.
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
- R-97 All movements commit together or none do; failed validation claims no key and creates no payment.
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
