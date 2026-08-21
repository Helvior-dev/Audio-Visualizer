"""
Loudness module: 1:1 MiniMeters-authentic vertical Loudness & Peak meter.

Features:
  - MiniMeters vertical meter group:
    • Scale markings: 0 -, 6 -, 12 -, 24 -, 36 -, 50 -
    • Dual-channel immediate Peak bars (L and R) with fast attack & peak-hold ticks
    • Perceived Loudness (LUFS / RMS) bar with peak-hold tick
    • Dynamic floating badge (-xx.xLUFS / -xx.xRMS) tracking level with compact width
  - Responsive layout:
    • Compact / Vertical window: perfectly centered meter with no distortion.
    • Wide / Fullscreen window: balanced mastering layout with side stats panel.
  - Interactive mode switching: click anywhere or on the meter to cycle
    through LUFS (M), LUFS (S), RMS (F), RMS (S), RMS (F +3dB), RMS (S +3dB).
"""

import sys
import ctypes
from pathlib import Path

import glfw
import numpy as np
from OpenGL.GL import *
import threading

sys.path.insert(0, str(Path(__file__).parent))
from audio_capture import AudioCapture
from window_utils import apply_dark_titlebar, set_window_icon
from text_render import TEXT_VERTEX_SHADER, TEXT_FRAGMENT_SHADER, TextRenderer
from audio_source_config import load_selected_source, SourceWatcher
from config import cfg

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

DB_MIN = -60.0
DB_MAX = 0.0

SCALE_TICKS = [0, 6, 12, 24, 36, 50]

MODES = [
    {"name": "LUFS (Momentary)", "unit": "LUFS", "key": "lufs_m", "label": "LUFS (M)"},
    {"name": "LUFS (Short-Term)", "unit": "LUFS", "key": "lufs_s", "label": "LUFS (S)"},
    {"name": "RMS (Fast)", "unit": "RMS", "key": "rms_f", "label": "RMS (Fast)"},
    {"name": "RMS (Slow)", "unit": "RMS", "key": "rms_s", "label": "RMS (Slow)"},
    {"name": "RMS (Fast +3dB)", "unit": "RMS", "key": "rms_f_3", "label": "RMS (Fast +3)"},
    {"name": "RMS (Slow +3dB)", "unit": "RMS", "key": "rms_s_3", "label": "RMS (Slow +3)"},
]

HELP_TITLE = "LOUDNESS"

HELP_LINES = [
    "Peak & Loudness monitoring matching MiniMeters.",
    "",
    "LEFT BARS (PEAK L / R):",
    "Immediate peak level for Left and Right channels",
    "with fast-attack response and peak-hold ticks.",
    "",
    "RIGHT BAR (LOUDNESS):",
    "Measures perceived loudness in LUFS (EBU R128)",
    "or RMS signal power.",
    "",
    "MODES (Click window to cycle):",
    "• LUFS (M)   Momentary 400ms window",
    "• LUFS (S)   Short-Term 3.0s window",
    "• RMS (F)    Fast 300ms RMS",
    "• RMS (S)    Slow 1000ms RMS",
    "• RMS (+3)   AES17 calibrated RMS",
]

HELP_FOOTER = "Click anywhere to close"

# ---------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------

