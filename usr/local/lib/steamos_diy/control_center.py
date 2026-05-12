#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Control Center
# VERSION:      1.3.0
# DESCRIPTION:  PyQt6 Dashboard for SteamOS-DIY with Search functionality.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/control_center.py
# LICENSE:      MIT
# =============================================================================
"""

# pylint: disable=too-many-lines

import os
import re
import subprocess  # nosec B404
import sys
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

# pylint: disable=no-name-in-module
from PyQt6.QtCore import (
    QRect,
    QRegularExpression,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# pylint: enable=no-name-in-module

from ruamel.yaml import YAML, YAMLError

from utils import extract_game_metadata, get_journal_cmd, get_ssot_var, jlog

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# Filesystem paths
_LIB_PATH: str = "/usr/local/lib/steamos_diy"
_SSOT_PATH: str = "/etc/default/steamos_diy.conf"
_WIKI_URL: str = "https://github.com/dlucca1986/SteamMachine-DIY/wiki"

# UI dimensions
_WINDOW_WIDTH: int = 1000
_WINDOW_HEIGHT: int = 700
_BUTTON_STYLE: str = "height: 40px; text-align: left; padding-left: 15px;"
_EDITOR_FONT_SIZE: int = 10
_BUTTON_RESET_MS: int = 2000

# Log scanning
_GAME_LOG_TAIL: int = 2000
_MIN_APPID_LEN: int = 3  # was 5 — caught >100000 only; now catches >=100
_MICROSECONDS_PER_SECOND: int = 1_000_000

# YAML formatter
_YAML_WIDTH: int = 4096
_YAML_INDENT_MAPPING: int = 2
_YAML_INDENT_SEQUENCE: int = 4
_YAML_INDENT_OFFSET: int = 2

# SSoT keys to pre-load into os.environ at startup
_SSOT_KEYS: tuple[str, ...] = (
    "next_session",
    "user_config",
    "games_conf_dir",
    "bin_gs",
    "bin_steam",
    "bin_plasma",
    "LOG_LEVEL",
    "VALIDATION_TIMEOUT",
    "NOTIFY_DELAY",
)

# Regex for extracting AppID from combo display "Name (12345)"
# Matches the LAST parenthesised number in the string, so names with
# embedded years like "Half-Life 2 (2004) (220)" resolve to 220.
_APPID_FROM_DISPLAY = re.compile(r"\((\d+)\)\s*$")

# Patterns for native (no-shell) journal scanning of game launches
_GAME_DIR_PATTERN = re.compile(r'chdir\s+"([^"]+)"')
_GAME_ID_PATTERN = re.compile(r"(?:gameID|AppID\s*=\s*)\s*(\d+)")
_GAME_LOG_NOISE = re.compile(r"GpuTopology|steamui|/steamapps/common$|bin/")


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
# Editor widgets — line numbers + syntax highlighting
# ---------------------------------------------------------------------------


class LineNumberArea(QWidget):
    """Sidebar widget that renders line numbers for YAMLEditor."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):  # pylint: disable=invalid-name
        """Qt override: report preferred width from the editor."""
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # pylint: disable=invalid-name
        """Qt override: delegate painting to the editor."""
        self.editor.line_number_area_paint_event(event)


class YAMLEditor(QPlainTextEdit):
    """Plain-text editor with line-number gutter and Enter-key auto-indent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.update_line_number_area_width(0)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def line_number_area_width(self):
        """Compute sidebar pixel width to fit the highest line number."""
        digits = 1
        max_val = max(1, self.blockCount())
        while max_val >= 10:
            max_val /= 10
            digits += 1
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        """Resize left viewport margin to match the current sidebar width."""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        """Scroll or repaint the line number area on scroll/content change."""
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):  # pylint: disable=invalid-name
        """Qt override: refit the sidebar geometry on editor resize."""
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(
                cr.left(), cr.top(), self.line_number_area_width(), cr.height()
            )
        )

    def line_number_area_paint_event(self, event):
        """Paint line numbers in the sidebar for the visible block range."""
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#2c3e50"))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset())
            .top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#95a5a6"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 5,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(num + 1),
                )
            block, num = block.next(), num + 1
            top, bottom = bottom, bottom + round(
                self.blockBoundingRect(block).height()
            )

    def keyPressEvent(self, event):  # pylint: disable=invalid-name
        """Auto-indent on Enter — preserve leading whitespace."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            indent = re.match(r"^\s*", cursor.block().text()).group(0)
            super().keyPressEvent(event)
            self.insertPlainText(indent)
        else:
            super().keyPressEvent(event)


