"""
Base Meter Widget built on PyQt6 QWidget with hardware double-buffering.
Provides ultra-high performance 2D vector rendering, HiDPI typography,
interactive help overlays, and undocking/docking controls with zero window-move lag.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy
)
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from .widgets.help_overlay import HelpOverlay


class BaseMeterWidget(QWidget):
    """
    Core visualizer widget with high-performance paint pipeline,
    help dialogs, and docking controls.
    """
    undock_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, title: str, help_lines: list[str], parent=None):
        super().__init__(parent)
        self.meter_title = title
        self.help_lines = help_lines
        self.is_paused = False
        self.is_standalone = False
        self.mouse_pos = QPointF(-1, -1)
        self.is_hovered = False

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 160)

        # Header Buttons (Help, Undock)
        self._init_header_controls()

        # Help overlay
        self.help_overlay = HelpOverlay(self.meter_title, self.help_lines, self)
        self.help_overlay.hide()

        # Render loop timer (used only when undocked in standalone floating window)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_render_tick)
        self.set_fps(60)

    def _init_header_controls(self):
        self.header_frame = QFrame(self)
        self.header_frame.setStyleSheet("""
            QFrame {
                background-color: transparent;
            }
            QToolButton {
                background-color: rgba(20, 20, 26, 180);
                color: #A0A0A8;
                border: 1px solid rgba(60, 60, 75, 140);
                border-radius: 3px;
                font-family: 'Segoe UI', Arial;
                font-size: 10px;
                font-weight: bold;
                padding: 1px 4px;
            }
            QToolButton:hover {
                background-color: rgba(45, 45, 60, 240);
                color: #58A6FF;
                border-color: #58A6FF;
            }
        """)
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(6, 4, 6, 0)
        h_layout.setSpacing(4)

        # Title Label
        self.title_lbl = QLabel(self.meter_title, self.header_frame)
        self.title_lbl.setStyleSheet("color: #70707C; font-weight: bold; font-size: 10px;")
        h_layout.addWidget(self.title_lbl)
        h_layout.addStretch(1)

        # Help Button
        self.help_btn = QToolButton(self.header_frame)
        self.help_btn.setText("?")
        self.help_btn.setToolTip("Show meter explanations")
        self.help_btn.setFixedSize(18, 18)
        self.help_btn.clicked.connect(self._toggle_help)
        h_layout.addWidget(self.help_btn)

        # Undock / Pop-out Button
        self.undock_btn = QToolButton(self.header_frame)
        self.undock_btn.setText("↗")
        self.undock_btn.setToolTip("Pop-out into floating window")
        self.undock_btn.setFixedSize(18, 18)
        self.undock_btn.clicked.connect(self.undock_requested.emit)
        h_layout.addWidget(self.undock_btn)

    def set_fps(self, fps: int):
        interval_ms = max(5, int(1000.0 / max(1, fps)))
        self.timer.setInterval(interval_ms)
        if self.is_standalone and not self.timer.isActive():
            self.timer.start()

    def set_standalone_mode(self, is_standalone: bool):
        self.is_standalone = is_standalone
        self.undock_btn.setVisible(not is_standalone)
        if is_standalone:
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _toggle_help(self):
        if self.help_overlay.isVisible():
            self.help_overlay.hide()
        else:
            self.help_overlay.setGeometry(self.rect())
            self.help_overlay.show()
            self.help_overlay.raise_()

    def _on_render_tick(self):
        if not self.is_paused and self.isVisible():
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.header_frame.setGeometry(0, 0, self.width(), 26)
        if self.help_overlay.isVisible():
            self.help_overlay.setGeometry(self.rect())

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.position()
        self.is_hovered = True
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        self.is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.mouse_pos = QPointF(-1, -1)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(11, 11, 13))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            self.render_ui(painter)
        finally:
            painter.end()

    def render_ui(self, painter: QPainter):
        """Override in subclasses to draw visuals and vector scales."""
        pass
