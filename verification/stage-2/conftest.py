"""Stage-2 prover suite configuration.

Reuses the stage-1 ledger machinery (markers, --lines, per-line report) unchanged by loading
verification/stage-1/conftest.py under another module name and re-exporting its hooks.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
S1 = HERE.parent / "stage-1"
sys.path.insert(0, str(S1))
sys.path.insert(0, str(HERE))

_spec = importlib.util.spec_from_file_location("s1_conftest", S1 / "conftest.py")
_s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_s1)

pytest_addoption = _s1.pytest_addoption
pytest_configure = _s1.pytest_configure
pytest_collection_modifyitems = _s1.pytest_collection_modifyitems
pytest_runtest_makereport = _s1.pytest_runtest_makereport
pytest_terminal_summary = _s1.pytest_terminal_summary
