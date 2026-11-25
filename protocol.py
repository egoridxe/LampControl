"""Pure BLE protocol implementation for Findn / MR Star / SymphonyLight (GATT--DEMO) lamps."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

CMD_PREFIX: Final[int] = 0xBC
CMD_SUFFIX: Final[int] = 0x55

KNOWN_LOCAL_NAMES: Final[tuple[str, ...]] = (
    "GATT--DEMO",
    "GATT-DEMO",
    "MR STAR",
    "MR-STAR",
    "SYMPHONY",
    "FINDN",
)

SERVICE_UUIDS: Final[tuple[str, ...]] = (
    "0000fff0-0000-1000-8000-00805f9b34fb",
    "00002022-0000-1000-8000-00805f9b34fb",
)

WRITE_CHAR_UUID: Final[str] = "0000fff3-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID: Final[str] = "0000fff4-0000-1000-8000-00805f9b34fb"

CMD_POWER: Final[int] = 0x01
CMD_LENGTH: Final[int] = 0x03
CMD_COLOR: Final[int] = 0x04
CMD_BRIGHTNESS: Final[int] = 0x05
CMD_EFFECT: Final[int] = 0x06
CMD_DIRECTION: Final[int] = 0x07
CMD_SPEED: Final[int] = 0x08
CMD_TIME_SYNC: Final[int] = 0x0B
CMD_TIMER: Final[int] = 0x0D
CMD_MIC_POWER: Final[int] = 0x0F
CMD_MIC_SENS_ALT: Final[int] = 0x10
CMD_MIC_EQ: Final[int] = 0x11
CMD_MIC_SENS: Final[int] = 0x12
CMD_WHITE: Final[int] = 0x13

DEFAULT_PRESET_COLORS: Final[list[str]] = [
    "#FF00FF",
    "#FF0000",
    "#00FFFF",
    "#D500FF",
    "#FFFF00",
    "#FF008C",
]

CLASSIC_COLORS: Final[list[tuple[str, str]]] = [
    ("Красный", "#FF0000"),
    ("Жёлтый", "#FFFF00"),
    ("Зелёный", "#00FF00"),
    ("Голубой", "#00FFFF"),
    ("Синий", "#0000FF"),
    ("Пурпурный", "#FF00FF"),
    ("Белый", "#FFFFFF"),
]


@dataclass(frozen=True)
class EffectItem:
    """Single built-in lamp animation mode."""

    index: int
    name: str
    ru_name: str
    category: str


EFFECTS: Final[list[EffectItem]] = [
    # Базовый
    EffectItem(1, "Automatic loop", "Автоматический цикл", "Базовый"),
    EffectItem(2, "Symphony", "Симфония", "Базовый"),
    EffectItem(3, "Colorful energy", "Разноцветная энергия", "Базовый"),
    EffectItem(4, "Colorful jumps", "Разноцветные прыжки", "Базовый"),
    EffectItem(5, "RGB jumps", "Прыжки RGB", "Базовый"),
    EffectItem(6, "YBP jumps", "Прыжки Ж-С-Ф", "Базовый"),
    EffectItem(7, "7 colors strobe", "Стробоскоп 7 цветов", "Базовый"),
    EffectItem(8, "RGB strobe", "Стробоскоп RGB", "Базовый"),
    EffectItem(9, "YPB strobe", "Стробоскоп Ж-Ф-С", "Базовый"),
    EffectItem(10, "7 colors gradient", "Градиент 7 цветов", "Базовый"),
    EffectItem(11, "Red-yellow gradient", "Градиент К-Ж", "Базовый"),
    EffectItem(12, "Red-purple gradient", "Градиент К-Ф", "Базовый"),
    EffectItem(13, "Green-cyan gradient", "Градиент З-Г", "Базовый"),
    EffectItem(14, "Green-yellow gradient", "Градиент З-Ж", "Базовый"),
    EffectItem(15, "Blue-purple gradient", "Градиент С-Ф", "Базовый"),
    EffectItem(16, "Red horse racing", "Красный бегущий огонь", "Базовый"),
    EffectItem(17, "Green horse racing", "Зелёный бегущий огонь", "Базовый"),
    EffectItem(18, "Blue horse racing", "Синий бегущий огонь", "Базовый"),
    EffectItem(19, "Yellow horse racing", "Жёлтый бегущий огонь", "Базовый"),
    EffectItem(20, "Cyan horse racing", "Голубой бегущий огонь", "Базовый"),
    EffectItem(21, "Purple horse racing", "Фиолетовый бегущий огонь", "Базовый"),
    EffectItem(22, "White horse racing", "Белый бегущий огонь", "Базовый"),
    EffectItem(23, "Colorful chasing", "Разноцветная погоня", "Базовый"),
    EffectItem(24, "RGB chasing", "Погоня RGB", "Базовый"),
    EffectItem(25, "YCP chasing", "Погоня Ж-Г-Ф", "Базовый"),
    EffectItem(26, "Colorful fluttering", "Разноцветное мерцание", "Базовый"),
    EffectItem(27, "RGB fluttering", "Мерцание RGB", "Базовый"),
    EffectItem(28, "YCP fluttering", "Мерцание Ж-Г-Ф", "Базовый"),
    EffectItem(29, "Colorful brushing", "Разноцветная кисть", "Базовый"),
    EffectItem(30, "RGB color brushing", "Кисть RGB", "Базовый"),
    EffectItem(31, "YCP color brushing", "Кисть Ж-Г-Ф", "Базовый"),
    EffectItem(32, "Colorful brush pull", "Волна кистью", "Базовый"),
    # Открытие & Закрытие
    EffectItem(35, "7 colors open-close", "7 цветов: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(36, "RGB open-close", "RGB: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(37, "YCP open-close", "Ж-Г-Ф: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(38, "Red open-close", "Красный: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(39, "Green open-close", "Зелёный: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(40, "Blue open-close", "Синий: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(41, "Yellow open-close", "Жёлтый: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(42, "Cyan open-close", "Голубой: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(43, "Purple open-close", "Фиолетовый: открытие и закрытие", "Открытие и закрытие"),
    EffectItem(44, "White open-close", "Белый: открытие и закрытие", "Открытие и закрытие"),
    # Переход
    EffectItem(45, "7 colors transition", "7 цветов: свет-тьма", "Переход"),
    EffectItem(46, "BRG transition", "С-К-З: свет-тьма", "Переход"),
    EffectItem(47, "VGY transition", "Ф-З-Ж: свет-тьма", "Переход"),
    EffectItem(48, "6 colors transition red", "6 цветов (красный старт)", "Переход"),
    EffectItem(49, "6 colors transition green", "6 цветов (зелёный старт)", "Переход"),
    EffectItem(50, "6 colors transition blue", "6 цветов (синий старт)", "Переход"),
    EffectItem(51, "6 colors transition cyan", "6 цветов (голубой старт)", "Переход"),
    EffectItem(52, "6 colors transition yellow", "6 цветов (жёлтый старт)", "Переход"),
    EffectItem(53, "6 colors transition purple", "6 цветов (фиол. старт)", "Переход"),
    EffectItem(54, "6 colors transition white", "6 цветов (белый старт)", "Переход"),
    # Бегущая вода
    EffectItem(55, "7 colors flowing water", "7 цветов: бегущая вода", "Бегущая вода"),
    EffectItem(56, "BGR running water", "С-З-К: бегущая вода", "Бегущая вода"),
    EffectItem(57, "PGY running water", "Ф-З-Ж: бегущая вода", "Бегущая вода"),
    EffectItem(58, "RG running water", "К-З: бегущая вода", "Бегущая вода"),
    EffectItem(59, "GB running water", "З-С: бегущая вода", "Бегущая вода"),
    EffectItem(60, "YB running water", "Ж-С: бегущая вода", "Бегущая вода"),
    EffectItem(61, "YC running water", "Ж-Г: бегущая вода", "Бегущая вода"),
    EffectItem(62, "BP running water", "С-Ф: бегущая вода", "Бегущая вода"),
    # Шлейф
    EffectItem(76, "7 colors tailing", "7 цветов: шлейф", "Шлейф"),
    EffectItem(77, "Red tailing", "Красный шлейф", "Шлейф"),
    EffectItem(78, "Green tailing", "Зелёный шлейф", "Шлейф"),
    EffectItem(79, "Blue tailing", "Синий шлейф", "Шлейф"),
    EffectItem(80, "Yellow tailing", "Жёлтый шлейф", "Шлейф"),
    EffectItem(81, "Cyan tailing", "Голубой шлейф", "Шлейф"),
    EffectItem(82, "Purple tailing", "Фиолетовый шлейф", "Шлейф"),
    EffectItem(83, "White tailing", "Белый шлейф", "Шлейф"),
    # Бег
    EffectItem(84, "Red running", "Красный бег", "Бег"),
    EffectItem(85, "Green running", "Зелёный бег", "Бег"),
    EffectItem(86, "Blue running", "Синий бег", "Бег"),
    EffectItem(87, "Yellow running", "Жёлтый бег", "Бег"),
    EffectItem(88, "Cyan running", "Голубой бег", "Бег"),
    EffectItem(89, "Purple running", "Фиолетовый бег", "Бег"),
    EffectItem(90, "White running", "Белый бег", "Бег"),
    EffectItem(91, "7 colors running", "7 цветов: бег", "Бег"),
    EffectItem(92, "BGR running", "С-З-К: бег", "Бег"),
    EffectItem(93, "PCY running", "Ф-Г-Ж: бег", "Бег"),
    EffectItem(94, "BPCY running", "С-Ф-Г-Ж: бег", "Бег"),
    EffectItem(95, "BGCY running", "С-З-Г-Ж: бег", "Бег"),
]

EFFECT_CATEGORIES: Final[list[str]] = [
    "Базовый",
    "Открытие и закрытие",
    "Переход",
    "Бегущая вода",
    "Шлейф",
    "Бег",
    "Все (1–117)",
]


def split_uint16(value: int) -> tuple[int, int]:
    """Split a 16-bit unsigned integer into (high_byte, low_byte)."""
    clamped = max(0, min(0xFFFF, int(value)))
    return (clamped >> 8) & 0xFF, clamped & 0xFF


def build_frame(cmd: int, payload: list[int] | bytes) -> bytes:
    """Wrap command and payload into BC <cmd> <len> <payload...> 55 packet."""
    data = list(payload)
    if not data:
        raise ValueError("Command payload cannot be empty")
    return bytes([CMD_PREFIX, cmd & 0xFF, len(data), *(b & 0xFF for b in data), CMD_SUFFIX])


def build_power(is_on: bool) -> bytes:
    """Build power ON/OFF packet."""
    return build_frame(CMD_POWER, [0x01 if is_on else 0x00])


def build_length(led_count: int) -> bytes:
    """Build LED point/pixel count packet (8..300)."""
    hi, lo = split_uint16(max(8, min(300, int(led_count))))
    return build_frame(CMD_LENGTH, [hi, lo])


def rgb_to_hs(r: int, g: int, b: int) -> tuple[int, float]:
    """Convert RGB (0..255) to Hue (0..360) and Saturation (0..100%)."""
    h, s, _ = colorsys.rgb_to_hsv(
        max(0, min(255, r)) / 255.0,
        max(0, min(255, g)) / 255.0,
        max(0, min(255, b)) / 255.0,
    )
    return round(h * 360) % 360, s * 100.0


def hs_to_rgb(hue_deg: float, sat_pct: float, val_pct: float = 100.0) -> tuple[int, int, int]:
    """Convert Hue (0..360), Saturation (0..100), Value (0..100) to RGB (0..255)."""
    r, g, b = colorsys.hsv_to_rgb(
        (hue_deg % 360.0) / 360.0,
        max(0.0, min(100.0, sat_pct)) / 100.0,
        max(0.0, min(100.0, val_pct)) / 100.0,
    )
    return round(r * 255), round(g * 255), round(b * 255)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse #RRGGBB hex string to RGB tuple."""
    clean = hex_color.strip().lstrip("#")
    if len(clean) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Format RGB tuple as #RRGGBB."""
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def build_hs_color(hue_deg: float, sat_pct: float) -> bytes:
    """Build HSV color packet (hue 0..360, saturation 0..1000)."""
    hue = max(0, min(360, round(hue_deg)))
    sat = max(0, min(1000, round(sat_pct * 10.0)))
    h_hi, h_lo = split_uint16(hue)
    s_hi, s_lo = split_uint16(sat)
    return build_frame(CMD_COLOR, [h_hi, h_lo, s_hi, s_lo, 0x00, 0x00])


