# What the shipped checks never asked

The event ships only part of each stage's checks (pocketful: ~79% of stage 1, ~35% of stage 2). The rubric's
"Effective" criterion asks what a factory built that those checks never asked for.
This table is our answer, generated from the repository and not written by hand:

- **Requirement:** the ledger's *Silent requirements* (`S-xx`: stated once in the spec, not
  exercised by any sample) and *Invariants* (`I-xx`: properties that must survive any
  sequence of concurrent operations), quoted from [`stage-1/LEDGER.md`](../stage-1/LEDGER.md).
- **Prover tests:** functions in [`verification/stage-1/`](../verification/stage-1/) tagged
  with that line (`@L("…")`), counted by parsing the test files.
- **Verdict:** the prover's round 4 against `d0b69b4` (the accepted revision): 441 tests,
  440 passed, 4 minutes 41 seconds. "Passing" counts the test runs and storm repetitions
  that passed for that line.

**Silent requirements: 23/24 pass. Invariants: 7/8 pass.** Every failure traces to
one cause: the 1000-user reset takes 13–18 s against the spec's 10 s limit for reset.
That is the known limit in the README. The factory found it, but the deadlock stopped it
from being routed back to the builder. Stage 2 carried it forward and fixed it.

| Line | Requirement (ledger text) | Prover tests | Prover round |
|---|---|---|---|
| **S-01** | Listen backlog must absorb 50 concurrent connects (ThreadingHTTPServer default `request_queue_size` is 5 -> raise it, e.g. 128). | 3 in `test_storms.py` | ✅ pass (15 passing) |
| **S-02** | scrypt cost must keep 50 concurrent logins/signups under 5 s on 2 vCPU and a large-fixture reset under 10 s; hash outside the global lock. | 2 in `test_storms.py`, `test_w1_runtime.py` | ✅ pass (6 passing) |
| **S-03** | Amount `1e3`/`1000.0` accepted and returned as integer `1000` in responses; amount `true` is 422 not 400. | 2 in `test_w1_model.py` | ✅ pass (15 passing) |
| **S-04** | `note: null` -> 422; `visibility: null` -> 422; non-string `to_handle` -> 400. | 2 in `test_w1_errors_auth.py` | ✅ pass (16 passing) |
| **S-05** | Key length 256 -> 422; empty key -> 400. | 2 in `test_w1_errors_auth.py` | ✅ pass (2 passing) |
| **S-06** | Replay body is identical even after the request was later cancelled/paid, and after export/import. | 3 in `test_w2_idempotency.py`, `test_w3_export_import.py` | ✅ pass (3 passing) |
| **S-07** | Same key + same body on a different path succeeds as a new request (201). | 2 in `test_w2_idempotency.py` | ✅ pass (2 passing) |
| **S-08** | 4xx-failed key is reusable — including after import. | 2 in `test_w2_idempotency.py`, `test_w3_export_import.py` | ✅ pass (6 passing) |
| **S-09** | Insufficient-funds pay leaves the request pending; after the payer receives money, the same request pays. | 1 in `test_w2_requests.py` | ✅ pass (1 passing) |
| **S-10** | `has_more` correct at exact boundaries (total == offset+limit -> false). | 2 in `test_w2_activity.py`, `test_w2_requests.py` | ✅ pass (2 passing) |
| **S-11** | Feed private payment visible to receiver; settlement members carry visibility per transfer. | 3 in `test_w2_activity.py`, `test_w3_settlements.py` | ✅ pass (3 passing) |
| **S-12** | Reset with a negative balance leaves the previous state fully intact (tokens included). | 2 in `test_s19_s24.py`, `test_w1_model.py` | ✅ pass (15 passing) |
| **S-13** | Unicode/emoji note round trip; 200 code-point note accepted, 201 rejected. | 2 in `test_w2_payments.py` | ✅ pass (9 passing) |
| **S-14** | Signup email `A.B-c@x.com` -> handle `a_b_c`; local part longer than 20 truncated; derived handle collision -> 409 `handle_taken` and the email is still free afterwards. | 3 in `test_w1_errors_auth.py` | ✅ pass (10 passing) |
| **S-15** | Malformed/unknown bearer token -> 401 even on endpoints that would otherwise 404/422. | 2 in `test_w1_errors_auth.py` | ✅ pass (8 passing) |
| **S-16** | Responses carry `Content-Type: application/json; charset=utf-8`; 204 has no body. | 2 in `test_w1_runtime.py` | ✅ pass (2 passing) |
| **S-17** | Import of invalid state leaves destination intact (tokens still work). | 3 in `test_w3_export_import.py` | ✅ pass (16 passing) |
| **S-18** | Settlement net affordability: A->B 100 and B->C 100 with B at 0 is affordable. | 1 in `test_w3_settlements.py` | ✅ pass (1 passing) |
| **S-19** | Signup precedence: an already-registered email gives 409 `email_taken`, not `handle_taken`; check email before handle. `Ada@x.com` after `ada@x.com` -> 409 `handle_taken` (D-07). | 1 in `test_s19_s24.py` | ✅ pass (1 passing) |
| **S-20** | Non-JSON constants `NaN`, `Infinity`, `-Infinity` -> 400 `malformed_request`; `1e400` (inf) amount -> 422, never 5xx; integer literal over 4300 digits -> 400, never 5xx. | 3 in `test_s19_s24.py` | ✅ pass (10 passing) |
| **S-21** | Lone surrogate in a note (`"\ud800"`) must never 5xx: response encoder falls back to `ensure_ascii` (same JSON value) — D-12. | 1 in `test_s19_s24.py` | ✅ pass (1 passing) |
| **S-22** | Reset and import bodies must be JSON objects; non-object or unparseable -> 400; parses but malformed fixture (missing `users`, non-integer balance, bad handle, duplicate id/handle/email, payment/request referencing unknown user) -> 422 `validation_failed`, change nothing. | 2 in `test_s19_s24.py` | ✅ pass (20 passing) |
| **S-23** | Large-fixture reset (1000 users) completes under 10 s (target < 6 s) on 2 vCPU. | 1 in `test_s19_s24.py` | ❌ fail (0 passing) — fails: test_1000_user_reset_under_10s |
| **S-24** | Split with 1000 unknown participant handles -> 404/422 promptly, never 5xx or timeout. | 1 in `test_s19_s24.py` | ✅ pass (1 passing) |
| **I-01** | Σ balances (sum of `GET /me` over all users) == Σ fixture balances (+0 for signups), after any sequence including concurrent storms. Observe: log in all users after a storm and sum. | 4 in `test_storms.py`, `test_w3_splits.py` | ✅ pass (16 passing) |
| **I-02** | No balance negative, ever. Observe: concurrent storm of payments/pays/settlements draining one wallet; `/me` never negative and number of 201s × amount ≤ starting balance. | 4 in `test_storms.py` | ✅ pass (20 passing) |
| **I-03** | A request moves money at most once. Observe: N concurrent pays of one request with different keys -> exactly one 201, the rest 409 `request_not_pending`; payer debited once. | 2 in `test_storms.py` | ✅ pass (10 passing) |
| **I-04** | Concurrent identical idempotent requests -> exactly one 201, rest 200 same body, one effect (one payment in activity, one debit). | 2 in `test_storms.py` | ✅ pass (30 passing) |
| **I-05** | A payment is either in both parties' activity with matching balance changes or in neither. | 4 in `test_storms.py`, `test_w2_payments.py` | ✅ pass (12 passing) |
| **I-06** | Request status is a one-way transition from `pending` to exactly one terminal state; concurrent pay/decline/cancel -> exactly one wins. | 1 in `test_storms.py` | ✅ pass (5 passing) |
| **I-07** | Export -> import -> export yields an equivalent state; balances, ids, tokens unchanged. | 2 in `test_storms.py`, `test_w3_export_import.py` | ✅ pass (6 passing) |
| **I-08** | No response is 5xx and none exceeds 5 s at 50 in flight. | 9 in `test_storms.py` | ❌ fail (65 passing) — violation: slow: POST /_test/reset -> 204 13.03s |

{FOOTER}

Regenerate: `python3 gen_never_asked.py <clone> <round ledger.json> <out.md> [stage] [notes.json] [round label]`.
