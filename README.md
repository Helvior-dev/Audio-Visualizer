# Audio Visualizer (v2.2.0)

Audio visualizer for Windows. Captures system output through WASAPI loopback or a microphone and displays six visualizations. The default frame rate is 144 FPS.

Stack: Python 3.10+, PyQt6, PyOpenGL (OpenGL 3.3 Core Profile shaders), NumPy, SciPy, PyAudioWPatch.

Config location: `%APPDATA%\Logovo-Dushnil\Audio-Visualizer\config.json`

## Modules

Six modules are arranged in a 2x3 grid:

| Top Row | Bottom Row |
|---|---|
| **Waveform:** Scrolling waveform colored by frequency. | **Spectrum Analyzer:** Logarithmic FFT spectrum with peak hold and frequency/note details on hover. |
| **Oscilloscope:** Triggered waveform display. | **Spectrogram:** Frequency-over-time heatmap. |
| **Stereometer:** Mid/Side plot and stereo correlation. | **Loudness Meter:** Momentary, short-term and integrated LUFS, LRA, and interpolated True Peak. Measurements are not certified for standards compliance. |

## Features

- **Floating modules:** Move individual modules into separate windows, or use **Detach All** and **Attach All** in the toolbar.
- **Pause Suite:** Stops rendering docked modules while floating modules continue updating. Paused graphs keep their current frame.
- **Frame rate:** 144 FPS by default. Settings also offer 30, 60 and 120 FPS.
- **Themes:** Blue, green, pink, red, amber, cyan and violet, plus a custom accent. Change the theme in **Settings > Appearance**.
- **Settings:** Appearance, Audio, Performance and Updates tabs.
- **Icon:** Multi-resolution `.ico` with sizes from 16x16 to 256x256.
- **Updates:** Checks GitHub releases on startup; a manual check is available in Settings.

## Shortcuts

- `R`: Reset Loudness Meter statistics (integrated LUFS, LRA and True Peak).

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

## Building Standalone .exe

To build a standalone single-folder distribution using PyInstaller:
```bash
python build_executable.py
```
Output will be placed in `dist/AudioVisualizer/AudioVisualizer.exe`.

## Repository Structure

- `core/`: Audio capture, DSP, configuration, version and updater.
- `gui/`: Windows, visualizers and dialogs.
- `assets/`: Icons and source logo.
- `scripts/`: Icon generation utility.
