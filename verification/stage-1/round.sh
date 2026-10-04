#!/usr/bin/env bash
# Prover round: clean build of a revision, isolated serve, health timing, suite run.
#
#   verification/stage-1/round.sh <revision> <n> [pytest args...]
#
# Band docker rules: one container or build at a time, containers named df-prover-<n>,
# every container removed when its check ends (trap below).
#
# Ledger lines: R-01 (build from RUN.md folder), R-02 (internal network, no outbound,
# --cpus 2 --memory 2g, -e PORT), R-03 (default port 8080 without PORT), R-04 (health
# within 60 s).
set -euo pipefail

REV=${1:?revision}
N=${2:?container number}
shift 2
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
PY=${PY:-/home/jp/band/dark-factory-wearedevs/.venv/bin/python}
FULL=$(git -C "$REPO" rev-parse "$REV^{commit}")
SHORT=${FULL:0:12}
SRC=/tmp/df-prover-src-$SHORT
IMG=df-prover-img:$SHORT
NAME=df-prover-$N
NET=df-prover-net
APP_PORT=9123
OUT=${OUT:-/tmp/df-prover-out-$SHORT-$N}
mkdir -p "$OUT"

cleanup() { docker rm -f "$NAME" "$NAME-default" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== revision $FULL"
rm -rf "$SRC" && mkdir -p "$SRC"
git -C "$REPO" archive "$FULL" stage-1 | tar -x -C "$SRC"
test -f "$SRC/stage-1/Dockerfile" || { echo "FAIL R-01: no stage-1/Dockerfile"; exit 2; }
test -f "$SRC/stage-1/RUN.md" || { echo "FAIL R-01: no stage-1/RUN.md"; exit 2; }

echo "== clean build (no cache)"
docker build --no-cache -q -t "$IMG" "$SRC/stage-1" | tee "$OUT/build.txt"

docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET" >/dev/null

wait_health() {  # url, budget seconds -> prints elapsed seconds or fails
  local url=$1 budget=$2 t0 now
  t0=$(date +%s.%N)
  while :; do
    if curl -fsS -m 2 "$url" 2>/dev/null | grep -q '"status"'; then
      now=$(date +%s.%N); echo "$now - $t0" | bc; return 0
    fi
    now=$(date +%s.%N)
    if (( $(echo "$now - $t0 > $budget" | bc) )); then return 1; fi
    sleep 0.25
  done
}

echo "== R-03 default port (no PORT env)"
docker run -d --name "$NAME-default" --network "$NET" --cpus 2 --memory 2g "$IMG" >/dev/null
IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$NAME-default")
if T=$(wait_health "http://$IP:8080/health" 60); then
  echo "PASS R-03 default port 8080 healthy after ${T}s"
else
  echo "FAIL R-03 no health on :8080 without PORT"; docker logs "$NAME-default" | tail -20
fi
docker rm -f "$NAME-default" >/dev/null

echo "== R-02/R-04 isolated serve: internal network, 2 vCPU, 2 GiB, PORT=$APP_PORT"
START=$(date +%s.%N)
docker run -d --name "$NAME" --network "$NET" --cpus 2 --memory 2g \
  -e PORT=$APP_PORT "$IMG" >/dev/null
IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$NAME")
if T=$(wait_health "http://$IP:$APP_PORT/health" 60); then
  echo "PASS R-04 healthy after ${T}s (PORT honoured, no outbound network)"
else
  echo "FAIL R-04 not healthy within 60s"; docker logs "$NAME" | tail -40; exit 3
fi
curl -sS -i "http://$IP:$APP_PORT/health" | tee "$OUT/health.txt"; echo

echo "== suite against http://$IP:$APP_PORT"
cd "$(dirname "$0")"
set +e
POCKETFUL_URL="http://$IP:$APP_PORT" "$PY" -m pytest --ledger-report "$OUT/ledger.json" "$@" \
  2>&1 | tee "$OUT/pytest.txt"
RC=${PIPESTATUS[0]}
set -e
docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' "$NAME" || true
docker logs "$NAME" > "$OUT/service.log" 2>&1 || true
echo "== outputs in $OUT (rc=$RC)"
exit "$RC"
