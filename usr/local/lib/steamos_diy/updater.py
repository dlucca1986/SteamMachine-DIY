#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      2.1.5
# DESCRIPTION:  Control Center updater UI: check, download, Konsole handoff.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/updater.py
# LICENSE:      MIT
# =============================================================================
"""

import shlex
import threading
from pathlib import Path

# pylint: disable=no-name-in-module
from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QPushButton

# pylint: enable=no-name-in-module

from utils import (
    UPDATES_DIR_NAME,
    USER_CONFIG_REL,
    VERSION,
    check_latest_release,
    download_release,
    spawn_native,
)

_IDLE_LABEL: str = "⬆️ Check for Updates"
_RELEASES_URL: str = (
    "https://github.com/dlucca1986/SteamMachine-DIY/releases"
)


# One deliberate entry point (check); the rest of the flow is signal-
# driven internals. Splitting it further would only scatter the feature.
# pylint: disable-next=too-few-public-methods
class UpdateManager(QObject):
    """Qt side of the in-app updater, mounted by the Maintenance tab.

    Owns its button (repurposed as a progress indicator while workers
    run) and drives the whole flow: release check → offer dialog →
    tarball download → installer handoff to a visible Konsole window.
    The no-Qt plumbing (API query, download, extraction) lives in
    utils.py; only presentation and threading glue live here.
    """

    _check_ready = pyqtSignal(object)  # ReleaseInfo | None
    _download_ready = pyqtSignal(object)  # extracted Path | None

    def __init__(self, window, button_style: str):
        super().__init__(window)
        self._win = window
        self._dest_root = Path.home() / USER_CONFIG_REL / UPDATES_DIR_NAME
        self.button = QPushButton(_IDLE_LABEL)
        self.button.setStyleSheet(button_style)
        self.button.clicked.connect(self.check)
        self._check_ready.connect(self._on_check)
        self._download_ready.connect(self._on_download)

    # ── Workers (daemon threads → signals) ────────────────────────────────

    def check(self):
        """Query GitHub for the latest release in a daemon thread."""
        self._set_busy("⏳ Checking for updates…")

        def worker() -> None:
            self._check_ready.emit(check_latest_release())

        threading.Thread(target=worker, daemon=True).start()

    def _download(self, info):
        """Fetch and unpack the release tarball in a daemon thread."""
        self._set_busy(f"⏳ Downloading v{info.version}…")

        def worker() -> None:
            self._download_ready.emit(
                download_release(info, self._dest_root)
            )

        threading.Thread(target=worker, daemon=True).start()

    # ── Button state ──────────────────────────────────────────────────────

    def _set_busy(self, label):
        self.button.setEnabled(False)
        self.button.setText(label)

    def _set_idle(self):
        self.button.setEnabled(True)
        self.button.setText(_IDLE_LABEL)

    # ── Result handlers (main thread) ─────────────────────────────────────

    def _on_check(self, info):
        """Route the check result to the matching dialog."""
        self._set_idle()
        if info is None:
            QMessageBox.warning(
                self._win,
                "Update Check",
                "Could not reach GitHub — check your connection.",
            )
        elif not info.is_newer:
            QMessageBox.information(
                self._win,
                "Update Check",
                f"You are up to date (v{VERSION}).",
            )
        else:
            self._offer(info)

    def _offer(self, info):
        """Present the newer release: download & install, or open its page."""
        box = QMessageBox(self._win)
        box.setWindowTitle("Update Available")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"<b>Version {info.version} is available</b>"
            f" — installed: v{VERSION}."
        )
        if info.notes.strip():
            box.setDetailedText(info.notes.strip())
        dl_btn = box.addButton(
            "Download && Install", QMessageBox.ButtonRole.AcceptRole
        )
        page_btn = box.addButton(
            "Open Release Page", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is dl_btn:
            self._download(info)
        elif box.clickedButton() is page_btn:
            QDesktopServices.openUrl(QUrl(info.html_url or _RELEASES_URL))

    def _on_download(self, src_dir):
        """Hand the unpacked release over to the installer in Konsole.

        The installer runs visibly in a terminal (live pacman/gcc output,
        polkit auth popup) — a long silent root operation would be both
        bad UX and undiagnosable when it fails.
        """
        self._set_idle()
        if src_dir is None:
            QMessageBox.warning(
                self._win,
                "Update Download",
                "Download failed — see the Diagnostics logs.",
            )
            return
        QMessageBox.information(
            self._win,
            "Installing Update",
            "The installer will now run in a terminal window.\n"
            "The system reboots automatically when it completes.",
        )
        # Absolute script path: pkexec starts programs in root's home,
        # so a relative ./install.sh would not resolve (the installer
        # then cd's to its own directory for the relative deploy paths).
        script = shlex.quote(str(src_dir / "install.sh"))
        spawn_native(
            "/usr/bin/konsole",
            [
                "/usr/bin/konsole",
                "--workdir",
                str(src_dir),
                "-e",
                "bash",
                "-c",
                f"pkexec bash {script} --update; echo; "
                "read -rp 'Press ENTER to close this window...'",
            ],
        )
