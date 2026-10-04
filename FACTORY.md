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
| **lead** | Claude Code · ⟨model⟩ | the ledger, the plan, routing, acceptance, the final report | writes product code or tests |
| **builder** | Claude Code · ⟨model⟩ | source, Dockerfile, RUN.md, unit tests | accepts its own work; edits the prover's tests |
| **prover** | Claude Code · ⟨model⟩ | black-box tests derived from the ledger; every check run | reads product code to decide what to test; fixes code |
| **auditor** | Claude Code · ⟨model⟩ | ledger challenge; review of every revision | fixes code; rejects without a concrete defect |

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
   concurrency sentence to be named before anyone builds. *Cost:* 10–20 minutes before
   the first line of code, and a ledger that can reach 100+ lines.
2. **The auditor challenges the ledger first.** A missed requirement costs nothing to add
   to a ledger and a lot to discover after the build. *Cost:* one extra round trip.
3. **The prover is independent by construction.** It derives tests from the ledger, not
   from the code, and owns a folder nobody else edits. That keeps one seat from being both
   author and judge. *Cost:* some duplication with the builder's unit tests, on purpose.
4. **Invariant storms, five repeats.** Concurrency bugs are probabilistic, so one green
   burst proves little. Each invariant gets a burst of conflicting, duplicated and
   replayed requests at the top allowed concurrency, then an exact read-back, five
   times. *Cost:* minutes of wall clock per round.
5. **Acceptance needs the same revision twice.** The prover's pass and the auditor's
   accept must name the same full commit hash, so a fix that slips in after review
   cannot ship. *Cost:* a re-check after every fix.
6. **Self-contained handoffs.** Seats see only what is addressed to them, so every handoff
   pastes the requirements in full, in numbered parts if needed. *Cost:* long messages,
   which beat a seat that guesses.
7. **Three strikes, then re-plan.** The third rejection of the same item makes the lead
   split it or change approach and log why, instead of looping.

## How it catches bad work

| Bad result | Caught by | Evidence it leaves |
|---|---|---|
| A requirement nobody built | ledger + auditor's challenge | a ledger line with no passing test |
| A race that passes once | prover's storms ×5 | the failing burst and its read-back |
| Code shaped to a sample check | auditor, item 2 of its review | a blocking finding naming the branch |
| A service that needs the network at run time | prover's clean, network-less build | a failed health check |
| Work ahead of the stage boundary | ledger boundary + auditor scope check | a scope finding |
| A fix that lands after review | same-hash acceptance rule | mismatched hashes in the room |

## Measured on the judged run

⟨fill from room.json and git log after the run⟩

| Measure | Value |
|---|---|
| Dispatch → stage 1 accepted | ⟨hh:mm⟩ |
| Work items / rejections that changed the work | ⟨n⟩ / ⟨n⟩ |
| Commits per seat | lead ⟨n⟩ · builder ⟨n⟩ · prover ⟨n⟩ · auditor ⟨n⟩ |
| Messages per seat | ⟨n⟩ each |
| Model spend | ⟨tokens or $, per seat⟩ |
| Sample checks, isolated mode | ⟨claimed stage: 1⟩ |

## What we tried that failed

⟨fill: rehearsal findings, e.g. handoffs that pointed at a message id instead of
pasting the requirement, and what changed in the mandates because of it⟩

## Stand it up yourself

1. Band Desktop 0.4.10+, Docker, Python 3.12+, model access for each seat.
2. Create four local Claude Code seats named **lead**, **builder**, **prover**,
   **auditor**, each with its working directory set to the absolute path of your result
   repository, and paste each one's file from `mandates/` as its instructions. Put the
   real model id on each file's `Model:` line.
3. Create a room, add all four, confirm each `@handle` gets a reply.
4. Send `@lead` one task: the spec's path, the result repository's path, a delivery
   contract and a time box. Then leave the room alone until the lead's final report.
