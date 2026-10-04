# Ledger Line — a dark factory for pocketful

Entry in the WeAreDevelopers × BAND **AI Dark Factory** hackathon (lablab.ai), track
**pocketful**: a wallet and payments API where money must never be created, destroyed or
spent twice.

**Team:** Jeffrey Pine Hein ([TechEMPOWER](https://techempower.org)), plus four agent seats.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [`FACTORY.md`](FACTORY.md) | the factory: seats, flow, design choices, costs, how it catches bad work | the human |
| [`mandates/`](mandates/) | one generic mandate per seat | the human |
| [`room.json`](room.json) | the full Band Desktop room of the judged run, downloaded unchanged | Band |
| [`stage-1/`](stage-1/) | the service: source, `Dockerfile`, `RUN.md`, `LEDGER.md` | the band |
| `verification/` | the prover's independent black-box tests | the band (prover) |
| ⟨`stage-2/`⟩ | ⟨only if accepted in the run⟩ | the band |

Everything under `stage-*/` and `verification/` came out of the room. The git history is
pushed exactly as the seats made it, with no amend, rebase or squash.

## Run the service

See [`stage-1/RUN.md`](stage-1/RUN.md). In short: `docker build` the folder, then run it
with `-e PORT=8080 -p 8080:8080`. It needs no network at run time.

## Result

⟨fill: claimed stage on the shipped checks in isolated mode; ledger lines passing; the
bad result the factory caught, with the room timestamps⟩

## Video and slides

⟨links after upload⟩

## License

MIT.
