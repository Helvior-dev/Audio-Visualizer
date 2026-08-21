"""
Dock container and floating module window support.
Allows seamlessly undocking visualizers into standalone native dark windows
and redocking them back into the main suite, with informative placeholder cards.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame
from PyQt6.QtGui import QIcon
from pathlib import Path
from ..frameless_window import NativeDarkWindow

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"


class FloatingModuleWindow(NativeDarkWindow):
    """
    Independent native window with dark DWM titlebar holding a detached visualizer module.
    """
    redock_requested = pyqtSignal(str)

    def __init__(self, module_id: str, title: str, parent=None):
        super().__init__(parent, is_floating_module=True)
        self.module_id = module_id
        self.setWindowTitle(title)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.setMinimumSize(360, 320)
        self._is_closing = False
        self.attached_widget = None

        # Floating Mini Toolbar (Dock back button & Pin)
        self.mini_bar = QWidget(self)
        self.mini_bar.setFixedHeight(28)
        self.mini_bar.setStyleSheet("""
            QWidget {
                background-color: #121216;
                color: #A0A0A8;
                font-family: 'Segoe UI', Arial;
                font-size: 10px;
                font-weight: bold;
            }
            QToolButton {
                background-color: #1A1A22;
                border: 1px solid #282834;
                border-radius: 3px;
                padding: 2px 6px;
                color: #A0A0A8;
            }
            QToolButton:hover {
                background-color: #262634;
                color: #58A6FF;
                border-color: #58A6FF;
            }
        """)
        mb_layout = QHBoxLayout(self.mini_bar)
        mb_layout.setContentsMargins(6, 2, 6, 2)
        mb_layout.setSpacing(6)

        # Redock Button
        self.redock_btn = QToolButton(self.mini_bar)
        self.redock_btn.setText("⇲ Dock to Suite")
        self.redock_btn.setToolTip("Return this module to the main window")
        self.redock_btn.clicked.connect(self._on_redock)
        mb_layout.addWidget(self.redock_btn)

        mb_layout.addStretch(1)

        # Pin / Always on Top Button
        self.pin_btn = QToolButton(self.mini_bar)
        self.pin_btn.setText("📌 Pin")
        self.pin_btn.setToolTip("Toggle Always on Top")
        self.pin_btn.clicked.connect(self._toggle_pin)
        mb_layout.addWidget(self.pin_btn)

        self.main_layout.addWidget(self.mini_bar)

        # Content Area
        self.content_container = QWidget(self)
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.content_container, 1)

    def _toggle_pin(self):
        new_pinned = not self.is_always_on_top()
        self.set_always_on_top(new_pinned)
        self.pin_btn.setStyleSheet("color: #58A6FF; border-color: #58A6FF;" if new_pinned else "")

    def attach_widget(self, widget: QWidget):
        self.attached_widget = widget
        self.content_layout.addWidget(widget)
        widget.show()
        if hasattr(widget, "set_standalone_mode"):
            widget.set_standalone_mode(True)

    def detach_widget(self) -> QWidget | None:
        if self.attached_widget is not None:
            widget = self.attached_widget
            self.content_layout.removeWidget(widget)
            widget.setParent(None)
            self.attached_widget = None
            if hasattr(widget, "set_standalone_mode"):
                widget.set_standalone_mode(False)
            return widget
        return None

    def _on_redock(self):
        if not self._is_closing:
            self._is_closing = True
            self.redock_requested.emit(self.module_id)

    def closeEvent(self, event):
        if not self._is_closing:
            self._is_closing = True
            self.redock_requested.emit(self.module_id)
        super().closeEvent(event)


class DockCard(QFrame):
    """
    Card wrapping a visualizer module when it is docked inside the main suite,
    or displaying a clear detached placeholder when it is popped out.
    """
    redock_requested = pyqtSignal(str)

    def __init__(self, module_id: str, widget: QWidget, title: str = "", parent=None):
        super().__init__(parent)
        self.module_id = module_id
        self.widget = widget
        self.title_str = title or module_id.capitalize()

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Placeholder widget when detached
        self.placeholder = QWidget(self)
        p_layout = QVBoxLayout(self.placeholder)
        p_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_layout.setSpacing(6)

        self.p_title = QLabel(f"⧉  {self.title_str.upper()} DETACHED", self.placeholder)
        self.p_title.setStyleSheet("color: #707588; font-weight: bold; font-size: 11px;")
        self.p_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.p_desc = QLabel("Currently running in a floating window", self.placeholder)
        self.p_desc.setStyleSheet("color: #4a4e60; font-size: 10px;")
        self.p_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.p_btn = QToolButton(self.placeholder)
        self.p_btn.setText("⇲  Dock to Suite")
        self.p_btn.setStyleSheet("""
            QToolButton {
                background-color: #1a1c26;
                color: #8fa0c0;
                border: 1px solid #2e3448;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 10px;
            }
            QToolButton:hover {
                background-color: #262c3e;
                color: #58A6FF;
                border-color: #58A6FF;
            }
        """)
        self.p_btn.clicked.connect(lambda: self.redock_requested.emit(self.module_id))

        p_layout.addWidget(self.p_title)
        p_layout.addWidget(self.p_desc)
        p_layout.addWidget(self.p_btn)
        self.placeholder.hide()

        # Add live widget and placeholder to card
        self.main_layout.addWidget(self.widget)
        self.main_layout.addWidget(self.placeholder)
        self._apply_style(is_detached=False)

    def set_detached(self, detached: bool):
        if detached:
            self.placeholder.show()
            self._apply_style(is_detached=True)
        else:
            self.placeholder.hide()
            self.widget.show()
            self._apply_style(is_detached=False)

    def _apply_style(self, is_detached: bool):
        if is_detached:
            self.setStyleSheet("""
                DockCard {
                    background-color: #0a0b0e;
                    border: 1px dashed #282c3c;
                    border-radius: 4px;
                }
            """)
        else:
            self.setStyleSheet("""
                DockCard {
                    background-color: #0b0b0d;
                    border: 1px solid #1c1d24;
                    border-radius: 4px;
                }
            """)