# pylint: disable=too-few-public-methods
class YAMLSyntaxHighlighter(QSyntaxHighlighter):
    """Regex-based syntax highlighter for YAML content in QPlainTextEdit."""

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self._setup_rules()

    def _setup_rules(self):
        styles = [
            (r"#.*", "#7f8c8d", False),
            (r"^\s*[\w.-]+(?=:)", "#3498db", True),
            (r'"[^"]*"', "#f1c40f", False),
            (r"'[^']*'", "#f1c40f", False),
            (r"^\s*-\s.*", "#27ae60", False),
            (r"\b\d+\b", "#e67e22", False),
            (r"[:\-]", "#e74c3c", True),
        ]
        for pat, col, bold in styles:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(col))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            self.rules.append((QRegularExpression(pat), fmt))

    def highlightBlock(self, text):  # pylint: disable=invalid-name
        """Called by Qt per visible block."""
        for expression, fmt in self.rules:
            it = expression.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ---------------------------------------------------------------------------
# Internal helpers — log filtering & journal parsing
# ---------------------------------------------------------------------------


def _is_game_log_line(line: str, chdir_marker: str) -> bool:
    return chdir_marker in line or "gameID " in line or "AppID = " in line


def _filter_game_journal_lines(stdout: str, home: str) -> list[str]:
    """Filter journalctl output; return last _GAME_LOG_TAIL game-launch lines.

    Args:
        stdout: Full ``journalctl --no-hostname`` output.
        home: User home path used as chdir prefix anchor.

    Returns:
        At most _GAME_LOG_TAIL most-recent matching lines, preserving order.
    """
    chdir_marker = f'chdir "{home}'
    matched = [
        line
        for line in stdout.splitlines()
        if _is_game_log_line(line, chdir_marker)
        and not _GAME_LOG_NOISE.search(line)
    ]
    return matched[-_GAME_LOG_TAIL:]


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