def build_rgb_color(r: int, g: int, b: int) -> bytes:
    """Convert RGB 0..255 to HS color command."""
    hue, sat = rgb_to_hs(r, g, b)
    return build_hs_color(hue, sat)


def build_brightness(percent: float, scale_1000: bool = True) -> bytes:
    """Build brightness packet (percent 1..100 mapped to 10..1000 or 3..100)."""
    pct = max(1.0, min(100.0, float(percent)))
    if scale_1000:
        val = max(10, min(1000, round(pct * 10.0)))
    else:
        val = max(3, min(100, round(pct)))
    hi, lo = split_uint16(val)
    return build_frame(CMD_BRIGHTNESS, [hi, lo, 0x00, 0x00, 0x00, 0x00])


def build_white(temp_value: int = 0) -> bytes:
    """Build dedicated white / color-temperature command (0x13)."""
    hi, lo = split_uint16(max(0, min(1000, int(temp_value))))
    return build_frame(CMD_WHITE, [hi, lo])


def build_effect(index: int) -> bytes:
    """Build animation mode command (index 1..117)."""
    idx = max(1, min(117, int(index)))
    hi, lo = split_uint16(idx)
    return build_frame(CMD_EFFECT, [hi, lo])


def build_direction(forward: bool) -> bytes:
    """Build effect direction command."""
    return build_frame(CMD_DIRECTION, [0x01 if forward else 0x00])


