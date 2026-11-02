"""Shared terminal-style palettes for the suite and its visualizations."""

from PyQt6.QtCore import Qt, QSize, QPointF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from core.config_manager import AppConfig

THEMES = {
    "green": ("Green Terminal", "#080b09", "#0b120d", "#354a38", "#91e5a3", "#65c77e", "#849184", "#1c281e"),
    "blue": ("Blue Terminal", "#080b10", "#0b121b", "#354b63", "#91c5ff", "#65a4e8", "#849bc0", "#1c2938"),
    "pink": ("Pink Terminal", "#0c080b", "#130a10", "#593448", "#ffa6d8", "#e77fba", "#ad8ba2", "#2a1a25"),
    "red": ("Red Terminal", "#0d0808", "#150909", "#593434", "#ff9696", "#e87373", "#b58d8d", "#2a1a1a"),
    "amber": ("Amber Terminal", "#0e0b07", "#191208", "#604727", "#f6c66e", "#dfa349", "#b7a082", "#2d2214"),
    "cyan": ("Cyan Terminal", "#071011", "#0b1c20", "#31565b", "#87e9e8", "#50c4ca", "#85adb3", "#193034"),
    "violet": ("Violet Terminal", "#0b0911", "#150f22", "#4d3d69", "#c6a6ff", "#a579e6", "#a895bd", "#261e36"),
}


def palette(config: AppConfig) -> dict[str, str]:
    name, root, card, border, accent, fill, muted, grid = THEMES.get(config.theme, THEMES["blue"])
    if config.theme == "custom":
        accent = config.accent_color
        fill = accent
    return dict(name=name, root=root, card=card, border=border, accent=accent,
                fill=fill, muted=muted, grid=grid, text="#d2dce8")


def rgb(hex_color: str) -> tuple[float, float, float]:
    color = hex_color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def control_style(colors: dict[str, str]) -> str:
    return f"""
        QWidget {{ color: {colors['text']}; font-family: 'Cascadia Mono', Consolas, monospace; }}
        QToolButton, QPushButton {{ background: {colors['card']}; color: {colors['text']};
            border: 1px solid {colors['border']}; border-radius: 0; padding: 4px 8px; }}
        QToolButton:hover, QPushButton:hover {{ color: {colors['accent']}; border-color: {colors['accent']}; }}
        QPushButton:checked {{ color: {colors['accent']}; border-color: {colors['accent']};
            background: {colors['grid']}; }}
    """


def apply_meter_header(widget, colors: dict[str, str]) -> None:
    widget.header_frame.setStyleSheet(control_style(colors) + "QToolButton { padding: 0; }")
    widget.title_lbl.setStyleSheet(f"color: {colors['muted']}; font-weight: bold; font-size: 10px;")
    widget.undock_btn.setText("")
    widget.undock_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    widget.undock_btn.setIconSize(QSize(14, 14))
    widget.undock_btn.setIcon(popout_icon(colors['accent']))
    widget.update()


def popout_icon(color: str) -> QIcon:
    """Draw the pop-out icon without relying on platform fonts."""
    image = QPixmap(16, 16)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.4))
    painter.drawLine(QPointF(2.5, 6.5), QPointF(2.5, 13.5))
    painter.drawLine(QPointF(2.5, 13.5), QPointF(10.5, 13.5))
    painter.drawLine(QPointF(6, 10), QPointF(13, 3))
    painter.drawLine(QPointF(8.5, 3), QPointF(13, 3))
    painter.drawLine(QPointF(13, 3), QPointF(13, 7.5))
    painter.end()
    return QIcon(image)
