# FACTORY — Ledger Line

A four-seat software factory that turns a written specification into a containerized
service, and does not take "the tests pass" for an answer. The factory's unit of truth is
a **requirements ledger**: every sentence of the spec that can be tested becomes a
numbered line, and nothing ships until an independent seat has shown each line passing
against the same committed revision a second seat has reviewed.

Everything in `mandates/` is generic. Hand the four files and a new spec to another team
and they work unchanged; the track lives only in the task the human dispatches.

## Seats

| Seat | Harness · model | Owns | Never does |
|---|---|---|---|
| **lead** | Claude Code · claude-opus-5-5 | the ledger, the plan, routing, acceptance, the final report | writes product code or tests |
| **builder** | Claude Code · claude-opus-5-5 | source, Dockerfile, RUN.md, unit tests | accepts its own work; edits the prover's tests |
| **prover** | Claude Code · claude-opus-5-5 | black-box tests derived from the ledger; every check run | reads product code to decide what to test; fixes code |
| **auditor** | Claude Code · claude-opus-5-5 | ledger challenge; review of every revision | fixes code; rejects without a concrete defect |

## Flow of one stage

```
human task ──► lead: LEDGER.md (R-nn requirements, I-nn invariants,
                      silent requirements, stage boundary)
                 │
                 ├──► auditor: challenge the ledger ──► lead merges corrections
                 │
                 ├──► builder: work item k (ledger lines pasted in full)
                 │        └──► commit + evidence block ──► prover + auditor
                 │                                            │
                 │     prover: clean image, no network, ledger tests,
                 │             invariant storms ×5, replays, regression
                 │     auditor: correctness-by-construction, scope,
                 │              written-to-spec-not-test, maintainability
                 │                                            │
                 ◄──────────── pass + accept on ONE revision ─┘
                 │      (any fail → back to builder with the evidence verbatim)
                 ▼
            final report: accepted hash, ledger table, rejections that changed the work
```

Items pipeline: while item *k* is under check, the builder starts item *k+1* from the
last accepted revision.

## Design choices and what they cost

1. **A ledger before code.** Sample checks cover part of each suite, so the spec, not the
   samples, has to drive the work. The ledger forces every table row, default and
   concurrency sentence to be named before anyone builds. *Cost in the judged run:* 1 min
   51 s from dispatch to the first ledger commit; the ledger reached R-00..R-101,
   I-01..I-08, S-01..S-24 and D-01..D-17.
2. **The auditor challenges the ledger first.** A missed requirement costs nothing to add
   to a ledger and a lot to discover after the build. *Measured:* the challenge found 12
   points, among them a missing requirement (R-00), three lines restored to the spec's
   own wording and six new silent requirements (S-19..S-24); the builder added 7
   decisions. The ledger was accepted 5 min 14 s after
   dispatch.
3. **The prover is independent by construction.** It derives tests from the ledger, not
   from the code, and owns a folder nobody else edits. That keeps one seat from being both
   author and judge. *Cost:* the prover's 406 tests duplicate some of the builder's unit
   tests, on purpose. It was also the most expensive seat (below).
4. **Invariant storms, five repeats.** Concurrency bugs are probabilistic, so one green
   burst proves little. Each invariant gets a burst of conflicting, duplicated and
   replayed requests at the top allowed concurrency, then an exact read-back, five
   times. *Cost:* minutes of wall clock per round.
5. **Acceptance needs the same revision twice.** The prover's pass and the auditor's
   accept must name the same full commit hash, so a fix that slips in after review
   cannot ship. *Cost:* a re-check after every fix.
6. **Self-contained handoffs.** Seats see only what is addressed to them, so every handoff
   pastes the requirements in full, in numbered parts if needed. In the judged run the
   lead sent W1 as three parts and W2 and W3 as two each, with ledger lines verbatim.
   *Cost:* long messages, which beat a seat that guesses.
7. **Three strikes, then re-plan.** The third rejection of the same item makes the lead
   split it or change approach and log why, instead of looping. In the judged run one
   rejection was enough ("rejection 1 of 3").
8. **Decisions are logged, deviations too.** The dispatch suggested sqlite3; the band
   chose in-memory structures behind one global lock instead, and recorded why in the
   ledger (D-01: an atomic export snapshot and import replacement become trivial).

## How it catches bad work

| Bad result | Caught by | Evidence it leaves |
|---|---|---|
| A requirement nobody built | ledger + auditor's challenge | a ledger line with no passing test |
| A race that passes once | prover's storms ×5 | the failing burst and its read-back |
| Code shaped to a sample check | auditor, item 2 of its review | a blocking finding naming the branch |
| A service that needs the network at run time | prover's clean, network-less build | a failed health check |
| Work ahead of the stage boundary | ledger boundary + auditor scope check | a scope finding |
| A fix that lands after review | same-hash acceptance rule | mismatched hashes in the room |

