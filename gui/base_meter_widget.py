"""
Base Meter Widget built on PyQt6 QWidget with hardware double-buffering.
Provides 2D vector rendering, HiDPI typography and docking controls.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy
)
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from .theme import palette, apply_meter_header, popout_icon


class BaseMeterWidget(QWidget):
    """
    Core visualizer widget with paint pipeline and docking controls.
    """
    undock_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.meter_title = title
        self.is_paused = False
        self.is_standalone = False
        self.mouse_pos = QPointF(-1, -1)
        self.is_hovered = False

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 160)

        # Header and pop-out control
        self._init_header_controls()

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

        # Pop-out button
        self.undock_btn = QToolButton(self.header_frame)
        self.undock_btn.setIcon(popout_icon("#91c5ff"))
        self.undock_btn.setToolTip("Move to a separate window")
        self.undock_btn.setFixedSize(18, 18)
        self.undock_btn.clicked.connect(self.undock_requested.emit)
        h_layout.addWidget(self.undock_btn)

    def set_fps(self, fps: int):
        interval_ms = max(5, int(1000.0 / max(1, fps)))
        self.timer.setInterval(interval_ms)

    def apply_theme(self, colors: dict[str, str]):
        apply_meter_header(self, colors)
        if self.is_standalone and not self.timer.isActive():
            self.timer.start()

    def set_standalone_mode(self, is_standalone: bool):
        self.is_standalone = is_standalone
        self.header_frame.setVisible(not is_standalone)
        self.update()
        if is_standalone:
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _on_render_tick(self):
        if not self.is_paused and self.isVisible():
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.header_frame.setGeometry(0, 0, self.width(), 26)

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
        painter.fillRect(self.rect(), QColor(palette(self.config)["root"]))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            self.render_ui(painter)
        finally:
            painter.end()

    def render_ui(self, painter: QPainter):
        """Override in subclasses to draw visuals and vector scales."""
        pass
