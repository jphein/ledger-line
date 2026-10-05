#!/usr/bin/env bash
# Prover round for stage 2:
#   verification/stage-2/round.sh <revision> <n> [extra pytest args for the stage-2 suite]
# Steps (one container at a time, named df-prover-<n>[-suffix], all removed on exit):
#   1. clean archive of <revision> (stage-1/ and stage-2/)
#   2. stage-1 image -> stage-1 export bundle for R-231/D-211 (written to /tmp only)
#   3. docker build -t df-s2 stage-2 ; --network none health probe via docker exec (R-02/R-04)
#   4. default-port check without PORT (R-03)
#   5. isolated serve (internal network, --cpus 2 --memory 2g, -e PORT) and:
#      a. carried-forward stage-1 suite (verification/stage-1, unchanged) minus tests
#         superseded by stage-2 amendments (R-206 adds /me fields)
#      b. stage-2 suite (API, storms, UI)
set -euo pipefail
REV=${1:?revision}; N=${2:?n}; shift 2
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
PY=${PY:-/home/jp/band/dark-factory-wearedevs/.venv/bin/python}
FULL=$(git -C "$REPO" rev-parse "$REV^{commit}")
SRC=/tmp/df-prover-src2-${FULL:0:12}
NET=df-prover-net
NAME=df-prover-$N
APP_PORT=9123
OUT=${OUT:-/tmp/df-prover-out2-${FULL:0:12}-$N}
mkdir -p "$OUT"
cleanup() { docker rm -f "$NAME" "$NAME-s1" "$NAME-none" "$NAME-default" >/dev/null 2>&1 || true; }
trap cleanup EXIT

ip_of() { docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$1"; }
wait_health() {  # url budget
  local t0 now; t0=$(date +%s.%N)
  while :; do
    if curl --noproxy '*' -fsS -m 2 "$1" 2>/dev/null | grep -q '"status"'; then
      now=$(date +%s.%N); echo "$now - $t0" | bc; return 0; fi
    now=$(date +%s.%N); (( $(echo "$now - $t0 > $2" | bc) )) && return 1; sleep 0.25
  done
}

echo "== revision $FULL"
rm -rf "$SRC" && mkdir -p "$SRC"
git -C "$REPO" archive "$FULL" stage-1 stage-2 | tar -x -C "$SRC"
docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET" >/dev/null

echo "== stage-1 export bundle (R-231)"
docker build -q -t df-prover-s1img "$SRC/stage-1" >/dev/null
docker run -d --name "$NAME-s1" --network "$NET" --cpus 2 --memory 2g -e PORT=$APP_PORT df-prover-s1img >/dev/null
IP=$(ip_of "$NAME-s1"); wait_health "http://$IP:$APP_PORT/health" 60 >/dev/null
POCKETFUL_URL="http://$IP:$APP_PORT" "$PY" "$REPO/verification/stage-2/make_s1_export.py" "$OUT/s1-export.json"
docker rm -f "$NAME-s1" >/dev/null

echo "== docker build -t df-s2 stage-2 (no cache)"
docker build --no-cache -q -t df-s2 "$SRC/stage-2" | tee "$OUT/build.txt"

echo "== --network none health probe"
docker run -d --network none --cpus 2 --memory 2g -e PORT=8080 --name "$NAME-none" df-s2 >/dev/null
T0=$(date +%s.%N); OKP=""
for i in $(seq 1 240); do
  if out=$(docker exec "$NAME-none" python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8080/health').read())" 2>/dev/null); then
    echo "PASS R-04 network-none health $out after $(echo "$(date +%s.%N) - $T0" | bc)s"; OKP=1; break; fi
  sleep 0.25
done
[ -n "$OKP" ] || { echo "FAIL R-04 no health within 60s"; docker logs "$NAME-none" | tail -30; exit 3; }
docker rm -f "$NAME-none" >/dev/null

echo "== R-03 default port"
docker run -d --name "$NAME-default" --network "$NET" --cpus 2 --memory 2g df-s2 >/dev/null
IP=$(ip_of "$NAME-default")
if T=$(wait_health "http://$IP:8080/health" 60); then echo "PASS R-03 :8080 after ${T}s"; else echo "FAIL R-03"; fi
docker rm -f "$NAME-default" >/dev/null

echo "== isolated serve"
docker run -d --name "$NAME" --network "$NET" --cpus 2 --memory 2g -e PORT=$APP_PORT df-s2 >/dev/null
IP=$(ip_of "$NAME")
T=$(wait_health "http://$IP:$APP_PORT/health" 60) && echo "PASS R-04 healthy after ${T}s" || { echo "FAIL R-04"; exit 3; }
URL="http://$IP:$APP_PORT"

set +e
echo "== carried-forward stage-1 suite against stage-2"
( cd "$REPO/verification/stage-1" && POCKETFUL_URL=$URL "$PY" -m pytest \
    --deselect test_w2_payments.py::test_me_exact_keys \
    --deselect test_w1_model.py::test_seeded_user_me \
    --deselect test_w1_errors_auth.py::test_signup_201_shape_and_token \
    --ledger-report "$OUT/ledger-s1.json" ) 2>&1 | tee "$OUT/pytest-s1.txt" | tail -60
RC1=${PIPESTATUS[0]}
echo "== stage-2 suite"
( cd "$REPO/verification/stage-2" && POCKETFUL_URL=$URL STAGE1_EXPORT="$OUT/s1-export.json" \
    UI_SHOTS="$OUT/shots" "$PY" -m pytest --ledger-report "$OUT/ledger-s2.json" "$@" ) \
    2>&1 | tee "$OUT/pytest-s2.txt" | tail -120
RC2=${PIPESTATUS[0]}
set -e
docker logs "$NAME" > "$OUT/service.log" 2>&1 || true
echo "== outputs in $OUT (stage-1 rc=$RC1, stage-2 rc=$RC2)"
[ "$RC1" = 0 ] && [ "$RC2" = 0 ]
