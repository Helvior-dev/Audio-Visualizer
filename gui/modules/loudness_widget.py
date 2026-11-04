"""
Loudness & Level Meter Module (PyQt6).
Dual-channel sample-peak bars, a LUFS/RMS bar and a statistics panel with
short-term/integrated LUFS, LRA and True Peak. Click to cycle modes.
"""

import time
import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from ..base_meter_widget import BaseMeterWidget
from core.dsp import LoudnessProcessor, DB_MIN, DB_MAX
from core.audio_worker import AudioWorker
from core.config_manager import AppConfig
from ..theme import palette

DB_MIN_METER = -60.0
DB_MAX_METER = 0.0

SCALE_TICKS = [0, 6, 12, 24, 36, 50]

MODES = [
    {"name": "LUFS (Momentary)", "unit": "LUFS", "key": "momentary_lufs"},
    {"name": "LUFS (Short-Term)", "unit": "LUFS", "key": "shortterm_lufs"},
    {"name": "RMS (Fast)", "unit": "RMS", "key": "rms_fast"},
    {"name": "RMS (Slow)", "unit": "RMS", "key": "rms_slow"},
    {"name": "RMS (Fast +3dB)", "unit": "RMS", "key": "rms_fast_3"},
    {"name": "RMS (Slow +3dB)", "unit": "RMS", "key": "rms_slow_3"},
]

class ChannelBallistics:
    ATTACK_PER_SEC = 220.0
    RELEASE_PER_SEC = 28.0
    PEAK_DECAY_DB_PER_SEC = 14.0

    def __init__(self):
        self.displayed_db = DB_MIN_METER
        self.peak_db = DB_MIN_METER

    def push_audio(self, samples: np.ndarray, dt: float):
        if len(samples) > 0:
            pk = float(np.max(np.abs(samples)))
        else:
            pk = 0.0

        pk_db = 20.0 * np.log10(max(pk, 1e-6))
        pk_db = max(DB_MIN_METER, min(DB_MAX_METER, pk_db))

        if pk_db >= self.displayed_db:
            self.displayed_db = pk_db
        else:
            self.displayed_db = max(DB_MIN_METER, self.displayed_db - self.RELEASE_PER_SEC * dt)

        if pk_db >= self.peak_db:
            self.peak_db = pk_db
        else:
            self.peak_db = max(self.displayed_db, self.peak_db - self.PEAK_DECAY_DB_PER_SEC * dt)

    def decay_idle(self, dt: float):
        self.displayed_db = max(DB_MIN_METER, self.displayed_db - self.RELEASE_PER_SEC * dt)
        self.peak_db = max(self.displayed_db, self.peak_db - self.PEAK_DECAY_DB_PER_SEC * dt)


