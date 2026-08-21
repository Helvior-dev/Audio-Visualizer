"""
Vectorscope / Stereometer Module.
Visualizes stereo imaging, mid/side phase alignment, and Pearson correlation.
- Real-time Mid/Side point cloud projection with dynamic theme accent color
- Dynamic aspect scaling that guarantees zero overlap between SIDE label and CORR bar on fullscreen
- CORR bar with pixel-perfect QPainterPath rounded-cap clipping
"""

import time
import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QPolygonF, QPainterPath
from ..base_meter_widget import BaseMeterWidget
from core.audio_worker import AudioWorker
from core.config_manager import load_config

HISTORY_POINTS = 1024
CORR_SMOOTHING_PER_SEC = 9.0

HELP_LINES = [
    "STEREOMETER",
    "",
    "Shows the shape of your stereo sound as a cloud of dots.",
    "",
    "• Vertical axis (MID): Monophonic energy (center channel).",
    "• Horizontal axis (SIDE): Stereo difference (stereo width).",
    "• Tall thin cloud: Mono-heavy, centered mix.",
    "• Wide round cloud: Spacious stereo field.",
    "",
    "CORRELATION (CORR):",
    "• +1.00: Perfect mono compatibility (identical L/R).",
    "•  0.00: Wide, uncorrelated stereo.",
    "• -1.00: Complete phase cancellation (out of phase).",
]


