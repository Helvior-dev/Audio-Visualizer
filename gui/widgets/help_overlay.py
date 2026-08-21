"""
Interactive Help Overlay widget.
Displays a centered, readable modal card with explanations when clicking the '?' button.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen


class HelpOverlay(QWidget):
    """
    Semi-transparent animated overlay displaying a centered help card over a meter.
    """
    closed = pyqtSignal()

    def __init__(self, title: str, description_lines: list[str], parent=None):
        super().__init__(parent)
        self.title = title
        self.lines = description_lines
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self._init_ui()

    def _init_ui(self):
        # Outer container layout
        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)
        self.outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered Card Frame
        self.card = QFrame(self)
        self.card.setMaximumWidth(540)
        self.card.setStyleSheet("""
            QFrame {
                background-color: #121218;
                border: 1px solid #2E2E3C;
                border-radius: 8px;
            }
        """)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 20, 24, 18)
        card_layout.setSpacing(10)

        # Title
        title_label = QLabel(self.title, self.card)
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        title_label.setFont(font)
        title_label.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title_label)

        # Body
        body_widget = QWidget(self.card)
        body_widget.setStyleSheet("background: transparent; border: none;")
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 4, 0, 4)
        body_layout.setSpacing(6)

        for line in self.lines:
            lbl = QLabel(line, body_widget)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet("color: #D2D2DC; background: transparent; border: none;")
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            body_layout.addWidget(lbl)

        card_layout.addWidget(body_widget)

        # Footer
        footer_label = QLabel("Click anywhere or press Esc to close", self.card)
        footer_label.setFont(QFont("Segoe UI", 8))
        footer_label.setStyleSheet("color: #727282; border: none; background: transparent;")
        footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(footer_label)

        self.outer_layout.addWidget(self.card)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Dark backdrop over entire widget/screen
        painter.fillRect(self.rect(), QColor(5, 5, 8, 200))

    def mousePressEvent(self, event):
        self.closed.emit()
        self.hide()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            self.hide()
            event.accept()
        super().keyPressEvent(event)
