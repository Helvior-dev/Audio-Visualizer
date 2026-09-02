"""
Settings & Audio Device Configuration Dialog.
Allows selecting audio devices (System loopback or physical microphones),
target frame rates, window opacity, and custom accent theme colors.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QSlider,
    QPushButton, QGroupBox, QFrame, QWidget, QColorDialog
)
from PyQt6.QtGui import QFont, QColor
from core.audio_capture import (
    list_audio_sources, AudioSource, KIND_LOOPBACK, KIND_MICROPHONE
)
from core.config_manager import AppConfig, save_config
from core.audio_worker import AudioWorker
from core.version import __version__, RELEASES_URL
from core.updater import UpdateCheckWorker
from .widgets.update_dialog import UpdateDialog

ACCENT_PRESETS = [
    ("Spectrum Magenta", "#FF4570"),
    ("Default Blue", "#58A6FF"),
    ("Neon Green", "#3DDC84"),
    ("Cyberpunk Cyan", "#00E5FF"),
    ("Hot Pink", "#FF2A85"),
    ("Amber Gold", "#FFB300"),
    ("Slate Blue", "#9BB3CE"),
]


class SettingsDialog(QDialog):
    config_updated = pyqtSignal(AppConfig)

    def __init__(self, config: AppConfig, audio_worker: AudioWorker, parent=None):
        super().__init__(parent)
        self.config = config
        self.audio_worker = audio_worker
        self._update_worker = None

        self.setWindowTitle("Settings")
        self.setFixedSize(540, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #14141A;
                color: #D8D8E0;
                font-family: 'Segoe UI', Arial, sans-serif;
                border: 1px solid #282834;
                border-radius: 6px;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                color: #58A6FF;
                border: 1px solid #242430;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }
            QLabel {
                color: #C0C0C8;
                font-size: 11px;
            }
            QComboBox {
                background-color: #1E1E26;
                color: #FFFFFF;
                border: 1px solid #343444;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox QAbstractItemView {
                background-color: #1E1E26;
                color: #FFFFFF;
                selection-background-color: #343448;
                selection-color: #58A6FF;
                border: 1px solid #343444;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #282836;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #58A6FF;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 1px solid #58A6FF;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #20202A;
                color: #FFFFFF;
                border: 1px solid #343444;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2C2C3C;
                border-color: #58A6FF;
            }
            QPushButton.primary-btn {
                background-color: #1F6FEB;
                border-color: #388BFD;
            }
            QPushButton.primary-btn:hover {
                background-color: #388BFD;
            }
        """)

        self._init_ui()
        self._load_devices()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Header Title
        title_lbl = QLabel("SETTINGS & CUSTOMIZATION", self)
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FFFFFF; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        # -------------------------------------------------------------
        # 1. Accent Theme & Colors (2-Row Clean Grid)
        # -------------------------------------------------------------
        theme_group = QGroupBox("ACCENT THEME & COLORS", self)
        tg_layout = QVBoxLayout(theme_group)
        tg_layout.setSpacing(8)

        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(8)

        self.preset_btns = []
        for idx, (name, hex_code) in enumerate(ACCENT_PRESETS):
            btn = QPushButton(name, theme_group)
            btn.setFixedHeight(28)
            is_active = (self.config.accent_color.upper() == hex_code.upper())
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#2A2A38' if is_active else '#181820'};
                    border: 1.5px solid {hex_code};
                    color: {hex_code};
                    font-size: 11px;
                    border-radius: 4px;
                    padding: 2px 8px;
                }}
                QPushButton:hover {{
                    background-color: #323244;
                }}
            """)
            btn.clicked.connect(lambda _, h=hex_code: self._set_accent_color(h))
            row = idx // 4
            col = idx % 4
            grid_layout.addWidget(btn, row, col)
            self.preset_btns.append((btn, hex_code))

        # Pick Custom Color button on row 1, col 3
        custom_container = QWidget(theme_group)
        cc_layout = QHBoxLayout(custom_container)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        cc_layout.setSpacing(6)

        self.color_preview = QLabel(custom_container)
        self.color_preview.setFixedSize(22, 22)
        self.color_preview.setStyleSheet(f"background-color: {self.config.accent_color}; border: 1px solid #444; border-radius: 3px;")
        cc_layout.addWidget(self.color_preview)

        custom_btn = QPushButton("🎨 Pick...", custom_container)
        custom_btn.setFixedHeight(28)
        custom_btn.clicked.connect(self._pick_custom_color)
        cc_layout.addWidget(custom_btn)

        grid_layout.addWidget(custom_container, 1, 3)

        tg_layout.addLayout(grid_layout)
        layout.addWidget(theme_group)

        # -------------------------------------------------------------
        # 2. Audio Capture Source
        # -------------------------------------------------------------
        audio_group = QGroupBox("AUDIO CAPTURE SOURCE", self)
        ag_layout = QVBoxLayout(audio_group)
        ag_layout.setSpacing(6)
        ag_layout.addWidget(QLabel("Select Output (Loopback) or Microphone:"))

        self.device_combo = QComboBox(self)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        ag_layout.addWidget(self.device_combo)
        layout.addWidget(audio_group)

        # -------------------------------------------------------------
        # 3. Performance & Display
        # -------------------------------------------------------------
        perf_group = QGroupBox("DISPLAY & PERFORMANCE", self)
        pg_layout = QVBoxLayout(perf_group)
        pg_layout.setSpacing(8)

        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("Target Frame Rate (FPS):"))
        self.fps_combo = QComboBox(self)
        self.fps_combo.addItems(["30 FPS", "60 FPS", "120 FPS", "144 FPS"])
        fps_map = {30: 0, 60: 1, 120: 2, 144: 3}
        self.fps_combo.setCurrentIndex(fps_map.get(self.config.fps_limit, 3))
        self.fps_combo.currentIndexChanged.connect(self._on_fps_changed)
        fps_layout.addWidget(self.fps_combo)
        pg_layout.addLayout(fps_layout)

        opac_layout = QHBoxLayout()
        opac_layout.addWidget(QLabel("Window Opacity:"))
        self.opac_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opac_slider.setRange(30, 100)
        self.opac_slider.setValue(int(self.config.window_opacity * 100))
        self.opac_slider.valueChanged.connect(self._on_opacity_changed)
        opac_layout.addWidget(self.opac_slider)
        self.opac_val_lbl = QLabel(f"{int(self.config.window_opacity * 100)}%", self)
        opac_layout.addWidget(self.opac_val_lbl)
        pg_layout.addLayout(opac_layout)

        layout.addWidget(perf_group)

        # -------------------------------------------------------------
        # 4. Updates & Software
        # -------------------------------------------------------------
        updates_group = QGroupBox("UPDATES & SOFTWARE", self)
        ug_layout = QVBoxLayout(updates_group)
        ug_layout.setSpacing(6)

        ver_row = QHBoxLayout()
        ver_lbl = QLabel(f"Current version: <b style='color: #FFFFFF;'>v{__version__}</b>", self)
        ver_row.addWidget(ver_lbl)
        ver_row.addStretch(1)

        self.check_update_btn = QPushButton("🔄 Check for Updates", self)
        self.check_update_btn.setFixedHeight(26)
        self.check_update_btn.clicked.connect(self._check_for_updates)
        ver_row.addWidget(self.check_update_btn)

        ug_layout.addLayout(ver_row)

        self.update_status_lbl = QLabel("", self)
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #888899;")
        ug_layout.addWidget(self.update_status_lbl)

        layout.addWidget(updates_group)

        layout.addStretch(1)

        # Bottom Close Button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Done", self)
        close_btn.setProperty("class", "primary-btn")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _set_accent_color(self, hex_code: str):
        self.config.accent_color = hex_code
        self.color_preview.setStyleSheet(f"background-color: {hex_code}; border: 1px solid #444; border-radius: 3px;")
        for btn, h in self.preset_btns:
            is_active = (h.upper() == hex_code.upper())
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#2A2A38' if is_active else '#181820'};
                    border: 1.5px solid {h};
                    color: {h};
                    font-size: 11px;
                    border-radius: 4px;
                    padding: 2px 8px;
                }}
            """)
        save_config(self.config)
        self.config_updated.emit(self.config)

    def _pick_custom_color(self):
        col = QColorDialog.getColor(QColor(self.config.accent_color), self, "Select Accent Color")
        if col.isValid():
            self._set_accent_color(col.name())

    def _load_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self._sources = []

        loopback_list, mic_list = list_audio_sources()

        for src in loopback_list:
            self._sources.append(src)
            self.device_combo.addItem(f"🔊 [Output Loopback] {src.name}", src)

        for src in mic_list:
            self._sources.append(src)
            self.device_combo.addItem(f"🎤 [Microphone] {src.name}", src)

        current_kind = self.config.audio_source_kind
        current_idx = self.config.audio_source_device_index

        found_match = False
        for i, src in enumerate(self._sources):
            if src.kind == current_kind and src.device_index == current_idx:
                self.device_combo.setCurrentIndex(i)
                found_match = True
                break

        if not found_match and len(self._sources) > 0:
            self.device_combo.setCurrentIndex(0)

        self.device_combo.blockSignals(False)

    def _on_device_changed(self, idx: int):
        if 0 <= idx < len(self._sources):
            selected = self._sources[idx]
            self.config.audio_source_kind = selected.kind
            self.config.audio_source_device_index = selected.device_index
            self.config.audio_source_name = selected.name
            self.audio_worker.change_source(selected)
            save_config(self.config)
            self.config_updated.emit(self.config)

    def _on_fps_changed(self, idx: int):
        fps_values = [30, 60, 120, 144]
        self.config.fps_limit = fps_values[idx]
        save_config(self.config)
        self.config_updated.emit(self.config)

    def _on_opacity_changed(self, val: int):
        self.config.window_opacity = val / 100.0
        self.opac_val_lbl.setText(f"{val}%")
        save_config(self.config)
        self.config_updated.emit(self.config)

    def _check_for_updates(self):
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("Checking...")
        self.update_status_lbl.setText("Connecting to GitHub...")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #58A6FF;")

        self._update_worker = UpdateCheckWorker(current_version=__version__, parent=self)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_worker.no_update.connect(self._on_no_update)
        self._update_worker.error_occurred.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_available(self, release_info: dict):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("🔄 Check for Updates")
        new_tag = release_info.get("tag_name", "vNext")
        self.update_status_lbl.setText(f"🎉 New version {new_tag} is available!")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #3DDC84; font-weight: bold;")
        dlg = UpdateDialog(release_info, is_preview=False, parent=self)
        dlg.exec()

    def _on_no_update(self, release_info: dict):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("🔄 Check for Updates")
        self.update_status_lbl.setText(f"✓ You are using the latest version (v{__version__})")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #3DDC84;")

    def _on_update_error(self, err_msg: str):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("🔄 Check for Updates")
        self.update_status_lbl.setText(f"Failed to check: {err_msg}")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #FF4570;")
