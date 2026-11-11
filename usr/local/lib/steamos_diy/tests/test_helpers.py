"""Regression tests for the helpers/ shims.

Covers two independent things:

1. The ImportError/SystemExit fallback shared by all 5 shims. A failed
   C-Core load in utils.py raises SystemExit(127), not ImportError: with
   only `except ImportError`, a broken libcore.so made every shim exit
   127 instead of its fallback code (0 or 7). steamos-update.py stands
   in for all five (scripts check that they share the template).

2. steamos-select-branch.py's -c/-l stdout contract (see the dedicated
   comment block below)."""

import runpy
import sys
from pathlib import Path

import pytest

_HELPERS_DIR = Path(__file__).resolve().parent.parent / "helpers"


def test_steamos_update_shim_falls_back_when_utils_load_fails(monkeypatch):
    def _broken_cdll(*_a, **_k):
        raise OSError("libcore.so missing")

    monkeypatch.setattr("ctypes.CDLL", _broken_cdll)
    # Force a fresh (failing) import inside the shim instead of reusing
    # the already-cached, conftest-mocked utils module; restored in
    # `finally` so later tests' own `utils` module-object reference
    # (bound at collection time) isn't left pointing at a stale entry.
    original_utils = sys.modules.pop("utils", None)
    try:
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(
                str(_HELPERS_DIR / "steamos-update.py"), run_name="not_main"
            )
        assert exc_info.value.code == 7
    finally:
        sys.modules.pop("utils", None)
        if original_utils is not None:
            sys.modules["utils"] = original_utils


# ---------------------------------------------------------------------------
# steamos-select-branch.py -c/-l — Steam reads the answer from stdout for
# its update-channel UI, and runs -c at every Game Mode start. -c/-l get a
# plain "stable" on stdout; a branch-switch request (any other argv) is
# only logged, nothing on stdout.
# ---------------------------------------------------------------------------

_SELECT_BRANCH = _HELPERS_DIR / "steamos-select-branch.py"


@pytest.mark.parametrize("flag", ["-c", "-l"])
def test_select_branch_prints_fake_branch_on_stdout(
    monkeypatch, capsys, flag
):
    monkeypatch.setattr(sys, "argv", ["steamos-select-branch", flag])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(_SELECT_BRANCH), run_name="__main__")
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == "stable\n"


def test_select_branch_switch_request_prints_nothing_to_stdout(
    monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["steamos-select-branch", "beta"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(_SELECT_BRANCH), run_name="__main__")
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""
