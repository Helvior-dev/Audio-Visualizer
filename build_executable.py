"""
Automated PyInstaller Build Script for Audio Visualizer.
Compiles the application into a standalone Windows executable with all assets,
icons, OpenGL dependencies, and audio capture libraries included.
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
ICON_ICO = ASSETS_DIR / "icon.ico"
ICON_PNG = ASSETS_DIR / "icon.png"

def build():
    print("==================================================")
    print("Building Audio Visualizer Standalone Executable...")
    print("==================================================")

    # Ensure icon.ico exists
    if not ICON_ICO.exists() and ICON_PNG.exists():
        from PyQt6.QtGui import QImage
        img = QImage(str(ICON_PNG))
        img.save(str(ICON_ICO), "ICO")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed", # No black console window
        f"--icon={str(ICON_ICO)}",
        "--name=AudioVisualizer",
        f"--add-data={str(ASSETS_DIR)}{os.pathsep}assets",
        "--hidden-import=PyQt6.QtOpenGLWidgets",
        "--hidden-import=pyaudiowpatch",
        "--hidden-import=scipy.signal",
        "--hidden-import=OpenGL.platform.win32",
        "--hidden-import=multiprocessing.shared_memory",
        str(BASE_DIR / "main.py")
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode == 0:
        print("\n==================================================")
        print("BUILD SUCCESSFUL!")
        print(f"Executable is located at: {BASE_DIR / 'dist' / 'AudioVisualizer' / 'AudioVisualizer.exe'}")
        print("==================================================")
    else:
        print("\nBUILD FAILED with error code:", res.returncode)

if __name__ == "__main__":
    build()
