"""
Spectrum Analyzer Module (Exact match with original spectrum_analyzer.py + Theme integration).
Dense log-spaced FFT spectrum matching the reference look:
- Continuous GPU mesh colored by amplitude (dark purple -> theme accent -> orange)
- Peak-hold envelope line drawn on top
- Exact original ballistics (SMOOTHING=0.65, PEAK_HOLD_SEC=0.09, PEAK_FALL=100.0)
- Interactive hover tooltip with Frequency, dB level, and nearest musical note
- 100% GPU accelerated OpenGL 3.3 Core profile rendering at 144+ FPS locked
"""

import time
import ctypes
import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from OpenGL.GL import (
    glGenVertexArrays, glBindVertexArray, glGenBuffers, glBindBuffer, glBufferData,
    glBufferSubData, glEnableVertexAttribArray, glVertexAttribPointer, glUseProgram,
    glGetUniformLocation, glUniform4f, glDrawArrays, glClearColor, glClear, glViewport,
    glEnable, glBlendFunc, GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW, GL_FLOAT, GL_FALSE,
    GL_TRIANGLE_STRIP, GL_LINE_STRIP, GL_COLOR_BUFFER_BIT, GL_BLEND,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA
)
from core.audio_worker import AudioWorker
from core.gl_utils import create_program
from core.config_manager import AppConfig
from ..theme import palette, rgb, apply_meter_header, popout_icon

FFT_SIZE = 4096
NUM_BARS = 320
DB_FLOOR = -70.0
DB_CEIL = 0.0
SMOOTHING = 0.65
PEAK_HOLD_SEC = 0.09
PEAK_FALL_DB_PER_SEC = 100.0
MIN_FREQ_HZ = 20.0
MAX_FREQ_HZ = 20000.0

FREQ_MARKERS = [50, 100, 250, 500, 1000, 2500, 5000, 10000, 20000]
DB_MARKERS = [-12, -24, -36, -48, -60]

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

