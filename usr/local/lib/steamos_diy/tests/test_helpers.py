"""Regression test for the helper shims' ImportError/SystemExit fallback.

utils.py's own module-level C-Core load failure raises SystemExit(127),
not ImportError -- previously invisible to each shim's `except
ImportError` handler, so a missing/broken libcore.so (e.g. mid-upgrade,
a corrupted install) made every "self-sufficient" shim exit 127 instead
of its documented fallback code (0 or 7), confusing Steam's own update
UI instead of letting it treat the call as simulated/up-to-date.

All 5 shims in helpers/ share the identical try/except shape;
steamos-update.py is exercised here as the representative case per
KISS/rule-of-three."""

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