# pylint: disable=too-many-instance-attributes
class SDYControlCenter(QMainWindow):
    """Main application window: diagnostics, maintenance, YAML editors."""

    process_finished = pyqtSignal(str, str, bool)  # (title, message, is_error)
    logs_ready = pyqtSignal(list, str)  # (entries, tag)
    games_detected = pyqtSignal(dict)  # {name: appid_or_name}

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamMachine-DIY Control Center")
        self.resize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        self.lib_path = _LIB_PATH
        self.conf_root = Path(os.path.expanduser("~/.config/steamos_diy"))

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
        self.copy_btn = None
        self.support_btn = None

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

        # Per-tab template view state
        self.view_states = {
            "global": {"is_template": False, "cache": ""},
            "games": {"is_template": False, "cache": ""},
        }

        self._load_ssot_to_env()
        self._setup_ui()

        # Wire async signals
        self.process_finished.connect(self._show_completion_message)
        self.logs_ready.connect(self._on_logs_ready)
        self.games_detected.connect(self._update_game_combo_ui)

        # Clear error highlight on any user edit
        self.global_editor.textChanged.connect(
            lambda: self.global_editor.setExtraSelections([])
        )
        self.game_editor.textChanged.connect(
            lambda: self.game_editor.setExtraSelections([])
        )

    # ── Setup ──────────────────────────────────────────────────────────────

    def _load_ssot_to_env(self):
        """Pre-load SSoT keys into os.environ; get_ssot_var caches on miss."""
        for key in _SSOT_KEYS:
            get_ssot_var(key)

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
        if index == 0:
            self.load_logs()

    # ── Diagnostics tab ────────────────────────────────────────────────────

    def init_diag_tab(self):
        """Build the Diagnostics tab layout and wire up signals."""
        self.diag_tab = QWidget()
        layout = QVBoxLayout()
        header = QHBoxLayout()
        self.tag_filter = QComboBox()
        self.tag_filter.addItems(["ALL", "CORE", "STEAM", "SYSTEM"])
        self.tag_filter.currentTextChanged.connect(self.load_logs)
        header.addWidget(QLabel("<b>Component Filter:</b>"))
        header.addWidget(self.tag_filter)
        header.addStretch()
        layout.addLayout(header)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Monospace", _EDITOR_FONT_SIZE))
        layout.addWidget(self.log_display)
        footer = QHBoxLayout()
        self.copy_btn = QPushButton("📋 Copy to Clipboard")
        self.copy_btn.clicked.connect(self.copy_logs)
        self.support_btn = QPushButton("🛠️ Export Support Log")
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

        tools = [
            (
                "🎮 Switch to Steam (Game Mode)",
                lambda: self._safe_spawn(
                    [
                        "/usr/bin/python3",
                        os.path.join(self.lib_path, "session_select.py"),
                        "steam",
                    ]
                ),
            ),
            ("📝 Edit System Config (SSoT)", self.edit_ssot_privileged),
            ("🧹 Clean System Logs (Vacuum)", self.cleanup_logs_privileged),
            ("📦 Create Full System Backup", self.run_backup),
            ("🔄 Restore from Archive", self.run_restore),
            (
                "🖥️ Open Konsole Terminal",
                lambda: self._safe_spawn(["/usr/bin/konsole"]),
            ),
            (
                "📂 Browse Config Folder",
                lambda: self._safe_spawn(
                    ["/usr/bin/xdg-open", str(self.conf_root)]
                ),
            ),
        ]
        for text, func in tools:
            btn = QPushButton(text)
            btn.setStyleSheet(_BUTTON_STYLE)
            btn.clicked.connect(func)
            layout.addWidget(btn)

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
            # pylint: disable=consider-using-with
            subprocess.Popen([editor, _SSOT_PATH])  # nosec B603
        except OSError as err:
            QMessageBox.critical(self, "Error", f"Failed to launch: {err}")

    def cleanup_logs_privileged(self):
        """Vacuum journal via pkexec; emits process_finished."""

        def worker() -> None:
            try:
                subprocess.run(  # nosec B603
                    ["/usr/bin/pkexec", "/usr/bin/journalctl", "--rotate"],
                    check=True,
                )
                subprocess.run(  # nosec B603
                    [
                        "/usr/bin/pkexec",
                        "/usr/bin/journalctl",
                        "--vacuum-time=1s",
                    ],
                    check=True,
                )
                self.process_finished.emit(
                    "Logs Cleaned", "Journal wiped.", False
                )
            except subprocess.CalledProcessError:
                self.process_finished.emit(
                    "Error", "Authentication or vacuum failed.", True
                )
            except OSError as err:
                # pkexec missing or other execve error
                self.process_finished.emit(
                    "Error", f"Cannot launch pkexec: {err}", True
                )

        threading.Thread(target=worker, daemon=True).start()

    def _safe_spawn(self, cmd):
        """Non-blocking Popen; logs errors to journal rather than raising."""
        try:
            # pylint: disable=consider-using-with
            subprocess.Popen(cmd)  # nosec B603
        except (subprocess.SubprocessError, OSError) as err:
            jlog("SYSTEM", f"SPAWN_FAILED: {cmd[0]}: {err}", level="WARN")

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
        self.combo_games.currentTextChanged.connect(self.load_game_file)
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
            stream = StringIO()
            yaml_parser.dump(data, stream)
            clean = stream.getvalue()
        except (YAMLError, OSError) as err:
            self._highlight_yaml_error(editor, err)
            return
        if raw.strip() == clean.strip():
            return
        editor.setPlainText(clean)
        hl = self.global_hl if editor is self.global_editor else self.game_hl
        hl.rehighlight()

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

    def _exit_template_mode(self, state, widgets):
        editor, save_btn, tmp_btn, hl = widgets
        editor.setPlainText(state["cache"])
        tmp_btn.setText("📄 View Template")
        state["is_template"] = False
        save_btn.setEnabled(True)
        hl.rehighlight()

    def _atomic_save(self, path, content, editor):
        """Validate YAML and write atomically via tmp+fsync+rename.

        Guarantees durability on btrfs/ext4 across abrupt power loss.

        Args:
            path: Destination path.
            content: YAML text to write.
            editor: Editor widget for error highlight on parse failure.
        """
        editor.setExtraSelections([])
        try:
            yaml_parser.load(content)
            p_obj = Path(path)
            p_obj.parent.mkdir(parents=True, exist_ok=True)
            tmp = p_obj.with_suffix(".tmp")

            # Write + fsync before rename for true durability
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p_obj)

            QMessageBox.information(self, "Success", "Configuration saved!")
        except YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            if mark:
                self._highlight_error_line(editor, mark.line)
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
        name = raw.split(" (")[0].strip()
        path = self.conf_root / "games.d" / f"{name}.yaml"
        if path.exists():
            self.game_editor.setPlainText(path.read_text(encoding="utf-8"))
        else:
            scaffold = self._scaffold_game_profile(raw, name)
            self.game_editor.setPlainText(scaffold)
        if self.game_hl:
            self.game_hl.rehighlight()

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
            f'GAME_EXTRA_ARGS: ""\nenv_vars:\n  # MANGOHUD: "1"\n'
        )

    def save_game_profile(self):
        """Atomically save the current game profile YAML to disk."""
        raw = self.combo_games.currentText().strip()
        if not raw:
            return
        name = raw.split(" (")[0].strip()
        path = self.conf_root / "games.d" / f"{name}.yaml"
        self._atomic_save(
            str(path), self.game_editor.toPlainText(), self.game_editor
        )

    # ── Game discovery (background thread) ─────────────────────────────────

    def refresh_detected_games(self):
        """Scan journal for game launches; emits games_detected when done.

        Runs journalctl directly (no shell) — pure-Python filtering avoids
        shell-injection risk when home contains metacharacters.
        """
        self.combo_games.setPlaceholderText("Scanning history...")
        home = os.path.expanduser("~")

        def worker() -> None:
            try:
                res = subprocess.run(  # nosec B603
                    [
                        "/usr/bin/journalctl",
                        "--since",
                        "24 hours ago",
                        "--no-hostname",
                        "--no-pager",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                lines = _filter_game_journal_lines(res.stdout, home)
                detected = self._parse_game_logs("\n".join(lines))
                self.games_detected.emit(detected)
            except (subprocess.SubprocessError, OSError):
                self.games_detected.emit({})

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
        gdir = self.conf_root / "games.d"
        if not gdir.exists():
            return
        for p in gdir.glob("*.yaml"):
            detected.setdefault(p.stem, p.stem)

    def _format_combo_items(self, detected):
        return [
            f"{n} ({a})" if a.isdigit() and a != n else n
            for n, a in sorted(detected.items())
        ]

    def _parse_game_logs(self, res: str) -> dict[str, str]:
        """Extract {name: appid_or_name} pairs from filtered journal text."""
        det: dict[str, str] = {}
        cur: str | None = None
        for line in res.splitlines():
            cur = self._update_detection(line, cur, det)
        return det

    @staticmethod
    def _apply_name_hit(value: str | None, det: dict[str, str]) -> str | None:
        if value is not None:
            det[value] = value
        return value

    @staticmethod
    def _apply_id_hit(
        cur: str | None, value: str | None, det: dict[str, str]
    ) -> None:
        if cur and value and len(value) >= _MIN_APPID_LEN:
            det[cur] = value

    def _update_detection(
        self, line: str, cur: str | None, det: dict[str, str]
    ) -> str | None:
        kind, value = extract_game_metadata(line)
        if kind == "NAME":
            return self._apply_name_hit(value, det) or cur
        if kind == "ID":
            self._apply_id_hit(cur, value, det)
        return cur

    # ── Journal export parsing for diagnostics ─────────────────────────────

    def _parse_export_format(
        self, stdout: str, launches: set[str]
    ) -> list[tuple[datetime, str]]:
        """Parse ``journalctl -o export`` into (timestamp, line) tuples.

        Args:
            stdout: Raw export-format journalctl output.
            launches: Mutated in place — LAUNCH_ARGS appended for dedup.

        Returns:
            (datetime, formatted_line) list in arrival order.
        """
        ents: list[tuple[datetime, str]] = []
        cur: dict[str, Any] = {}
        for line in stdout.splitlines():
            entry = self._consume_export_line(line, cur, launches)
            if entry is not None:
                ents.append(entry)
                cur = {}
        return ents

    def _consume_export_line(
        self,
        line: str,
        cur: dict[str, Any],
        launches: set[str],
    ) -> tuple[datetime, str] | None:
        """Accumulate one export-format field; return entry on MESSAGE=.

        Args:
            line: Single export-format line.
            cur: Accumulator dict for the current record (mutated in place).
            launches: Mutated — LAUNCH_ARGS strings appended as side effect.

        Returns:
            (datetime, formatted_line) on MESSAGE= terminator, else None.
        """
        if line.startswith("__REALTIME_TIMESTAMP="):
            cur["ts"] = datetime.fromtimestamp(
                int(line.split("=")[1]) / _MICROSECONDS_PER_SECOND
            )
            return None
        if line.startswith("SYSLOG_IDENTIFIER="):
            cur["id"] = line.split("=")[1]
            return None
        if line.startswith("MESSAGE="):
            return self._finalize_export_entry(line, cur, launches)
        return None

    @staticmethod
    def _finalize_export_entry(
        line: str, cur: dict[str, Any], launches: set[str]
    ) -> tuple[datetime, str]:
        msg = line.split("=", 1)[1]
        ident = cur.get("id", "SYSTEM")
        ts = cur.get("ts", datetime.now())
        if ident == "STEAM" and "LAUNCH_ARGS" in msg:
            launches.add(msg.split("LAUNCH_ARGS:", 1)[-1].strip())
        return (ts, f"[{ts.strftime('%H:%M:%S')}] {ident}: {msg}")

    def _fetch_gamescope_logs(
        self, launches: set[str]
    ) -> list[tuple[datetime, str]]:
        """Pull gamescope journal lines, skipping echoes of known *launches*.

        Args:
            launches: LAUNCH_ARGS already emitted — prevents duplicate display.

        Returns:
            (datetime, formatted_line) list ready for merge-sort.
        """
        stdout = self._run_journalctl_iso()
        if not stdout:
            return []

        ents = []
        for line in stdout.splitlines():
            if "gamescope" not in line.lower():
                continue
            entry = self._parse_gamescope_line(line, launches)
            if entry is not None:
                ents.append(entry)
        return ents

    def _run_journalctl_iso(self) -> str:
        try:
            res = subprocess.run(  # nosec B603
                [
                    "/usr/bin/journalctl",
                    "--since",
                    "1 hour ago",
                    "-o",
                    "short-iso",
                    "--no-pager",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return res.stdout or ""
        except OSError:
            return ""

    def _parse_gamescope_line(
        self, line: str, launches: set[str]
    ) -> tuple[datetime, str] | None:
        """Parse one gamescope line; return None if duplicate or malformed."""
        parsed = self._split_gamescope_line(line)
        if parsed is None:
            return None
        ts, msg = parsed
        if self._is_duplicate_launch(msg, launches):
            return None
        d_msg = msg if "[gamescope]" in msg else f"[gamescope] {msg}"
        return (ts, f"[{ts.strftime('%H:%M:%S')}] {d_msg}")

    def _split_gamescope_line(self, line: str) -> tuple[datetime, str] | None:
        try:
            ps = line.split(" ", 2)
            if len(ps) < 3:
                return None
            ts = datetime.fromisoformat(ps[0]).replace(tzinfo=None)
            msg = (
                ps[2].split(": ", 1)[1].strip()
                if ": " in ps[2]
                else ps[2].strip()
            )
            return ts, msg
        except (IndexError, ValueError):
            return None

    @staticmethod
    def _is_duplicate_launch(msg: str, launches: set[str]) -> bool:
        if "LAUNCH_ARGS" not in msg:
            return False
        arg = msg.split("LAUNCH_ARGS:", 1)[-1].strip()
        return arg in launches

    # ── Logs UI flow ───────────────────────────────────────────────────────

    def load_logs(self):
        """Reload logs in a daemon thread; emits logs_ready when done."""
        tag = re.sub(
            r"[^\x00-\x7F]+", "", self.tag_filter.currentText()
        ).strip()

        self.log_display.setPlainText("Loading logs...")
        self.tag_filter.setEnabled(False)

        def worker() -> None:
            launches: set[str] = set()
            try:
                res = subprocess.run(  # nosec B603
                    get_journal_cmd(tag),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                ents = self._parse_export_format(res.stdout, launches)
                if tag in ("ALL", "STEAM"):
                    ents.extend(self._fetch_gamescope_logs(launches))
                if ents:
                    ents.sort(key=lambda x: x[0])
                self.logs_ready.emit(ents, tag)
            except (subprocess.CalledProcessError, OSError) as err:
                self.logs_ready.emit([], f"ERROR:{err}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_logs_ready(self, ents, tag):
        self.tag_filter.setEnabled(True)

        if tag.startswith("ERROR:"):
            self.log_display.setPlainText(f"Log Retrieval Error: {tag[6:]}")
            return

        if ents:
            self._display_colored_logs("\n".join(e[1] for e in ents))
        else:
            self.log_display.setPlainText(f"No {tag} activity.")

    def _apply_log_style(self, line):
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
        lines, last, count = logs.strip().split("\n"), None, 1

        def flush(c):
            if c > 1:
                self.log_display.append(
                    f"&nbsp;&nbsp;&nbsp;&nbsp;<i style='color:#7f8c8d;'>"
                    f"⤷ Repeated {c} times</i>"
                )

        for line in lines:
            m = re.search(r"^\[\d{2}:\d{2}:\d{2}\]\s+(.*)", line)
            pure = m.group(1) if m else line
            if pure == last:
                count += 1
                continue
            flush(count)
            count, last = 1, pure
            self.log_display.append(self._apply_log_style(line))
        flush(count)

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
        """Export the gamescope support log to a user-chosen file."""
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Log", "sdy_support.log"
        )
        if dest:
            try:
                Path(dest).write_text(
                    self.log_display.toPlainText(), encoding="utf-8"
                )
            except OSError as err:
                QMessageBox.critical(self, "Save Error", str(err))

    # ── Async result handlers ─────────────────────────────────────────────

    def _show_completion_message(self, title, message, is_error):
        if is_error:
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.information(self, title, message)

    # ── Privileged operations ─────────────────────────────────────────────

    def run_backup(self):
        """Run backup via pkexec in a daemon thread; emits process_finished."""
        script = os.path.join(self.lib_path, "backup.py")
        QMessageBox.information(self, "Backup", "Backup process started...")

        def worker() -> None:
            try:
                subprocess.run(  # nosec B603
                    ["/usr/bin/pkexec", "/usr/bin/python3", script],
                    check=True,
                )
                self.process_finished.emit("Success", "Backup done!", False)
            except subprocess.CalledProcessError:
                self.process_finished.emit("Error", "Backup failed.", True)
            except OSError as err:
                self.process_finished.emit(
                    "Error", f"Cannot launch pkexec: {err}", True
                )

        threading.Thread(target=worker, daemon=True).start()

    def run_restore(self):
        """Restore from archive under pkexec; emits process_finished."""
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Select Backup", "", "*.tar.gz"
        )
        if not fpath:
            return
        script = os.path.join(self.lib_path, "restore.py")
        QMessageBox.information(self, "Restore", "Restore process started.")

        def worker() -> None:
            try:
                subprocess.run(  # nosec B603
                    ["/usr/bin/pkexec", "/usr/bin/python3", script, fpath],
                    check=True,
                )
                self.process_finished.emit(
                    "Restore Complete", "Restored!", False
                )
            except subprocess.CalledProcessError:
                self.process_finished.emit("Restore Error", "Failed.", True)
            except OSError as err:
                self.process_finished.emit(
                    "Restore Error", f"Cannot launch pkexec: {err}", True
                )

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SDYControlCenter()
    window.show()
    sys.exit(app.exec())