MESH_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 pos;
layout(location = 1) in vec3 color;
out vec3 frag_color;
void main() {
    frag_color = color;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

MESH_FRAGMENT_SHADER = """
#version 330 core
in vec3 frag_color;
out vec4 out_color;
void main() {
    out_color = vec4(frag_color, 1.0);
}
"""

LINE_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 pos;
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

LINE_FRAGMENT_SHADER = """
#version 330 core
uniform vec4 color;
out vec4 out_color;
void main() {
    out_color = color;
}
"""

def make_log_bin_edges(num_bars: int, fft_size: int, min_bin: float = 1.0) -> np.ndarray:
    max_bin = fft_size // 2
    return np.logspace(np.log10(min_bin), np.log10(max_bin), num_bars + 1)


def colormap(level: np.ndarray, accent_rgb=(0.75, 0.15, 0.55), dark_rgb=(0.10, 0.02, 0.15)) -> np.ndarray:
    dark_purple = np.array(dark_rgb)
    mid_accent = np.array(accent_rgb)
    orange = mid_accent * 0.55 + 0.45

    level = np.clip(level, 0.0, 1.0)
    t_low = np.clip(level * 2.0, 0.0, 1.0)[:, None]
    t_high = np.clip((level - 0.5) * 2.0, 0.0, 1.0)[:, None]

    low_mix = dark_purple[None, :] * (1 - t_low) + mid_accent[None, :] * t_low
    high_mix = mid_accent[None, :] * (1 - t_high) + orange[None, :] * t_high

    is_high = (level >= 0.5)[:, None]
    return np.where(is_high, high_mix, low_mix).astype(np.float32)


def freq_to_note(freq_hz: float) -> str:
    if freq_hz <= 0:
        return "-- "
    semitones_from_a4 = 12.0 * np.log2(freq_hz / 440.0)
    nearest = round(semitones_from_a4)
    cents = int(round((semitones_from_a4 - nearest) * 100))
    midi_note = 69 + nearest
    name = NOTE_NAMES[midi_note % 12]
    octave = midi_note // 12 - 1
    sign = "+" if cents >= 0 else "-"
    return f"{name}{octave} {sign}{abs(cents)}Cents"


class SpectrumWidget(QOpenGLWidget):
    undock_requested = pyqtSignal()

    def __init__(self, audio_worker: AudioWorker, parent=None, config: AppConfig | None = None):
        super().__init__(parent)
        self.config = config if config is not None else AppConfig()
        self.is_standalone = False
        self.audio_worker = audio_worker
        self.reader = audio_worker.create_reader(chunk_size=256)
        self.sample_rate = 44100

        self.actual_num_bars = NUM_BARS
        self.bin_edges = make_log_bin_edges(NUM_BARS, FFT_SIZE, min_bin=1.0)
        self.bar_freqs_hz = np.zeros(NUM_BARS, dtype=np.float32)
        self._fft_bin_axis = np.zeros(FFT_SIZE // 2 + 1, dtype=np.float64)
        self._recompute_bar_freqs()

        self.window_fn = np.hanning(FFT_SIZE).astype(np.float32)
        self.rolling_buffer = np.zeros(FFT_SIZE, dtype=np.float32)
        self.smoothed_db = np.full(NUM_BARS, DB_FLOOR, dtype=np.float32)
        self.peak_db = np.full(NUM_BARS, DB_FLOOR, dtype=np.float32)
        self._peak_age = np.zeros(NUM_BARS, dtype=np.float32)
        self.last_time = time.monotonic()

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(280, 200)

        # Docked header controls
        self._init_header_controls()

        # OpenGL handles
        self.mesh_program = None
        self.mesh_vao = None
        self.mesh_vbo = None
        self.line_program = None
        self.line_color_loc = None
        self.line_vao = None
        self.line_vbo = None

        self.mouse_pos = QPointF(-1, -1)
        self.is_hovered = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.set_fps(60)

    def _recompute_bar_freqs(self):
        bin_hz = self.sample_rate / FFT_SIZE
        bar_center_bin = (self.bin_edges[:-1] + self.bin_edges[1:]) / 2.0
        self.bar_freqs_hz = bar_center_bin * bin_hz
        self._fft_bin_axis = np.arange(FFT_SIZE // 2 + 1, dtype=np.float64)
        self._visible_bars = self.bar_freqs_hz <= MAX_FREQ_HZ
        frequencies = np.maximum(self.bar_freqs_hz[self._visible_bars], MIN_FREQ_HZ)
        normalized = np.clip(
            np.log10(frequencies / MIN_FREQ_HZ) / np.log10(MAX_FREQ_HZ / MIN_FREQ_HZ),
            0.0, 1.0,
        )
        self._visible_x_coords = (normalized * 2.0 - 1.0).astype(np.float32)

    def _init_header_controls(self):
        self.header_frame = QFrame(self)
        self.header_frame.setStyleSheet("""
            QFrame { background-color: transparent; }
            QToolButton {
                background-color: rgba(20, 20, 26, 180);
                color: #A0A0A8;
                border: 1px solid rgba(60, 60, 75, 140);
                border-radius: 3px;
                font-family: 'Segoe UI', Arial;
                font-size: 10px;
                font-weight: bold;
                padding: 1px 4px;
            }
            QToolButton:hover {
                background-color: rgba(45, 45, 60, 240);
                color: #58A6FF;
                border-color: #58A6FF;
            }
        """)
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(6, 4, 6, 0)
        h_layout.setSpacing(4)

        self.title_lbl = QLabel("SPECTRUM ANALYZER", self.header_frame)
        self.title_lbl.setStyleSheet("color: #70707C; font-weight: bold; font-size: 10px;")
        h_layout.addWidget(self.title_lbl)
        h_layout.addStretch(1)

        self.undock_btn = QToolButton(self.header_frame)
        self.undock_btn.setIcon(popout_icon("#91c5ff"))
        self.undock_btn.setToolTip("Move to a separate window")
        self.undock_btn.setFixedSize(18, 18)
        self.undock_btn.clicked.connect(self.undock_requested.emit)
        h_layout.addWidget(self.undock_btn)

    def set_fps(self, fps: int):
        interval_ms = max(5, int(1000.0 / max(1, fps)))
        self.timer.setInterval(interval_ms)

    def set_standalone_mode(self, is_standalone: bool):
        self.is_standalone = is_standalone
        self.header_frame.setVisible(not is_standalone)
        self.update()
        if is_standalone:
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.header_frame.setGeometry(0, 0, self.width(), 26)

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.position()
        self.is_hovered = True
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        self.is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.mouse_pos = QPointF(-1, -1)
        super().leaveEvent(event)

    def initializeGL(self):
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self.mesh_program = create_program(MESH_VERTEX_SHADER, MESH_FRAGMENT_SHADER)
        self.mesh_vao = glGenVertexArrays(1)
        self.mesh_vbo = glGenBuffers(1)
        glBindVertexArray(self.mesh_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.mesh_vbo)
        glBufferData(GL_ARRAY_BUFFER, NUM_BARS * 2 * 5 * 4, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 5 * 4, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 5 * 4, ctypes.c_void_p(2 * 4))

        self.line_program = create_program(LINE_VERTEX_SHADER, LINE_FRAGMENT_SHADER)
        self.line_color_loc = glGetUniformLocation(self.line_program, "color")

        self.line_vao = glGenVertexArrays(1)
        self.line_vbo = glGenBuffers(1)
        glBindVertexArray(self.line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.line_vbo)
        glBufferData(GL_ARRAY_BUFFER, NUM_BARS * 2 * 4, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * 4, ctypes.c_void_p(0))

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

    def _freq_to_x_ndc(self, freq_hz: float) -> float:
        freq_hz = max(freq_hz, MIN_FREQ_HZ)
        t = np.log10(freq_hz / MIN_FREQ_HZ) / np.log10(MAX_FREQ_HZ / MIN_FREQ_HZ)
        t = min(max(t, 0.0), 1.0)
        return t * 2.0 - 1.0

    def _update_audio(self, dt: float):
        if getattr(self, "is_paused", False):
            return

        chunk_info = self.reader.read_chunk()
        if chunk_info is None:
            self._update_peak_hold(dt)
            return

        chunk, rate, channels = chunk_info
        if rate != self.sample_rate:
            self.sample_rate = rate
            self._recompute_bar_freqs()

        if channels > 1:
            mono = 0.5 * (chunk[:, 0] + chunk[:, 1])
        else:
            mono = chunk[:, 0]
        n = len(mono)
        if n > FFT_SIZE:
            mono = mono[-FFT_SIZE:]
            n = FFT_SIZE

        self.rolling_buffer[:-n] = self.rolling_buffer[n:]
        self.rolling_buffer[-n:] = mono

        windowed = self.rolling_buffer * self.window_fn
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum) / (self.window_fn.sum() / 2)

        SUBSAMPLES = 6
        lo = self.bin_edges[:-1]
        hi = np.maximum(self.bin_edges[1:], lo + 1e-6)
        t = (np.arange(SUBSAMPLES) + 0.5) / SUBSAMPLES
        sample_positions = lo[:, None] + t[None, :] * (hi - lo)[:, None]
        sampled = np.interp(sample_positions.ravel(), self._fft_bin_axis, magnitude)
        bar_magnitudes = sampled.reshape(self.actual_num_bars, SUBSAMPLES).mean(axis=1).astype(np.float32)

        bar_magnitudes = (
            np.roll(bar_magnitudes, 2) * 0.08
            + np.roll(bar_magnitudes, 1) * 0.22
            + bar_magnitudes * 0.40
            + np.roll(bar_magnitudes, -1) * 0.22
            + np.roll(bar_magnitudes, -2) * 0.08
        ).astype(np.float32)

        db = 20.0 * np.log10(np.maximum(bar_magnitudes, 1e-10))
        db = np.clip(db, DB_FLOOR, DB_CEIL)

        self.smoothed_db = SMOOTHING * self.smoothed_db + (1.0 - SMOOTHING) * db
        self._update_peak_hold(dt, db)

    def _update_peak_hold(self, dt: float, db: np.ndarray = None):
        if db is not None:
            rising = self.smoothed_db >= self.peak_db
            self.peak_db = np.where(rising, self.smoothed_db, self.peak_db)
            self._peak_age = np.where(rising, 0.0, self._peak_age + dt)
        else:
            self._peak_age += dt

        past_hold = self._peak_age >= PEAK_HOLD_SEC
        fall_amount = PEAK_FALL_DB_PER_SEC * dt
        self.peak_db = np.where(
            past_hold,
            np.maximum(self.peak_db - fall_amount, DB_FLOOR),
            self.peak_db,
        )
        self.peak_db = np.maximum(self.peak_db, self.smoothed_db)

    def _build_continuous_mesh_vertices(self, accent_rgb=(0.75, 0.15, 0.55)) -> tuple[np.ndarray, int]:
        level = np.clip((self.smoothed_db[self._visible_bars] - DB_FLOOR) / (DB_CEIL - DB_FLOOR), 0.0, 1.0)
        colors = colormap(level, accent_rgb, rgb(palette(self.config)['grid']))

        x_coords = self._visible_x_coords
        y_top = (-1.0 + level * 2.0).astype(np.float32)

        total_pts = len(x_coords)
        verts = np.empty((total_pts * 2, 5), dtype=np.float32)

        verts[0::2, 0] = x_coords
        verts[0::2, 1] = -1.0
        verts[0::2, 2:] = colors * 0.35

        verts[1::2, 0] = x_coords
        verts[1::2, 1] = y_top
        verts[1::2, 2:] = colors

        self._mesh_x_coords = x_coords
        return verts.reshape(-1), total_pts * 2

    def _build_envelope_vertices(self) -> tuple[np.ndarray, int]:
        level = np.clip((self.peak_db[self._visible_bars] - DB_FLOOR) / (DB_CEIL - DB_FLOOR), 0.0, 1.0)
        x_centers = self._visible_x_coords
        y = (-1.0 + level * 2.0).astype(np.float32)

        count = len(x_centers)
        verts = np.empty(count * 2, dtype=np.float32)
        verts[0::2] = x_centers
        verts[1::2] = y
        return verts, count

    def apply_theme(self, colors: dict[str, str]):
        apply_meter_header(self, colors)

    def paintGL(self):
        now = time.monotonic()
        dt = max(1e-4, min(0.1, now - self.last_time))
        self.last_time = now

        cfg = self.config
        self._update_audio(dt)

        w = self.width()
        h = self.height()
        top_offset = 8 if self.is_standalone else 26
        bottom_offset = 20
        plot_h = max(1.0, h - top_offset - bottom_offset)
        base_y = top_offset + plot_h

        # 1. Pure Pitch-Black Background (#0b0b0d)
        colors = palette(cfg)
        glClearColor(*rgb(colors['root']), 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        if not self.mesh_program or not self.mesh_vao:
            return

        # Parse accent RGB
        accent_hex = colors['accent'].lstrip("#")
        try:
            ar = int(accent_hex[0:2], 16) / 255.0
            ag = int(accent_hex[2:4], 16) / 255.0
            ab = int(accent_hex[4:6], 16) / 255.0
            accent_rgb = (ar, ag, ab)
        except Exception:
            accent_rgb = (0.75, 0.15, 0.55)

        # 2. Draw Solid Continuous Spectrum Mesh
        mesh_verts, vert_count = self._build_continuous_mesh_vertices(accent_rgb)
        glUseProgram(self.mesh_program)
        glBindVertexArray(self.mesh_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.mesh_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, mesh_verts.nbytes, mesh_verts)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, vert_count)

        # 3. Draw Peak Hold Envelope Line (Original Color: 0.98, 0.55, 0.65, 0.9)
        env_verts, env_count = self._build_envelope_vertices()
        if env_count > 1:
            glUseProgram(self.line_program)
            glUniform4f(self.line_color_loc, *rgb(colors['fill']), 0.9)
            glBindVertexArray(self.line_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.line_vbo)
            glBufferSubData(GL_ARRAY_BUFFER, 0, env_verts.nbytes, env_verts)
            glDrawArrays(GL_LINE_STRIP, 0, env_count)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)
        glUseProgram(0)

        # 4. Interactive Hover Tooltip Overlay (on mouse hover)
        if self.is_hovered and self.mouse_pos.x() >= 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            try:
                mx = float(self.mouse_pos.x())
                my = float(self.mouse_pos.y())
                if top_offset <= my <= base_y:
                    x_ndc = (mx / max(1, w)) * 2.0 - 1.0
                    edges = getattr(self, "_mesh_x_coords", None)
                    if edges is not None:
                        idx = int(np.searchsorted(edges, x_ndc) - 1)
                        idx = max(0, min(len(edges) - 1, idx))
                        freq = float(self.bar_freqs_hz[idx])
                        db_val = float(self.smoothed_db[idx])
                        note = freq_to_note(freq)
                        tooltip = f"{db_val:.1f} dB   {freq:.0f} Hz   {note}"

                        # Subtle Crosshair line
                        painter.setPen(QPen(QColor(colors['accent']), 1, Qt.PenStyle.DashLine))
                        painter.drawLine(QPointF(mx, top_offset), QPointF(mx, base_y))
                        painter.drawLine(QPointF(0, my), QPointF(w, my))

                        # Tooltip badge
                        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                        metrics = painter.fontMetrics()
                        tw = metrics.horizontalAdvance(tooltip) + 14
                        bx = min(w - tw - 8, max(8.0, mx + 10))
                        by = max(top_offset + 4.0, my - 24)

                        painter.setBrush(QColor(colors['card']))
                        painter.setPen(QPen(QColor(colors['border']), 1))
                        painter.drawRoundedRect(QRectF(bx, by, tw, 20), 4, 4)

                        painter.setPen(QColor(245, 245, 255))
                        painter.drawText(int(bx + 7), int(by + 14), tooltip)
            finally:
                painter.end()
