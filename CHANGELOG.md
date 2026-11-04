# Changelog

## 2.2.1

### Fixed
- The `R` shortcut now resets integrated LUFS, LRA and True Peak without crashing. The physical key also works with a Russian keyboard layout on Windows.

### Changed
- The Windows build folder and executable are now named `Audio-Visualizer`.

## 2.2.0

### Added
- Seven coordinated terminal-style themes with blue as the default, including a custom accent option and support for existing settings.
- Separate Appearance, Audio, Performance and Updates settings tabs.
- Streaming True Peak measurement and reference-signal regression tests.
- Vector-drawn pop-out icons for docked modules.

### Changed
- Preserved 144 FPS by default while caching spectrum positions and rendering 512 of 1024 stored stereometer points.
- Updated interface labels and help text to remove emoji and clarify control behavior.
- Updated the main window, floating windows, dialogs and visualizations when the selected theme changes.
- Removed module help popovers and the duplicate header inside floating windows; the native window title remains. The main window title now uses normal capitalization.

### Fixed
- Aligned the floating-module toolbar with the main controls: consistent height, themed button borders and a visible always-on-top state.
- Audio reader recovery after buffer wraps and source changes, large callbacks and cleanup after failed stream startup.
- Integrated LUFS window accumulation for varying input block sizes.
- True Peak startup behavior when measuring hard-onset signals.

True Peak results match the tested FFmpeg reference signals within 0.2 dB; standards compliance has not been certified.
