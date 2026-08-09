"""
Spectrogram (Waterfall) module.

Renders a 2D rolling heatmap of frequencies over time.
Uses a 2D OpenGL texture updated ring-buffer style (one row per frame),
with the fragment shader handling the scrolling offset and colormapping.
"""

import sys
import ctypes
from pathlib import Path
import math

import glfw
import numpy as np
from OpenGL.GL import *
import threading

sys.path.insert(0, str(Path(__file__).parent))
from audio_capture import AudioCapture
from window_utils import apply_dark_titlebar, set_window_icon
from text_render import TextRenderer, link_program as text_link_program, TEXT_VERTEX_SHADER, TEXT_FRAGMENT_SHADER
from audio_source_config import load_selected_source, SourceWatcher

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

FFT_SIZE = 4096
MIN_FREQ_HZ = 20.0
MAX_FREQ_HZ = 20000.0
DB_FLOOR = -90.0
DB_CEIL = 0.0

TEXTURE_WIDTH = 1024  
TEXTURE_HEIGHT = 512  

QUAD_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 pos;
layout(location = 1) in vec2 uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
    v_uv = uv;
}
"""

QUAD_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_uv;
out vec4 out_color;

uniform sampler2D tex;
uniform float scroll_offset;

vec3 get_colormap(float level) {
    vec3 color_bg = vec3(0.02, 0.0, 0.05);
    vec3 color_mid1 = vec3(0.35, 0.0, 0.35);
    vec3 color_mid2 = vec3(0.85, 0.25, 0.15);
    vec3 color_mid3 = vec3(0.95, 0.85, 0.15);
    vec3 color_peak = vec3(1.0, 1.0, 1.0);
    
    if (level < 0.25) return mix(color_bg, color_mid1, level * 4.0);
    if (level < 0.50) return mix(color_mid1, color_mid2, (level - 0.25) * 4.0);
    if (level < 0.75) return mix(color_mid2, color_mid3, (level - 0.50) * 4.0);
    return mix(color_mid3, color_peak, (level - 0.75) * 4.0);
}

void main() {
    vec2 st = v_uv;
    st.x = fract(st.x + scroll_offset);
    float intensity = texture(tex, st).r;
    out_color = vec4(get_colormap(intensity), 1.0);
}
"""

