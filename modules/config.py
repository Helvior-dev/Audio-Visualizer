import json
import os
from pathlib import Path

# When frozen, BASE_DIR should be the location of the exe to persist config.
import sys
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent

CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "theme": {
        "bg": "#0b0b0d",
        "card_bg": "#17171b",
        "card_bg_hover": "#1f1f25",
        "card_border": "#26262c",
        "text_primary": "#e9e9ee",
        "text_muted": "#6f6f79",
        "accent": "#3ddc84",
        "dot_idle": "#3a3a42",
        "icon_color": "#9b9ba6",
        
        "visualizer_bg": "#0b0b0d",
        "visualizer_accent": "#3ddc84",
        "visualizer_secondary": "#758295"
    }
}


class Config:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self._last_mtime = 0
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                self._last_mtime = os.path.getmtime(CONFIG_PATH)
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # Simple merge for top-level keys
                    if "theme" in user_config:
                        self.data["theme"].update(user_config["theme"])
            except Exception as e:
                print(f"Failed to load config: {e}")
        else:
            self.save()

    def reload_if_changed(self) -> bool:
        """Returns True if the config was reloaded."""
        if not CONFIG_PATH.exists():
            return False
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime > self._last_mtime:
                self.load()
                return True
        except Exception:
            pass
        return False

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get_color(self, key: str, default: str = "#ffffff") -> str:
        return self.data["theme"].get(key, default)

    def get_color_rgb(self, key: str, default: str = "#ffffff") -> tuple[float, float, float]:
        hex_str = self.get_color(key, default).lstrip('#')
        if len(hex_str) != 6:
            return (1.0, 1.0, 1.0)
        return (
            int(hex_str[0:2], 16) / 255.0,
            int(hex_str[2:4], 16) / 255.0,
            int(hex_str[4:6], 16) / 255.0
        )

# Global singleton
cfg = Config()
