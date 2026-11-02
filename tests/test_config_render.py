"""Verify module rendering uses in-memory settings instead of disk reads."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QPixmap, QPolygonF

from core.config_manager import AppConfig
from gui.main_window import MainWindow
from gui.settings_dialog import SettingsDialog
from gui.theme import THEMES, palette
from gui.widgets.update_dialog import UpdateDialog
from gui.widgets.dock_container import FloatingModuleWindow
from gui.frameless_window import NativeDarkWindow
from gui.modules.loudness_widget import LoudnessWidget
from gui.modules.oscilloscope_widget import OscilloscopeWidget
from gui.modules.spectrogram_widget import SpectrogramWidget
from gui.modules.spectrum_widget import SpectrumWidget
from gui.modules.vectorscope_widget import VectorscopeWidget
from gui.modules.vectorscope_widget import HISTORY_POINTS
from gui.modules.waveform_widget import WaveformWidget


class ConfigRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_modules_use_shared_config_and_receive_replacement(self):
        config = AppConfig(theme="custom", accent_color="#FF4570")
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widgets = [cls(worker, config=config) for cls in (
            LoudnessWidget, WaveformWidget, OscilloscopeWidget,
            SpectrumWidget, SpectrogramWidget, VectorscopeWidget,
        )]
        try:
            for widget in widgets:
                self.assertIs(widget.config, config)

            updated = AppConfig(theme="custom", accent_color="#00E5FF", fps_limit=60)
            window = SimpleNamespace(
                config=config, modules={str(i): widget for i, widget in enumerate(widgets)},
                master_timer=Mock(), setWindowOpacity=Mock(), update=Mock(), _apply_theme=Mock(),
            )
            MainWindow._on_config_updated(window, updated)
            for widget in widgets:
                self.assertIs(widget.config, updated)
            self.assertEqual(window.master_timer.setInterval.call_args.args[0], 16)
            window.setWindowOpacity.assert_called_once_with(updated.window_opacity)
        finally:
            for widget in widgets:
                widget.close()

    def test_spectrogram_rebuilds_colors_after_config_change_without_disk(self):
        config = AppConfig(theme="custom", accent_color="#FF4570")
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widget = SpectrogramWidget(worker, config=config)
        widget.resize(520, 300)
        canvas = QPixmap(520, 300)
        try:
            for accent in ("#FF4570", "#00E5FF"):
                config.accent_color = accent
                painter = QPainter(canvas)
                try:
                    widget.render_ui(painter)
                finally:
                    painter.end()
                self.assertEqual(widget.last_accent_hex, accent)
        finally:
            widget.close()

    def test_spectrum_cached_coordinates_match_scalar_calculation_after_rate_change(self):
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widget = SpectrumWidget(worker)
        try:
            for rate in (44100, 48000, 96000):
                widget.sample_rate = rate
                widget._recompute_bar_freqs()
                expected = np.array([
                    widget._freq_to_x_ndc(freq)
                    for freq in widget.bar_freqs_hz[widget._visible_bars]
                ], dtype=np.float32)
                np.testing.assert_allclose(widget._visible_x_coords, expected, atol=1e-6)
                mesh, vertices = widget._build_continuous_mesh_vertices()
                envelope, count = widget._build_envelope_vertices()
                np.testing.assert_allclose(mesh.reshape(-1, 5)[0::2, 0], expected, atol=1e-6)
                np.testing.assert_allclose(envelope.reshape(-1, 2)[:, 0], expected, atol=1e-6)
                self.assertEqual(vertices, 2 * count)
        finally:
            widget.close()

    def test_vectorscope_preserves_history_but_draws_half_the_points(self):
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widget = VectorscopeWidget(worker)
        widget.resize(460, 300)
        canvas = QPixmap(460, 300)
        polygon_sizes = []

        def record_polygon(points):
            polygon_sizes.append(len(points))
            return QPolygonF(points)

        try:
            with patch("gui.modules.vectorscope_widget.QPolygonF", side_effect=record_polygon):
                painter = QPainter(canvas)
                try:
                    widget.render_ui(painter)
                finally:
                    painter.end()
            self.assertEqual(len(widget.points), HISTORY_POINTS)
            self.assertEqual(polygon_sizes, [HISTORY_POINTS // 2])
        finally:
            widget.close()

    def test_settings_tabs_and_live_theme_selection(self):
        config = AppConfig()
        worker = Mock()
        with patch("gui.settings_dialog.list_audio_sources", return_value=([], [])), patch(
            "gui.settings_dialog.save_config"
        ) as save:
            dialog = SettingsDialog(config, worker)
            try:
                self.assertEqual(config.theme, "blue")
                self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
                                 ["Appearance", "Audio", "Performance", "Updates"])
                for theme in THEMES:
                    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData(theme))
                    self.assertEqual(config.theme, theme)
                    self.assertEqual(palette(config)["accent"], THEMES[theme][4])
                dialog._set_accent_color("#123456")
                self.assertEqual((config.theme, palette(config)["accent"]), ("custom", "#123456"))
                self.assertEqual(dialog.theme_combo.currentData(), "custom")
                self.assertTrue(save.called)
            finally:
                dialog.close()

    def test_spectrogram_recolors_existing_history_on_theme_switch(self):
        config = AppConfig()
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widget = SpectrogramWidget(worker, config=config)
        widget.waterfall_levels.fill(140)
        canvas = QPixmap(520, 300)
        try:
            colors = []
            for theme in ("blue", "green"):
                config.theme = theme
                painter = QPainter(canvas)
                try:
                    widget.render_ui(painter)
                finally:
                    painter.end()
                colors.append(widget.waterfall_buffer[0, 0].copy())
            self.assertFalse(np.array_equal(colors[0], colors[1]))
            np.testing.assert_array_equal(widget.waterfall_buffer[0, 0], widget.colormap_lut[140])
        finally:
            widget.close()

    def test_update_dialog_inherits_active_theme(self):
        config = AppConfig(theme="violet")
        with patch("gui.settings_dialog.list_audio_sources", return_value=([], [])):
            settings = SettingsDialog(config, Mock())
            dialog = UpdateDialog({"tag_name": "vNext"}, parent=settings)
            try:
                self.assertEqual(dialog.theme_colors["accent"], THEMES["violet"][4])
                self.assertIn(THEMES["violet"][1], dialog.styleSheet())
            finally:
                dialog.close()
                settings.close()

    def test_meter_header_popout_icons_and_floating_titles(self):
        config = AppConfig(theme="blue")
        worker = Mock()
        worker.create_reader.return_value.read_chunk.return_value = None
        widgets = [widget_class(worker, config=config) for widget_class in (
            LoudnessWidget, WaveformWidget, OscilloscopeWidget,
            SpectrumWidget, SpectrogramWidget, VectorscopeWidget,
        )]
        try:
            for widget in widgets:
                self.assertFalse(widget.is_standalone)
                widget.apply_theme(palette(config))
                self.assertFalse(hasattr(widget, "help_btn"))
                self.assertEqual(widget.undock_btn.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
                image = widget.undock_btn.icon().pixmap(16, 16).toImage()
                self.assertFalse(image.isNull())
                self.assertTrue(any(image.pixelColor(x, y).alpha() for x in range(16) for y in range(16)))
                widget.set_standalone_mode(True)
                self.assertTrue(widget.header_frame.isHidden())
                widget.set_standalone_mode(False)
                self.assertFalse(widget.header_frame.isHidden())
        finally:
            for widget in widgets:
                widget.close()

    def test_floating_toolbar_matches_theme_and_pin_state(self):
        window = FloatingModuleWindow("oscilloscope", "Oscilloscope")
        try:
            for name in ("blue", "pink"):
                colors = palette(AppConfig(theme=name))
                window.apply_theme(colors)
                self.assertEqual(window.mini_bar.height(), 34)
                self.assertIn(colors["accent"], window.mini_bar.styleSheet())
                self.assertEqual(window.redock_btn.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextOnly)
                self.assertEqual(window.pin_btn.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextOnly)
                self.assertEqual(window.pin_btn.styleSheet(), "")
            with patch.object(NativeDarkWindow, "set_always_on_top") as pin:
                window.pin_btn.click()
                pin.assert_called_with(True)
                self.assertTrue(window.pin_btn.isChecked())
                window.pin_btn.click()
                pin.assert_called_with(False)
                self.assertFalse(window.pin_btn.isChecked())
        finally:
            window._is_closing = True
            window.close()


if __name__ == "__main__":
    unittest.main()