SOLID_VERTEX_SHADER = """
#version 330
in vec2 pos;
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

SOLID_FRAGMENT_SHADER = """
#version 330
uniform vec3 color;
uniform float alpha;
out vec4 out_color;
void main() {
    out_color = vec4(color, alpha);
}
"""


def compile_shader(source: str, shader_type) -> int:
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        error = glGetShaderInfoLog(shader).decode()
        raise RuntimeError(f"Shader compile error: {error}")
    return shader


def link_program(vertex_src: str, fragment_src: str) -> int:
    vs = compile_shader(vertex_src, GL_VERTEX_SHADER)
    fs = compile_shader(fragment_src, GL_FRAGMENT_SHADER)
    program = glCreateProgram()
    glAttachShader(program, vs)
    glAttachShader(program, fs)
    glLinkProgram(program)
    if not glGetProgramiv(program, GL_LINK_STATUS):
        error = glGetProgramInfoLog(program).decode()
        raise RuntimeError(f"Program link error: {error}")
    glDeleteShader(vs)
    glDeleteShader(fs)
    return program


# ---------------------------------------------------------------------
# K-weighting Filter (ITU-R BS.1770-4 / EBU R128)
# ---------------------------------------------------------------------

def _high_shelf_coeffs(fs: float, f0: float, gain_db: float, q: float):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    sqrt_a = np.sqrt(A)

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrt_a * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrt_a * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrt_a * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrt_a * alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _high_pass_coeffs(fs: float, f0: float, q: float):
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)

    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


class Biquad:
    def __init__(self, b0, b1, b2, a1, a2):
        self.b0, self.b1, self.b2, self.a1, self.a2 = b0, b1, b2, a1, a2
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x)
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        z1, z2 = self.z1, self.z2
        for i in range(len(x)):
            xi = x[i]
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            y[i] = yi
        self.z1, self.z2 = z1, z2
        return y


class KWeightingFilter:
    def __init__(self, sample_rate: float):
        b0, b1, b2, a1, a2 = _high_shelf_coeffs(
            sample_rate, f0=1681.9744509555319, gain_db=3.99984385397, q=0.7071752369554193
        )
        self.stage1 = Biquad(b0, b1, b2, a1, a2)
        b0, b1, b2, a1, a2 = _high_pass_coeffs(
            sample_rate, f0=38.13547087613982, q=0.5003270373253953
        )
        self.stage2 = Biquad(b0, b1, b2, a1, a2)

    def process(self, x: np.ndarray) -> np.ndarray:
        return self.stage2.process(self.stage1.process(x))


# ---------------------------------------------------------------------
# DSP Engine
# ---------------------------------------------------------------------

class LoudnessEngine:
    PEAK_DECAY_RATE = 22.0
    PEAK_HOLD_DECAY_RATE = 14.0

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self.kw_l = KWeightingFilter(sample_rate)
        self.kw_r = KWeightingFilter(sample_rate)

        # Buffer lengths
        self.m_samples = max(1, int(round(0.400 * sample_rate)))
        self.s_samples = max(1, int(round(3.000 * sample_rate)))
        self.rms_f_samples = max(1, int(round(0.300 * sample_rate)))
        self.rms_s_samples = max(1, int(round(1.000 * sample_rate)))

        self._buf_kw_sq = np.zeros(self.s_samples, dtype=np.float64)
        self._buf_raw_sq = np.zeros(self.rms_s_samples, dtype=np.float64)
        self._kw_filled = 0
        self._raw_filled = 0

        # Integrated & LRA tracking
        self.gating_block_samples = max(1, int(round(0.4 * sample_rate)))
        self._block_hop_samples = max(1, int(round(0.1 * sample_rate)))
        self._samples_since_block = 0
        self._integrated_blocks: list[float] = []

        self._st_hop_samples = max(1, int(round(1.0 * sample_rate)))
        self._samples_since_st = 0
        self._st_history: list[float] = []

        self.peak_l = DB_MIN
        self.peak_r = DB_MIN
        self.peak_hold_l = DB_MIN
        self.peak_hold_r = DB_MIN
        self.max_peak = DB_MIN

        self.lufs_m = DB_MIN
        self.lufs_s = DB_MIN
        self.lufs_int = DB_MIN
        self.lra = 0.0
        self.rms_f = DB_MIN
        self.rms_s = DB_MIN
        self.rms_f_3 = DB_MIN
        self.rms_s_3 = DB_MIN

        self.loudness_displayed = DB_MIN
        self.loudness_peak_hold = DB_MIN

    @staticmethod
    def _power_to_lufs(power: float) -> float:
        if power <= 1e-12:
            return DB_MIN
        return -0.691 + 10.0 * np.log10(power)

    @staticmethod
    def _power_to_rms(power: float) -> float:
        if power <= 1e-12:
            return DB_MIN
        return 10.0 * np.log10(power)

    def push(self, left: np.ndarray, right: np.ndarray, dt: float):
        if len(left) == 0:
            decay_step = self.PEAK_DECAY_RATE * dt
            self.peak_l = max(DB_MIN, self.peak_l - decay_step)
            self.peak_r = max(DB_MIN, self.peak_r - decay_step)
            hold_step = self.PEAK_HOLD_DECAY_RATE * dt
            self.peak_hold_l = max(DB_MIN, self.peak_hold_l - hold_step)
            self.peak_hold_r = max(DB_MIN, self.peak_hold_r - hold_step)
            self.loudness_displayed = max(DB_MIN, self.loudness_displayed - decay_step)
            self.loudness_peak_hold = max(DB_MIN, self.loudness_peak_hold - hold_step)
            return

        # 1. Immediate Peaks
        pk_l = float(np.max(np.abs(left)))
        pk_r = float(np.max(np.abs(right)))
        pk_l_db = 20.0 * np.log10(max(pk_l, 1e-6))
        pk_r_db = 20.0 * np.log10(max(pk_r, 1e-6))

        decay_step = self.PEAK_DECAY_RATE * dt
        self.peak_l = pk_l_db if pk_l_db > self.peak_l else max(DB_MIN, self.peak_l - decay_step)
        self.peak_r = pk_r_db if pk_r_db > self.peak_r else max(DB_MIN, self.peak_r - decay_step)

        hold_step = self.PEAK_HOLD_DECAY_RATE * dt
        self.peak_hold_l = pk_l_db if pk_l_db >= self.peak_hold_l else max(self.peak_l, self.peak_hold_l - hold_step)
        self.peak_hold_r = pk_r_db if pk_r_db >= self.peak_hold_r else max(self.peak_r, self.peak_hold_r - hold_step)
        self.max_peak = max(self.max_peak, max(pk_l_db, pk_r_db))

        # 2. K-Weighted Loudness (LUFS)
        kl = self.kw_l.process(left.astype(np.float64))
        kr = self.kw_r.process(right.astype(np.float64))
        kw_sq = kl * kl + kr * kr

        n_kw = len(kw_sq)
        if n_kw >= self.s_samples:
            self._buf_kw_sq[:] = kw_sq[-self.s_samples:]
            self._kw_filled = self.s_samples
        else:
            self._buf_kw_sq = np.roll(self._buf_kw_sq, -n_kw)
            self._buf_kw_sq[-n_kw:] = kw_sq
            self._kw_filled = min(self.s_samples, self._kw_filled + n_kw)

        if self._kw_filled > 0:
            m_len = min(self.m_samples, self._kw_filled)
            self.lufs_m = self._power_to_lufs(self._buf_kw_sq[-m_len:].mean())
            self.lufs_s = self._power_to_lufs(self._buf_kw_sq[-self._kw_filled:].mean())

        # Integrated blocks
        self._samples_since_block += n_kw
        while self._kw_filled >= self.gating_block_samples and self._samples_since_block >= self._block_hop_samples:
            self._samples_since_block -= self._block_hop_samples
            self._integrated_blocks.append(float(self._buf_kw_sq[-self.gating_block_samples:].mean()))
            if len(self._integrated_blocks) > 10_000:
                self._integrated_blocks = self._integrated_blocks[-5_000:]
        if self._integrated_blocks:
            self.lufs_int = self._compute_integrated()

        # LRA
        self._samples_since_st += n_kw
        if self._samples_since_st >= self._st_hop_samples:
            self._samples_since_st = 0
            self._st_history.append(self.lufs_s)
            if len(self._st_history) > 2_000:
                self._st_history = self._st_history[-1_000:]
            self.lra = self._compute_lra()

        # 3. Raw RMS
        raw_sq = (left.astype(np.float64) ** 2 + right.astype(np.float64) ** 2) * 0.5
        n_raw = len(raw_sq)
        if n_raw >= self.rms_s_samples:
            self._buf_raw_sq[:] = raw_sq[-self.rms_s_samples:]
            self._raw_filled = self.rms_s_samples
        else:
            self._buf_raw_sq = np.roll(self._buf_raw_sq, -n_raw)
            self._buf_raw_sq[-n_raw:] = raw_sq
            self._raw_filled = min(self.rms_s_samples, self._raw_filled + n_raw)

        if self._raw_filled > 0:
            f_len = min(self.rms_f_samples, self._raw_filled)
            rms_f_val = self._power_to_rms(self._buf_raw_sq[-f_len:].mean())
            rms_s_val = self._power_to_rms(self._buf_raw_sq[-self._raw_filled:].mean())
            self.rms_f = rms_f_val
            self.rms_s = rms_s_val
            self.rms_f_3 = rms_f_val + 3.0103
            self.rms_s_3 = rms_s_val + 3.0103

    def _compute_integrated(self) -> float:
        blocks = np.array(self._integrated_blocks)
        loudness = -0.691 + 10.0 * np.log10(np.maximum(blocks, 1e-12))
        gated = blocks[loudness > -70.0]
        if len(gated) == 0:
            return -70.0
        mean_gated = float(gated.mean())
        rel_th = self._power_to_lufs(mean_gated) - 10.0
        gated2 = gated[(-0.691 + 10.0 * np.log10(np.maximum(gated, 1e-12))) > rel_th]
        if len(gated2) == 0:
            return self._power_to_lufs(mean_gated)
        return self._power_to_lufs(float(gated2.mean()))

    def _compute_lra(self) -> float:
        if len(self._st_history) < 2:
            return 0.0
        vals = np.array(self._st_history)
        vals = vals[vals > -70.0]
        if len(vals) < 2:
            return 0.0
        mean_p = np.mean(10 ** ((vals + 0.691) / 10.0))
        rel_gate = self._power_to_lufs(mean_p) - 20.0
        gated = vals[vals > rel_gate]
        if len(gated) < 2:
            return 0.0
        return float(np.percentile(gated, 95.0) - np.percentile(gated, 10.0))

    def get_mode_value(self, mode_idx: int) -> tuple[float, str]:
        mode = MODES[mode_idx % len(MODES)]
        key = mode["key"]
        val = getattr(self, key, DB_MIN)
        return val, mode["unit"]

    def update_displayed_loudness(self, target_db: float, dt: float):
        rate = 60.0 if target_db > self.loudness_displayed else 25.0
        max_step = rate * dt
        diff = target_db - self.loudness_displayed
        if abs(diff) <= max_step:
            self.loudness_displayed = target_db
        else:
            self.loudness_displayed += max_step if diff > 0 else -max_step

        hold_step = self.PEAK_HOLD_DECAY_RATE * dt
        if target_db >= self.loudness_peak_hold:
            self.loudness_peak_hold = target_db
        else:
            self.loudness_peak_hold = max(self.loudness_displayed, self.loudness_peak_hold - hold_step)


# ---------------------------------------------------------------------
# UI Window
# ---------------------------------------------------------------------

class LoudnessWindow:
    def __init__(self):
        if not glfw.init():
            raise RuntimeError("GLFW init failed")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

        self.width, self.height = 360, 480

        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        self.window = glfw.create_window(self.width, self.height, "Loudness", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("GLFW window creation failed")

        monitor = glfw.get_primary_monitor()
        mode = glfw.get_video_mode(monitor)
        glfw.set_window_pos(self.window, (mode.size.width - self.width) // 2, (mode.size.height - self.height) // 2)
        glfw.set_window_size_limits(self.window, 220, 260, glfw.DONT_CARE, glfw.DONT_CARE)

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        glfw.set_framebuffer_size_callback(self.window, self._on_resize)
        glfw.set_mouse_button_callback(self.window, self._on_mouse_button)
        glfw.set_cursor_pos_callback(self.window, self._on_cursor_move)
        apply_dark_titlebar(self.window)
        set_window_icon(self.window, ICON_PATH)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self.solid_program = link_program(SOLID_VERTEX_SHADER, SOLID_FRAGMENT_SHADER)
        self.solid_color_loc = glGetUniformLocation(self.solid_program, "color")
        self.solid_alpha_loc = glGetUniformLocation(self.solid_program, "alpha")

        self.text_program = link_program(TEXT_VERTEX_SHADER, TEXT_FRAGMENT_SHADER)
        self.text = TextRenderer(self.text_program)

        self.solid_vao = glGenVertexArrays(1)
        glBindVertexArray(self.solid_vao)
        self.solid_vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        glBufferData(GL_ARRAY_BUFFER, 64 * 2 * 4, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        self.audio = AudioCapture(chunk_size=256, source=load_selected_source())
        self.source_watcher = SourceWatcher()
        self.engine = LoudnessEngine(self.audio.rate)
        self.last_time = glfw.get_time()

        self.mode_index = 0
        self.mode_toast_time = 0.0

        self.help_icon_cx = 0.90
        self.help_icon_cy = 0.90
        self.help_icon_r = 0.04
        self.help_open = False
        self.mouse_x, self.mouse_y = -1.0, -1.0

    def _on_resize(self, window, width, height):
        self.width, self.height = width, height

    def _on_cursor_move(self, window, xpos, ypos):
        self.mouse_x, self.mouse_y = xpos, ypos

    def _px_to_ndc(self, px_x: float, px_y: float) -> tuple[float, float]:
        ndc_x = (px_x / max(1, self.width)) * 2.0 - 1.0
        ndc_y = 1.0 - (px_y / max(1, self.height)) * 2.0
        return ndc_x, ndc_y

    def _on_mouse_button(self, window, button, action, mods):
        if button not in (glfw.MOUSE_BUTTON_LEFT, glfw.MOUSE_BUTTON_RIGHT) or action != glfw.PRESS:
            return
        if self.help_open:
            self.help_open = False
            return

        ndc_x, ndc_y = self._px_to_ndc(self.mouse_x, self.mouse_y)
        dx = ndc_x - self.help_icon_cx
        dy = ndc_y - self.help_icon_cy
        if dx * dx + dy * dy <= self.help_icon_r * self.help_icon_r:
            self.help_open = True
            return

        if button == glfw.MOUSE_BUTTON_LEFT:
            self.mode_index = (self.mode_index + 1) % len(MODES)
        else:
            self.mode_index = (self.mode_index - 1) % len(MODES)
        self.mode_toast_time = glfw.get_time()

    def _update_audio(self):
        new_source = self.source_watcher.check()
        if new_source is not None:
            self.audio.reopen(new_source)
            self.engine = LoudnessEngine(self.audio.rate)

        now = glfw.get_time()
        dt = max(1e-4, min(0.1, now - self.last_time))
        self.last_time = now

        chunk = self.audio.read_chunk()
        if chunk is not None and len(chunk) > 0:
            left = chunk[:, 0]
            right = chunk[:, 1] if chunk.shape[1] > 1 else chunk[:, 0]
            self.engine.push(left, right, dt)
        else:
            self.engine.push(np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32), dt)

        cur_val, _ = self.engine.get_mode_value(self.mode_index)
        self.engine.update_displayed_loudness(cur_val, dt)

    def _draw_quad_px(self, x0: float, y0: float, x1: float, y1: float, color, alpha=1.0):
        # Pixel coordinates: top-left (0,0), bottom-right (win_w, win_h)
        nx0, ny0 = self._px_to_ndc(x0, y0)
        nx1, ny1 = self._px_to_ndc(x1, y1)

        glUseProgram(self.solid_program)
        glBindVertexArray(self.solid_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        verts = np.array(
            [nx0, ny0, nx1, ny0, nx1, ny1, nx0, ny0, nx1, ny1, nx0, ny1], dtype=np.float32
        )
        glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
        glUniform3f(self.solid_color_loc, *color)
        glUniform1f(self.solid_alpha_loc, alpha)
        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

    def _text_px(self, s, x_px, y_px, scale, color, align="left", valign="top"):
        nx, ny = self._px_to_ndc(x_px, y_px)
        self.text.draw(s, nx, ny, pixel_scale=scale, win_w=self.width, win_h=self.height,
                       color=color, align=align, valign=valign)

    def _draw_help_icon(self):
        ndc_x, ndc_y = self._px_to_ndc(self.mouse_x, self.mouse_y)
        dx = ndc_x - self.help_icon_cx
        dy = ndc_y - self.help_icon_cy
        hovering = (dx * dx + dy * dy <= self.help_icon_r * self.help_icon_r)

        icon_color = (0.78, 0.82, 0.90) if hovering else (0.42, 0.44, 0.50)
        
        # Draw circle in pixel space at top right
        icon_px_x = self.width - 24.0
        icon_px_y = 22.0
        r_px = 12.0
        
        aspect = self.height / self.width if self.width > 0 else 1.0
        glUseProgram(self.solid_program)
        glUniform3f(self.solid_color_loc, *icon_color)
        glUniform1f(self.solid_alpha_loc, 0.85)
        angles = np.linspace(0, 2 * np.pi, 24, endpoint=True, dtype=np.float32)
        nx, ny = self._px_to_ndc(icon_px_x, icon_px_y)
        r_ndc = (r_px / max(1, self.height)) * 2.0
        verts = np.stack(
            [nx + np.cos(angles) * r_ndc * aspect, ny + np.sin(angles) * r_ndc],
            axis=1,
        ).astype(np.float32)
        glBindVertexArray(self.solid_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
        glDrawArrays(GL_LINE_STRIP, 0, 24)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        self._text_px("?", icon_px_x, icon_px_y, 0.95, icon_color, align="center", valign="middle")

    def _draw_help_overlay(self):
        self._draw_quad_px(0, 0, self.width, self.height, (0.0, 0.0, 0.0), alpha=0.82)
        pad = 20.0
        self._draw_quad_px(pad, pad, self.width - pad, self.height - pad, (0.08, 0.08, 0.10), alpha=0.98)

        self._text_px(HELP_TITLE, self.width / 2.0, pad + 18.0, 1.4, (0.92, 0.94, 0.98), align="center", valign="top")

        start_y = pad + 52.0
        line_h = 22.0
        for i, line in enumerate(HELP_LINES):
            is_heading = line.startswith("LEFT BARS") or line.startswith("RIGHT BAR") or line.startswith("MODES")
            color = (0.90, 0.92, 0.97) if is_heading else (0.65, 0.67, 0.73)
            scale = 0.95 if is_heading else 0.80
            self._text_px(line, pad + 24.0, start_y + i * line_h, scale, color, align="left", valign="top")

        self._text_px(HELP_FOOTER, self.width / 2.0, self.height - pad - 14.0, 0.80, (0.50, 0.52, 0.58), align="center", valign="bottom")

    def render_frame(self):
        glViewport(0, 0, self.width, self.height)
        bg_color = cfg.get_color_rgb("visualizer_bg", default="#0b0b0d")
        glClearColor(*bg_color, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        w = float(self.width)
        h = float(self.height)

        y_top_px = 36.0
        y_bot_px = h - 24.0
        track_h_px = y_bot_px - y_top_px

        track_bg_color = (0.07, 0.08, 0.09)
        bar_fill_color = (0.61, 0.70, 0.81)    # MiniMeters slate blue
        peak_hold_color = (0.80, 0.87, 0.94)
        text_muted = (0.55, 0.57, 0.63)

        def db_to_px_y(db: float) -> float:
            t = max(0.0, min(1.0, (db - DB_MIN) / (DB_MAX - DB_MIN)))
            return y_bot_px - t * track_h_px

        # Proportional layout metrics in pixels
        scale_num_w = 22.0
        tick_len = 6.0
        pk_w_each = 11.0
        pk_gap = 2.0
        loud_w = 18.0
        badge_w = 76.0
        badge_h = 26.0

        core_meter_w = scale_num_w + tick_len + 6.0 + (pk_w_each * 2 + pk_gap) + 6.0 + loud_w + 5.0 + badge_w

        has_stats_panel = (w >= 440.0)

        if has_stats_panel:
            meter_x0 = max(24.0, (w * 0.44 - core_meter_w) / 2.0)
        else:
            meter_x0 = max(10.0, (w - core_meter_w) / 2.0)

        scale_x = meter_x0 + scale_num_w + tick_len

        # -------------------------------------------------------------
        # 1. Scale Ticks (0 -, 6 -, 12 -, 24 -, 36 -, 50 -)
        # -------------------------------------------------------------
        for tick_val in SCALE_TICKS:
            db_val = -float(tick_val)
            y_tick = db_to_px_y(db_val)

            # Dash mark '-'
            self._draw_quad_px(scale_x - tick_len, y_tick - 0.75, scale_x, y_tick + 0.75, text_muted)
            # Number right-aligned to dash
            self._text_px(str(tick_val), scale_x - tick_len - 3.0, y_tick, 1.2, text_muted, align="right", valign="middle")

        # -------------------------------------------------------------
        # 2. Dual Peak Meter (Left & Right channels)
        # -------------------------------------------------------------
        pk_l_x = scale_x + 6.0
        pk_r_x = pk_l_x + pk_w_each + pk_gap

        # Background tracks
        self._draw_quad_px(pk_l_x, y_top_px, pk_l_x + pk_w_each, y_bot_px, track_bg_color)
        self._draw_quad_px(pk_r_x, y_top_px, pk_r_x + pk_w_each, y_bot_px, track_bg_color)

        # Filled Peak bars
        y_l = db_to_px_y(self.engine.peak_l)
        y_r = db_to_px_y(self.engine.peak_r)
        if y_l < y_bot_px:
            self._draw_quad_px(pk_l_x, y_l, pk_l_x + pk_w_each, y_bot_px, bar_fill_color)
        if y_r < y_bot_px:
            self._draw_quad_px(pk_r_x, y_r, pk_r_x + pk_w_each, y_bot_px, bar_fill_color)

        # Peak hold ticks
        y_pk_hold_l = db_to_px_y(self.engine.peak_hold_l)
        y_pk_hold_r = db_to_px_y(self.engine.peak_hold_r)
        tick_h = 1.0
        if y_pk_hold_l < y_bot_px - 2.0:
            self._draw_quad_px(pk_l_x, y_pk_hold_l - tick_h, pk_l_x + pk_w_each, y_pk_hold_l + tick_h, peak_hold_color)
        if y_pk_hold_r < y_bot_px - 2.0:
            self._draw_quad_px(pk_r_x, y_pk_hold_r - tick_h, pk_r_x + pk_w_each, y_pk_hold_r + tick_h, peak_hold_color)

        # -------------------------------------------------------------
        # 3. Loudness Meter (LUFS / RMS)
        # -------------------------------------------------------------
        loud_x = pk_r_x + pk_w_each + 6.0

        # Background track
        self._draw_quad_px(loud_x, y_top_px, loud_x + loud_w, y_bot_px, track_bg_color)

        # Filled Loudness bar
        y_loud = db_to_px_y(self.engine.loudness_displayed)
        if y_loud < y_bot_px:
            self._draw_quad_px(loud_x, y_loud, loud_x + loud_w, y_bot_px, bar_fill_color)

        # Loudness Peak Hold tick
        y_loud_hold = db_to_px_y(self.engine.loudness_peak_hold)
        if y_loud_hold < y_bot_px - 2.0:
            self._draw_quad_px(loud_x, y_loud_hold - tick_h, loud_x + loud_w, y_loud_hold + tick_h, peak_hold_color)

        # -------------------------------------------------------------
        # 4. Dynamic Floating Value Badge (Compact, attached)
        # -------------------------------------------------------------
        cur_val, unit_suffix = self.engine.get_mode_value(self.mode_index)
        badge_val_str = f"{cur_val:.1f}{unit_suffix}" if cur_val > -69.0 else f"---{unit_suffix}"

        badge_x = loud_x + loud_w + 5.0
        badge_cy = max(y_top_px + badge_h * 0.5, min(y_bot_px - badge_h * 0.5, y_loud))
        badge_y0 = badge_cy - badge_h * 0.5
        badge_y1 = badge_cy + badge_h * 0.5

        # Solid Badge
        self._draw_quad_px(badge_x, badge_y0, badge_x + badge_w, badge_y1, bar_fill_color)

        # Dark bold centered text
        self._text_px(
            badge_val_str,
            badge_x + badge_w * 0.5,
            badge_cy,
            1.25,
            (0.04, 0.04, 0.05),
            align="center",
            valign="middle",
        )

        # -------------------------------------------------------------
        # 5. Secondary Stats Panel (When wide / maximized)
        # -------------------------------------------------------------
        if has_stats_panel:
            panel_x0 = w * 0.48
            panel_w = min(420.0, w - panel_x0 - 24.0)

            stats = [
                ("SHORT-TERM", f"{self.engine.lufs_s:.1f} LUFS" if self.engine.lufs_s > -69.0 else "--- LUFS", (0.45, 0.78, 0.95)),
                ("INTEGRATED", f"{self.engine.lufs_int:.1f} LUFS" if self.engine.lufs_int > -69.0 else "--- LUFS", (0.94, 0.95, 0.98)),
                ("RANGE (LRA)", f"{self.engine.lra:.1f} LU", (0.60, 0.63, 0.70)),
                ("MAX PEAK", f"{self.engine.max_peak:.1f} dBFS" if self.engine.max_peak > -69.0 else "--- dBFS", (0.90, 0.35, 0.30) if self.engine.max_peak > -0.5 else (0.85, 0.87, 0.92)),
            ]

            card_bg = (0.06, 0.06, 0.08)
            card_border = (0.12, 0.13, 0.16)

            is_grid = (panel_w >= 180.0 and track_h_px >= 120.0)

            if is_grid:
                cols = 2
                col_gap = 8.0
                row_gap = 8.0
                item_w = (panel_w - col_gap) / 2.0
                item_h = (track_h_px - row_gap) / 2.0

                for idx, (lbl, val, col) in enumerate(stats):
                    c = idx % cols
                    r = idx // cols
                    ix = panel_x0 + c * (item_w + col_gap)
                    iy = y_top_px + r * (item_h + row_gap)

                    self._draw_quad_px(ix, iy, ix + item_w, iy + item_h, card_bg)

                    self._text_px(lbl, ix + 10.0, iy + 8.0, 0.90, (0.45, 0.48, 0.55), align="left", valign="top")
                    self._text_px(val, ix + 10.0, iy + item_h - 10.0, 1.4, col, align="left", valign="bottom")
            else:
                item_h = (track_h_px - 3 * 6.0) / 4.0
                for idx, (lbl, val, col) in enumerate(stats):
                    iy = y_top_px + idx * (item_h + 6.0)
                    self._draw_quad_px(panel_x0, iy, panel_x0 + panel_w, iy + item_h, card_bg)
                    self._text_px(lbl, panel_x0 + 10.0, iy + item_h * 0.5, 0.90, (0.45, 0.48, 0.55), align="left", valign="middle")
                    self._text_px(val, panel_x0 + panel_w - 10.0, iy + item_h * 0.5, 1.3, col, align="right", valign="middle")

        # -------------------------------------------------------------
        # 6. Mode Change Toast Header
        # -------------------------------------------------------------
        now = glfw.get_time()
        if now - self.mode_toast_time < 2.0:
            alpha = max(0.0, min(1.0, (2.0 - (now - self.mode_toast_time)) * 2.0))
            mode_name = MODES[self.mode_index]["name"]
            toast_color = (0.85 * alpha, 0.88 * alpha, 0.95 * alpha)
            self._text_px(mode_name, w * 0.5, 18.0, 1.1, toast_color, align="center", valign="middle")

        # -------------------------------------------------------------
        # 7. Help Icon & Overlay
        # -------------------------------------------------------------
        self._draw_help_icon()
        if self.help_open:
            self._draw_help_overlay()

    def run(self):
        try:
            self._update_audio()
            self.render_frame()
            glfw.swap_buffers(self.window)
            glfw.show_window(self.window)

            glfw.make_context_current(None)
            self.running = True

            def render_thread():
                glfw.make_context_current(self.window)
                while self.running:
                    now = glfw.get_time()
                    if now - getattr(self, "_last_config_check", 0) > 1.0:
                        self._last_config_check = now
                        try:
                            cfg.reload_if_changed()
                        except:
                            pass
                    self._update_audio()
                    self.render_frame()
                    glfw.swap_buffers(self.window)

            t = threading.Thread(target=render_thread)
            t.start()

            while not glfw.window_should_close(self.window):
                glfw.wait_events_timeout(0.016)

            self.running = False
            t.join()
        finally:
            self.audio.close()
            glfw.terminate()


def main():
    app = LoudnessWindow()
    app.run()


if __name__ == "__main__":
    main()