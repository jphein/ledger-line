# Prover suite — stage 1

Black-box tests derived from `stage-1/LEDGER.md` and the stage-1 spec only.

- Full round on a revision (clean build, default-port check, isolated serve with
  `--network internal --cpus 2 --memory 2g`, health timing, suite):
  `verification/stage-1/round.sh <rev> <n> [pytest args]`
- Against an already running service:
  `POCKETFUL_URL=http://127.0.0.1:18080 python -m pytest verification/stage-1 [--lines R-41..R-75,I-03]`

Each test carries `@pytest.mark.ledger(...)`; the run ends with a per-line PASS/FAIL table.
Conventions checked on every response (5xx, >5 s, Content-Type, error shape, 204 body,
id length, RFC 3339) are reported against R-05/R-07/R-08/R-10/R-21/R-30/S-16/I-08.
Storms run 50 in flight and repeat 5 times each.