**Stage 1 of the judged run** (all times PDT, from `room.json` and `git log`):

- 15:43: the auditor accepted W1 but filed four findings. Two of them, a body containing
  `1e999999999999` crashing number handling into a 500, and numbers rounded to 28 digits
  making two different bodies compare equal for idempotent replay, became reachable in W2.
- 15:45: the auditor rejected W2, "changes needed (2 blocking)", with reproductions. The
  lead forwarded the evidence verbatim to the builder as rejection 1 of 3, citing ledger
  lines R-30, R-46, R-09 and D-11.
- 15:48: the builder fixed it in `d0b69b4` (exact, iterative canonical form; exact
  integral check; plus chunked bodies and socket timeouts), with new tests.
- 15:50: the auditor re-reviewed the touched files and accepted W1, W2 and W3 at
  `d0b69b4`.
- 16:07: the prover's round 4 at `d0b69b4` passed 440 of 441 checks. The failure was
  S-23, the 1000-user reset over the spec's 10 s limit, reproduced three times in
  isolation at 14–18 s.

**Stage 2** (dispatched separately at 17:31:59 into the same room):

- 17:34: the lead committed the stage-2 ledger (R-200..R-267, I-200..I-205,
  S-200..S-214) and carried the failed S-23 forward as a stage-2 requirement (R-202).
  At 17:36 the auditor's challenge added 13 points, among them a rewrite of the S-23
  fix's own design (D-208).
- 17:37: the auditor rejected the builder's first S-23 commit because it implemented
  the *old* wording of D-208. The builder had already superseded it (`fad9ad0`).
- 17:50: X2 (the browser UI) was rejected on R-245: the activity feed fetched one page
  of 50 and silently dropped the rest. The fix (`be463b8`) pages every list to the end.
- 17:57: the binding verdict on X1–X3 was "changes needed": a hold's expiry was clamped
  with floating-point seconds (R-212). The fix landed in `18849a9` at 17:58, and the
  auditor accepted at 17:59.
- 18:04: the prover timed S-23 in the 2-vCPU container: 6.24 s and 8.34 s for 1000
  distinct passwords. That passes 10 s, but not the lead's own 7 s margin (D-215). The
  lead lowered the seeded-user hashing cost; the one-line change (`3793fd2`) was
  accepted by the auditor at 18:05.
- 18:17: the prover's full round at `18849a9`: no product failures, every
  machine-checkable line passing, the sample harness claiming stage 2 (35/35). The first
  run had 5 failures, all bugs in the prover's own browser tests (fixed in `8fba553`,
  re-run passing). The prover reported them as its own, and did not ask the builder to
  change correct code.

## Measured on the judged run

| Measure | Stage 1 | Stage 2 |
|---|---|---|
| Dispatch (the only human message of the stage) | 15:31:42 | 17:31:59 |
| First ledger commit | 15:33:33 | 17:34:28 |
| Ledger challenge merged | 15:36:56 (12 points) | 17:36:44 (13 points) |
| Work items | W1, W2, W3 | X1 (API, holds), X2 (UI core), X3 (screens, visual pass) |
| Rejections that changed the work | 1 (W2: 2 blocking) | 3 (X1 D-208 wording; X2 R-245; X1 R-212), plus the D-215 cost decision |
| Auditor's binding accept | 15:50:20 (+18 min 38 s) | 17:59:37 (+27 min 38 s); re-check of `3793fd2` 18:05:20 |
| Prover's own suite | 440 of 441 at `d0b69b4` | 267 of 272 at `18849a9`; the 5 were its own test bugs, fixed and re-run passing: no product failures |
| Sample checks, prover's run | 147/147 (s1-1) | 24/35 at 18:03 (s2-1, `ea8af63`) → 35/35 at 18:17 (s2-2, `18849a9`) |
| Ended | deadlock at 16:10 (no report) | seats stopped by the operator's helper at 18:18 (no report) |

| Per seat, whole run | lead | builder | prover | auditor |
|---|---|---|---|---|
| Commits | 8 | 14 | 14 | 0 (it reviews, never commits) |
| Room messages | 51 | 19 | 10 | 17 |
| Room events (messages, tool calls, results) | 369 | 535 | 508 | 283 |

`room.json` holds 1698 events: the four seats' 1695, plus the human joining the room and
the two dispatches. By stage: stage 1 lead 141 · builder 208 · prover 235 ·
auditor 100; stage 2 lead 228 · builder 327 · prover 273 · auditor 183.

| Model spend (`band usage`, catalog list prices, not a bill) | |
|---|---|
| Judged room, stage 1 | 24.4 M tokens, ≈ $15.06: prover $6.33 · builder $4.37 · auditor $2.38 · lead $1.98 |
| Judged room, stage 2 | not measured: Band attributed the stage-2 seat sessions to no room |
| Rehearsal room (practice track) | 5.8 M tokens, ≈ $4.55 |