def build_speed(percent: int) -> bytes:
    """Build animation speed command (1..100)."""
    spd = max(1, min(100, round(percent)))
    return build_frame(CMD_SPEED, [spd])


def build_mic_power(is_on: bool) -> bytes:
    """Build built-in hardware microphone mode ON/OFF command."""
    return build_frame(CMD_MIC_POWER, [0x01 if is_on else 0x00])


def build_mic_eq(eq_index: int) -> bytes:
    """Build built-in hardware microphone EQ index (1..4)."""
    return build_frame(CMD_MIC_EQ, [max(1, min(4, int(eq_index)))])


def build_mic_sensitivity(percent: int, use_alt_cmd: bool = False) -> bytes:
    """Build built-in microphone sensitivity command (1..100)."""
    cmd = CMD_MIC_SENS_ALT if use_alt_cmd else CMD_MIC_SENS
    return build_frame(cmd, [max(1, min(100, round(percent)))])


def build_time_sync(dt: datetime | None = None, weekday_plus_one: bool = True) -> bytes:
    """Build clock synchronization packet.

    weekday_plus_one adds 1 day because Findn firmware computes weekday off by -1.
    """
    now = dt or datetime.now()
    target = now + timedelta(days=1) if weekday_plus_one else now
    y_hi, y_lo = split_uint16(target.year)
    return build_frame(
        CMD_TIME_SYNC,
        [y_hi, y_lo, target.month, target.day, target.hour, target.minute, target.second],
    )


