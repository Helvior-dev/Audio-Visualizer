"""
Suite Toolbar & Control Bar widget for Native Windows.
Provides module switcher buttons, pause suite button, undock/dock all button, settings toggle, and pin controls.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QToolButton, QSizePolicy
)


class TitleBar(QWidget):
    """
    Top control toolbar inside the main window.
    """
    pin_toggled = pyqtSignal(bool)
    settings_clicked = pyqtSignal()
    module_toggled = pyqtSignal(str, bool)
    pause_suite_toggled = pyqtSignal(bool)
    undock_all_toggled = pyqtSignal(bool)

    def __init__(self, parent_window, title="AUDIO VISUALIZER", is_floating=False, is_main=True):
        super().__init__(parent_window)
        self.window = parent_window
        self.title_text = title
        self.is_main = is_main
        self._is_pinned = False
        self._is_paused = False
        self._is_undocked_all = False

        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QWidget {
                background-color: #121216;
                color: #C8C8CE;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
            }
            QToolButton {
                background-color: #181820;
                border: 1px solid #282834;
                border-radius: 4px;
                padding: 3px 8px;
                color: #A0A0A8;
                font-weight: bold;
            }
            QToolButton:hover {
                background-color: #242432;
                color: #FFFFFF;
                border-color: #58A6FF;
            }
            QToolButton:pressed {
                background-color: #303042;
            }
            QPushButton {
                background-color: #16161C;
                color: #656575;
                border: 1px solid #24242E;
                border-radius: 4px;
                padding: 3px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1E1E28;
                color: #A0A0B0;
                border-color: #3E3E50;
            }
            QPushButton:checked {
                background-color: #1A283C;
                color: #58A6FF;
                border: 1px solid #58A6FF;
                font-weight: bold;
            }
            QPushButton:checked:hover {
                background-color: #223652;
                border-color: #79B8FF;
            }
        """)

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # Module toggle buttons
        self.module_buttons = {}
        if self.is_main:
            module_defs = [
                ("loudness", "LUFS"),
                ("waveform", "Waveform"),
                ("oscilloscope", "Oscilloscope"),
                ("spectrum", "Spectrum"),
                ("spectrogram", "Waterfall"),
                ("vectorscope", "Stereo"),
            ]
            for mod_id, mod_label in module_defs:
                btn = QPushButton(mod_label, self)
                btn.setCheckable(True)
                btn.setChecked(True)
                btn.setFixedHeight(24)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda checked, m=mod_id: self._on_btn_clicked(m, checked))
                self.module_buttons[mod_id] = btn
                layout.addWidget(btn)

        layout.addStretch(1)

        # Pause Suite button (visible only when at least one module is floating)
        if self.is_main:
            self.pause_btn = QToolButton(self)
            self.pause_btn.setText("⏸ Pause Suite")
            self.pause_btn.setToolTip("Pause docked suite visualizations (leaves external floating windows running)")
            self.pause_btn.clicked.connect(self._toggle_pause_suite)
            self.pause_btn.hide()
            layout.addWidget(self.pause_btn)

            # Undock All / Dock All Button
            self.undock_all_btn = QToolButton(self)
            self.undock_all_btn.setText("↗ Undock All")
            self.undock_all_btn.setToolTip("Pop-out all active modules into floating windows")
            self.undock_all_btn.clicked.connect(self._toggle_undock_all)
            layout.addWidget(self.undock_all_btn)

            # Settings Button
            self.settings_btn = QToolButton(self)
            self.settings_btn.setText("⚙ Settings")
            self.settings_btn.setToolTip("Settings & Audio Devices")
            self.settings_btn.clicked.connect(self.settings_clicked.emit)
            layout.addWidget(self.settings_btn)

        # Pin / Always on Top
        self.pin_btn = QToolButton(self)
        self.pin_btn.setText("📌 Pin")
        self.pin_btn.setToolTip("Toggle Always on Top")
        self.pin_btn.clicked.connect(self._toggle_pin)
        layout.addWidget(self.pin_btn)

    def _on_btn_clicked(self, mod_id: str, checked: bool):
        self.module_toggled.emit(mod_id, checked)

    def _toggle_pin(self):
        self._is_pinned = not self._is_pinned
        self.pin_btn.setStyleSheet("color: #58A6FF; border-color: #58A6FF; background-color: #1A283C;" if self._is_pinned else "")
        self.pin_toggled.emit(self._is_pinned)

    def _toggle_pause_suite(self):
        self._is_paused = not self._is_paused
        if self._is_paused:
            self.pause_btn.setText("▶ Resume Suite")
            self.pause_btn.setStyleSheet("color: #FFB300; border-color: #FFB300; background-color: #2D2510;")
        else:
            self.pause_btn.setText("⏸ Pause Suite")
            self.pause_btn.setStyleSheet("")
        self.pause_suite_toggled.emit(self._is_paused)

    def _toggle_undock_all(self):
        self._is_undocked_all = not self._is_undocked_all
        self.set_undock_all_state(self._is_undocked_all)
        self.undock_all_toggled.emit(self._is_undocked_all)

    def set_undock_all_state(self, is_undocked: bool):
        self._is_undocked_all = is_undocked
        if hasattr(self, "undock_all_btn"):
            if is_undocked:
                self.undock_all_btn.setText("⇲ Dock All")
                self.undock_all_btn.setToolTip("Return all floating modules back to the suite")
                self.undock_all_btn.setStyleSheet("color: #58A6FF; border-color: #58A6FF; background-color: #1A283C;")
            else:
                self.undock_all_btn.setText("↗ Undock All")
                self.undock_all_btn.setToolTip("Pop-out all active modules into floating windows")
                self.undock_all_btn.setStyleSheet("")

    def set_has_floating(self, has_floating: bool):
        if hasattr(self, "pause_btn"):
            self.pause_btn.setVisible(has_floating)
            if not has_floating and self._is_paused:
                self._toggle_pause_suite()

    def set_module_checked(self, module_id: str, checked: bool):
        if module_id in self.module_buttons:
            btn = self.module_buttons[module_id]
            btn.setChecked(checked)
