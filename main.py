"""
Audio Visualizer (Modular Suite for PyQt6).
Entry point of the application.
"""

import sys
import os
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QFont, QColor, QPalette

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR))

from core.config_manager import load_config
from core.audio_capture import AudioSource
from core.audio_worker import AudioWorker
from gui.main_window import MainWindow

ICON_PATH = BASE_DIR / "assets" / "icon.png"


def create_app():
    # Enable High DPI scaling
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    app.setApplicationName("Audio Visualizer")
    app.setOrganizationName("Logovo-Dushnil")

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Global Dark Palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(18, 18, 22))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 230))
    palette.setColor(QPalette.ColorRole.Base, QColor(14, 14, 18))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(24, 24, 30))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(20, 20, 26))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(240, 240, 250))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 230))
    palette.setColor(QPalette.ColorRole.Button, QColor(24, 24, 30))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 230))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(88, 166, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    # Set default UI font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Global stylesheet
    app.setStyleSheet("""
        QToolTip {
            background-color: #1A1A22;
            color: #E0E0EC;
            border: 1px solid #38384A;
            border-radius: 4px;
            padding: 4px 8px;
            font-family: 'Segoe UI', Arial;
            font-size: 11px;
        }
        QScrollBar:vertical {
            background: #14141A;
            width: 8px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #282834;
            min-height: 20px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover {
            background: #404054;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
    """)

    return app


def main():
    config = load_config()

    app = create_app()

    # Initialize audio worker
    source = AudioSource(
        kind=config.audio_source_kind,
        device_index=config.audio_source_device_index,
        name=config.audio_source_name,
    )
    audio_worker = AudioWorker(source=source)

    # Initialize main window
    main_window = MainWindow(config=config, audio_worker=audio_worker)
    main_window.show()

    exit_code = app.exec()
    audio_worker.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
