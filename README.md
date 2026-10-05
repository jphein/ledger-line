# Ledger Line — a dark factory for pocketful

Entry in the WeAreDevelopers × BAND **AI Dark Factory** hackathon (lablab.ai), track
**pocketful**: a wallet and payments app where money must never be created, destroyed or
spent twice.

**Team:** Jeffrey Pine Hein ([TechEMPOWER](https://techempower.org)), plus four agent seats.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [`FACTORY.md`](FACTORY.md) | the factory: seats, flow, design choices, costs, how it catches bad work, what failed | the human |
| [`mandates/`](mandates/) | one generic mandate per seat | the human |
| [`room.json`](room.json) | the full Band Desktop room of the judged run (stages 1 and 2), downloaded unchanged | Band |
| [`stage-1/`](stage-1/) | stage 1: the JSON API, with `Dockerfile`, `RUN.md`, `LEDGER.md` and unit tests | the band |
| [`stage-2/`](stage-2/) | stage 2: `stage-1/` carried forward, plus the browser UI and holds/authorizations | the band |
| [`verification/`](verification/) | the prover's independent black-box and browser tests, per stage | the band (prover) |
| [`evidence/`](evidence/) | what the shipped checks never asked (per stage) and commit ↔ room traceability, generated from `room.json`, git and the prover's own round outputs | the human, from the band's artifacts |

Everything under `stage-*/` and `verification/` came out of the room. The git history is
pushed exactly as the seats made it, with no amend, rebase or squash. The only human
commits are the factory description and mandates before the run, the license, and the
room exports after each stage.

## Run the service

See [`stage-2/RUN.md`](stage-2/RUN.md) (or `stage-1/RUN.md`). In short: `docker build`
the folder, then run it with `-e PORT=8080 -p 8080:8080` and open
`http://localhost:8080/`. It needs no network at run time.

## Result

Checked with the event harness in **isolated mode** (internal network with no outbound
access, 2 vCPU, 2 GiB) on a fresh clone of the final revision:

| Folder | Suite 1 | Suite 2 | Next stage's suite | Claimed |
|---|---|---|---|---|
| `stage-1/` | **147/147** | fails, as it should | — | **stage 1** |
| `stage-2/` | **147/147** | **35/35** | stage 3 fails, as it should | **stage 2** |

- **Stage 1:** the prover's own suite (441 tests, each tagged with its ledger lines)
  passed 440 at the accepted revision `d0b69b4`. The one failure (S-23, below) was
  carried into stage 2 as a requirement and fixed there.
- **Stage 2:** the prover's round at `18849a9` found no product failures. Its first run
  had 5 failures (267 passed), all in the prover's own browser tests. They were fixed in
  `8fba553` and re-run passing, so every machine-checkable ledger line passed. The acceptance revision `3793fd2` changes one
  line after it (the password-hashing cost for seeded users) and was accepted by the
  auditor.
- The factory caught and fixed real defects before acceptance in both stages. In stage
  1 there was a crash on huge numbers and replays compared at 28 digits. In stage 2 the
  feed showed only the first 50 payments, and a hold's expiry was clamped with
  floating-point arithmetic. See FACTORY.md.

### Disclosures

- **Stage 1 has no final report from the lead.** The run deadlocked at 16:10: the
  prover's result message was staged but never posted. FACTORY.md, "What we tried
  that failed", has the details from the room log.
- **Stage 2 was dispatched separately into the same room**, as the participant guide
  allows ("you may dispatch each stage separately"). After the stage-1 deadlock, a
  generic liveness rule went into the **stage-2 dispatch**, not into the mandates: never
  leave a blocking command attached to a turn, wait only with a timeout, and end every
  turn so replies post. The mandates are unchanged.
- **The stage-2 run was cut short, and the coordinator's stage-2 report was never
  written.** The operator's helper agent stopped the seats at 18:18, believing the
  run had finished. No code or messages were changed. At that moment the lead had
  just asked the prover for one more round on `3793fd2`.

### Known limits

- **S-23, reset with a 1000-user fixture (spec limit 10 s), depends on the CPU.** We
  timed 1000 *distinct* passwords in a 2-vCPU, 2 GiB container:

  | | Desktop CPU (Ryzen 9 3900X) | Laptop CPU (i5-8365U, with the factory running) |
  |---|---|---|
  | `stage-1/` | 3.7–3.9 s | 14–18 s (fails) |
  | `stage-2/` | 1.8 s | 6.2–8.3 s at the earlier cost; stage 2 then halved the seeded-user cost |

  The container's CPU limit caps cores, not per-core speed, so a slow grading machine can
  still exceed 10 s with `stage-1/`. `stage-2/` lowers the scrypt cost for
  *fixture-seeded* users to n=2¹⁰; signups keep n=2¹¹.
- **Fixture password hashing (stage 2):** to make a 1000-user reset fast, users seeded
  with the *same* password share one scrypt derivation, made per user by an outer
  salted SHA-256. This affects only the unauthenticated test-reset endpoint's fixture
  users; real signups hash individually.
- Stages 3 and 4 were not attempted.

## Video and slides

- Video: https://youtu.be/WMwBttawW9M (narrated walkthrough of stages 1 and 2, with the room recording and the band-built UI; synthetic voice, Azure DragonHD). Stage-1-only cut: https://youtu.be/pRyQLyAkll8
- Slides: `ledger-line-slides-v2.pdf` (in the submission)

## License

MIT, see [LICENSE](LICENSE).
