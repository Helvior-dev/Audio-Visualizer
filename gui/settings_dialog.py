"""
Settings & Audio Device Configuration Dialog.
Allows selecting audio devices (System loopback or physical microphones),
target frame rates, window opacity, and custom accent theme colors.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QSlider,
    QPushButton, QGroupBox, QFrame, QWidget, QColorDialog, QTabWidget
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
from .theme import THEMES, palette

class SettingsDialog(QDialog):
    config_updated = pyqtSignal(AppConfig)

    def __init__(self, config: AppConfig, audio_worker: AudioWorker, parent=None):
        super().__init__(parent)
        self.config = config
        self.audio_worker = audio_worker
        self._update_worker = None

        self.setWindowTitle("Settings")
        self.resize(580, 410)
        self.setMinimumSize(500, 360)
        self.apply_theme()

        self._init_ui()
        self._load_devices()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Header Title
        title_lbl = QLabel("SETTINGS & CUSTOMIZATION", self)
        title_lbl.setFont(QFont("Cascadia Mono", 12, QFont.Weight.Bold))
        layout.addWidget(title_lbl)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)
        appearance = QWidget(self)
        audio = QWidget(self)
        performance = QWidget(self)
        updates = QWidget(self)
        for page, label in ((appearance, "Appearance"), (audio, "Audio"),
                            (performance, "Performance"), (updates, "Updates")):
            self.tabs.addTab(page, label)

        appearance_layout = QVBoxLayout(appearance)
        audio_layout = QVBoxLayout(audio)
        performance_layout = QVBoxLayout(performance)
        updates_layout = QVBoxLayout(updates)

        # -------------------------------------------------------------
        # 1. Accent Theme & Colors (2-Row Clean Grid)
        # -------------------------------------------------------------
        theme_group = QGroupBox("COLOR THEME", appearance)
        tg_layout = QVBoxLayout(theme_group)
        tg_layout.setSpacing(8)
        tg_layout.addWidget(QLabel("Choose a complete palette for the interface and meters:"))
        self.theme_combo = QComboBox(theme_group)
        for key, values in THEMES.items():
            self.theme_combo.addItem(values[0], key)
        self.theme_combo.addItem("Custom accent (blue base)", "custom")
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.config.theme))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        tg_layout.addWidget(self.theme_combo)

        custom_container = QWidget(theme_group)
        cc_layout = QHBoxLayout(custom_container)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        self.color_preview = QLabel(custom_container)
        self.color_preview.setFixedSize(22, 22)
        cc_layout.addWidget(self.color_preview)
        custom_btn = QPushButton("Choose custom accent...", custom_container)
        custom_btn.clicked.connect(self._pick_custom_color)
        cc_layout.addWidget(custom_btn)
        cc_layout.addStretch(1)
        tg_layout.addWidget(custom_container)
        appearance_layout.addWidget(theme_group)

        # -------------------------------------------------------------
        # 2. Audio Capture Source
        # -------------------------------------------------------------
        audio_group = QGroupBox("AUDIO CAPTURE SOURCE", audio)
        ag_layout = QVBoxLayout(audio_group)
        ag_layout.setSpacing(6)
        ag_layout.addWidget(QLabel("Select Output (Loopback) or Microphone:"))

        self.device_combo = QComboBox(self)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        ag_layout.addWidget(self.device_combo)
        audio_layout.addWidget(audio_group)
        audio_layout.addStretch(1)

        # -------------------------------------------------------------
        # 3. Performance & Display
        # -------------------------------------------------------------
        perf_group = QGroupBox("FRAME RATE", performance)
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
        performance_layout.addWidget(perf_group)

        display_group = QGroupBox("WINDOW", appearance)
        display_layout = QVBoxLayout(display_group)

        opac_layout = QHBoxLayout()
        opac_layout.addWidget(QLabel("Window Opacity:"))
        self.opac_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opac_slider.setRange(30, 100)
        self.opac_slider.setValue(int(self.config.window_opacity * 100))
        self.opac_slider.valueChanged.connect(self._on_opacity_changed)
        opac_layout.addWidget(self.opac_slider)
        self.opac_val_lbl = QLabel(f"{int(self.config.window_opacity * 100)}%", self)
        opac_layout.addWidget(self.opac_val_lbl)
        display_layout.addLayout(opac_layout)
        appearance_layout.addWidget(display_group)
        appearance_layout.addStretch(1)
        performance_layout.addStretch(1)

        # -------------------------------------------------------------
        # 4. Updates & Software
        # -------------------------------------------------------------
        updates_group = QGroupBox("UPDATES & SOFTWARE", updates)
        ug_layout = QVBoxLayout(updates_group)
        ug_layout.setSpacing(6)

        ver_row = QHBoxLayout()
        ver_lbl = QLabel(f"Current version: <b style='color: #FFFFFF;'>v{__version__}</b>", self)
        ver_row.addWidget(ver_lbl)
        ver_row.addStretch(1)

        self.check_update_btn = QPushButton("Check for Updates", self)
        self.check_update_btn.setFixedHeight(26)
        self.check_update_btn.clicked.connect(self._check_for_updates)
        ver_row.addWidget(self.check_update_btn)

        ug_layout.addLayout(ver_row)

        self.update_status_lbl = QLabel("", self)
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #888899;")
        ug_layout.addWidget(self.update_status_lbl)

        updates_layout.addWidget(updates_group)
        updates_layout.addStretch(1)

        # Bottom Close Button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Done", self)
        close_btn.setProperty("class", "primary-btn")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        self.apply_theme()

    def _set_accent_color(self, hex_code: str):
        self.config.theme = "custom"
        self.config.accent_color = hex_code
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData("custom"))
        self.theme_combo.blockSignals(False)
        self.apply_theme()
        save_config(self.config)
        self.config_updated.emit(self.config)

    def _on_theme_changed(self, index: int):
        name = self.theme_combo.itemData(index)
        if name is None:
            return
        self.config.theme = name
        if name != "custom":
            self.config.accent_color = THEMES[name][4]
        self.apply_theme()
        save_config(self.config)
        self.config_updated.emit(self.config)

    def apply_theme(self):
        colors = palette(self.config)
        self.setStyleSheet(f"""
            QDialog {{ background: {colors['root']}; color: {colors['text']};
                font-family: 'Cascadia Mono', Consolas, monospace; }}
            QTabWidget::pane {{ border: 1px solid {colors['border']}; }}
            QTabBar::tab {{ background: {colors['root']}; color: {colors['muted']};
                border: 0; border-bottom: 2px solid transparent; padding: 9px 13px; }}
            QTabBar::tab:selected {{ color: {colors['accent']}; border-bottom-color: {colors['fill']}; }}
            QGroupBox {{ color: {colors['accent']}; border: 1px solid {colors['border']};
                margin-top: 12px; padding-top: 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 0 6px; }}
            QLabel {{ color: {colors['text']}; }}
            QPushButton, QComboBox {{ background: {colors['card']}; color: {colors['text']};
                border: 1px solid {colors['border']}; border-radius: 0; padding: 6px 9px; }}
            QPushButton:hover, QComboBox:hover {{ border-color: {colors['accent']}; }}
            QComboBox QAbstractItemView {{ background: {colors['card']}; color: {colors['text']};
                selection-background-color: {colors['grid']}; border: 1px solid {colors['border']}; }}
            QSlider::groove:horizontal {{ height: 4px; background: {colors['grid']}; }}
            QSlider::sub-page:horizontal {{ background: {colors['fill']}; }}
            QSlider::handle:horizontal {{ background: {colors['accent']}; width: 12px; margin: -5px 0; }}
        """)
        if hasattr(self, "color_preview"):
            self.color_preview.setStyleSheet(f"background: {colors['accent']}; border: 1px solid {colors['border']};")

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
            self.device_combo.addItem(f"System Audio: {src.name}", src)

        for src in mic_list:
            self._sources.append(src)
            self.device_combo.addItem(f"Microphone: {src.name}", src)

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
        self.update_status_lbl.setStyleSheet(f"font-size: 10px; color: {palette(self.config)['accent']};")

        self._update_worker = UpdateCheckWorker(current_version=__version__, parent=self)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_worker.no_update.connect(self._on_no_update)
        self._update_worker.error_occurred.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_available(self, release_info: dict):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")
        new_tag = release_info.get("tag_name", "vNext")
        self.update_status_lbl.setText(f"Version {new_tag} is available.")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #3DDC84; font-weight: bold;")
        dlg = UpdateDialog(release_info, is_preview=False, parent=self)
        dlg.exec()

    def _on_no_update(self, release_info: dict):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")
        self.update_status_lbl.setText(f"You have the latest version (v{__version__}).")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #3DDC84;")

    def _on_update_error(self, err_msg: str):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("Check for Updates")
        self.update_status_lbl.setText(f"Failed to check: {err_msg}")
        self.update_status_lbl.setStyleSheet("font-size: 10px; color: #FF4570;")
