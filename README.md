# Audio Visualizer (v2.1.0)

Real-time audio visualization suite for Windows. Captures audio directly from any output (headphones, speakers) via WASAPI Loopback with zero latency and renders meters and plots on GPU shaders at 144+ FPS.

Stack: Python 3.10+, PyQt6, PyOpenGL (OpenGL 3.3 Core Profile shaders), NumPy, SciPy, PyAudioWPatch.

Config location: `%APPDATA%\Logovo-Dushnil\Audio-Visualizer\config.json`

---

## Modules

The suite consists of 6 visualizer modules organized in a balanced 2x3 grid:

| Top Row | Bottom Row |
|---|---|
| **Waveform** — Dynamic rolling waveform history with pitch-based spectral coloring (bass = crimson, mids = theme accent, treble = cyan). Rendered via GPU shaders. | **Spectrum Analyzer** — Logarithmic FFT spectrum with smooth decay, peak-hold lines, and hover frequency/note tooltips. |
| **Oscilloscope** — Vector phase oscilloscope with auto-triggering and neon glow. | **Spectrogram** — Fast 2D frequency-over-time heatmap with accent-aware gradients. |
| **Stereometer** — Mid/Side Lissajous diamond scatter plot and stereo phase correlation meter (-1.0 to +1.0). | **Loudness Meter** — EBU R128 compliance meters: Momentary, Short-Term, Integrated LUFS, LRA, and True Peak. |

---

## Features

- **Docking & Floating Windows**: Run as a unified 2x3 grid or pop out any module into a borderless floating window. Use `↗ Undock All` / `⇲ Dock All` in the top bar to detach or redock all modules in one click.
- **Smart Pause (Pause Suite)**: When visualizers are undocked, docked background rendering is frozen to save GPU/CPU resources while floating windows continue running.
- **Freeze State**: When paused, graphs hold their current frame instead of resetting to zero.
- **144 FPS by default**: Default frame rate is set to 144 FPS with support for 30 / 60 / 120 / 144 FPS in settings.
- **Accent Themes**: 7 built-in presets (Spectrum Magenta, Cyberpunk Cyan, Hot Pink, Neon Green, Default Blue, Amber Gold, Slate Blue) plus custom HEX/RGB picker. The accent applies globally across all modules.
- **Squircle Icon**: Multi-resolution `.ico` (16x16 up to 256x256) with transparent padding, ambient drop shadow, and Lanczos super-sampling for Windows 11 desktop and taskbar.
- **Release Updater**: Background check against GitHub releases API on launch, with in-app changelog dialog, download button, and manual "Check for Updates" in Settings.

---

## Shortcuts

- `R` — Reset Loudness Meter statistics (Integrated LUFS, LRA, True Peak).

---

## Setup & Running

### Requirements
- Windows 10 / 11 (64-bit)
- Python 3.10+

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run
```bash
python main.py
```
or double-click `run.bat`.

---

## Building Standalone .exe

To build a standalone single-folder distribution using PyInstaller:
```bash
python build_executable.py
```
Output will be placed in `dist/AudioVisualizer/AudioVisualizer.exe`.

---

## Repository Structure

- `core/` — Audio capture (WASAPI Loopback), DSP algorithms, config manager, version & updater.
- `gui/` — Main window, title bar, dock containers, OpenGL visualizer widgets, settings and update dialogs.
- `assets/` — Icons (`icon.ico`, `icon.png`, source logo).
- `scripts/` — Utility scripts (`generate_icons.py`).
- `Old-Version/` — Archived legacy implementation.
