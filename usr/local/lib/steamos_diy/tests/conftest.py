"""Shared pytest fixtures for the steamos_diy test suite.

Two problems every test in this package would otherwise hit:

1. utils.py loads libcore.so via ctypes.CDLL at import time and calls
   sys.exit(127) if it's missing — real hardware only. ctypes.CDLL is
   patched below, before any test module imports utils/backup/etc., so
   the whole suite runs on any machine.
2. utils.get_ssot_var() caches the SSoT file in a module-level dict the
   first time it's read. Tests must not leak that cache (or the
   os.environ mirror _load_ssot_cache populates) into each other.
"""

import ctypes
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_STEAMOS_DIY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_STEAMOS_DIY_DIR))

# Must happen before the first `import utils` anywhere in the suite.
_FAKE_CORE_LIB = MagicMock(name="fake_libcore")
ctypes.CDLL = lambda path, *a, **kw: _FAKE_CORE_LIB  # noqa: ARG005


@pytest.fixture(autouse=True)
def _isolate_ssot_cache(tmp_path, monkeypatch):
    """Reset utils' SSoT cache/env around every test; point it at nothing.

    Without this, the first get_ssot_var() call in *any* test would try
    to parse the real /etc/default/steamos_diy.conf on whatever machine
    runs the suite — hermetic by default; tests that need specific
    values use the set_ssot fixture instead.
    """
    import utils  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(
        utils, "SSOT_CONF_PATH", str(tmp_path / "unused_ssot.conf")
    )
    env_snapshot = dict(os.environ)
    utils.clear_ssot_cache()
    yield
    utils.clear_ssot_cache()
    os.environ.clear()
    os.environ.update(env_snapshot)


@pytest.fixture
def set_ssot():
    """Seed the SSoT cache directly, bypassing file I/O.

    Usage: set_ssot(BACKUP_KEEP="3", user_config="/tmp/x/config.yaml")
    """
    import utils  # pylint: disable=import-outside-toplevel

    def _set(**values: str) -> None:
        utils._SSOT_CACHE.update(  # pylint: disable=protected-access
            {k: str(v) for k, v in values.items()}
        )
        utils._SSOT_LOADED[0] = True  # pylint: disable=protected-access

    return _set
