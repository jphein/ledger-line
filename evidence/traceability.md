# Commit ↔ room traceability

Judges compare the git history with `room.json`. This table does that comparison,
generated from both files (not by hand). For each commit the seats made, it gives the
first room message that names the commit's hash: who sent it, at what time (PDT), and to
which seats.

**27 of 36 seat commits are named in a room message.** The rest
appear in the seats' own tool output (their `git` commands) but were not announced; see
the last column.

| Commit | Author | Committed | Subject | First room message naming it |
|---|---|---|---|---|
| `fce262b` | lead | 15:33:33 | ledger: stage-1 LEDGER.md (R-01..R-101, I-01..I-08, S-01..S-18) | 15:33:48 **lead** → auditor (+6 later) |
| `c28af32` | lead | 15:35:45 | ledger: merge auditor challenge and builder points (R-00, S-19..S-24,  | not named in a message; in 5 tool event(s), first 15:35:45 by lead |
| `4be21dc` | lead | 15:36:02 | ledger: work item map W1-W3 | 15:36:12 **lead** → builder (+5 later) |
| `24230d4` | lead | 15:37:03 | ledger: auditor non-blocking clarifications (D-11, D-14, W3 invariants | 15:42:09 **builder** → auditor, lead, prover |
| `86dd629` | builder | 15:41:46 | W1: skeleton, runtime contract, reset/fixture, errors, auth, /me (R-00 | 15:42:09 **builder** → auditor, lead, prover (+3 later) |
| `2e6b10e` | prover | 15:41:56 | verification: stage-1 harness + W1/W2 black-box tests | 15:43:50 **auditor** → builder, lead, prover |
| `1e1bedb` | builder | 15:44:15 | W2: idempotency, payments, requests, activity (R-41..R-75, I-01..I-06, | 15:44:29 **builder** → auditor, lead, prover (+3 later) |
| `c2c103e` | prover | 15:44:45 | verification: W3 tests and invariant storms | 15:45:29 **auditor** → builder, lead, prover |
| `92408b5` | prover | 15:45:50 | verification: round.sh clean build + isolated serve (R-01..R-04) | not named in a message; in 9 tool event(s), first 15:45:50 by prover |
| `633018b` | builder | 15:46:53 | W3: splits, settlements, export/import (R-76..R-101, I-07, S-17, S-18, | 15:47:09 **builder** → auditor, lead, prover (+3 later) |
| `d0b69b4` | builder | 15:48:54 | W2 fix: exact iterative canonical(), exact integral_value, chunked bod | 15:49:19 **builder** → auditor, lead, prover (+4 later) |
| `1f1034a` | prover | 15:59:48 | verification: fix six test bugs found against a reference run | 15:59:55 **prover** → lead |
| `54eb3a7` | prover | 16:01:25 | verification: S-19..S-24 and auditor canonical() probes | not named in a message; in 5 tool event(s), first 16:01:25 by prover |
| `c57dcbf` | prover | 16:01:46 | verification: fix keepalive_expiry placement (Limits) | not named in a message; in 5 tool event(s), first 16:01:47 by prover |
| `e978153` | prover | 16:02:32 | verification: ignore environment proxies (trust_env=False) | not named in a message; in 4 tool event(s), first 16:02:33 by prover |
| `61b8e1e` | Jeffrey Pine Hein (human) | 17:11:50 | chore: add room.json (Band full session export) | human commit, outside the run |
| `d0cf74a` | Jeffrey Pine Hein (human) | 17:18:12 | docs: factory results, deadlock write-up, known limits, MIT license | human commit, outside the run |
| `8410475` | lead | 17:34:28 | ledger: stage-2 LEDGER.md (R-200..R-267, I-200..I-205, S-200..S-214, D | 17:34:47 **lead** → auditor (+9 later) |
| `a61ead7` | builder | 17:35:53 | X1: copy stage-1 to stage-2 (R-200) | 17:36:57 **builder** → auditor, lead, prover (+4 later) |
| `8dd6abe` | builder | 17:36:41 | X1: hash each distinct fixture password once, quota-sized pool (R-202, | 17:36:57 **builder** → auditor, lead, prover (+7 later) |
| `6304bdb` | lead | 17:36:44 | ledger(stage-2): merge auditor challenge (D-203..D-205, D-208, D-211.. | 17:37:02 **lead** → builder (+3 later) |
| `fad9ad0` | builder | 17:38:19 | X1: per-user sha256 wrapper over shared fixture scrypt, per ledger D-2 | 17:38:44 **builder** → auditor, lead, prover (+7 later) |
| `f4c99db` | lead | 17:39:05 | ledger(stage-2): D-215 seeded-user scrypt cost fallback | not named in a message; in 4 tool event(s), first 17:39:05 by lead |
| `7bd06b3` | prover | 17:40:26 | verification(stage-2): X1 API tests, storms, round script | 17:40:36 **prover** → lead (+1 later) |
| `55ca8b3` | builder | 17:43:51 | X1: holds and authorizations API, expiry, upgrade import, one shared s | 17:44:13 **builder** → auditor, lead, prover (+6 later) |
| `ea8af63` | builder | 17:48:28 | X2: UI shell, negotiation, auth screens, wallet home, feed, refresh, u | 17:48:46 **builder** → auditor, lead, prover (+10 later) |
| `c5dd3f9` | prover | 17:50:56 | verification(stage-2): X2/X3 headless Playwright UI tests | 17:51:03 **prover** → lead |
| `562d826` | prover | 17:52:42 | verification(stage-2): R-245 feed shows every visible payment past 50/ | not named in a message; in 5 tool event(s), first 17:52:43 by prover |
| `bc6e73f` | builder | 17:52:46 | X3: requests, split, holds screens, authorize form, visual pass, RUN.m | 17:53:19 **builder** → auditor, lead, prover (+3 later) |
| `be463b8` | builder | 17:55:34 | X2 fix: page every list to the end, uncertain outcomes outside *-error | 17:55:57 **builder** → auditor, lead, prover (+11 later) |
| `ecde887` | builder | 17:56:35 | X3: browser smoke scripts incl. S-204 upgrade retry (R-232, S-204) | 17:56:57 **builder** → auditor, lead, prover (+6 later) |
| `18849a9` | builder | 17:58:41 | X1 fix: exact integer ttl clamp, de-dup paged lists by id (R-212, R-30 | 17:58:59 **builder** → auditor, lead, prover (+11 later) |
| `839c79d` | prover | 18:00:38 | verification(stage-2): R-201 fetches the HTML screen with the raw clie | 18:04:16 **prover** → auditor, builder, lead (+2 later) |
| `42299a9` | lead | 18:04:31 | ledger(stage-2): decision log — D-215 applied (seeded n=2^10) | 18:04:51 **lead** → auditor, prover (+2 later) |
| `3793fd2` | builder | 18:04:36 | X1: FIXTURE_N 2^10 for seeded users per container timing (R-202, S-215 | 18:05:00 **builder** → auditor, lead, prover (+3 later) |
| `9a07bec` | prover | 18:05:33 | verification(stage-2): round.sh honours UI_SHOTS | not named in a message; in 1 tool event(s), first 18:05:34 by prover |
| `8fba553` | prover | 18:15:54 | verification(stage-2): fix three UI test bugs found at 18849a9 | 18:17:41 **prover** → auditor, builder, lead (+1 later) |
| `c27f5e2` | prover | 18:18:04 | verification(stage-2): R-31 signup shape test on the stage-2 image | not named in a message; in 1 tool event(s), first 18:18:05 by prover |
| `d949869` | Jeffrey Pine Hein (human) | 18:29:27 | chore: update room.json (Band full session export, stages 1 and 2) | human commit, outside the run |

## Work distribution

| Seat | Commits | Room messages | Tool calls | All room events |
|---|---|---|---|---|
| lead | 8 | 51 | 96 | 369 |
| builder | 14 | 19 | 198 | 535 |
| prover | 14 | 10 | 177 | 508 |
| auditor | 0 | 17 | 89 | 283 |

Human messages in the room: 2 (15:31:42, 17:31:58): the dispatches only.
The auditor makes no commits by design: its work is the ledger challenge and the verdicts.

### Who addressed whom (room messages, by `@handle`)

| From → to | Messages |
|---|---|
| lead → builder | 37 |
| lead → prover | 23 |
| lead → auditor | 22 |
| builder → lead | 18 |
| auditor → lead | 17 |
| builder → auditor | 14 |
| builder → prover | 14 |
| auditor → builder | 13 |
| auditor → prover | 13 |
| prover → lead | 9 |
| prover → builder | 5 |
| prover → auditor | 2 |

Regenerate: `python3 gen_traceability.py <clone> room.json 041446d traceability.md`.
