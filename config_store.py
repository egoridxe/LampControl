"""Persistent JSON configuration storage for LampControl (supports PyInstaller .exe)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from protocol import DEFAULT_PRESET_COLORS


def default_config_path() -> Path:
    """Return persistent config path (AppData when frozen as .exe, local folder in dev)."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "LampControl"
        base.mkdir(parents=True, exist_ok=True)
        return base / "config.json"
    return Path(__file__).resolve().parent / "config.json"


CONFIG_PATH = default_config_path()


def resource_path(relative_path: str) -> Path:
    """Resolve bundled asset path in both dev mode and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


@dataclass
class AppConfig:
    """Saved user preferences and last lamp state."""

    theme: str = "light"  # "light" | "dark"
    last_mac: str = ""
    last_name: str = ""
    auto_connect: bool = True
    auto_power_on: bool = True
    led_count: int = 60
    hue: float = 217.0
    saturation: float = 89.0
    brightness: int = 100
    speed: int = 55
    direction_forward: bool = True
    reverse_direction_polarity: bool = False
    brightness_scale_1000: bool = True
    mic_alt_cmd: bool = False
    last_effect: int = 1
    presets: list[str] = field(default_factory=lambda: list(DEFAULT_PRESET_COLORS))
    timer_hour: int = 23
    timer_minute: int = 0
    timer_power_on: bool = False
    timer_weekdays: list[bool] = field(default_factory=lambda: [True] * 7)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Load config from disk, returning defaults on missing or invalid JSON."""
    if not path.exists():
        return AppConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg = AppConfig()
        for key, value in raw.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        if cfg.theme not in ("light", "dark"):
            cfg.theme = "light"
        if len(cfg.presets) < 6:
            cfg.presets = list(DEFAULT_PRESET_COLORS)
        if len(cfg.timer_weekdays) != 7:
            cfg.timer_weekdays = [True] * 7
        return cfg
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Path = CONFIG_PATH) -> None:
    """Persist config to JSON, creating parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
