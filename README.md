# Ledger Line — a dark factory for pocketful

Entry in the WeAreDevelopers × BAND **AI Dark Factory** hackathon (lablab.ai), track
**pocketful**: a wallet and payments API where money must never be created, destroyed or
spent twice.

**Team:** Jeffrey Pine Hein ([TechEMPOWER](https://techempower.org)), plus four agent seats.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [`FACTORY.md`](FACTORY.md) | the factory: seats, flow, design choices, costs, how it catches bad work, what failed | the human |
| [`mandates/`](mandates/) | one generic mandate per seat | the human |
| [`room.json`](room.json) | the full Band Desktop room of the judged run, downloaded unchanged | Band |
| [`stage-1/`](stage-1/) | the service: source, `Dockerfile`, `RUN.md`, `LEDGER.md`, unit tests | the band |
| [`verification/`](verification/) | the prover's independent black-box tests | the band (prover) |

Everything under `stage-1/` and `verification/` came out of the room. The git history is
pushed exactly as the seats made it, with no amend, rebase or squash. The only human
commits are the factory description and mandates before the run, and `room.json` after
it.

## Run the service

See [`stage-1/RUN.md`](stage-1/RUN.md). In short: `docker build` the folder, then run it
with `-e PORT=8080 -p 8080:8080`. It needs no network at run time.

## Result

- **Stage 1 claimed on the shipped checks, in isolated mode** (internal network with no
  outbound access, 2 vCPU, 2 GiB): suite 1 **147/147**, and the stage-2 suite fails as it
  should, so there is no overshoot. Checked on a fresh clone of `61b8e1e`; `stage-1/` there
  is byte-identical to `d0b69b4`, the revision the auditor accepted.
- The prover's own suite (406 tests, each tagged with its ledger lines) passed **440 of
  441** checks at `d0b69b4`, storms included.
- The factory caught and fixed real defects before acceptance. The auditor rejected
  work item W2 with two blocking findings: a request body with a huge exponent returned
  a 500, and idempotent replays compared numbers rounded to 28 digits. Both were fixed
  in `d0b69b4` and re-reviewed. See FACTORY.md.
- **There is no final report from the lead.** At 16:10 the run deadlocked: the prover's
  result message was staged but never posted, and every seat ended up waiting on another.
  FACTORY.md, "What we tried that failed", has the details from the room log.

### Known limits

- **Reset with a 1000-user fixture takes 14–18 s** in a 2-vCPU container, against the
  spec's 10 s limit for reset (ledger line S-23). The prover measured it three times
  (16.10 s, 14.61 s, 18.04 s). The likely cause is password hashing for every seeded user
  during reset. It was found by the factory, but the fix was never routed back because
  of the deadlock. We did not fix it by hand: code in `stage-1/` is the band's alone.
- Stage 1 only. Stages 2–4 were not attempted.

## Video and slides

⟨links after upload⟩

## License

MIT.
