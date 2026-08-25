"""Tests for utils.py's SSoT numeric-value guard.

get_ssot_num() is what stands between a hand-edited SSoT typo and an
unguarded ValueError aborting the session boot (the exact failure mode
2.1.1 fixed: a malformed VALIDATION_TIMEOUT crashed run() before the
session launched, and systemd's Restart=on-failure looped until the
start-limit tripped — black TTY, no diagnostic). This pins the
degrade-to-default contract every timing parameter in the SSoT relies
on."""

import utils


def test_get_ssot_num_returns_default_when_key_missing():
    assert utils.get_ssot_num("SOME_MISSING_KEY", 2.5) == 2.5


def test_get_ssot_num_parses_valid_value(set_ssot):
    set_ssot(TERM_TIMEOUT="7.5")
    assert utils.get_ssot_num("TERM_TIMEOUT", 5.0) == 7.5


def test_get_ssot_num_falls_back_on_malformed_value(set_ssot):
    set_ssot(VALIDATION_TIMEOUT="5s")
    assert utils.get_ssot_num("VALIDATION_TIMEOUT", 3.0) == 3.0


def test_get_ssot_num_falls_back_on_empty_value(set_ssot):
    set_ssot(NOTIFY_DELAY="")
    assert utils.get_ssot_num("NOTIFY_DELAY", 0.4) == 0.4


def test_get_ssot_num_falls_back_on_stray_comma(set_ssot):
    """A decimal comma is a realistic hand-edit mistake (locale habit)."""
    set_ssot(POST_START_DELAY="2,0")
    assert utils.get_ssot_num("POST_START_DELAY", 2.0) == 2.0
