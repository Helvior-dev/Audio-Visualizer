"""
Main Application Suite Window for Audio Visualizer.
Manages the balanced 2x3 suite layout:
  Row 0: [ WAVEFORM ] [ OSCILLOSCOPE ] [ STEREOMETER ]
  Row 1: [ SPECTRUM ANALYZER ] [ SPECTROGRAM ] [ LOUDNESS METER ]
Individual meter toggles, undocking/docking with informative detached placeholders,
Dynamic Suite Pause button (pauses docked visualizations when external windows are open),
and settings. Includes Master Render Timer for silky smooth window moving and 0% CPU overhead.
"""

from PyQt6.QtCore import Qt, QRect, QSize, QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy
)
from .frameless_window import FramelessWindow
from .widgets.titlebar import TitleBar
from .widgets.dock_container import DockCard, FloatingModuleWindow
from .settings_dialog import SettingsDialog
from .modules.loudness_widget import LoudnessWidget
from .modules.waveform_widget import WaveformWidget
from .modules.oscilloscope_widget import OscilloscopeWidget
from .modules.spectrum_widget import SpectrumWidget
from .modules.spectrogram_widget import SpectrogramWidget
from .modules.vectorscope_widget import VectorscopeWidget
from core.config_manager import AppConfig, save_config
from core.audio_worker import AudioWorker


