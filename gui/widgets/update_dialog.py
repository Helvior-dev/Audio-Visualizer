"""
Update Notification Dialog for Audio Visualizer.
Presents the user with new version announcements, changelog notes,
and a direct button to open the GitHub Releases page.
"""

from pathlib import Path
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QPushButton, QFrame, QWidget
)
from PyQt6.QtGui import QFont, QIcon, QPixmap, QDesktopServices

from core.version import RELEASES_URL, __version__
from core.config_manager import AppConfig
from ..theme import palette

ICON_PNG = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png"


class UpdateDialog(QDialog):
    """
    Modal window notifying the user of a new software release.
    """
    def __init__(self, release_info: dict, is_preview: bool = False, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.is_preview = is_preview
        self.theme_colors = palette(getattr(parent, "config", AppConfig()))

        self.setWindowTitle("Доступно обновление / New Version Available" if not is_preview else "[Preview] Окно обновления")
        self.setFixedSize(520, 420)
        colors = self.theme_colors
        self.setStyleSheet(f"""
            QDialog {{ background: {colors['root']}; color: {colors['text']};
                font-family: 'Cascadia Mono', Consolas, monospace; }}
            QLabel {{ color: {colors['text']}; }}
            QTextBrowser {{ background: {colors['card']}; color: {colors['text']};
                border: 1px solid {colors['border']}; padding: 10px; }}
            QPushButton {{ background: {colors['card']}; color: {colors['text']};
                border: 1px solid {colors['border']}; padding: 7px 14px; }}
            QPushButton:hover {{ color: {colors['accent']}; border-color: {colors['accent']}; }}
        """)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header Row (Icon + Title + Versions)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(14)

        # App Squircle Icon
        icon_lbl = QLabel(self)
        if ICON_PNG.exists():
            pix = QPixmap(str(ICON_PNG)).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_lbl.setPixmap(pix)
        icon_lbl.setFixedSize(56, 56)
        header_layout.addWidget(icon_lbl)

        # Title and Version information
        title_box = QVBoxLayout()
        title_box.setSpacing(3)

        title_text = "Доступна новая версия" if not self.is_preview else "Предпросмотр окна обновления"
        main_title = QLabel(title_text, self)
        main_title.setFont(QFont("Cascadia Mono", 13, QFont.Weight.Bold))
        title_box.addWidget(main_title)

        cur_v = self.release_info.get("current_version", __version__)
        new_v = self.release_info.get("tag_name", "vNext")

        ver_badge = QLabel(f"Установлена: <span style='color: {self.theme_colors['muted']};'>v{cur_v.lstrip('v')}</span>  ➔  Доступна: <span style='color: {self.theme_colors['accent']}; font-weight: bold;'>{new_v}</span>", self)
        ver_badge.setStyleSheet("font-size: 11px;")
        title_box.addWidget(ver_badge)

        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        layout.addLayout(header_layout)

        # Release Title
        rel_name = self.release_info.get("name", "")
        if rel_name and rel_name != new_v:
            name_lbl = QLabel(rel_name, self)
            name_lbl.setFont(QFont("Cascadia Mono", 10, QFont.Weight.Bold))
            name_lbl.setStyleSheet(f"color: {self.theme_colors['text']}; padding-top: 2px;")
            name_lbl.setWordWrap(True)
            layout.addWidget(name_lbl)

        # Release Notes / Changelog Body
        body_text = self.release_info.get("body", "").strip()
        if not body_text:
            body_text = "Новая версия Audio Visualizer доступна на GitHub. Нажмите кнопку ниже, чтобы перейти к странице релиза и скачать обновление."

        text_browser = QTextBrowser(self)
        text_browser.setOpenExternalLinks(True)
        text_browser.setMarkdown(body_text)
        layout.addWidget(text_browser, 1)

        # Buttons footer
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        close_btn = QPushButton("Закрыть" if not self.is_preview else "Закрыть тест", self)
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)

        btn_layout.addStretch(1)

        open_btn = QPushButton("Открыть страницу релиза", self)
        open_btn.setProperty("class", "download-btn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_release_url)
        btn_layout.addWidget(open_btn)

        layout.addLayout(btn_layout)

    def _open_release_url(self):
        url_str = self.release_info.get("html_url", RELEASES_URL)
        QDesktopServices.openUrl(QUrl(url_str))
        self.accept()
