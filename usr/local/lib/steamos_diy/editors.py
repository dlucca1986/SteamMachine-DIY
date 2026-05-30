#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      2.1.0
# DESCRIPTION:  Line-number gutter and syntax highlighting for QPlainTextEdit.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/editors.py
# LICENSE:      MIT
# =============================================================================
"""

import re

# pylint: disable=no-name-in-module
from PyQt6.QtCore import QRect, QRegularExpression, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

# pylint: enable=no-name-in-module


class LineNumberArea(QWidget):
    """Sidebar widget that renders line numbers for YAMLEditor."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    # pylint: disable=missing-function-docstring
    def sizeHint(self):  # pylint: disable=invalid-name
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # pylint: disable=invalid-name
        self.editor.line_number_area_paint_event(event)

    # pylint: enable=missing-function-docstring


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
        digits = len(str(max(1, self.blockCount())))
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
        styles = [
            (r"#.*", "#7f8c8d", False),
            (r"^\s*[\w.-]+(?=:)", "#3498db", True),
            (r'"[^"]*"', "#f1c40f", False),
            (r"'[^']*'", "#f1c40f", False),
            (r"^\s*-\s.*", "#27ae60", False),
            (r"\b\d+\b", "#e67e22", False),
            (r"[:\-]", "#e74c3c", True),
        ]
        self.rules = []
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