class MainWindow(FramelessWindow):
    def __init__(self, config: AppConfig, audio_worker: AudioWorker, parent=None):
        super().__init__(parent)
        self.config = config
        self.audio_worker = audio_worker
        self.setWindowTitle("AUDIO VISUALIZER")

        self.modules = {}
        self.dock_cards = {}
        self.floating_windows = {}
        self._is_suite_paused = False

        # 1. Custom Titlebar
        self.title_bar = TitleBar(self, title="AUDIO VISUALIZER", is_floating=False, is_main=True)
        self.title_bar.pin_toggled.connect(self.set_always_on_top)
        self.title_bar.settings_clicked.connect(self._open_settings)
        self.title_bar.module_toggled.connect(self._toggle_module)
        self.title_bar.pause_suite_toggled.connect(self._on_pause_suite_toggled)
        self.title_bar.undock_all_toggled.connect(self._toggle_undock_all)

        self.main_layout.addWidget(self.title_bar)

        # 2. Main Content Container & Layout
        self.content_widget = QWidget(self)
        self.content_layout = None
        self.main_layout.addWidget(self.content_widget, 1)

        # 3. Create all 6 Visualizer Modules
        self._init_modules()

        # 4. Apply initial layout and active states
        self._rebuild_layout()
        self._apply_initial_state()

        # 5. Master Render Timer (synchronizes all docked modules with 0% drag lag)
        self.master_timer = QTimer(self)
        self.master_timer.timeout.connect(self._on_master_render_tick)
        self.master_timer.start(max(5, int(1000.0 / max(1, self.config.fps_limit))))

    def _init_modules(self):
        title_map = {
            "loudness": "Loudness Meter",
            "waveform": "Waveform",
            "oscilloscope": "Oscilloscope",
            "spectrum": "Spectrum Analyzer",
            "spectrogram": "Spectrogram",
            "vectorscope": "Stereometer",
        }

        # Instantiate visualizer widgets
        self.modules = {
            "loudness": LoudnessWidget(self.audio_worker),
            "waveform": WaveformWidget(self.audio_worker),
            "oscilloscope": OscilloscopeWidget(self.audio_worker),
            "spectrum": SpectrumWidget(self.audio_worker),
            "spectrogram": SpectrogramWidget(self.audio_worker),
            "vectorscope": VectorscopeWidget(self.audio_worker),
        }

        # Wrap in DockCards and connect undock requests
        for mod_id, widget in self.modules.items():
            widget.undock_requested.connect(lambda m=mod_id: self._undock_module(m))
            widget.timer.stop()
            card = DockCard(mod_id, widget, title=title_map.get(mod_id, mod_id.capitalize()))
            card.redock_requested.connect(self._redock_module)
            self.dock_cards[mod_id] = card

    def _on_pause_suite_toggled(self, is_paused: bool):
        self._is_suite_paused = is_paused
        for mod_id, widget in self.modules.items():
            if not self.config.floating_modules.get(mod_id, False):
                widget.is_paused = is_paused
                widget.update()

    def _on_master_render_tick(self):
        if not self.isVisible() or self.isMinimized() or self._is_suite_paused:
            return
        for mod_id, widget in self.modules.items():
            if not self.config.floating_modules.get(mod_id, False) and self.config.active_modules.get(mod_id, True):
                try:
                    widget.update()
                except RuntimeError:
                    pass

    def _apply_initial_state(self):
        self.setWindowOpacity(self.config.window_opacity)

        for widget in self.modules.values():
            widget.set_fps(self.config.fps_limit)

        if self.config.always_on_top:
            self.set_always_on_top(True)
            self.title_bar._is_pinned = True
            self.title_bar.pin_btn.setStyleSheet("color: #58A6FF;")

        geom = self.config.window_geometry.get("main", {"x": 100, "y": 100, "width": 1280, "height": 600})
        self.setGeometry(geom.get("x", 100), geom.get("y", 100), max(600, geom.get("width", 1280)), max(360, geom.get("height", 600)))

        for mod_id, is_active in self.config.active_modules.items():
            self.title_bar.set_module_checked(mod_id, is_active)
            card = self.dock_cards.get(mod_id)
            if card:
                card.setVisible(is_active)

        for mod_id, is_floating in list(self.config.floating_modules.items()):
            if is_floating:
                self._undock_module(mod_id)

        self._update_floating_status()

    def _update_floating_status(self):
        has_floating = any(self.config.floating_modules.values())
        self.title_bar.set_has_floating(has_floating)

        active_mods = [m for m, active in self.config.active_modules.items() if active]
        all_undocked = len(active_mods) > 0 and all(self.config.floating_modules.get(m, False) for m in active_mods)
        self.title_bar.set_undock_all_state(all_undocked)

    def _toggle_undock_all(self, undock_all: bool):
        if undock_all:
            for mod_id in list(self.modules.keys()):
                if not self.config.floating_modules.get(mod_id, False) and self.config.active_modules.get(mod_id, True):
                    self._undock_module(mod_id)
        else:
            for mod_id in list(self.floating_windows.keys()):
                self._redock_module(mod_id)

    def _rebuild_layout(self):
        old_layout = self.content_widget.layout()
        if old_layout is not None:
            while old_layout.count() > 0:
                old_layout.takeAt(0)
            from PyQt6.sip import delete
            delete(old_layout)

        layout = QGridLayout(self.content_widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 3 columns, 2 rows
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)

        # Row 0: Waveform (col 0), Oscilloscope (col 1), Stereometer (col 2)
        layout.addWidget(self.dock_cards["waveform"], 0, 0, 1, 1)
        layout.addWidget(self.dock_cards["oscilloscope"], 0, 1, 1, 1)
        layout.addWidget(self.dock_cards["vectorscope"], 0, 2, 1, 1)

        # Row 1: Spectrum (col 0), Spectrogram (col 1), Loudness (col 2)
        layout.addWidget(self.dock_cards["spectrum"], 1, 0, 1, 1)
        layout.addWidget(self.dock_cards["spectrogram"], 1, 1, 1, 1)
        layout.addWidget(self.dock_cards["loudness"], 1, 2, 1, 1)

        self.content_layout = layout

    def _toggle_module(self, module_id: str, checked: bool):
        self.config.active_modules[module_id] = checked
        self.title_bar.set_module_checked(module_id, checked)
        if self.config.floating_modules.get(module_id, False):
            float_win = self.floating_windows.get(module_id)
            if float_win:
                float_win.setVisible(checked)
                if checked:
                    float_win.raise_()
        card = self.dock_cards.get(module_id)
        if card:
            card.setVisible(checked)
        save_config(self.config)

    def _undock_module(self, module_id: str):
        if module_id not in self.modules:
            return

        widget = self.modules[module_id]
        card = self.dock_cards[module_id]

        card.main_layout.removeWidget(widget)
        card.set_detached(True)

        widget.is_paused = False
        widget.set_standalone_mode(True)

        title_map = {
            "loudness": "Loudness Meter",
            "waveform": "Waveform",
            "oscilloscope": "Oscilloscope",
            "spectrum": "Spectrum Analyzer",
            "spectrogram": "Spectrogram",
            "vectorscope": "Stereometer",
        }
        
        default_sizes = {
            "loudness": (550, 300),
            "waveform": (650, 280),
            "oscilloscope": (650, 320),
            "spectrum": (580, 320),
            "spectrogram": (550, 300),
            "vectorscope": (460, 460),
        }

        float_win = FloatingModuleWindow(module_id, title=title_map.get(module_id, module_id.capitalize()))
        float_win.attach_widget(widget)
        float_win.redock_requested.connect(self._redock_module)

        d_w, d_h = default_sizes.get(module_id, (460, 320))
        saved_geom = self.config.window_geometry.get(module_id, {"x": 200, "y": 200, "width": d_w, "height": d_h})
        float_win.setGeometry(
            saved_geom.get("x", 200), saved_geom.get("y", 200),
            max(d_w, saved_geom.get("width", d_w)), max(d_h, saved_geom.get("height", d_h))
        )
        float_win.set_always_on_top(self.is_always_on_top())

        self.floating_windows[module_id] = float_win
        self.config.floating_modules[module_id] = True
        save_config(self.config)

        is_active = self.config.active_modules.get(module_id, True)
        float_win.setVisible(is_active)
        if is_active:
            widget.show()

        self._update_floating_status()

    def _redock_module(self, module_id: str):
        widget = self.modules.get(module_id)
        card = self.dock_cards.get(module_id)

        if module_id in self.floating_windows:
            float_win = self.floating_windows.pop(module_id)
            geom = float_win.geometry()
            self.config.window_geometry[module_id] = {
                "x": geom.x(), "y": geom.y(), "width": geom.width(), "height": geom.height()
            }
            float_win._is_closing = True
            detached_w = float_win.detach_widget()
            if detached_w:
                widget = detached_w
            float_win.close()

        if widget and card:
            widget.set_standalone_mode(False)
            widget.is_paused = self._is_suite_paused
            card.main_layout.insertWidget(0, widget)
            card.set_detached(False)
            widget.show()

        self.config.floating_modules[module_id] = False
        save_config(self.config)
        self._update_floating_status()

    def set_always_on_top(self, pinned: bool):
        self.config.always_on_top = pinned
        super().set_always_on_top(pinned)
        for float_win in self.floating_windows.values():
            float_win.set_always_on_top(pinned)
        save_config(self.config)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_R:
            if "loudness" in self.modules:
                self.modules["loudness"].reset_stats()
            self.update()
            return
        super().keyPressEvent(event)

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self.audio_worker, self)
        dlg.config_updated.connect(self._on_config_updated)
        dlg.exec()

    def _on_config_updated(self, new_config: AppConfig):
        self.config = new_config
        self.setWindowOpacity(self.config.window_opacity)
        self.master_timer.setInterval(max(5, int(1000.0 / max(1, self.config.fps_limit))))
        for w in self.modules.values():
            w.set_fps(self.config.fps_limit)
        self.update()

    def closeEvent(self, event):
        self.master_timer.stop()
        
        geom = self.geometry()
        self.config.window_geometry["main"] = {
            "x": geom.x(), "y": geom.y(), "width": geom.width(), "height": geom.height()
        }
        for mod_id, float_win in list(self.floating_windows.items()):
            try:
                fg = float_win.geometry()
                self.config.window_geometry[mod_id] = {
                    "x": fg.x(), "y": fg.y(), "width": fg.width(), "height": fg.height()
                }
                float_win._is_closing = True
                float_win.detach_widget()
                float_win.close()
            except Exception:
                pass

        self.floating_windows.clear()
        save_config(self.config)
        self.audio_worker.close()
        super().closeEvent(event)

        app = QApplication.instance()
        if app:
            app.quit()