SOLID_VERTEX_SHADER = """
#version 330 core
in vec2 pos;
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

SOLID_FRAGMENT_SHADER = """
#version 330 core
uniform vec3 color;
uniform float alpha;
out vec4 out_color;
void main() {
    out_color = vec4(color, alpha);
}
"""

HELP_TITLE = "SPECTROGRAM"
HELP_TEXT_LINES = [
    "Displays a scrolling heatmap of frequency content over time.",
    "",
    "Horizontal axis: Time (scrolling right-to-left)",
    "Vertical axis: Frequency (Bass at bottom, Treble at top)",
    "Color: Loudness (Dark purple = quiet, White/Yellow = loud)",
]
HELP_FOOTER = "Click anywhere to close"

def compile_shader(source: str, shader_type) -> int:
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        raise RuntimeError(glGetShaderInfoLog(shader).decode())
    return shader

def link_program(vertex_src: str, fragment_src: str) -> int:
    vs = compile_shader(vertex_src, GL_VERTEX_SHADER)
    fs = compile_shader(fragment_src, GL_FRAGMENT_SHADER)
    program = glCreateProgram()
    glAttachShader(program, vs)
    glAttachShader(program, fs)
    glLinkProgram(program)
    if not glGetProgramiv(program, GL_LINK_STATUS):
        raise RuntimeError(glGetProgramInfoLog(program).decode())
    glDeleteShader(vs)
    glDeleteShader(fs)
    return program

class SpectrogramWindow:
    def __init__(self):
        if not glfw.init():
            raise RuntimeError("GLFW init failed")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

        self.width, self.height = 800, 400
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        self.window = glfw.create_window(self.width, self.height, "Spectrogram", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("GLFW window creation failed")

        monitor = glfw.get_primary_monitor()
        mode = glfw.get_video_mode(monitor)
        glfw.set_window_pos(self.window, (mode.size.width - self.width) // 2, (mode.size.height - self.height) // 2)

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        glfw.set_framebuffer_size_callback(self.window, self._on_resize)
        glfw.set_mouse_button_callback(self.window, self._on_mouse_button)
        glfw.set_cursor_pos_callback(self.window, self._on_cursor_move)
        apply_dark_titlebar(self.window)
        set_window_icon(self.window, ICON_PATH)

        self.program = link_program(QUAD_VERTEX_SHADER, QUAD_FRAGMENT_SHADER)
        self.scroll_loc = glGetUniformLocation(self.program, "scroll_offset")
        
        self.text_program = text_link_program(TEXT_VERTEX_SHADER, TEXT_FRAGMENT_SHADER)
        self.text_renderer = TextRenderer(self.text_program)
        
        # Setup Fullscreen Quad
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        self.vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        quad_verts = np.array([
            -1.0, -1.0,  0.0, 0.0,
             1.0, -1.0,  1.0, 0.0,
             1.0,  1.0,  1.0, 1.0,
            -1.0, -1.0,  0.0, 0.0,
             1.0,  1.0,  1.0, 1.0,
            -1.0,  1.0,  0.0, 1.0,
        ], dtype=np.float32)
        glBufferData(GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL_STATIC_DRAW)
        stride = 4 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(2 * 4))
        
        # Solid program for help overlay
        self.solid_program = link_program(SOLID_VERTEX_SHADER, SOLID_FRAGMENT_SHADER)
        self.solid_color_loc = glGetUniformLocation(self.solid_program, "color")
        self.solid_alpha_loc = glGetUniformLocation(self.solid_program, "alpha")
        self.solid_vao = glGenVertexArrays(1)
        glBindVertexArray(self.solid_vao)
        self.solid_vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        glBufferData(GL_ARRAY_BUFFER, 1024 * 2 * 4, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        # Help state
        self.help_icon_cx = 0.93
        self.help_icon_cy = 0.95
        self.help_icon_r = 0.035
        self.help_open = False
        self.mouse_x, self.mouse_y = -1.0, -1.0
        
        # Setup Texture
        self.tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        
        empty_data = np.zeros((TEXTURE_HEIGHT, TEXTURE_WIDTH), dtype=np.float32)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R32F, TEXTURE_WIDTH, TEXTURE_HEIGHT, 0, GL_RED, GL_FLOAT, empty_data)

        self.current_col = 0
        
        initial_source = load_selected_source()
        self.audio = AudioCapture(chunk_size=512, source=initial_source)
        self.source_watcher = SourceWatcher()
        self.sample_rate = self.audio.rate if initial_source else 48000
        self.window_fn = np.hanning(FFT_SIZE).astype(np.float32)
        self.rolling_buffer = np.zeros(FFT_SIZE, dtype=np.float32)
        
        self.last_valid_time = glfw.get_time()
        self.running = False
        
        self._recompute_bins()

    def _recompute_bins(self):
        nyquist = self.sample_rate / 2.0
        n_fft_bins = FFT_SIZE // 2 + 1
        self._fft_bin_axis = np.linspace(0, nyquist, n_fft_bins)
        
        log_min = np.log10(MIN_FREQ_HZ)
        log_max = np.log10(MAX_FREQ_HZ)
        log_edges = np.linspace(log_min, log_max, TEXTURE_HEIGHT + 1)
        self.bin_freq_edges = 10.0 ** log_edges
        
        self.bin_indices = np.searchsorted(self._fft_bin_axis, self.bin_freq_edges)

    def _on_resize(self, window, width, height):
        self.width, self.height = max(1, width), max(1, height)

    def _on_cursor_move(self, window, xpos, ypos):
        self.mouse_x, self.mouse_y = xpos, ypos

    def _mouse_to_window_ndc(self, xpos, ypos):
        if self.width <= 0 or self.height <= 0:
            return 0.0, 0.0
        x = (xpos / self.width) * 2.0 - 1.0
        y = 1.0 - (ypos / self.height) * 2.0
        return x, y

    def _on_mouse_button(self, window, button, action, mods):
        if button != glfw.MOUSE_BUTTON_LEFT or action != glfw.PRESS:
            return
        if self.help_open:
            self.help_open = False
            return
        x, y = self._mouse_to_window_ndc(self.mouse_x, self.mouse_y)
        dx = x - self.help_icon_cx
        dy = y - self.help_icon_cy
        if dx * dx + dy * dy <= self.help_icon_r * self.help_icon_r:
            self.help_open = True

    def _update_audio(self):
        new_source = self.source_watcher.check()
        if new_source is not None:
            self.audio.reopen(new_source)
            self.rolling_buffer[:] = 0.0
            self.sample_rate = self.audio.rate
            self._recompute_bins()

        chunk = self.audio.read_chunk()
        if chunk is not None:
            mono = chunk.mean(axis=1).astype(np.float32)
            n = len(mono)
            if n > FFT_SIZE:
                mono = mono[-FFT_SIZE:]
                n = FFT_SIZE
            self.rolling_buffer = np.roll(self.rolling_buffer, -n)
            self.rolling_buffer[-n:] = mono
            self.last_valid_time = glfw.get_time()
        else:
            if glfw.get_time() - getattr(self, "last_valid_time", 0) > 0.05:
                self.rolling_buffer *= 0.8

        windowed = self.rolling_buffer * self.window_fn
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum) / (self.window_fn.sum() / 2)

        bins = np.zeros(TEXTURE_HEIGHT, dtype=np.float32)
        for i in range(TEXTURE_HEIGHT):
            start_idx = self.bin_indices[i]
            end_idx = self.bin_indices[i+1]
            if start_idx == end_idx:
                end_idx = start_idx + 1
            if end_idx > len(magnitude):
                end_idx = len(magnitude)
            
            if start_idx < len(magnitude):
                bins[i] = np.mean(magnitude[start_idx:end_idx])
            else:
                bins[i] = 0.0

        db = 20.0 * np.log10(np.maximum(bins, 1e-10))
        level = (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)
        level = np.clip(level, 0.0, 1.0).astype(np.float32)
        level = np.ascontiguousarray(level)
        
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glTexSubImage2D(GL_TEXTURE_2D, 0, self.current_col, 0, 1, TEXTURE_HEIGHT, GL_RED, GL_FLOAT, level)
        
        self.current_col = (self.current_col + 1) % TEXTURE_WIDTH

    def _draw_circle_window(self, cx, cy, r, color, alpha=1.0, segments=24):
        aspect = self.width / self.height if self.height > 0 else 1.0
        rx = r
        ry = r * aspect
        verts = []
        for i in range(segments):
            a1 = 2.0 * math.pi * i / segments
            verts.extend([cx + math.cos(a1)*rx, cy + math.sin(a1)*ry])
        verts = np.array(verts, dtype=np.float32)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
        glUniform3f(self.solid_color_loc, *color)
        glUniform1f(self.solid_alpha_loc, alpha)
        glDrawArrays(GL_LINE_LOOP, 0, segments)

    def _draw_quad_window(self, x0, y0, x1, y1, color, alpha=1.0):
        verts = np.array([x0, y0, x1, y0, x1, y1, x0, y0, x1, y1, x0, y1], dtype=np.float32)
        glBindBuffer(GL_ARRAY_BUFFER, self.solid_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
        glUniform3f(self.solid_color_loc, *color)
        glUniform1f(self.solid_alpha_loc, alpha)
        glDrawArrays(GL_TRIANGLES, 0, 6)

    def _text_window(self, s, x_ndc, y_ndc, scale, color, align="left", valign="top"):
        self.text_renderer.draw(s, x_ndc, y_ndc, pixel_scale=scale,
                        win_w=self.width, win_h=self.height, color=color,
                        align=align, valign=valign)

    def render_frame(self):
        from config import cfg
        glViewport(0, 0, self.width, self.height)
        bg_color = cfg.get_color_rgb("visualizer_bg")
        glClearColor(*bg_color, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        glUseProgram(self.program)
        
        offset = self.current_col / TEXTURE_WIDTH
        glUniform1f(self.scroll_loc, offset)

        glBindVertexArray(self.vao)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindVertexArray(0)
        
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        
        if self.help_open:
            glUseProgram(self.solid_program)
            glBindVertexArray(self.solid_vao)
            self._draw_quad_window(-1.0, -1.0, 1.0, 1.0, (0.0, 0.0, 0.0), alpha=0.72)
            self._draw_quad_window(-0.95, -0.85, 0.95, 0.85, (0.08, 0.08, 0.1), alpha=0.97)
            glBindVertexArray(0)
            
            title_y = 0.72
            self._text_window(HELP_TITLE, 0.0, title_y, 1.4, (0.92, 0.92, 0.97), align="center")
            line_h = 0.082
            start_y = title_y - 0.18
            for i, line in enumerate(HELP_TEXT_LINES):
                if line:
                    self._text_window(line, 0.0, start_y - i * line_h, 0.72, (0.7, 0.7, 0.75), align="center")
            footer_y = start_y - len(HELP_TEXT_LINES) * line_h - 0.05
            self._text_window(HELP_FOOTER, 0.0, footer_y, 0.7, (0.55, 0.55, 0.6), align="center")
        else:
            hovering = False
            x, y = self._mouse_to_window_ndc(self.mouse_x, self.mouse_y)
            dx_m, dy_m = x - self.help_icon_cx, y - self.help_icon_cy
            if dx_m * dx_m + dy_m * dy_m <= self.help_icon_r * self.help_icon_r:
                hovering = True
            glUseProgram(self.solid_program)
            glBindVertexArray(self.solid_vao)
            icon_color = (0.75, 0.75, 0.8) if hovering else (0.5, 0.5, 0.55)
            self._draw_circle_window(self.help_icon_cx, self.help_icon_cy, self.help_icon_r, icon_color, alpha=0.9)
            glBindVertexArray(0)
            self._text_window("?", self.help_icon_cx, self.help_icon_cy, 1.1, icon_color, align="center", valign="middle")

        glDisable(GL_BLEND)

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
                while self.running and not glfw.window_should_close(self.window):
                    now = glfw.get_time()
                    if now - getattr(self, "_last_config_check", 0) > 1.0:
                        self._last_config_check = now
                        try:
                            from config import cfg
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
    app = SpectrogramWindow()
    app.run()

if __name__ == "__main__":
    main()
