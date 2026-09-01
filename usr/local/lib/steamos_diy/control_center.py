#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Control Center
# VERSION:      2.1.7
# DESCRIPTION:  PyQt6 dashboard: diagnostics, maintenance and YAML editing.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/control_center.py
# LICENSE:      MIT
# =============================================================================
"""

# pylint: disable=too-many-lines  # cohesive UI god-object, splitting hurts

import html
import os
import re

# B404: importing subprocess isn't the risk — every call site below
# passes a fixed argv list, never shell=True or user-controlled input.
import subprocess  # nosec B404
import sys
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path

from editors import YAMLEditor, YAMLSyntaxHighlighter
from health import get_service_status, run_preflight
from journal import (
    fetch_gamescope_logs,
    fetch_tagged_entries,
    filter_game_journal_lines,
    parse_game_logs,
)

# PyQt6's compiled C-extension bindings aren't visible to pylint's static
# import resolution, so these genuine, existing symbols get flagged.
# pylint: disable=no-name-in-module
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# pylint: enable=no-name-in-module
from ruamel.yaml import YAML, YAMLError
from updater import UpdateManager
from utils import (
    CONFIG_FILE_NAME,
    CORE_LIB_DIR,
    GAMES_CONF_SUBDIR,
    JOURNALCTL_BIN,
    KONSOLE_BIN,
    PYTHON3_BIN,
    SSOT_CONF_PATH,
    USER_CONFIG_REL,
    VERSION,
    get_ssot_var,
    spawn_native,
    write_atomic,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# UI / network constants
_WIKI_URL: str = "https://github.com/dlucca1986/SteamMachine-DIY/wiki"

# UI dimensions
_WINDOW_WIDTH: int = 1000
_WINDOW_HEIGHT: int = 700
_BUTTON_STYLE: str = "height: 40px; text-align: left; padding-left: 15px;"
_EDITOR_FONT_SIZE: int = 10
_BUTTON_RESET_MS: int = 2000
# Redraws the whole log view (clear + one QTextEdit.append() per
# surviving line) on every keystroke otherwise - a real stutter on a
# session with hours/days of accumulated journal lines.
_LOG_FILTER_DEBOUNCE_MS: int = 200

# YAML formatter
_YAML_WIDTH: int = 4096
_YAML_INDENT_MAPPING: int = 2
_YAML_INDENT_SEQUENCE: int = 4
_YAML_INDENT_OFFSET: int = 2

# Matches the LAST parenthesised number — "Half-Life 2 (2004) (220)" → 220.
_APPID_FROM_DISPLAY = re.compile(r"\((\d+)\)\s*$")
_LOG_TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s+(.*)")


def _extract_game_name_from_display(raw: str) -> str:
    """Strip a trailing "(AppID)" suffix from a combo display string.

    _format_combo_items() only ever appends the suffix at the very end
    (same anchor as _APPID_FROM_DISPLAY), so stripping via that anchor
    instead of splitting on the first "(" avoids truncating a game name
    that legitimately contains "(" of its own, e.g. "Portal (Test Build)"
    plus an appid suffix would otherwise collide with a game named
    "Portal".
    """
    return _APPID_FROM_DISPLAY.sub("", raw).strip()


# ---------------------------------------------------------------------------
# YAML parser — Round-Trip preserves comments and quoting on save.
# ---------------------------------------------------------------------------

yaml_parser = YAML()
yaml_parser.preserve_quotes = True
yaml_parser.indent(
    mapping=_YAML_INDENT_MAPPING,
    sequence=_YAML_INDENT_SEQUENCE,
    offset=_YAML_INDENT_OFFSET,
)
yaml_parser.width = _YAML_WIDTH


# ---------------------------------------------------------------------------
# Support report — pure text assembly, no Qt (runs in a worker thread)
# ---------------------------------------------------------------------------


def _fetch_support_logs() -> list[str]:
    """Raw ALL-tag log lines (+ gamescope) for the report; never raises."""
    launches: set[str] = set()
    try:
        ents = fetch_tagged_entries("ALL", launches)
        ents.extend(fetch_gamescope_logs(launches))
    except (subprocess.SubprocessError, OSError) as err:
        return [f"(log retrieval failed: {err})"]
    if not ents:
        return ["(no project log entries in this window)"]
    ents.sort(key=lambda x: x[0])
    return [e[1] for e in ents]


def _build_support_report() -> str:
    """Assemble the full diagnostic report: system, service, preflight, logs.

    Logs are re-fetched raw with the ALL tag set — independent of the
    Diagnostics filter and without the display-side dedup collapse, so
    the file is complete and machine-greppable.
    """
    status = get_service_status()
    lines = [
        "=== SteamMachine-DIY Support Report ===",
        f"Generated: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S}",
        f"Kernel: {os.uname().release}",
        "",
        "--- Service ---",
        (
            f"steamos_diy: {status.active} ({status.sub}) | "
            f"restarts: {status.restarts} | last exit: {status.exit_code}"
        ),
        "",
        "--- Preflight ---",
    ]
    for res in run_preflight():
        mark = "PASS" if res.ok else "FAIL"
        lines.append(f"{mark} {res.name} - {res.detail}")

    lines.extend(["", "--- Logs (last 12h, all tags + gamescope) ---"])
    lines.extend(_fetch_support_logs())
    return "\n".join(lines) + "\n"


def _resolve_config_paths(default_root: Path) -> tuple[Path, Path]:
    """Resolve (conf_root, games_conf_dir) from the SSoT.

    Falls back to default_root/"config.yaml" resp.
    default_root/GAMES_CONF_SUBDIR when the SSoT doesn't set
    user_config/games_conf_dir — but when it does, this must follow it:
    sdy.py and health.py already resolve both dynamically, and a
    hardcoded default here would let the GUI silently edit a file the
    session launcher no longer reads. Kept as a pure function of
    *default_root* (no direct Path.home() call) so it's testable without
    touching the real home directory; the one call site always passes
    Path.home() / USER_CONFIG_REL, and the games_conf_dir fallback shares
    utils.GAMES_CONF_SUBDIR with utils.default_games_conf_dir() (used by
    sdy.py) so the two can't silently drift onto different subdirectory
    names.
    """
    conf_root = Path(
        get_ssot_var("user_config", str(default_root / CONFIG_FILE_NAME))
    ).parent
    games_conf_dir = Path(
        get_ssot_var(
            "games_conf_dir", str(default_root / GAMES_CONF_SUBDIR)
        )
    )
    return conf_root, games_conf_dir


def _core_script_argv(name: str, *args: str) -> list[str]:
    """argv to run a CORE_LIB_DIR script under PYTHON3_BIN.

    Collapses the [PYTHON3_BIN, CORE_LIB_DIR/name, *args] shape that used
    to be independently retyped at each of this file's 3 call sites
    (session_select.py, backup.py, restore.py) — same reasoning as
    utils.SYSTEMCTL_BIN/JOURNALCTL_BIN's own centralization comment.
    """
    return [PYTHON3_BIN, os.path.join(CORE_LIB_DIR, name), *args]


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


# One cohesive main-window object owning every tab's widgets; splitting
# it into sub-objects would scatter state without reducing complexity.
# pylint: disable=too-many-instance-attributes
class SDYControlCenter(QMainWindow):
    """Main application window: diagnostics, maintenance, YAML editors."""

    # pylint: disable=too-many-public-methods  # Qt slots + closeEvent override

    process_finished = pyqtSignal(str, str, bool)  # (title, message, is_error)
    # Fires when a lock_key's guard actually clears, so the matching
    # button(s) can be safely re-enabled — separate from process_finished
    # because a sticky timeout (see _run_pkexec) reports completion
    # without releasing the lock, so the button must stay disabled then.
    pkexec_lock_released = pyqtSignal(str)  # lock_key
    logs_ready = pyqtSignal(list, str)  # (entries, tag)
    games_detected = pyqtSignal(dict)  # {name: appid_or_name}
    preflight_ready = pyqtSignal(list)  # list[CheckResult]
    service_status_ready = pyqtSignal(object)  # ServiceStatus

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SteamMachine-DIY Control Center — v{VERSION}")
        self.resize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        self.conf_root, self.games_conf_dir = _resolve_config_paths(
            Path.home() / USER_CONFIG_REL
        )

        # Guards _run_pkexec against a second privileged operation
        # targeting the same files starting while one is already
        # running — keyed by lock_key so unrelated operations (journal
        # vacuum vs. Backup/Restore, which don't share any target file)
        # don't block each other.
        self._pkexec_busy: dict[str, bool] = {}

        # Guards _refresh_service_status against overlapping polls: its
        # subprocess.run timeout (5s) is longer than the QTimer interval
        # that calls it (4s), so without this a slow `systemctl show`
        # would let the next tick launch a second thread/subprocess
        # before the first returns, piling up under load instead of
        # simply skipping a cycle.
        self._service_status_busy = False

        # Guards refresh_detected_games against a second scan starting
        # while one is still in flight — without this, a fast second
        # scan's result could be overwritten when a slower first scan
        # (still running from an earlier click) finishes after it and
        # emits games_detected last (CLAUDE.md checklist item 17).
        self._scan_games_busy = False

        # Guards load_logs against a second fetch starting while one is
        # still in flight — on_tab_changed calls load_logs unconditionally
        # every time the Diagnostics tab is (re-)selected, so switching
        # away and back while a journalctl fetch is still running could
        # otherwise start a second worker; whichever thread's logs_ready
        # lands last would silently overwrite the other's result (same
        # class of guard as _scan_games_busy/_service_status_busy above,
        # CLAUDE.md checklist item 17).
        self._logs_busy = False

        # Populated by init_maint_tab; declared here so pylint sees it
        # set in __init__ like every other instance attribute.
        self._lock_key_buttons: dict[str, list[QPushButton]] = {}

        # Style maps — emoji + colour per log category
        self.log_styles = {
            "CORE:": ("🔵", "#3498db"),
            "STEAM:": ("🎮", "#2ecc71"),
            "SYSTEM:": ("⚙️", "#f39c12"),
            "DEBUG:": ("🔍", "#95a5a6"),
            "ERROR:": ("🚫", "#e74c3c"),
        }
        self.gs_levels = {
            "[Error]": ("❌", "#ff4444"),
            "[Warn]": ("⚠️", "#ffbb33"),
            "[Info]": ("ℹ️", "#33b5e5"),
        }

        # Tab references (populated by init_*_tab)
        self.diag_tab = None
        self.maint_tab = None
        self.global_tab = None
        self.games_tab = None
        self.tabs = None

        # Diagnostics tab widgets
        self.log_display = None
        self.tag_filter = None
        self.log_search = None
        self.copy_btn = None
        self.support_btn = None
        self._log_filter_timer = None
        self._log_text = ""  # last fetched logs, cached for live filtering

        # Global config tab widgets
        self.global_editor = None
        self.combo_global_files = None
        self.global_temp_btn = None
        self.global_save_btn = None
        self.global_hl = None

        # Games tab widgets
        self.combo_games = None
        self.game_editor = None
        self.game_temp_btn = None
        self.game_save_btn = None
        self.game_hl = None

        # Maintenance tab widgets
        self.updater = None

        # Service health strip (status bar)
        self.service_label = None
        self._service_timer = None

        # Per-tab template view state
        self.view_states = {
            "global": {"is_template": False, "cache": ""},
            "games": {"is_template": False, "cache": ""},
        }

        self._setup_ui()

        # Wire async signals
        self.process_finished.connect(self._show_completion_message)
        self.pkexec_lock_released.connect(self._on_pkexec_lock_released)
        self.logs_ready.connect(self._on_logs_ready)
        self.games_detected.connect(self._update_game_combo_ui)
        self.preflight_ready.connect(self._on_preflight_ready)
        self.service_status_ready.connect(self._on_service_status)

        # Clear error highlight on any user edit
        self.global_editor.textChanged.connect(
            lambda: self.global_editor.setExtraSelections([])
        )
        self.game_editor.textChanged.connect(
            lambda: self.game_editor.setExtraSelections([])
        )

        # Ctrl+S saves the editor on the active tab
        QShortcut(
            QKeySequence.StandardKey.Save, self, self._save_current_tab
        )

        # Service health strip + periodic refresh
        self._setup_service_strip()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tabs)
        self.init_diag_tab()
        self.init_maint_tab()
        self.init_global_tab()
        self.init_games_tab()
        self.tabs.addTab(self.diag_tab, "Diagnostics")
        self.tabs.addTab(self.maint_tab, "Maintenance")
        self.tabs.addTab(self.global_tab, "Global Options")
        self.tabs.addTab(self.games_tab, "Game Overrides")

    def on_tab_changed(self, index):
        """Reload logs when the user switches to the diagnostics tab."""
        if index == self.tabs.indexOf(self.diag_tab):
            self.load_logs()

    def _setup_service_strip(self):
        """Mount the service-health label in the status bar and poll it."""
        self.service_label = QLabel("steamos_diy: …")
        self.statusBar().addPermanentWidget(self.service_label)
        self._service_timer = QTimer(self)
        self._service_timer.timeout.connect(self._refresh_service_status)
        self._service_timer.start(4000)
        self._refresh_service_status()

    # ── Diagnostics tab ────────────────────────────────────────────────────

    def init_diag_tab(self):
        """Build the Diagnostics tab layout and wire up signals."""
        self.diag_tab = QWidget()
        layout = QVBoxLayout()
        header = QHBoxLayout()
        self.tag_filter = QComboBox()
        self.tag_filter.addItems(["ALL", "CORE", "STEAM", "SYSTEM"])
        self.tag_filter.currentTextChanged.connect(self.load_logs)
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("🔍 Filter logs…")
        self.log_search.setClearButtonEnabled(True)
        self._log_filter_timer = QTimer(self)
        self._log_filter_timer.setSingleShot(True)
        self._log_filter_timer.timeout.connect(self._apply_log_filter)
        self.log_search.textChanged.connect(self._schedule_log_filter)
        header.addWidget(QLabel("<b>Component Filter:</b>"))
        header.addWidget(self.tag_filter)
        header.addWidget(self.log_search, 1)
        layout.addLayout(header)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Monospace", _EDITOR_FONT_SIZE))
        layout.addWidget(self.log_display)
        footer = QHBoxLayout()
        self.copy_btn = QPushButton("📋 Copy to Clipboard")
        self.copy_btn.clicked.connect(self.copy_logs)
        self.support_btn = QPushButton("🛠️ Export Support Report")
        self.support_btn.clicked.connect(self.export_support_log)
        footer.addWidget(self.copy_btn)
        footer.addWidget(self.support_btn)
        footer.addStretch()
        layout.addLayout(footer)
        self.diag_tab.setLayout(layout)

    # ── Maintenance tab ────────────────────────────────────────────────────

    def init_maint_tab(self):
        """Build the Maintenance tab layout and wire up signals."""
        self.maint_tab = QWidget()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(QLabel("<b>System Management</b>"))

        # Fourth element (lock_key) is None for tools that aren't guarded
        # by _run_pkexec; the button is then never disabled/re-enabled.
        tools = [
            (
                "🎮 Switch to Steam (Game Mode)",
                lambda: spawn_native(
                    PYTHON3_BIN,
                    _core_script_argv("session_select.py", "steam"),
                ),
                None,
            ),
            ("📝 Edit System Config (SSoT)", self.edit_ssot_privileged, None),
            ("🩺 Validate Configuration", self.validate_config, None),
            (
                "🧹 Clean System Logs (Vacuum)",
                self.cleanup_logs_privileged,
                "vacuum",
            ),
            ("📦 Create Full System Backup", self.run_backup, "files"),
            ("🔄 Restore from Archive", self.run_restore, "files"),
            (
                "🖥️ Open Konsole Terminal",
                lambda: spawn_native(KONSOLE_BIN, [KONSOLE_BIN]),
                None,
            ),
            (
                "📂 Browse Config Folder",
                lambda: spawn_native(
                    "/usr/bin/xdg-open",
                    ["/usr/bin/xdg-open", str(self.conf_root)],
                ),
                None,
            ),
        ]
        # Populates self._lock_key_buttons (declared in __init__) so
        # _run_pkexec can visually disable the button(s) tied to a
        # lock_key while it's busy, then re-enable them once the guard
        # actually clears (see pkexec_lock_released's own comment) —
        # mirrors updater.py's _set_busy pattern (CLAUDE.md checklist
        # item 15) instead of leaving the only feedback a 3s status toast.
        for text, func, lock_key in tools:
            btn = QPushButton(text)
            btn.setStyleSheet(_BUTTON_STYLE)
            btn.clicked.connect(func)
            layout.addWidget(btn)
            if lock_key is not None:
                self._lock_key_buttons.setdefault(lock_key, []).append(btn)

        # Whole updater flow (check → download → Konsole handoff) lives
        # in updater.py; the tab only mounts its button.
        self.updater = UpdateManager(self, _BUTTON_STYLE)
        layout.addWidget(self.updater.button)

        wiki_btn = QPushButton("📖 Open Project Wiki (Online)")
        wiki_btn.setStyleSheet(_BUTTON_STYLE)
        wiki_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_WIKI_URL))
        )
        layout.addSpacing(20)
        layout.addWidget(QLabel("<b>Documentation & Support</b>"))
        layout.addWidget(wiki_btn)
        self.maint_tab.setLayout(layout)

    def edit_ssot_privileged(self):
        """Open SSoT in Kate, falling back to KWrite."""
        kate = "/usr/bin/kate"
        editor = kate if os.path.exists(kate) else "/usr/bin/kwrite"
        try:
            # The editor must keep running after this call returns — a
            # `with` block would wait for it to close before continuing.
            # pylint: disable=consider-using-with
            subprocess.Popen([editor, SSOT_CONF_PATH])  # nosec B603
        except OSError as err:
            QMessageBox.critical(self, "Error", f"Failed to launch: {err}")

    def cleanup_logs_privileged(self):
        """Vacuum journal via pkexec; emits process_finished."""
        self._run_pkexec(
            [JOURNALCTL_BIN, "--rotate", "--vacuum-time=1s"],
            lock_key="vacuum",
            ok_title="Logs Cleaned",
            ok_msg="Journal wiped.",
            err_title="Error",
            err_msg="Authentication or vacuum failed.",
            sticky_on_timeout=False,
        )

    def validate_config(self):
        """Run preflight checks in a daemon thread; emit preflight_ready."""

        def worker() -> None:
            try:
                self.preflight_ready.emit(run_preflight())
            # A daemon thread's uncaught exception has nowhere to go —
            # stderr is /dev/null when the app is launched detached (see
            # the journal.py aware/naive-datetime bug) — so this is the
            # last line of defense against a silently-dead worker, not a
            # substitute for catching the specific cause upstream
            # (health.py already does).
            # pylint: disable-next=broad-except
            except Exception as err:  # noqa: BLE001
                self.process_finished.emit("Preflight Error", str(err), True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_preflight_ready(self, results):
        """Render the preflight report as a colored message box."""
        rows = []
        for res in results:
            ico, col = (
                ("✅", "#2ecc71") if res.ok else ("❌", "#e74c3c")
            )
            rows.append(
                f"<span style='color:{col};'>{ico} <b>{res.name}</b></span>"
                f" — {res.detail}"
            )
        box = QMessageBox(self)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("<br>".join(rows))
        if all(r.ok for r in results):
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Preflight: PASSED")
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Preflight: ISSUES FOUND")
        box.exec()

    # ── Global Options tab ─────────────────────────────────────────────────

    def init_global_tab(self):
        """Build the Global Config tab layout and wire up signals."""
        self.global_tab = QWidget()
        layout = QVBoxLayout()
        header = QHBoxLayout()
        self.combo_global_files = QComboBox()
        self.combo_global_files.addItems(
            ["config.yaml", "config.example.yaml", "gamescope.example.yaml"]
        )
        self.combo_global_files.currentTextChanged.connect(
            self.load_global_file
        )
        header.addWidget(QLabel("<b>Target File:</b>"))
        header.addWidget(self.combo_global_files, 1)
        layout.addLayout(header)
        self.global_editor = YAMLEditor()
        self.global_editor.setFont(QFont("Monospace", _EDITOR_FONT_SIZE))
        self.global_hl = YAMLSyntaxHighlighter(self.global_editor.document())
        layout.addWidget(self.global_editor)
        btns = QHBoxLayout()
        self.global_temp_btn = QPushButton("📄 View Template")
        self.global_temp_btn.clicked.connect(
            lambda: self.toggle_template("global")
        )
        fix_btn = QPushButton("🪄 Beautify")
        fix_btn.clicked.connect(lambda: self.beautify_yaml(self.global_editor))
        self.global_save_btn = QPushButton("💾 Save Configuration")
        self.global_save_btn.clicked.connect(self.save_global_config)
        btns.addWidget(self.global_temp_btn)
        btns.addWidget(fix_btn)
        btns.addStretch()
        btns.addWidget(self.global_save_btn)
        layout.addLayout(btns)
        self.global_tab.setLayout(layout)
        self.load_global_file()

    # ── Game Overrides tab ─────────────────────────────────────────────────

    def init_games_tab(self):
        """Build the Game Profiles tab layout and wire up signals."""
        self.games_tab = QWidget()
        layout = QVBoxLayout()
        header = QHBoxLayout()
        self.combo_games = QComboBox()
        self.combo_games.setEditable(True)
        # `activated` (selection/Enter) — NOT currentTextChanged. The latter
        # fires per keystroke on an editable combo, re-scaffolding the editor
        # and discarding edits while the user is still typing a name.
        self.combo_games.activated.connect(
            lambda _i: self.load_game_file(self.combo_games.currentText())
        )
        btn_scan = QPushButton("🔍 Scan History")
        btn_scan.clicked.connect(self.refresh_detected_games)
        header.addWidget(QLabel("<b>Game ID:</b>"))
        header.addWidget(self.combo_games, 1)
        header.addWidget(btn_scan)
        layout.addLayout(header)
        self.game_editor = YAMLEditor()
        self.game_editor.setFont(QFont("Monospace", _EDITOR_FONT_SIZE))
        self.game_hl = YAMLSyntaxHighlighter(self.game_editor.document())
        layout.addWidget(self.game_editor)
        btns = QHBoxLayout()
        self.game_temp_btn = QPushButton("📄 View Template")
        self.game_temp_btn.clicked.connect(
            lambda: self.toggle_template("games")
        )
        fix_btn = QPushButton("🪄 Beautify")
        fix_btn.clicked.connect(lambda: self.beautify_yaml(self.game_editor))
        self.game_save_btn = QPushButton("💾 Save Game Profile")
        self.game_save_btn.clicked.connect(self.save_game_profile)
        btns.addWidget(self.game_temp_btn)
        btns.addWidget(fix_btn)
        btns.addStretch()
        btns.addWidget(self.game_save_btn)
        layout.addLayout(btns)
        self.games_tab.setLayout(layout)

    # ── YAML editor helpers ────────────────────────────────────────────────

    def _highlight_yaml_error(self, editor, err: Exception) -> None:
        mark = getattr(err, "problem_mark", None)
        if mark:
            self._highlight_error_line(editor, mark.line)

    def beautify_yaml(self, editor):
        """Re-format the YAML in *editor* through the round-trip parser."""
        raw = editor.toPlainText()
        if not raw.strip():
            return
        try:
            data = yaml_parser.load(raw.replace("\t", "  "))
            # A comments-only document loads as None and would dump as
            # "null", wiping the user's comments — leave it untouched.
            if data is None:
                self.statusBar().showMessage("Nothing to format", 2000)
                return
            stream = StringIO()
            yaml_parser.dump(data, stream)
            clean = stream.getvalue()
        except YAMLError as err:
            self._highlight_yaml_error(editor, err)
            self.statusBar().showMessage("Syntax error — see highlight", 3000)
            return
        if raw.strip() == clean.strip():
            self.statusBar().showMessage("Already clean", 2000)
            return
        # Single undoable edit — setPlainText would wipe the undo history;
        # the saved scroll offset keeps the view from jumping to the top.
        scroll = editor.verticalScrollBar().value()
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(clean)
        cursor.endEditBlock()
        editor.verticalScrollBar().setValue(scroll)
        hl = self.global_hl if editor is self.global_editor else self.game_hl
        hl.rehighlight()
        self.statusBar().showMessage("✨ YAML formatted", 2000)

    def toggle_template(self, context):
        """Toggle between live config and read-only template view.

        Args:
            context: "global" or "games" — selects the editor pair.
        """
        state = self.view_states[context]
        widgets = self._template_widgets_for(context)

        if state["is_template"]:
            self._exit_template_mode(state, widgets)
        else:
            self._enter_template_mode(context, state, widgets)

    def _template_widgets_for(self, context):
        if context == "global":
            return (
                self.global_editor,
                self.global_save_btn,
                self.global_temp_btn,
                self.global_hl,
            )
        return (
            self.game_editor,
            self.game_save_btn,
            self.game_temp_btn,
            self.game_hl,
        )

    def _template_path_for(self, context):
        """Derive template path for *context*; file may not exist."""
        if context == "global":
            current = self.combo_global_files.currentText()
        else:
            current = "game.example.yaml"
        fname = (
            current
            if ".example." in current
            else current.replace(".yaml", ".example.yaml")
        )
        return self.conf_root / fname

    def _enter_template_mode(self, context, state, widgets):
        editor, save_btn, tmp_btn, hl = widgets
        t_path = self._template_path_for(context)
        if not t_path.exists():
            return
        state["cache"] = editor.toPlainText()
        editor.setPlainText(t_path.read_text(encoding="utf-8"))
        tmp_btn.setText("⬅️ Back to Editor")
        state["is_template"] = True
        save_btn.setEnabled(False)
        hl.rehighlight()
        editor.document().setModified(False)

    def _exit_template_mode(self, state, widgets):
        editor, save_btn, tmp_btn, hl = widgets
        editor.setPlainText(state["cache"])
        tmp_btn.setText("📄 View Template")
        state["is_template"] = False
        save_btn.setEnabled(True)
        hl.rehighlight()
        editor.document().setModified(False)

    def _atomic_save(self, path, content, editor):
        """Validate YAML and persist via the C-Core atomic-write path."""
        editor.setExtraSelections([])
        try:
            parsed = yaml_parser.load(content)
            if parsed is not None and not isinstance(parsed, dict):
                # Matches load_yaml_safe()'s own contract (utils.py): a
                # non-mapping root degrades to {} at load time, silently
                # dropping the whole profile -- reject it here instead
                # of reporting a save that will actually vanish on the
                # next load.
                raise YAMLError(
                    "Root must be a mapping (key: value pairs), not a "
                    f"{type(parsed).__name__}."
                )
            p_obj = Path(path)
            p_obj.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(p_obj, content)
            editor.document().setModified(False)
            QMessageBox.information(self, "Success", "Configuration saved!")
        except YAMLError as exc:
            self._highlight_yaml_error(editor, exc)
            QMessageBox.critical(self, "Syntax Error", str(exc))
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def _highlight_error_line(self, editor, idx):
        sels = []
        for hex_col, off in [("#e74c3c", 0), ("#f39c12", -1)]:
            if idx + off < 0:
                continue
            sel = QTextEdit.ExtraSelection()
            col = QColor(hex_col)
            col.setAlpha(50)
            sel.format.setBackground(col)
            sel.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True
            )
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            for _ in range(idx + off):
                cursor.movePosition(cursor.MoveOperation.Down)
            sel.cursor = cursor
            sel.cursor.select(cursor.SelectionType.LineUnderCursor)
            sels.append(sel)
        editor.setExtraSelections(sels)

    def load_global_file(self):
        """Load the selected global YAML file into the editor."""
        path = self.conf_root / self.combo_global_files.currentText()
        if path.exists():
            self.global_editor.setPlainText(path.read_text(encoding="utf-8"))
            if self.global_hl:
                self.global_hl.rehighlight()
            self.global_editor.document().setModified(False)

    def save_global_config(self):
        """Atomically save the global YAML editor content to disk."""
        dest = self.conf_root / self.combo_global_files.currentText()
        self._atomic_save(
            str(dest), self.global_editor.toPlainText(), self.global_editor
        )

    def load_game_file(self, raw):
        """Load or scaffold YAML profile for the selected game.

        Args:
            raw: Combo display string — "Name (AppID)" or bare name.
        """
        if not raw or "/" in raw:
            return
        name = _extract_game_name_from_display(raw)
        path = self.games_conf_dir / f"{name}.yaml"
        if path.exists():
            self.game_editor.setPlainText(path.read_text(encoding="utf-8"))
        else:
            scaffold = self._scaffold_game_profile(raw, name)
            self.game_editor.setPlainText(scaffold)
        if self.game_hl:
            self.game_hl.rehighlight()
        self.game_editor.document().setModified(False)

    def _scaffold_game_profile(self, raw, name):
        """Build default YAML profile; includes SDY_ID header if AppID present.

        Returns YAML with STEAM_APPID header when AppID is found in *raw*,
        else a bare scaffold.
        """
        m = _APPID_FROM_DISPLAY.search(raw)
        aid = m.group(1) if m else ""
        hdr = f'# SDY_ID: {aid}\nSTEAM_APPID: "{aid}"\n' if aid else ""
        return (
            f'{hdr}# Profile for {name}\nGAME_WRAPPER: ""\n'
            f'GAME_EXTRA_ARGS: ""\nenv_vars:\n'
        )

    def save_game_profile(self):
        """Atomically save the current game profile YAML to disk."""
        raw = self.combo_games.currentText().strip()
        if not raw:
            return
        if "/" in raw:
            # Same guard as load_game_file: a "/" would escape games.d/.
            self.statusBar().showMessage(
                "Invalid game name — '/' not allowed", 3000
            )
            return
        name = _extract_game_name_from_display(raw)
        path = self.games_conf_dir / f"{name}.yaml"
        self._atomic_save(
            str(path), self.game_editor.toPlainText(), self.game_editor
        )

    # ── Unsaved-changes guard ──────────────────────────────────────────────

    def _save_current_tab(self):
        """Ctrl+S — save the editor on the active tab (skips template view)."""
        idx = self.tabs.currentIndex()
        if idx == self.tabs.indexOf(self.global_tab) and not self.view_states[
            "global"
        ]["is_template"]:
            self.save_global_config()
        elif idx == self.tabs.indexOf(self.games_tab) and not self.view_states[
            "games"
        ]["is_template"]:
            self.save_game_profile()

    def _dirty_editors(self):
        """Return the save callables of editors holding unsaved changes.

        Template views are skipped — they are read-only previews, and their
        modified flag is cleared on entry/exit so they never read as dirty.
        """
        dirty = []
        if (
            not self.view_states["global"]["is_template"]
            and self.global_editor.document().isModified()
        ):
            dirty.append(self.save_global_config)
        if (
            not self.view_states["games"]["is_template"]
            and self.game_editor.document().isModified()
        ):
            dirty.append(self.save_game_profile)
        return dirty

    # Qt override; camelCase name is mandated by QMainWindow's own API.
    def closeEvent(self, event):  # pylint: disable=invalid-name
        """Qt override: warn before discarding unsaved editor changes."""
        dirty = self._dirty_editors()
        if not dirty:
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved changes in the editor. Save before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if reply == QMessageBox.StandardButton.Save:
            for save in dirty:
                save()
        event.accept()

    # ── Game discovery (background thread) ─────────────────────────────────

    def refresh_detected_games(self):
        """Scan journal for game launches; emits games_detected when done.

        Runs journalctl directly (no shell) — pure-Python filtering avoids
        shell-injection risk when home contains metacharacters. Skips the
        scan if one is already in flight (see _scan_games_busy's comment).
        """
        if self._scan_games_busy:
            return
        self._scan_games_busy = True
        self.combo_games.setPlaceholderText("Scanning history...")
        home = os.path.expanduser("~")

        def worker() -> None:
            try:
                try:
                    # Fixed argv, no shell — see this method's docstring
                    # on why journalctl is invoked directly instead of a
                    # shell.
                    # duplicate-code: these 5 kwargs intentionally mirror
                    # journal.py::fetch_tagged_entries's own journalctl
                    # call (errors="replace" for the same binary-safe-
                    # export-format reason) — not an independent
                    # reimplementation worth extracting for 5 shared lines.
                    # pylint: disable=duplicate-code
                    res = subprocess.run(  # nosec B603
                        [
                            JOURNALCTL_BIN,
                            "--since",
                            "24 hours ago",
                            "--no-hostname",
                            "--no-pager",
                        ],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        check=True,
                        timeout=10,
                    )
                    # pylint: enable=duplicate-code
                    lines = filter_game_journal_lines(res.stdout, home)
                    detected = parse_game_logs("\n".join(lines))
                    self.games_detected.emit(detected)
                except (subprocess.SubprocessError, OSError):
                    self.games_detected.emit({})
            finally:
                self._scan_games_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _update_game_combo_ui(self, detected):
        """Repopulate combo from detected games + on-disk profiles.

        Args:
            detected: {name: appid_or_name}; empty dict triggers placeholder.
        """
        self._merge_on_disk_profiles(detected)
        items = self._format_combo_items(detected)
        self.combo_games.clear()
        if items:
            self.combo_games.addItems(items)
        else:
            self.combo_games.setPlaceholderText("Journal unavailable.")

    def _merge_on_disk_profiles(self, detected):
        gdir = self.games_conf_dir
        if not gdir.exists():
            return
        for p in gdir.glob("*.yaml"):
            detected.setdefault(p.stem, p.stem)

    @staticmethod
    def _format_combo_items(detected):
        return [
            f"{n} ({a})" if a.isdigit() and a != n else n
            for n, a in sorted(detected.items())
        ]

    # ── Logs UI flow ───────────────────────────────────────────────────────

    def load_logs(self):
        """Reload logs in a daemon thread; emits logs_ready when done.

        Skips the request if a previous fetch hasn't returned yet (see
        _logs_busy's own comment for why that's needed).
        """
        if self._logs_busy:
            return
        self._logs_busy = True
        tag = self.tag_filter.currentText().strip()

        self.log_display.setPlainText("Loading logs...")
        self.tag_filter.setEnabled(False)

        def worker() -> None:
            launches: set[str] = set()
            try:
                ents = fetch_tagged_entries(tag, launches)
                if tag in ("ALL", "STEAM"):
                    ents.extend(fetch_gamescope_logs(launches))
                ents.sort(key=lambda x: x[0])
                self.logs_ready.emit(ents, tag)
            except (subprocess.SubprocessError, OSError) as err:
                self.logs_ready.emit([], f"ERROR:{err}")
            finally:
                self._logs_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_logs_ready(self, ents, tag):
        self.tag_filter.setEnabled(True)

        if tag.startswith("ERROR:"):
            self.log_display.setPlainText(f"Log Retrieval Error: {tag[6:]}")
            return

        if ents:
            self._log_text = "\n".join(e[1] for e in ents)
            self._display_colored_logs(self._log_text)
        else:
            self._log_text = ""
            self.log_display.setPlainText(f"No {tag} activity.")

    def _schedule_log_filter(self):
        """Debounce _apply_log_filter (re)starting a single-shot timer.

        Re-rendering on every keystroke (clear + one QTextEdit.append()
        per surviving line) is a real stutter with hours/days of
        accumulated journal lines; waiting for a short pause in typing
        collapses a burst of keystrokes into one render.
        """
        self._log_filter_timer.start(_LOG_FILTER_DEBOUNCE_MS)

    def _apply_log_filter(self):
        """Re-render the cached logs honouring the search box (live filter)."""
        if self._log_text:
            self._display_colored_logs(self._log_text)

    def _apply_log_style(self, line):
        # QTextEdit.append renders rich text: escape first so a literal
        # "<...>" in a log payload displays instead of vanishing as a tag.
        # The style markers matched below contain no escapable characters.
        line = html.escape(line, quote=False)
        for tag, (ico, col) in self.log_styles.items():
            if tag in line:
                return line.replace(
                    tag, f"<b style='color:{col};'>{ico} {tag}</b>"
                )
        if "[gamescope]" in line:
            return self._style_gamescope_line(line)
        return line

    def _style_gamescope_line(self, line):
        line = line.replace(
            "[gamescope]", "<b style='color:#1abc9c;'>[gamescope]</b>"
        )
        for lvl, (ico, col) in self.gs_levels.items():
            if lvl in line:
                line = line.replace(
                    lvl,
                    f"<span style='color:{col};'>{ico} {lvl}</span>",
                )
        if "LAUNCH_ARGS" in line:
            line = line.replace(
                "LAUNCH_ARGS",
                "🚀 <b style='color:#2ecc71;'>LAUNCH_ARGS</b>",
            )
        return line

    def _display_colored_logs(self, logs):
        self.log_display.clear()
        query = self.log_search.text().strip().lower()
        lines, last, count, shown = logs.strip().split("\n"), None, 1, 0

        def flush(c):
            if c > 1:
                self.log_display.append(
                    f"&nbsp;&nbsp;&nbsp;&nbsp;<i style='color:#7f8c8d;'>"
                    f"⤷ Repeated {c} times</i>"
                )

        for line in lines:
            if query and query not in line.lower():
                continue
            m = _LOG_TIMESTAMP_RE.search(line)
            pure = m.group(1) if m else line
            if pure == last:
                count += 1
                continue
            flush(count)
            count, last = 1, pure
            self.log_display.append(self._apply_log_style(line))
            shown += 1
        flush(count)
        if query and shown == 0:
            self.log_display.append(
                "<i style='color:#7f8c8d;'>No lines match the filter.</i>"
            )

    def copy_logs(self):
        """Copy the log display content to the system clipboard."""
        txt = self.log_display.toPlainText()
        if txt:
            QApplication.clipboard().setText(txt)
            self.copy_btn.setText("✅ Copied!")
            QTimer.singleShot(
                _BUTTON_RESET_MS,
                lambda: self.copy_btn.setText("📋 Copy to Clipboard"),
            )

    def export_support_log(self):
        """Save a full support report (service, preflight, raw logs).

        Unlike the clipboard copy, this does not export the on-screen
        view: the report is rebuilt from scratch in a worker thread so
        it is complete regardless of the active filter.
        """
        now = datetime.now().astimezone()
        default = f"sdy_support_{now:%Y%m%d_%H%M%S}.log"
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Support Report", default
        )
        if not dest:
            return

        def worker() -> None:
            try:
                Path(dest).write_text(
                    _build_support_report(), encoding="utf-8"
                )
                self.process_finished.emit(
                    "Support Report", f"Saved: {dest}", False
                )
            except OSError as err:
                self.process_finished.emit("Save Error", str(err), True)

        threading.Thread(target=worker, daemon=True).start()

    # ── Async result handlers ─────────────────────────────────────────────

    def _show_completion_message(self, title, message, is_error):
        if is_error:
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.information(self, title, message)

    def _on_pkexec_lock_released(self, lock_key: str) -> None:
        """Re-enable the button(s) tied to *lock_key* (main-thread slot)."""
        for btn in self._lock_key_buttons.get(lock_key, []):
            btn.setEnabled(True)

    def _refresh_service_status(self):
        """Fetch service status off-thread; emit service_status_ready.

        Skips the tick if a previous poll hasn't returned yet (see
        _service_status_busy's own comment for why that's needed).
        """
        if self._service_status_busy:
            return
        self._service_status_busy = True

        def worker() -> None:
            try:
                self.service_status_ready.emit(get_service_status())
            finally:
                self._service_status_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_service_status(self, status):
        """Update the status-bar strip from a ServiceStatus snapshot."""
        col = {"active": "#2ecc71", "failed": "#e74c3c"}.get(
            status.active, "#95a5a6"
        )
        self.service_label.setText(
            f"<span style='color:{col};'>●</span> steamos_diy: "
            f"{status.active} ({status.sub}) · restarts: "
            f"{status.restarts} · last exit: {status.exit_code}"
        )

    # ── Privileged operations ─────────────────────────────────────────────

    # pylint: disable=too-many-arguments
    # 5 logical inputs (cmd + 4 status strings). The status strings are
    # keyword-only so call sites stay self-documenting; collapsing them
    # into a tuple/dataclass would hurt clarity more than it would help.
    def _run_pkexec(
        self,
        cmd: list[str],
        *,
        lock_key: str,
        ok_title: str,
        ok_msg: str,
        err_title: str,
        err_msg: str,
        sticky_on_timeout: bool = True,
    ) -> None:
        """Run *cmd* under pkexec in a daemon thread; emit process_finished.

        Single entry point for every privileged operation in the UI —
        journal vacuum, backup, and restore all route through here. Guarded
        by _pkexec_busy[lock_key] so two privileged operations that target
        the same files (Backup and Restore, both lock_key="files") can
        never run concurrently — but an operation that shares no files with
        either (journal vacuum, lock_key="vacuum") never blocks or is
        blocked by them. The 300s timeout budget includes however long the
        user takes at the polkit password prompt, not just cmd's own
        runtime — for Backup/Restore that time is deliberately left "stuck"
        on timeout (see sticky_on_timeout below), since the underlying
        script may genuinely still be writing files.
        """
        if self._pkexec_busy.get(lock_key):
            self.statusBar().showMessage(
                "Another privileged operation is already running…", 3000
            )
            return
        self._pkexec_busy[lock_key] = True
        for btn in self._lock_key_buttons.get(lock_key, []):
            btn.setEnabled(False)

        def worker() -> None:
            # Left True (never reset in the finally below) only on a
            # timeout when sticky_on_timeout is set — every other outcome,
            # expected or not, always resets it, so an exception this code
            # doesn't even know to expect can't leave the guard silently
            # stuck.
            timed_out = False
            try:
                # cmd's elements are always either fixed literals or a
                # single whole GUI-provided value passed as its own list
                # entry (e.g. run_restore's QFileDialog path) — never
                # built by concatenating GUI input into a larger token
                # (see checklist item 20 in CLAUDE.md). No shell is
                # invoked, so that's safe. Generous timeout: backup/
                # restore can legitimately take minutes, not seconds.
                subprocess.run(  # nosec B603
                    ["/usr/bin/pkexec", *cmd], check=True, timeout=300
                )
                self.process_finished.emit(ok_title, ok_msg, False)
            except subprocess.TimeoutExpired:
                # pkexec's own PID is killed by subprocess.run(), but not
                # any privileged grandchild it spawned (backup.py,
                # restore.py, a chown -R) — it may still be writing to
                # the same files. We have no way to confirm it's actually
                # gone, so sticky_on_timeout callers (Backup/Restore) leave
                # _pkexec_busy[lock_key] deliberately True rather than risk
                # a second privileged run overlapping it; only a Control
                # Center restart clears it. Non-sticky callers (journal
                # vacuum: idempotent, no file-overlap risk from a second
                # concurrent run) reset normally — a timeout there is far
                # more likely to be a slow/abandoned polkit password
                # prompt than a genuinely wedged operation, and locking
                # journal cleanup out until restart over that would be
                # pure user-hostile downside for zero safety benefit.
                timed_out = sticky_on_timeout
                message = (
                    "Operation timed out after 5 minutes. The privileged "
                    "process may still be running — restart Control "
                    "Center before starting another privileged "
                    "operation."
                    if sticky_on_timeout
                    else "Operation timed out after 5 minutes "
                    "(authentication may have taken too long) — you can "
                    "try again."
                )
                self.process_finished.emit(err_title, message, True)
            except subprocess.CalledProcessError:
                self.process_finished.emit(err_title, err_msg, True)
            except OSError as err:
                self.process_finished.emit(
                    err_title, f"Cannot launch pkexec: {err}", True
                )
            finally:
                if not timed_out:
                    self._pkexec_busy[lock_key] = False
                    # Never touch the button widgets directly from this
                    # background thread — emit and let the main-thread
                    # slot (_on_pkexec_lock_released) do it, same as
                    # process_finished above.
                    self.pkexec_lock_released.emit(lock_key)

        threading.Thread(target=worker, daemon=True).start()

    def run_backup(self):
        """Run backup via pkexec in a daemon thread; emits process_finished."""
        QMessageBox.information(self, "Backup", "Backup process started...")
        self._run_pkexec(
            _core_script_argv("backup.py"),
            lock_key="files",
            ok_title="Success",
            ok_msg="Backup done!",
            err_title="Error",
            err_msg="backup.py failed.",
        )

    def run_restore(self):
        """Restore from archive under pkexec; emits process_finished."""
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Select Backup", "", "*.tar.gz"
        )
        if not fpath:
            return
        QMessageBox.information(self, "Restore", "Restore process started.")
        self._run_pkexec(
            _core_script_argv("restore.py", fpath),
            lock_key="files",
            ok_title="Restore Complete",
            ok_msg="Restored!",
            err_title="Restore Error",
            err_msg="restore.py failed.",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SDYControlCenter()
    window.show()
    sys.exit(app.exec())
