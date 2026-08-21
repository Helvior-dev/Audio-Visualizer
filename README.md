# Audio Visualizer (Modern Pro Suite for PyQt6)

A high-performance, 100% GPU-accelerated audio visualization suite for Windows built with **PyQt6**, **PyOpenGL (OpenGL 3.3 Core Profile Shaders)**, **NumPy**, **SciPy**, and **PyAudioWPatch (WASAPI Loopback)**.

---

## Visualizer Modules

1. **Waveform (History Waveform)**:
   - Rolling audio waveform history scrolling right to left in real time.
   - Dynamic spectral pitch coloring (Bass = Crimson/Pink, Mids = Theme Accent/Peach, Treble = Cyan/Violet).
   - Pure GPU shader acceleration (144+ FPS locked, 0% CPU).

2. **Oscilloscope**:
   - High-speed vector waveform visualizer with direct GPU shader rendering.
   - Dynamic electrical brightness and custom theme adaptation.

3. **Spectrum Analyzer**:
   - Fast, musical FFT spectrum analyzer with smooth decay and peak-hold lines.
   - Interactive frequency note / pitch tooltip on hover.

4. **Spectrogram (Waterfall)**:
   - High-speed 2D frequency heatmap scrolling horizontally.
   - Dynamic palette gradient anchored to the active accent theme.

5. **Stereometer (Vectorscope)**:
   - Mid/Side Lissajous diamond scatter plot.
   - Real-time stereo phase correlation meter (-1.0 to +1.0).

6. **Loudness & Level Meter**:
   - EBU R128 / ITU-R BS.1770-4 compliance.
   - Momentary, Short-Term, and Integrated LUFS, Loudness Range (LRA), and True-Peak meters.
   - Responsive layout adapting to card sizes.

---

## Key Features

- **Docking & Floating Windows**:
  - Unified balanced 2x3 grid suite or individual standalone floating windows.
  - One-click `↗ Undock All` / `⇲ Dock All` toggle to pop-out or restore all visualizers at once.
- **Dynamic Suite Pause (`⏸ Pause Suite`)**:
  - Automatically activates when modules are undocked to freeze docked background rendering (0% CPU/GPU overhead) while floating windows run actively.
- **Custom Accent Themes**:
  - 7 built-in presets (*Spectrum Magenta, Cyberpunk Cyan, Hot Pink, Neon Green, Default Blue, Amber Gold, Slate Blue*) + custom RGB color picker.
- **App Configuration Storage**:
  - Configurations and window geometries are safely stored in `%APPDATA%\Logovo-Dushnil\Audio-Visualizer\config.json`.

---

## Quick Start & Running

### Requirements
- Windows 10 / Windows 11
- Python 3.10+

### Installation
```bash
pip install -r requirements.txt
```

### Launch
```bash
python main.py
```
or double-click `run.bat`.

---

## Building Standalone Executable (.exe)
To compile a standalone Windows `.exe` using PyInstaller:
```bash
python build_executable.py
```
The compiled executable will be generated at `dist/AudioVisualizer/AudioVisualizer.exe`.

---

## Legacy Version
The previous version of the codebase has been archived in the [`Old-Version/`](./Old-Version/) directory.
