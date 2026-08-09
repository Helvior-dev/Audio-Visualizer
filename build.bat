@echo off
echo Building AudioVisualizer...
python -m PyInstaller -y --name "AudioVisualizer" --noconsole --icon=modules/assets/icon.ico --add-data "modules;modules" --collect-all glfw --collect-all OpenGL main.py
echo Build complete. The executable is located in the dist/AudioVisualizer folder.
