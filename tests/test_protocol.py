"""Unit tests for protocol packet encoding, config persistence, and color math."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config_store import AppConfig, load_config, save_config
from protocol import (
    EFFECT_CATEGORIES,
    build_brightness,
    build_direction,
    build_effect,
    build_hs_color,
    build_length,
    build_mic_eq,
    build_mic_power,
    build_mic_sensitivity,
    build_power,
    build_rgb_color,
    build_speed,
    build_time_sync,
    build_timer,
    build_white,
    get_effects_for_category,
    hs_to_rgb,
    parse_raw_hex,
    rgb_to_hs,
)


def test_power_commands() -> None:
    assert build_power(True) == bytes([0xBC, 0x01, 0x01, 0x01, 0x55])
    assert build_power(False) == bytes([0xBC, 0x01, 0x01, 0x00, 0x55])


def test_length_command_clamping() -> None:
    assert build_length(8) == bytes([0xBC, 0x03, 0x02, 0x00, 0x08, 0x55])
    assert build_length(2) == bytes([0xBC, 0x03, 0x02, 0x00, 0x08, 0x55])
    assert build_length(300) == bytes([0xBC, 0x03, 0x02, 0x01, 0x2C, 0x55])
    assert build_length(999) == bytes([0xBC, 0x03, 0x02, 0x01, 0x2C, 0x55])


def test_color_commands() -> None:
    assert build_hs_color(0, 100) == bytes([0xBC, 0x04, 0x06, 0x00, 0x00, 0x03, 0xE8, 0x00, 0x00, 0x55])
    assert build_hs_color(240, 100) == bytes([0xBC, 0x04, 0x06, 0x00, 0xF0, 0x03, 0xE8, 0x00, 0x00, 0x55])
    assert build_rgb_color(0, 255, 0) == bytes([0xBC, 0x04, 0x06, 0x00, 0x78, 0x03, 0xE8, 0x00, 0x00, 0x55])
    assert build_rgb_color(255, 255, 255) == bytes([0xBC, 0x04, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x55])


def test_hs_rgb_roundtrip() -> None:
    for hue in (0, 60, 120, 180, 240, 300):
        rgb = hs_to_rgb(hue, 100.0)
        h_out, s_out = rgb_to_hs(*rgb)
        assert h_out == hue
        assert round(s_out) == 100


def test_brightness_modes() -> None:
    assert build_brightness(100, scale_1000=True) == bytes([0xBC, 0x05, 0x06, 0x03, 0xE8, 0x00, 0x00, 0x00, 0x00, 0x55])
    assert build_brightness(1, scale_1000=True) == bytes([0xBC, 0x05, 0x06, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x55])
    assert build_brightness(100, scale_1000=False) == bytes([0xBC, 0x05, 0x06, 0x00, 0x64, 0x00, 0x00, 0x00, 0x00, 0x55])
    assert build_brightness(1, scale_1000=False) == bytes([0xBC, 0x05, 0x06, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x55])


def test_effects_direction_speed() -> None:
    assert build_effect(1) == bytes([0xBC, 0x06, 0x02, 0x00, 0x01, 0x55])
    assert build_effect(43) == bytes([0xBC, 0x06, 0x02, 0x00, 0x2B, 0x55])
    assert build_direction(True) == bytes([0xBC, 0x07, 0x01, 0x01, 0x55])
    assert build_direction(False) == bytes([0xBC, 0x07, 0x01, 0x00, 0x55])
    assert build_speed(50) == bytes([0xBC, 0x08, 0x01, 0x32, 0x55])
    assert build_white(0) == bytes([0xBC, 0x13, 0x02, 0x00, 0x00, 0x55])


def test_mic_and_schedule_commands() -> None:
    assert build_mic_power(True) == bytes([0xBC, 0x0F, 0x01, 0x01, 0x55])
    assert build_mic_eq(3) == bytes([0xBC, 0x11, 0x01, 0x03, 0x55])
    assert build_mic_sensitivity(75, use_alt_cmd=False) == bytes([0xBC, 0x12, 0x01, 0x4B, 0x55])
    assert build_mic_sensitivity(75, use_alt_cmd=True) == bytes([0xBC, 0x10, 0x01, 0x4B, 0x55])

    dt = datetime(2026, 11, 30, 21, 15, 40)
    # weekday_plus_one rolls Nov 30 cleanly into Dec 1 instead of invalid Nov 31
    assert build_time_sync(dt, weekday_plus_one=True) == bytes(
        [0xBC, 0x0B, 0x07, 0x07, 0xEA, 12, 1, 21, 15, 40, 0x55]
    )

    weekdays = [True, False, False, False, False, False, True]  # Mon + Sun -> 0b1000001 = 65
    assert build_timer(power_on=False, enable=True, weekdays=weekdays, hour=23, minute=30) == bytes(
        [0xBC, 0x0D, 0x06, 0x01, 0x00, 0x01, 65, 23, 30, 0x55]
    )
    assert build_timer(power_on=True, enable=False, weekdays=weekdays, hour=7, minute=0) == bytes(
        [0xBC, 0x0D, 0x06, 0x01, 0x01, 0x00, 0x80 | 65, 7, 0, 0x55]
    )


def test_raw_hex_and_effects_catalog() -> None:
    assert parse_raw_hex("BC 01 01 01 55") == bytes([0xBC, 0x01, 0x01, 0x01, 0x55])
    assert parse_raw_hex("0xBC,0x01,0x01,0x00,0x55") == bytes([0xBC, 0x01, 0x01, 0x00, 0x55])
    assert parse_raw_hex("bc01010155") == bytes([0xBC, 0x01, 0x01, 0x01, 0x55])

    for cat in EFFECT_CATEGORIES:
        items = get_effects_for_category(cat)
        assert len(items) > 0
    assert len(get_effects_for_category("Все (1–117)")) == 117


def test_config_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg = AppConfig(
        theme="dark",
        last_mac="AA:BB:CC:DD:EE:FF",
        last_name="GATT--DEMO",
        led_count=120,
        brightness=77,
    )
    save_config(cfg, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded.theme == "dark"
    assert loaded.last_mac == "AA:BB:CC:DD:EE:FF"
    assert loaded.last_name == "GATT--DEMO"
    assert loaded.led_count == 120
    assert loaded.brightness == 77