Final check, isolated mode, fresh clone: `stage-1/` claims stage 1 (147/147);
`stage-2/` claims stage 2 (147/147 + 35/35), and the stage-3 suite fails, as it should.

## What we tried that failed

### 1. The judged run deadlocked on a reply that never left a seat

At 16:10:02 the prover sent its round-4 result ("W1+W2+W3 at d0b69b4: one fail, S-23")
through the room's reply tool. The tool answered `"staged": true`: the reply is held
until the seat's turn ends. But the prover had left two background watchers running,
following log files of runs that had already finished, and its turn could not end while
they ran. In its own notes at 16:21 and 16:27 the prover says it was "still waiting on
lead or builder"; it believed it had replied. At 16:27:42 the background task stopped
and the turn closed **without the staged reply ever being posted**. The last text in the
room is the lead's handoff at 16:00:10.

The lead was waiting on that reply with nothing else in flight, so every seat was waiting
on another, and the rules allow no human to break the tie. Result: the auditor-accepted
revision `d0b69b4` stands, S-23 was never routed back to the builder, and there is no
final report.

Why the mandates missed it: every rule in them is about the *content* of a handoff
(self-contained, full hash, evidence block). None is about its *liveness*. Lessons
we would build into the next version of the mandates (not changed here, because
`mandates/` must be the ones the run used):

- *All seats:* post the reply before starting any background or watch task, and end
  every turn with no background task attached.
- *Lead:* every handoff has a reply deadline. When it passes, re-send once, then
  re-route if the work allows, and log the stall.
- *Prover:* bounded waits only, with a timeout on every wait. Never an open-ended
  follow.

For stage 2 we put the first and third of these into the **stage-2 dispatch** as a
"liveness rule" (the task, not the mandates). In stage 2 every one of the 40 replies
the seats sent was posted; none stayed staged.

### 2. The stage-2 run was cut short from outside the factory

At 18:18 the operator's helper agent stopped the seats, believing the run had finished.
No code or messages were changed. The coordinator's stage-2 report was therefore never
written. The lead had just asked the prover for one more round on the acceptance
revision `3793fd2` (one line after the fully proven `18849a9`). The dispatch's time box
allowed new work until 19:11. Lesson for operators: a stopped seat looks exactly like a
finished one, so stop a run only on the coordinator's final report.

### 3. A performance requirement measured on the wrong instrument

The builder did measure the password-hashing cost before choosing parameters: "1000
scrypt hashes … n=2^11: 2.47 s", and it noted itself that "this host is not a measured
2-vCPU container". In the 2-vCPU container the 1000-user reset took 14–18 s. The ledger
had the requirement (S-23) and the prover caught it, so the factory worked as designed up
to the routing step that the deadlock cut off. Stage 2 closed the loop: the lead carried
S-23 forward as R-202, the auditor rewrote the fix's design, and the prover timed it *in
the 2-vCPU container* (6.24–8.34 s). The lead then halved the seeded-user cost for
margin. Lesson: a performance number is measured under the stated limits or it is not
evidence. The limits cap cores, not per-core speed, and the same stage-1 code resets in
3.7 s on a desktop CPU and 14–18 s on the laptop that ran the factory.

### 4. Rehearsal findings (practice track, before the judged run)

- **A burst the service couldn't absorb, caught by the storms.** The prover's 50-wide
  storm showed `200: 44, TimeoutError: 6`. The builder reproduced it at 1,000 requests
  (`200: 949, TimeoutError: 51`), traced it to the server's listen backlog, and fixed it.
  The re-run was `200: 1000`. One green burst would have shipped it.
- **The auditor ran docker, against the task.** The task gave docker to the prover, one
  build at a time, on a shared 7 GB machine. During a review the auditor ran its own
  `docker build` anyway. The lead caught it in the room and redirected it: the auditor
  reviews by reading code and running unit tests, and cites the prover's report for
  container evidence. Lesson: a role boundary that lives only in the task is easy to
  cross; the reviewer's mandate should say what it relies on others for.
- **Host Python ≠ image Python.** Unit tests ran on the host's Python 3.14 while the image
  ships 3.12, so a green host run said little about the image. The judged dispatch names
  the 3.12 interpreter for host-side unit tests. In the judged run the builder confirmed
  it ("Host tests run only with …python3.12").

## Stand it up yourself

1. Band Desktop 0.4.10+, Docker, Python 3.12+, model access for each seat.
2. Create four local Claude Code seats named **lead**, **builder**, **prover**,
   **auditor**, each with its working directory set to the absolute path of your result
   repository and its permissions set so it can run shell, git and docker without
   asking (a prompt stalls an unattended run). Use each one's file from `mandates/` as its
   instructions, and put the real model id on each file's `Model:` line.
3. Create a room, add all four, confirm each `@handle` gets a reply.
4. Send `@lead` one task: the spec's path, the result repository's path, a delivery
   contract, the machine's limits and a time box. Then leave the room alone until the
   lead's final report.
