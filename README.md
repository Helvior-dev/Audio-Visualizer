# Audio Visualizer (v2.2.0)

Real-time audio visualization suite for Windows. Captures system output via WASAPI Loopback or a microphone and displays six meters and plots. The target frame rate is 144 FPS by default.

Stack: Python 3.10+, PyQt6, PyOpenGL (OpenGL 3.3 Core Profile shaders), NumPy, SciPy, PyAudioWPatch.

Config location: `%APPDATA%\Logovo-Dushnil\Audio-Visualizer\config.json`

---

## Modules

The suite consists of 6 visualizer modules organized in a balanced 2x3 grid:

| Top Row | Bottom Row |
|---|---|
| **Waveform** — Dynamic rolling waveform history with pitch-based spectral coloring (bass = crimson, mids = theme accent, treble = cyan). Rendered via GPU shaders. | **Spectrum Analyzer** — Logarithmic FFT spectrum with smooth decay, peak-hold lines, and hover frequency/note tooltips. |
| **Oscilloscope** — Vector phase oscilloscope with auto-triggering and neon glow. | **Spectrogram** — Fast 2D frequency-over-time heatmap with accent-aware gradients. |
| **Stereometer** — Mid/Side scatter plot and stereo phase correlation meter (-1.0 to +1.0). | **Loudness Meter** — Momentary, Short-Term and Integrated LUFS, LRA, and interpolated True Peak. These measurements are not certified for standards compliance. |

---

## Features

- **Docking & Floating Windows**: Run as a unified 2x3 grid or move individual modules into native windows. Use **Detach All** / **Attach All** in the toolbar to move all visible modules at once.
- **Smart Pause (Pause Suite)**: When visualizers are undocked, docked background rendering is frozen to save GPU/CPU resources while floating windows continue running.
- **Freeze State**: When paused, graphs hold their current frame instead of resetting to zero.
- **144 FPS by default**: Default frame rate is set to 144 FPS with support for 30 / 60 / 120 / 144 FPS in settings.
- **Themes**: Seven coordinated dark palettes (blue by default, plus green, pink, red, amber, cyan and violet). Select one in **Settings > Appearance**, or choose a custom accent on the blue base palette. Themes apply to the interface and all six visualizations.
- **Settings**: Appearance, Audio, Performance and Updates tabs.
- **Squircle Icon**: Multi-resolution `.ico` (16x16 up to 256x256) with transparent padding, ambient drop shadow, and Lanczos super-sampling for Windows 11 desktop and taskbar.
- **Release Updater**: Background check against GitHub releases API on launch, with a release-notes dialog and a manual check in Settings.

---

## Shortcuts

- `R` — Reset Loudness Meter statistics (Integrated LUFS, LRA, True Peak).

---

## Setup & Running

### Requirements
- Windows 10 / 11 (64-bit)
- Python 3.10+

### Install Dependencies
Use an isolated virtual environment. On Windows PowerShell (only if `venv` does not already exist):
```bash
py -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Run
```bash
venv\Scripts\python.exe main.py
```
In VS Code, open this folder, select `venv\Scripts\python.exe` as the Python interpreter and run `main.py`.

See [CHANGELOG.md](CHANGELOG.md) for release changes.

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
