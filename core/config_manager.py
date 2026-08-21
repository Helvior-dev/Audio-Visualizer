"""
Configuration manager for Audio Visualizer.
Stores application configuration, geometry, themes, and states in:
%APPDATA%\\Logovo-Dushnil\\Audio-Visualizer\\config.json
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any

# Primary configuration directory in user's AppData/Logovo-Dushnil/Audio-Visualizer
appdata = os.getenv("APPDATA")
if appdata:
    CONFIG_DIR = Path(appdata) / "Logovo-Dushnil" / "Audio-Visualizer"
else:
    CONFIG_DIR = Path.home() / "AppData" / "Roaming" / "Logovo-Dushnil" / "Audio-Visualizer"

CONFIG_PATH = CONFIG_DIR / "config.json"
LOCAL_LEGACY_CONFIG = Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class AppConfig:
    audio_source_kind: str = "loopback"
    audio_source_device_index: int | None = None
    audio_source_name: str = "Default system audio"
    
    fps_limit: int = 60
    always_on_top: bool = False
    window_opacity: float = 1.0
    
    # Active modules (whether each widget is visible/running)
    active_modules: Dict[str, bool] = field(default_factory=lambda: {
        "loudness": True,
        "waveform": True,
        "oscilloscope": True,
        "spectrum": True,
        "spectrogram": True,
        "vectorscope": True
    })
    
    # Layout mode
    layout_mode: str = "docked_grid"
    
    # Docked vs floating state for each module
    floating_modules: Dict[str, bool] = field(default_factory=lambda: {
        "loudness": False,
        "waveform": False,
        "oscilloscope": False,
        "spectrum": False,
        "spectrogram": False,
        "vectorscope": False
    })
    
    # Window geometries and positions
    window_geometry: Dict[str, Any] = field(default_factory=lambda: {
        "main": {"x": 100, "y": 100, "width": 1280, "height": 600},
        "loudness": {"x": 150, "y": 150, "width": 550, "height": 300},
        "waveform": {"x": 180, "y": 180, "width": 650, "height": 280},
        "oscilloscope": {"x": 200, "y": 200, "width": 650, "height": 320},
        "spectrum": {"x": 250, "y": 250, "width": 580, "height": 320},
        "spectrogram": {"x": 300, "y": 300, "width": 550, "height": 300},
        "vectorscope": {"x": 350, "y": 350, "width": 460, "height": 460}
    })
    
    # Theme & Visual Customization
    accent_color: str = "#58A6FF"  # Hex color for UI highlights and meter accents
    
    # Module-specific DSP and visualization tuning
    spectrum_smoothing: float = 0.65
    spectrum_peak_hold_sec: float = 0.12
    oscilloscope_samples: int = 2048
    vectorscope_points: int = 1024


def load_config() -> AppConfig:
    """Load configuration from %APPDATA%\\Logovo-Dushnil\\Audio-Visualizer\\config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Migrate legacy local config if AppData config doesn't exist yet
    if not CONFIG_PATH.exists() and LOCAL_LEGACY_CONFIG.exists():
        try:
            with open(LOCAL_LEGACY_CONFIG, "r", encoding="utf-8") as lf:
                legacy_data = json.load(lf)
            with open(CONFIG_PATH, "w", encoding="utf-8") as af:
                json.dump(legacy_data, af, indent=2, ensure_ascii=False)
        except Exception:
            pass

    if not CONFIG_PATH.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            config = AppConfig()
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            return config
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Atomically save configuration to %APPDATA%\\Logovo-Dushnil\\Audio-Visualizer\\config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    try:
        tmp_path = CONFIG_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp_path, CONFIG_PATH)
        except Exception:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if tmp_path.exists():
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error saving config: {e}")