class VectorscopeWidget(BaseMeterWidget):
    def __init__(self, audio_worker: AudioWorker, parent=None):
        super().__init__("STEREOMETER", HELP_LINES, parent)
        self.audio_worker = audio_worker
        self.reader = audio_worker.create_reader(chunk_size=256)
        self.points = np.zeros((HISTORY_POINTS, 2), dtype=np.float32)
        self.correlation = 0.0
        self.displayed_correlation = 0.0
        self.last_time = time.monotonic()

    def render_ui(self, painter: QPainter):
        now = time.monotonic()
        dt = max(0.001, min(0.1, now - self.last_time))
        self.last_time = now

        cfg = load_config()

        w = self.width()
        h = self.height()
        top_offset = 26

        # 1. Read exact new frames since last tick
        if not self.is_paused:
            chunk_info = self.reader.read_chunk()
            if chunk_info is not None:
                chunk, rate, channels = chunk_info
                if chunk.shape[1] >= 2:
                    left = chunk[:, 0]
                    right = chunk[:, 1]
                else:
                    left = chunk[:, 0]
                    right = chunk[:, 0]

                # Mid / Side decomposition:
                mid = (left + right) * 0.5
                side = (left - right) * 0.5

                n = len(mid)
                if n > 0:
                    new_pts = np.stack([side, mid], axis=1).astype(np.float32)
                    if n >= HISTORY_POINTS:
                        self.points[:] = new_pts[-HISTORY_POINTS:]
                    else:
                        self.points[:-n] = self.points[n:]
                        self.points[-n:] = new_pts

                # Pearson correlation
                if len(left) > 16 and np.std(left) > 1e-6 and np.std(right) > 1e-6:
                    corr = np.corrcoef(left, right)[0, 1]
                    self.correlation = float(np.clip(corr, -1.0, 1.0))
                else:
                    self.correlation = 0.0

            # Smooth displayed correlation
            max_step = CORR_SMOOTHING_PER_SEC * dt
            diff = self.correlation - self.displayed_correlation
            if abs(diff) <= max_step:
                self.displayed_correlation = self.correlation
            else:
                self.displayed_correlation += max_step if diff > 0 else -max_step

        # 2. Dynamic Scaling & Layout Calculation
        corr_block_h = min(80.0, max(46.0, h * 0.14))
        content_h = max(50.0, h - top_offset - corr_block_h)
        side_len = min(w - 40.0, content_h)

        scale_fac = max(0.85, min(2.8, side_len / 320.0))

        cx = w / 2.0
        cy = top_offset + content_h / 2.0
        radius = (side_len / 2.0) * 0.78

        # 3. Draw Diamond Guide & Axes
        diag_pen = QPen(QColor(71, 76, 87), max(1.0, 1.2 * scale_fac))
        painter.setPen(diag_pen)

        p_top = QPointF(cx, cy - radius)
        p_bottom = QPointF(cx, cy + radius)
        p_left = QPointF(cx - radius, cy)
        p_right = QPointF(cx + radius, cy)

        # Outer diamond
        painter.drawLine(p_top, p_right)
        painter.drawLine(p_right, p_bottom)
        painter.drawLine(p_bottom, p_left)
        painter.drawLine(p_left, p_top)

        # Cross & diagonal axes
        guide_pen = QPen(QColor(42, 45, 52), max(1.0, 1.0 * scale_fac), Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        painter.drawLine(p_left, p_right)
        painter.drawLine(p_top, p_bottom)

        d_rad = radius * 0.7071
        painter.drawLine(QPointF(cx - d_rad, cy - d_rad), QPointF(cx + d_rad, cy + d_rad))
        painter.drawLine(QPointF(cx - d_rad, cy + d_rad), QPointF(cx + d_rad, cy - d_rad))

        # Labels: MID, SIDE, L, R
        label_font_size = max(8, int(8.5 * scale_fac))
        painter.setFont(QFont("Segoe UI", label_font_size, QFont.Weight.Bold))
        painter.setPen(QColor(140, 140, 153))

        label_offset = 6 * scale_fac
        painter.drawText(int(cx - 12 * scale_fac), int(cy - radius - label_offset), "MID")
        painter.drawText(int(cx - 14 * scale_fac), int(cy + radius + 14 * scale_fac), "SIDE")
        painter.drawText(int(cx - radius - 20 * scale_fac), int(cy + 5 * scale_fac), "L")
        painter.drawText(int(cx + radius + 8 * scale_fac), int(cy + 5 * scale_fac), "R")

        # 4. Point Cloud in Active Theme Accent Color
        accent_col = QColor(getattr(cfg, "accent_color", "#58A6FF"))
        pt_color = QColor(
            min(255, int(accent_col.red() * 0.85 + 40)),
            min(255, int(accent_col.green() * 0.85 + 40)),
            min(255, int(accent_col.blue() * 0.85 + 40)),
            230
        )

        pxs = cx + self.points[:, 0] * (radius * 0.92)
        pys = cy - self.points[:, 1] * (radius * 0.92)

        polygon = QPolygonF([QPointF(float(pxs[i]), float(pys[i])) for i in range(HISTORY_POINTS)])

        pt_size = max(2.0, min(3.8, 2.2 * scale_fac))
        pt_pen = QPen(pt_color, pt_size)
        pt_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pt_pen)
        painter.drawPoints(polygon)

        # 5. Correlation Bar
        bar_w = min(w * 0.78, max(220.0, 260.0 * scale_fac))
        bar_h = max(10.0, 10.0 * scale_fac)
        bar_x = cx - bar_w / 2.0
        bar_y = h - max(26.0, 28.0 * scale_fac)
        corner_r = bar_h / 2.0

        bar_rect = QRectF(bar_x, bar_y, bar_w, bar_h)
        bar_path = QPainterPath()
        bar_path.addRoundedRect(bar_rect, corner_r, corner_r)

        painter.fillPath(bar_path, QColor(36, 36, 44))
        painter.setPen(QPen(QColor(55, 55, 65), 1))
        painter.drawPath(bar_path)

        mid_x = cx
        val_x = mid_x + self.displayed_correlation * (bar_w / 2.0)
        fill_color = accent_col if self.displayed_correlation >= 0.0 else QColor(235, 65, 55)

        painter.save()
        painter.setClipPath(bar_path)
        if self.displayed_correlation >= 0:
            fill_rect = QRectF(mid_x, bar_y - 1, val_x - mid_x, bar_h + 2)
        else:
            fill_rect = QRectF(val_x, bar_y - 1, mid_x - val_x, bar_h + 2)
        painter.fillRect(fill_rect, fill_color)
        painter.restore()

        # Correlation Value Text
        corr_font_size = max(8, int(8.5 * scale_fac))
        painter.setFont(QFont("Segoe UI", corr_font_size, QFont.Weight.Bold))
        painter.setPen(QColor(210, 210, 220))
        corr_text = f"CORR {self.displayed_correlation:+.2f}"
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(corr_text)
        painter.drawText(int(cx - tw / 2.0), int(bar_y - 5), corr_text)
