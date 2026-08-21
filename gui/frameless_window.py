"""
Native Dark Window implementation with Windows DWM dark title bar.
Uses standard OS window management (native title bar, buttons, minimize/maximize/snap)
with forced dark theme on Windows 10 & 11 and zero-flicker native Always on Top.
"""

import sys
import ctypes
from ctypes import c_int, byref, sizeof
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout


class NativeDarkWindow(QWidget):
    """
    Standard Windows window with enforced dark DWM titlebar and Always-on-Top support.
    """
    def __init__(self, parent=None, is_floating_module=False):
        super().__init__(parent)
        self.is_floating_module = is_floating_module
        self._is_pinned = False

        # Use native OS window with standard title bar
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.setStyleSheet("background-color: #0b0b0d;")

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_dark_dwm()
        if self._is_pinned:
            self._apply_topmost_native(True)

    def apply_dark_dwm(self):
        """Enforce dark mode titlebar on Windows 10 and Windows 11."""
        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                val = c_int(1)
                # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Win 10 20H1+ / Win 11, 19 on older builds)
                res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, byref(val), sizeof(val)
                )
                if res != 0:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, 19, byref(val), sizeof(val)
                    )
            except Exception:
                pass

    def _apply_topmost_native(self, pinned: bool):
        if sys.platform == "win32" and self.winId():
            try:
                hwnd = int(self.winId())
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                insert_after = HWND_TOPMOST if pinned else HWND_NOTOPMOST
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    insert_after,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )
            except Exception:
                pass

    def set_always_on_top(self, pinned: bool):
        self._is_pinned = pinned
        if self.windowHandle():
            self.windowHandle().setFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)

        self._apply_topmost_native(pinned)
        self.apply_dark_dwm()

    def is_always_on_top(self) -> bool:
        return self._is_pinned


FramelessWindow = NativeDarkWindow
