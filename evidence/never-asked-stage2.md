# What the shipped checks never asked — stage 2

The event ships only part of each stage's checks (pocketful: ~79% of stage 1, ~35% of stage 2). The rubric's
"Effective" criterion asks what a factory built that those checks never asked for.
This table is our answer, generated from the repository and not written by hand:

- **Requirement:** the ledger's *Silent requirements* (`S-xx`: stated once in the spec, not
  exercised by any sample) and *Invariants* (`I-xx`: properties that must survive any
  sequence of concurrent operations), quoted from [`stage-2/LEDGER.md`](../stage-2/LEDGER.md).
- **Prover tests:** functions in [`verification/stage-2/`](../verification/stage-2/) tagged
  with that line (`@L("…")`), counted by parsing the test files.
- **Verdict:** the prover's round 13 against `18849a9` (image identical to the acceptance revision except one hashing-cost line): 272 tests, 267 passed on the first run, 4 minutes 27 seconds. "Passing" counts the test runs and storm repetitions
  that passed for that line.

**Silent requirements: 17/18 pass. Invariants: 6/6 pass.** The one raw failure, S-214,
was a bug in the prover's own test (fixed and re-run passing). The stage-2 suite
also re-runs the whole stage-1 suite against `stage-2/` (438 passed, 3 deselected where
stage 2 amends the response shape).

| Line | Requirement (ledger text) | Prover tests | Prover round |
|---|---|---|---|
| **S-200** | The UI's fetches to `/requests` and `/authorizations` must request JSON (no `Accept: text/html`), or they get HTML. | 1 in `test_x2_ui.py` | ✅ pass (2 passing) |
| **S-201** | Browser `Accept` for navigation includes `text/html` among others (`text/html,application/xhtml+xml,...`): negotiate on "contains text/html", not equality. | 2 in `test_x2_ui.py` | ✅ pass (8 passing) |
| **S-202** | Pay form idempotency key is kept per unchanged form contents; changing any field (handle, amount, note, visibility) mints a new key; a refused (4xx) payment's key may be reused (§7) but a changed field still mints a new one. | 2 in `test_x2_ui.py` | ✅ pass (5 passing) |
| **S-203** | Lost response = network error or no response (fetch rejects, timeout, 5xx-like); a 4xx with an error body is a confirmed refusal (pay-error), anything else is uncertain (pay-uncertain). | 5 in `test_x2_ui.py` | ✅ pass (6 passing) |
| **S-204** | Retry of an uncertain payment after import returns 200 with the original payment (idempotency record survived import) and the UI treats 200 as success. | 1 in `test_x3_ui.py` | ✅ pass (1 passing) |
| **S-205** | `authorization-expires-{id}` text is the raw RFC 3339 string exactly as the API returns it. | 2 in `test_x3_ui.py` | ✅ pass (2 passing) |
| **S-206** | Capture default amount pre-fill is the remaining amount formatted as a decimal input (e.g. `20.00`). | 2 in `test_x3_ui.py` | ✅ pass (4 passing) |
| **S-207** | `wallet-held` absent (not just hidden or zero) when held is 0; `auth-error`, `pay-error`, `pay-uncertain` absent when there is none. | 6 in `test_x2_ui.py`, `test_x3_ui.py` | ✅ pass (10 passing) |
| **S-208** | `current-handle` text has no `@`; `current-user` on every signed-in screen, including `/requests`, `/split`, `/authorizations`. | 2 in `test_x2_ui.py` | ✅ pass (2 passing) |
| **S-209** | Capture `final` of wrong type (e.g. `"false"`) -> 400 `malformed_request`; `amount: null`? -> 422 (amount rule). | 1 in `test_x1_api.py` | ✅ pass (6 passing) |
| **S-210** | Expiry boundary: `expires_at == now` is expired; ttl of 1–2 s in a fixture expires on time on reads with no writes. | 2 in `test_x1_api.py` | ✅ pass (2 passing) |
| **S-211** | Seeded expired-by-clock open holds are excluded from the R-215 sum ("unexpired open holds"). | 1 in `test_x1_api.py` | ✅ pass (1 passing) |
| **S-212** | After logout, protected screens send the user to login (no stale `current-user`). | 1 in `test_x2_ui.py` | ✅ pass (1 passing) |
| **S-213** | Unauthenticated visit to `/`, `/requests`, `/split`, `/authorizations` shows or redirects to login, never a raw JSON 401. | 2 in `test_x2_ui.py` | ✅ pass (5 passing) |
| **S-214** | A stale request pay button (request cancelled elsewhere) -> `request-error` and the list refreshes (R-252); same pattern for a stale capture/void button -> `authorization-error` and refresh. | 4 in `test_x3_ui.py` | ❌ fail (3 passing) — fails: test_stale_decline_and_cancel_buttons. first run FAIL from a prover test bug (fixed in 8fba553, re-run pass; product correct) |
| **S-215** | A 1000-user fixture with all-distinct passwords resets in < 10 s in the 2 vCPU container (over HTTP). | 1 in `test_x1_api.py` | ✅ pass (1 passing) |
| **S-216** | ttl=1 in the fixture: authorise then capture immediately -> 201; capture after 1.5 s -> 409 `authorization_expired`. | 1 in `test_x1_api.py` | ✅ pass (1 passing) |
| **S-217** | Fixture authorisation validation: unknown from/to user, from == to, amount outside 1..1000000000 or non-integral, bad visibility/status, non-RFC 3339 `expires_at`, duplicate id, non-positive/non-integral `authorization_ttl_seconds` -> 422 `validation_failed`, nothing changed. Seeded `captured` without `captured_amount` defaults per D-206. | 2 in `test_x1_api.py` | ✅ pass (13 passing) |
| **I-200** | Σ `total` over all users == Σ seeded balances after any storm including authorize/capture/void/expiry. | 1 in `test_x1_storms.py` | ✅ pass (5 passing) |
| **I-201** | `available ≥ 0` and `available == total − held` at every read, including during storms of payments, authorisations, captures and settlements against one wallet. | 2 in `test_x1_storms.py` | ✅ pass (10 passing) |
| **I-202** | Σ captures of one authorisation ≤ its amount; concurrent captures with different keys never over-capture; concurrent identical captures -> one 201, rest 200, one payment. | 2 in `test_x1_storms.py` | ✅ pass (15 passing) |
| **I-203** | Concurrent capture vs void on one open authorisation: outcomes match some serial order (either the capture succeeds and void then 409/voids the remainder, or void wins and capture 409). | 1 in `test_x1_storms.py` | ✅ pass (5 passing) |
| **I-204** | After expiry, `held` drops and `available` rises without any write request. | 1 in `test_x1_api.py` | ✅ pass (1 passing) |
| **I-205** | UI: double-submitting the unchanged pay form moves money once (one payment in feed, balance falls once). | 2 in `test_x2_ui.py` | ✅ pass (2 passing) |

{FOOTER}

Regenerate: `python3 gen_never_asked.py <clone> <round ledger.json> <out.md> [stage] [notes.json] [round label]`.