class LoudnessWidget(BaseMeterWidget):
    def __init__(self, audio_worker: AudioWorker, parent=None, config: AppConfig | None = None):
        super().__init__("LOUDNESS", parent)
        self.config = config if config is not None else AppConfig()
        self.audio_worker = audio_worker
        self.reader = audio_worker.create_reader(chunk_size=256)
        self.loudness_proc = LoudnessProcessor(44100)
        self.ch_left = ChannelBallistics()
        self.ch_right = ChannelBallistics()
        self.last_time = time.monotonic()

        self.mode_index = 0
        self.loudness_displayed = DB_MIN_METER
        self.loudness_peak_hold = DB_MIN_METER
        self.mode_toast_time = 0.0

    def reset_stats(self):
        self.loudness_proc.reset_integrated()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mode_index = (self.mode_index + 1) % len(MODES)
            self.mode_toast_time = time.monotonic()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.mode_index = (self.mode_index - 1) % len(MODES)
            self.mode_toast_time = time.monotonic()
            self.update()
        super().mousePressEvent(event)

    def _db_to_y(self, db: float, y_bot: float, y_top: float) -> float:
        t = max(0.0, min(1.0, (db - DB_MIN_METER) / (DB_MAX_METER - DB_MIN_METER)))
        return y_bot - t * (y_bot - y_top)

    def _get_current_loudness(self) -> tuple[float, str]:
        mode = MODES[self.mode_index]
        key = mode["key"]
        if hasattr(self.loudness_proc, key):
            val = getattr(self.loudness_proc, key)
        else:
            val = self.loudness_proc.momentary_lufs
        return val, mode["unit"]

    def render_ui(self, painter: QPainter):
        now = time.monotonic()
        dt = max(0.001, min(0.1, now - self.last_time))
        self.last_time = now

        cfg = self.config
        colors = palette(cfg)

        # Read audio chunk
        if not self.is_paused:
            chunk_info = self.reader.read_chunk()
            if chunk_info is not None:
                samples, rate, channels = chunk_info
                if self.loudness_proc.sample_rate != rate and rate > 0:
                    self.loudness_proc = LoudnessProcessor(rate)

                if channels >= 2:
                    left = samples[:, 0]
                    right = samples[:, 1]
                elif channels == 1:
                    left = samples[:, 0]
                    right = samples[:, 0]
                else:
                    left = np.zeros(len(samples), dtype=np.float32)
                    right = np.zeros(len(samples), dtype=np.float32)

                self.loudness_proc.process(left, right, dt)
                self.ch_left.push_audio(left, dt)
                self.ch_right.push_audio(right, dt)
            else:
                self.ch_left.decay_idle(dt)
                self.ch_right.decay_idle(dt)

            # Update smoothed loudness
            target_loudness, unit_suffix = self._get_current_loudness()
            rate = 60.0 if target_loudness > self.loudness_displayed else 25.0
            max_step = rate * dt
            diff = target_loudness - self.loudness_displayed
            if abs(diff) <= max_step:
                self.loudness_displayed = target_loudness
            else:
                self.loudness_displayed += max_step if diff > 0 else -max_step

            if target_loudness >= self.loudness_peak_hold:
                self.loudness_peak_hold = target_loudness
            else:
                self.loudness_peak_hold = max(self.loudness_displayed, self.loudness_peak_hold - 14.0 * dt)
        else:
            target_loudness, unit_suffix = self._get_current_loudness()

        w = self.width()
        h = self.height()
        top_offset = 8.0 if self.is_standalone else 32.0
        bottom_offset = 16.0

        y_top = top_offset + 4.0
        y_bot = h - bottom_offset
        track_h = y_bot - y_top

        track_bg_color = QColor(colors['grid'])
        accent_hex = colors['accent']
        bar_fill_color = QColor(accent_hex)
        peak_hold_color = QColor(colors['text'])
        text_muted_color = QColor(colors['muted'])

        scale_num_w = 20.0
        tick_len = 6.0
        pk_w_each = 10.0
        pk_gap = 2.0
        loud_w = 16.0
        badge_w = 74.0
        badge_h = 24.0
        core_meter_w = scale_num_w + tick_len + 6.0 + (pk_w_each * 2 + pk_gap) + 6.0 + loud_w + 5.0 + badge_w

        has_stats_panel = (w >= 330.0)

        if has_stats_panel:
            meter_x0 = 16.0
        else:
            meter_x0 = max(10.0, (w - core_meter_w) / 2.0)

        scale_x = meter_x0 + scale_num_w + tick_len

        # -------------------------------------------------------------
        # 1. Scale Ticks (0 -, 6 -, 12 -, 24 -, 36 -, 50 -)
        # -------------------------------------------------------------
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Medium))
        metrics = painter.fontMetrics()
        for tick_val in SCALE_TICKS:
            db_val = -float(tick_val)
            y_tick = self._db_to_y(db_val, y_bot, y_top)

            painter.setPen(QPen(text_muted_color, 1.2))
            painter.drawLine(QPointF(scale_x - tick_len, y_tick), QPointF(scale_x, y_tick))

            num_str = str(tick_val)
            tw = metrics.horizontalAdvance(num_str)
            painter.setPen(text_muted_color)
            painter.drawText(int(scale_x - tick_len - tw - 3), int(y_tick + metrics.ascent() / 2.0 - 1), num_str)

        # -------------------------------------------------------------
        # 2. Dual Peak Meter (Left & Right channels)
        # -------------------------------------------------------------
        pk_l_x = scale_x + 6.0
        pk_r_x = pk_l_x + pk_w_each + pk_gap

        # Background tracks
        painter.setBrush(QBrush(track_bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(pk_l_x, y_top, pk_w_each, track_h))
        painter.drawRect(QRectF(pk_r_x, y_top, pk_w_each, track_h))

        # Filled Peak bars
        y_l = self._db_to_y(self.ch_left.displayed_db, y_bot, y_top)
        y_r = self._db_to_y(self.ch_right.displayed_db, y_bot, y_top)

        painter.setBrush(QBrush(bar_fill_color))
        if y_l < y_bot:
            painter.drawRect(QRectF(pk_l_x, y_l, pk_w_each, y_bot - y_l))
        if y_r < y_bot:
            painter.drawRect(QRectF(pk_r_x, y_r, pk_w_each, y_bot - y_r))

        # Peak hold ticks
        y_pk_hold_l = self._db_to_y(self.ch_left.peak_db, y_bot, y_top)
        y_pk_hold_r = self._db_to_y(self.ch_right.peak_db, y_bot, y_top)
        painter.setPen(QPen(peak_hold_color, 1.5))
        if y_pk_hold_l < y_bot - 2:
            painter.drawLine(QPointF(pk_l_x, y_pk_hold_l), QPointF(pk_l_x + pk_w_each, y_pk_hold_l))
        if y_pk_hold_r < y_bot - 2:
            painter.drawLine(QPointF(pk_r_x, y_pk_hold_r), QPointF(pk_r_x + pk_w_each, y_pk_hold_r))

        # -------------------------------------------------------------
        # 3. Loudness Meter (LUFS / RMS)
        # -------------------------------------------------------------
        loud_x = pk_r_x + pk_w_each + 6.0

        # Background track
        painter.setBrush(QBrush(track_bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(loud_x, y_top, loud_w, track_h))

        # Filled bar
        y_loud = self._db_to_y(self.loudness_displayed, y_bot, y_top)
        painter.setBrush(QBrush(bar_fill_color))
        if y_loud < y_bot:
            painter.drawRect(QRectF(loud_x, y_loud, loud_w, y_bot - y_loud))

        # Loudness Peak Hold tick
        y_loud_hold = self._db_to_y(self.loudness_peak_hold, y_bot, y_top)
        if y_loud_hold < y_bot - 2:
            painter.setPen(QPen(peak_hold_color, 1.5))
            painter.drawLine(QPointF(loud_x, y_loud_hold), QPointF(loud_x + loud_w, y_loud_hold))

        # -------------------------------------------------------------
        # 4. Dynamic Floating Value Badge
        # -------------------------------------------------------------
        badge_val_str = f"{target_loudness:.1f}{unit_suffix}" if target_loudness > -69.0 else f"---{unit_suffix}"
        badge_x = loud_x + loud_w + 5.0
        badge_cy = max(y_top + badge_h / 2.0, min(y_bot - badge_h / 2.0, y_loud))
        badge_y0 = badge_cy - badge_h / 2.0

        painter.setBrush(QBrush(bar_fill_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(badge_x, badge_y0, badge_w, badge_h), 2, 2)

        # High-contrast bold text
        text_color = QColor(10, 10, 14) if bar_fill_color.lightness() > 120 else QColor(245, 245, 250)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(text_color)
        painter.drawText(QRectF(badge_x, badge_y0, badge_w, badge_h), Qt.AlignmentFlag.AlignCenter, badge_val_str)

        # -------------------------------------------------------------
        # 5. Right Stats Grid Panel (When width allows >= 330px)
        # -------------------------------------------------------------
        if has_stats_panel:
            panel_x = badge_x + badge_w + 14.0
            panel_w = w - panel_x - 12.0
            if panel_w >= 100.0:
                stats = [
                    ("SHORT-TERM", f"{self.loudness_proc.shortterm_lufs:.1f} LUFS" if self.loudness_proc.shortterm_lufs > -69.0 else "--- LUFS", QColor(colors['fill'])),
                    ("INTEGRATED", f"{self.loudness_proc.integrated_lufs:.1f} LUFS" if self.loudness_proc.integrated_lufs > -69.0 else "--- LUFS", QColor(colors['text'])),
                    ("RANGE (LRA)", f"{self.loudness_proc.lra:.1f} LU", QColor(colors['muted'])),
                    ("TRUE PEAK", f"{self.loudness_proc.true_peak_db:.1f} dBTP" if self.loudness_proc.true_peak_db > -69.0 else "--- dBTP", QColor(235, 75, 65) if self.loudness_proc.true_peak_db > -0.5 else QColor(colors['accent'])),
                ]

                card_bg = QColor(colors['card'])
                card_border = QColor(colors['border'])
                cols = 2
                col_gap = 6.0
                row_gap = 6.0
                item_w = (panel_w - col_gap) / 2.0
                item_h = (track_h - row_gap) / 2.0

                for idx, (lbl, val, col) in enumerate(stats):
                    c = idx % cols
                    r = idx // cols
                    ix = panel_x + c * (item_w + col_gap)
                    iy = y_top + r * (item_h + row_gap)

                    painter.setBrush(QBrush(card_bg))
                    painter.setPen(QPen(card_border, 1))
                    painter.drawRoundedRect(QRectF(ix, iy, item_w, item_h), 4, 4)

                    painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                    painter.setPen(QColor(colors['muted']))
                    painter.drawText(QRectF(ix + 6, iy + 4, item_w - 12, 12), Qt.AlignmentFlag.AlignLeft, lbl)

                    painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    painter.setPen(col)
                    painter.drawText(QRectF(ix + 6, iy + 16, item_w - 12, item_h - 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, val)

        # Mode toast
        if now - self.mode_toast_time < 2.0:
            alpha = int(max(0.0, min(1.0, (2.0 - (now - self.mode_toast_time)) * 2.0)) * 255)
            mode_name = MODES[self.mode_index]["name"]
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(220, 225, 240, alpha))
            painter.drawText(QRectF(0, 4, w, 18), Qt.AlignmentFlag.AlignCenter, mode_name)
