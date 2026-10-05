"""Produce a stage-1 export bundle for the R-231 / D-211 upgrade tests.

Run against the team's stage-1 service:
    POCKETFUL_URL=http://<stage-1 ip>:<port> python make_s1_export.py /tmp/out.json

The bundle holds live tokens and hashes (a private test artifact): write it under /tmp only,
never commit it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage-1"))
import pf  # noqa: E402
from pf import ok  # noqa: E402


def main(out: str):
    w = pf.world(pf.fixture())
    body = {"to_handle": "bob", "amount": 123, "note": "before upgrade"}
    key = pf.new_key()
    payment = ok(w.ada.post("/payments", body, key=key), 201)
    failed_key = pf.new_key()
    r = w.ada.pay("bob", 10**8, key=failed_key)
    assert r.status_code == 409, r.text
    pending = ok(w.bob.ask("ada", 77, note="still payable"), 201)
    export = ok(pf.Api().get("/_test/export"))
    bundle = {"export": export, "tokens": {"ada": w.ada.token, "bob": w.bob.token},
              "payment_key": key, "payment_body": body, "payment": payment,
              "failed_key": failed_key, "pending_request_id": pending["request_id"],
              "balances": {"ada": w.ada.balance(), "bob": w.bob.balance()}}
    Path(out).write_text(json.dumps(bundle))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1])
