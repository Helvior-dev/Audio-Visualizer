"""
Spectrogram Module.
Renders a rolling 2D heatmap of frequencies scrolling horizontally (left-to-right).
Features:
- Dynamic colormap generated from active theme accent color
- Real-time fast musical waterfall scrolling
- High-efficiency direct QImage memory blit
"""

import time
import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QImage, QColor, QFont, QPen
from ..base_meter_widget import BaseMeterWidget
from core.audio_worker import AudioWorker
from core.config_manager import load_config

HELP_LINES = [
    "SPECTROGRAM",
    "",
    "Visualizes frequencies over time as a horizontally scrolling 2D heatmap.",
    "",
    "• Vertical axis: Frequency (20 Hz bass at bottom to 20 kHz treble at top).",
    "• Horizontal axis: Time (scrolling horizontally from right to left).",
    "• Color intensity: Amplitude / energy level adapted to active theme color.",
]

FREQ_MARKERS = [100, 500, 1000, 5000, 10000, 20000]


def generate_accent_lut(accent_hex: str) -> np.ndarray:
    """Generate 256 RGB entries harmoniously anchored to the active theme accent color."""
    hex_str = accent_hex.lstrip("#")
    try:
        ar = int(hex_str[0:2], 16)
        ag = int(hex_str[2:4], 16)
        ab = int(hex_str[4:6], 16)
    except Exception:
        ar, ag, ab = 88, 166, 255

    stops = [
        (0.00, np.array([10, 5, 18])),
        (0.28, np.array([int(ar * 0.45), int(ag * 0.45), int(ab * 0.45)])),
        (0.60, np.array([ar, ag, ab])),
        (0.82, np.array([255, 210, 80])),
        (1.00, np.array([255, 255, 245])),
    ]

    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        for j in range(len(stops) - 1):
            t0, c0 = stops[j]
            t1, c1 = stops[j + 1]
            if t0 <= t <= t1:
                factor = (t - t0) / (t1 - t0)
                lut[i] = (c0 * (1.0 - factor) + c1 * factor).astype(np.uint8)
                break
    return lut


class SpectrogramWidget(BaseMeterWidget):
    def __init__(self, audio_worker: AudioWorker, time_cols: int = 400, freq_bins: int = 256, parent=None):
        super().__init__("SPECTROGRAM", HELP_LINES, parent)
        self.audio_worker = audio_worker
        self.reader = audio_worker.create_reader(chunk_size=256)
        self.time_cols = time_cols
        self.freq_bins = freq_bins
        
        self.last_accent_hex = ""
        self.colormap_lut = generate_accent_lut("#58A6FF")

        # Shape: (height=freq_bins, width=time_cols, channels=3)
        self.waterfall_buffer = np.zeros((freq_bins, time_cols, 3), dtype=np.uint8)
        self.fft_size = 2048
        self.window = np.hanning(self.fft_size).astype(np.float32)
        self.audio_buf = np.zeros(self.fft_size, dtype=np.float32)
        self.sample_accumulator = np.empty(0, dtype=np.float32)
        
        # Logarithmic frequency spacing from 20 Hz to 20 kHz
        self.log_freqs = np.geomspace(20000.0, 20.0, freq_bins).astype(np.float32)

    def _freq_to_y(self, freq: float, top: float, plot_h: float) -> float:
        min_f = 20.0
        max_f = 20000.0
        t = (np.log10(freq) - np.log10(min_f)) / (np.log10(max_f) - np.log10(min_f))
        return float(top + plot_h * (1.0 - np.clip(t, 0.0, 1.0)))

    def render_ui(self, painter: QPainter):
        cfg = load_config()

        accent_hex = getattr(cfg, "accent_color", "#58A6FF")
        if accent_hex != self.last_accent_hex:
            self.last_accent_hex = accent_hex
            self.colormap_lut = generate_accent_lut(accent_hex)

        w = self.width()
        h = self.height()
        top_offset = 26
        left_margin = 28
        plot_w = w - left_margin
        plot_h = h - top_offset - 6

        # 1. Fetch audio via stream reader
        if not self.is_paused:
            rate = 44100
            chunk_info = self.reader.read_chunk()
            if chunk_info is not None:
                chunk, rate, channels = chunk_info
                if chunk.shape[1] >= 2:
                    mono = 0.5 * (chunk[:, 0] + chunk[:, 1])
                else:
                    mono = chunk[:, 0]

                if len(mono) > 0:
                    self.sample_accumulator = np.concatenate([self.sample_accumulator, mono])

            # Slice accumulator into slices of 256 samples (~172 slices/sec for fast, energetic scrolling)
            SLICE_SIZE = 256
            num_slices = len(self.sample_accumulator) // SLICE_SIZE
            if num_slices > 0:
                num_slices = min(num_slices, 6) # Cap per tick
                for s in range(num_slices):
                    sub = self.sample_accumulator[s * SLICE_SIZE:(s + 1) * SLICE_SIZE]
                    n_sub = len(sub)
                    self.audio_buf[:-n_sub] = self.audio_buf[n_sub:]
                    self.audio_buf[-n_sub:] = sub

                    # Compute FFT
                    fft_complex = np.fft.rfft(self.audio_buf * self.window)
                    magnitudes = np.abs(fft_complex) / (self.fft_size / 2.0)
                    db_spec = 20.0 * np.log10(np.maximum(magnitudes, 1e-6))

                    fft_freqs = np.fft.rfftfreq(self.fft_size, 1.0 / max(1, rate))
                    indices = np.searchsorted(fft_freqs, self.log_freqs[::-1])
                    indices = np.clip(indices, 0, len(db_spec) - 1)
                    col_db = db_spec[indices][::-1]

                    norm_level = np.clip((col_db + 80.0) / 80.0, 0.0, 1.0)
                    lut_indices = (norm_level * 255).astype(np.uint8)
                    new_col_rgb = self.colormap_lut[lut_indices]

                    # Shift left, insert new slice on right
                    self.waterfall_buffer[:, :-1, :] = self.waterfall_buffer[:, 1:, :]
                    self.waterfall_buffer[:, -1, :] = new_col_rgb

                used = num_slices * SLICE_SIZE
                self.sample_accumulator = self.sample_accumulator[used:]

        # 2. Draw Waterfall Image
        img_h, img_w, _ = self.waterfall_buffer.shape
        qimg = QImage(
            self.waterfall_buffer.data,
            img_w,
            img_h,
            img_w * 3,
            QImage.Format.Format_RGB888
        )
        target_rect = QRectF(left_margin, top_offset, plot_w, plot_h)
        painter.drawImage(target_rect, qimg)

        # 3. Frequency Scale Labels & Subtle Grid Lines
        painter.setFont(QFont("Segoe UI", 8))
        for freq in FREQ_MARKERS:
            y = self._freq_to_y(freq, top_offset, plot_h)
            if y < top_offset + 10 or y > top_offset + plot_h - 4:
                continue

            # Grid Line
            painter.setPen(QPen(QColor(255, 255, 255, 18), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(left_margin, y), QPointF(w, y))

            # Label
            lbl = f"{int(freq/1000)}k" if freq >= 1000 else str(freq)
            painter.setPen(QColor(100, 100, 115))
            painter.drawText(QRectF(0, y - 6, left_margin - 4, 12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, lbl)