def build_timer(
    power_on: bool,
    enable: bool,
    weekdays: list[bool],
    hour: int,
    minute: int,
) -> bytes:
    """Build hardware schedule timer packet.

    weekdays is a 7-element boolean list starting Monday (index 0) to Sunday (index 6).
    """
    mask = 0
    for idx, active in enumerate(weekdays[:7]):
        if active:
            mask |= 1 << idx
    flag = 0x00 if enable else 0x80
    return build_frame(
        CMD_TIMER,
        [
            0x01,
            0x01 if power_on else 0x00,
            0x01 if enable else 0x00,
            flag | mask,
            max(0, min(23, int(hour))),
            max(0, min(59, int(minute))),
        ],
    )


def parse_raw_hex(hex_str: str) -> bytes:
    """Parse user-entered hex string like 'BC 01 01 01 55' or 'bc01010155' into bytes."""
    cleaned = hex_str.replace(",", " ").replace("0x", "").replace("0X", "").strip()
    if not cleaned:
        raise ValueError("Пустая hex-строка")
    tokens = cleaned.split()
    if len(tokens) == 1 and len(tokens[0]) > 2:
        return bytes.fromhex(tokens[0])
    return bytes(int(tok, 16) for tok in tokens)


def get_effects_for_category(category: str) -> list[EffectItem]:
    """Return effects matching a UI category, or full 1..117 catalog."""
    if category == "Все (1–117)":
        by_idx = {item.index: item for item in EFFECTS}
        result: list[EffectItem] = []
        for idx in range(1, 118):
            if idx in by_idx:
                result.append(by_idx[idx])
            else:
                result.append(EffectItem(idx, f"Mode {idx}", f"Режим #{idx}", "Другие"))
        return result
    return [item for item in EFFECTS if item.category == category]
