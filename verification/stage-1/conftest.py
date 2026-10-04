"""Prover suite configuration: ledger markers, line selection and the per-line report.

    pytest verification/stage-1 --lines R-01..R-40,S-14
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pf  # noqa: E402

GLOBAL_LINES = {"R-05", "R-07", "R-08", "R-10", "R-21", "R-30", "S-16", "I-08"}
_results: dict[str, dict] = defaultdict(lambda: {"pass": [], "fail": [], "skip": []})
_selected: set[str] | None = None


def expand(spec: str) -> set[str]:
    out = set()
    for part in filter(None, (p.strip() for p in spec.split(","))):
        m = re.fullmatch(r"([A-Z])-(\d+)\.\.(?:[A-Z]-)?(\d+)", part)
        if m:
            p, a, b = m.group(1), int(m.group(2)), int(m.group(3))
            out |= {f"{p}-{i:02d}" for i in range(a, b + 1)}
        else:
            out.add(part)
    return out


def pytest_addoption(parser):
    parser.addoption("--lines", default=None,
                     help="comma list of ledger lines/ranges to run, e.g. R-01..R-40,S-14")
    parser.addoption("--ledger-report", default=None, help="write per-line JSON here")


def pytest_configure(config):
    global _selected
    config.addinivalue_line("markers", "ledger(*lines): ledger lines this test covers")
    spec = config.getoption("--lines")
    _selected = expand(spec) if spec else None


def _lines(item) -> list[str]:
    out = []
    for m in item.iter_markers("ledger"):
        out.extend(m.args)
    return out


def pytest_collection_modifyitems(config, items):
    if _selected is None:
        return
    keep, drop = [], []
    for it in items:
        (keep if set(_lines(it)) & _selected else drop).append(it)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" or (rep.when == "setup" and not rep.passed):
        bucket = "pass" if rep.passed else ("skip" if rep.skipped else "fail")
        for line in _lines(item):
            _results[line][bucket].append(item.nodeid)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    lines = set(_results)
    if _selected is not None:
        lines = (lines | _selected) & (_selected | GLOBAL_LINES)
    for line, items in pf.VIOLATIONS.items():
        if _selected is None or line in _selected or line in GLOBAL_LINES:
            lines.add(line)

    def key(s):
        m = re.fullmatch(r"([A-Z])-(\d+)", s)
        return ("RIS".find(m.group(1)), int(m.group(2))) if m else (9, s)

    report = {}
    tr.section("ledger lines")
    for line in sorted(lines, key=key):
        r = _results.get(line, {"pass": [], "fail": [], "skip": []})
        v = pf.VIOLATIONS.get(line, [])
        if r["fail"] or v:
            status = "FAIL"
        elif r["pass"]:
            status = "PASS"
        elif line in GLOBAL_LINES and not v and _results:
            status = "PASS"  # checked on every response, no violation seen
        else:
            status = "NOT RUN"
        report[line] = {"status": status, "pass": len(r["pass"]), "fail": r["fail"],
                        "violations": v}
        tr.write_line(f"{line:6} {status:8} pass={len(r['pass'])} fail={len(r['fail'])}"
                      + (f" violations={len(v)}" if v else ""))
        for f in r["fail"]:
            tr.write_line(f"         - {f}")
        for d in v[:5]:
            tr.write_line(f"         ! {d}")
    passed = [k for k, x in report.items() if x["status"] == "PASS"]
    failed = [k for k, x in report.items() if x["status"] == "FAIL"]
    tr.write_line(f"ledger: {len(passed)} pass / {len(failed)} fail: {' '.join(failed)}")
    path = config.getoption("--ledger-report") or os.environ.get("LEDGER_REPORT")
    if path:
        Path(path).write_text(json.dumps(report, indent=2))
