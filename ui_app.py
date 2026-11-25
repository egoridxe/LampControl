"""Minimalist Google Material 3 desktop UI with Light/Dark themes for BLE lamps."""

from __future__ import annotations

from collections import deque
import ctypes
import sys
import time
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from audio_sync import AudioDeviceOption, AudioSyncEngine, list_audio_devices
from ble_manager import BLEManager, DiscoveredLamp
from color_wheel import ColorWheelCanvas
from config_store import AppConfig, load_config, resource_path, save_config
from protocol import (
    CLASSIC_COLORS,
    EFFECT_CATEGORIES,
    EffectItem,
    build_brightness,
    build_direction,
    build_effect,
    build_hs_color,
    build_length,
    build_mic_eq,
    build_mic_power,
    build_mic_sensitivity,
    build_power,
    build_speed,
    build_time_sync,
    build_timer,
    get_effects_for_category,
    hex_to_rgb,
    hs_to_rgb,
    parse_raw_hex,
    rgb_to_hex,
    rgb_to_hs,
)
from screen_sync import ScreenSyncEngine

# Google Material Design 3 dual-mode palette: (Light, Dark)
SURFACE = ("#F8F9FA", "#131314")
RAIL_BG = ("#F1F3F4", "#1B1C1E")
CARD_BG = ("#FFFFFF", "#1E1F20")
CARD_SUB = ("#F1F3F4", "#282A2C")
HOVER_SUB = ("#E8EAED", "#33363A")
BORDER = ("#E0E3EB", "#2F3136")
TEXT_PRIMARY = ("#202124", "#E3E3E3")
TEXT_SECONDARY = ("#5F6368", "#9AA0A6")
PRIMARY = ("#1A73E8", "#8AB4F8")
PRIMARY_HOVER = ("#1557B0", "#AECBFA")
ON_PRIMARY = ("#FFFFFF", "#062E6F")
TONAL_BG = ("#D2E3FC", "#004A77")
TONAL_HOVER = ("#C2D7F8", "#005C94")
TONAL_TEXT = ("#174EA6", "#C2E7FF")
POWER_ON_BG = ("#E6F4EA", "#0F5223")
POWER_ON_HOVER = ("#CEEAD6", "#16692E")
POWER_ON_TEXT = ("#137333", "#6DD58C")
DANGER_BG = ("#FCE8E6", "#601410")
DANGER_HOVER = ("#FAD2CF", "#7A1B16")
DANGER_TEXT = ("#C5221F", "#F2B8B5")

FONT_FAMILY = "Segoe UI"


def _contrast_fg(hex_color: str) -> str:
    r, g, b = hex_to_rgb(hex_color)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#202124" if luminance > 155 else "#FFFFFF"


def _set_windows_titlebar_dark(window: tk.Misc, dark: bool) -> None:
    """Sync native Windows 10/11 title bar color with Light/Dark theme."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def _apply_window_icon(window: tk.Misc) -> None:
    """Apply LampControl .ico to window titlebar & taskbar safely."""
    ico = resource_path("assets/lamp.ico")
    if ico.exists():
        try:
            window.iconbitmap(default=str(ico))
        except Exception:
            pass


class SettingsWindow(ctk.CTkToplevel):
    """Material 3 Settings, compatibility switches, and live BLE console."""

    def __init__(self, master: LampControlApp) -> None:
        super().__init__(master)
        self.app = master
        self.title("Настройки и диагностика BLE")
        self.geometry("680x580")
        self.minsize(600, 480)
        self.configure(fg_color=SURFACE)
        self.transient(master)
        self.grab_set()
        self.after(20, self._sync_native_chrome)

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Compatibility card
        opts_card = ctk.CTkFrame(
            container, fg_color=CARD_BG, corner_radius=20, border_width=1, border_color=BORDER
        )
        opts_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            opts_card,
            text="Поведение и совместимость прошивки",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(16, 10))

        self.var_autoconnect = ctk.BooleanVar(value=self.app.cfg.auto_connect)
        self.var_autopower = ctk.BooleanVar(value=self.app.cfg.auto_power_on)
        self.var_bri1000 = ctk.BooleanVar(value=self.app.cfg.brightness_scale_1000)
        self.var_rev_pol = ctk.BooleanVar(value=self.app.cfg.reverse_direction_polarity)
        self.var_alt_mic = ctk.BooleanVar(value=self.app.cfg.mic_alt_cmd)

        switches = [
            (self.var_autoconnect, "Автоподключение к последней лампе при запуске"),
            (self.var_autopower, "Автоматически включать лампу при выборе цвета или режима"),
            (self.var_bri1000, "Шкала яркости 10–1000 (выключите для старых прошив. 3–100)"),
            (self.var_rev_pol, "Инвертировать полярность переключателя направления P"),
            (self.var_alt_mic, "Альтернативная команда чувствительности микрофона (0x10)"),
        ]
        for var, label in switches:
            ctk.CTkSwitch(
                opts_card,
                text=label,
                variable=var,
                command=self._apply_flags,
                progress_color=PRIMARY,
                button_color=("#FFFFFF", "#E3E3E3"),
                fg_color=BORDER,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            ).pack(anchor="w", padx=18, pady=5)

        ctk.CTkFrame(opts_card, height=10, fg_color="transparent").pack()

        # Raw Hex card
        raw_card = ctk.CTkFrame(
            container, fg_color=CARD_BG, corner_radius=20, border_width=1, border_color=BORDER
        )
        raw_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            raw_card,
            text="Отправить RAW команду (Hex, формат BC <cmd> <len> ... 55)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(14, 8))

        raw_row = ctk.CTkFrame(raw_card, fg_color="transparent")
        raw_row.pack(fill="x", padx=18, pady=(0, 14))

        self.raw_entry = ctk.CTkEntry(
            raw_row,
            placeholder_text="BC 01 01 01 55",
            height=36,
            corner_radius=18,
            fg_color=CARD_SUB,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.raw_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.raw_entry.insert(0, "BC 01 01 01 55")

        ctk.CTkButton(
            raw_row,
            text="Отправить",
            width=112,
            height=36,
            corner_radius=18,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._send_raw,
        ).pack(side="right")

        # BLE Log card
        log_card = ctk.CTkFrame(
            container, fg_color=CARD_BG, corner_radius=20, border_width=1, border_color=BORDER
        )
        log_card.pack(fill="both", expand=True)

        log_head = ctk.CTkFrame(log_card, fg_color="transparent")
        log_head.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            log_head,
            text="Журнал BLE",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkButton(
            log_head,
            text="Очистить",
            width=86,
            height=28,
            corner_radius=14,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._clear_log,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_card,
            corner_radius=14,
            fg_color=CARD_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=11),
            activate_scrollbars=True,
        )
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.refresh_log()

    def _sync_native_chrome(self) -> None:
        if not self.winfo_exists():
            return
        _apply_window_icon(self)
        _set_windows_titlebar_dark(self, self.app.cfg.theme == "dark")

    def _apply_flags(self) -> None:
        self.app.cfg.auto_connect = self.var_autoconnect.get()
        self.app.cfg.auto_power_on = self.var_autopower.get()
        self.app.cfg.brightness_scale_1000 = self.var_bri1000.get()
        self.app.cfg.reverse_direction_polarity = self.var_rev_pol.get()
        self.app.cfg.mic_alt_cmd = self.var_alt_mic.get()
        save_config(self.app.cfg)

    def _send_raw(self) -> None:
        try:
            payload = parse_raw_hex(self.raw_entry.get())
        except ValueError as exc:
            messagebox.showerror("Некорректный Hex", str(exc), parent=self)
            return
        if not self.app.ble.is_connected:
            messagebox.showwarning("Нет подключения", "Сначала подключитесь к лампе.", parent=self)
            return
        self.app.ble.send_immediate(payload)

    def _clear_log(self) -> None:
        self.app.log_lines.clear()
        self.refresh_log()

    def refresh_log(self) -> None:
        if not self.winfo_exists():
            return
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", "\n".join(self.app.log_lines))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


class LampControlApp(ctk.CTk):
    """Minimalist Google Material 3 Lamp Control desktop application."""

    def __init__(self) -> None:
        self.cfg: AppConfig = load_config()
        ctk.set_appearance_mode(self.cfg.theme)
        ctk.set_default_color_theme("blue")
        super().__init__()

        self._closing = False
        self._syncing_ui = False
        self._is_powered_on = False
        self._active_tab = "adjust"
        self._active_category = EFFECT_CATEGORIES[0]
        self._active_effect_idx = self.cfg.last_effect
        self._discovered: list[DiscoveredLamp] = []
        self._audio_devices: list[AudioDeviceOption] = []
        self._log_lines: deque[str] = deque(maxlen=250)
        self._settings_win: SettingsWindow | None = None
        self._sleep_deadline: float | None = None
        self._effect_buttons: dict[int, ctk.CTkButton] = {}
        self._preset_buttons: list[ctk.CTkButton] = []
        self._weekday_vars: list[ctk.BooleanVar] = []
        self._selected_preset_slot = 0
        self._logo_image: ctk.CTkImage | None = None

        self.title("Lamp Control")
        self.geometry("1040x720")
        self.minsize(940, 650)
        self.configure(fg_color=SURFACE)
        _apply_window_icon(self)

        self.ble = BLEManager(
            on_status=self._on_ble_status_bg,
            on_log=self._on_ble_log_bg,
        )
        self.audio_sync = AudioSyncEngine(
            send_color_cb=self._send_sync_color_bg,
            send_brightness_cb=self._send_sync_brightness_bg,
            on_level=self._on_audio_level_bg,
            on_error=self._on_sync_error_bg,
        )
        self.screen_sync = ScreenSyncEngine(
            send_color_cb=self._send_sync_color_bg,
            send_brightness_cb=self._send_sync_brightness_bg,
            on_preview=self._on_screen_preview_bg,
            on_error=self._on_sync_error_bg,
        )

        self._build_shell()
        self._build_pages()

        self.select_tab("adjust")
        self._refresh_audio_devices()
        self._update_sleep_label()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(30, lambda: _set_windows_titlebar_dark(self, self.cfg.theme == "dark"))
        self.after(280, self._startup_scan_and_connect)

    @property
    def log_lines(self) -> deque[str]:
        return self._log_lines

    # ------------------------------------------------------------------ Shell: Navigation Rail + Top Bar

    def _build_shell(self) -> None:
        # Left Google Navigation Rail
        self.rail = ctk.CTkFrame(self, width=216, corner_radius=0, fg_color=RAIL_BG)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)

        # Hairline vertical separator
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=BORDER).pack(side="left", fill="y")

        # Brand block
        brand = ctk.CTkFrame(self.rail, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(20, 22))

        logo_path = resource_path("assets/lamp_logo.png")
        if logo_path.exists():
            try:
                pil_logo = Image.open(logo_path)
                self._logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(34, 34))
                ctk.CTkLabel(brand, text="", image=self._logo_image).pack(side="left", padx=(0, 10))
            except Exception:
                pass

        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", fill="x")
        ctk.CTkLabel(
            brand_text,
            text="Lamp",
            font=ctk.CTkFont(family=FONT_FAMILY, size=19, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text="Bluetooth LED",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w")

        # Navigation destinations (Material 3 rounded full pills)
        tabs = [
            ("adjust", "●   Цвет"),
            ("mode", "✦   Режимы"),
            ("music", "♫   Музыка и Экран"),
            ("mic", "◎   Микрофон"),
            ("schedule", "◷   Расписание"),
        ]
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in tabs:
            btn = ctk.CTkButton(
                self.rail,
                text=label,
                anchor="w",
                height=44,
                corner_radius=22,
                fg_color="transparent",
                hover_color=HOVER_SUB,
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                command=lambda k=key: self.select_tab(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        # Bottom rail controls: Theme Switcher + Settings
        rail_bottom = ctk.CTkFrame(self.rail, fg_color="transparent")
        rail_bottom.pack(side="bottom", fill="x", padx=14, pady=(10, 16))

        ctk.CTkFrame(rail_bottom, height=1, fg_color=BORDER).pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            rail_bottom,
            text="Тема оформления",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TEXT_SECONDARY,
        ).pack(anchor="w", padx=4, pady=(0, 6))

        self.theme_seg = ctk.CTkSegmentedButton(
            rail_bottom,
            values=["Светлая", "Тёмная"],
            height=34,
            corner_radius=17,
            fg_color=CARD_BG,
            selected_color=TONAL_BG,
            selected_hover_color=TONAL_HOVER,
            unselected_color=CARD_BG,
            unselected_hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_theme_changed,
        )
        self.theme_seg.set("Тёмная" if self.cfg.theme == "dark" else "Светлая")
        self.theme_seg.pack(fill="x", pady=(0, 10))

        self.settings_btn = ctk.CTkButton(
            rail_bottom,
            text="⚙   Настройки и BLE",
            anchor="w",
            height=40,
            corner_radius=20,
            fg_color="transparent",
            hover_color=HOVER_SUB,
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            command=self._open_settings,
        )
        self.settings_btn.pack(fill="x")

        # Right main workspace
        main_col = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        main_col.pack(side="left", fill="both", expand=True)

        # Minimalist Top Bar
        topbar = ctk.CTkFrame(main_col, height=68, fg_color=SURFACE, corner_radius=0)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        top_inner = ctk.CTkFrame(topbar, fg_color="transparent")
        top_inner.pack(fill="both", expand=True, padx=22, pady=14)

        self.status_badge = ctk.CTkLabel(
            top_inner,
            text="●  Отключено",
            fg_color=CARD_SUB,
            text_color=TEXT_SECONDARY,
            corner_radius=16,
            padx=12,
            pady=6,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        )
        self.status_badge.pack(side="left", padx=(0, 10))

        self.device_var = ctk.StringVar(
            value=self._format_saved_device_label() if self.cfg.last_mac else "Нажмите «Поиск»..."
        )
        self.device_menu = ctk.CTkOptionMenu(
            top_inner,
            variable=self.device_var,
            values=[self.device_var.get()],
            width=210,
            height=36,
            dynamic_resizing=False,
            corner_radius=18,
            fg_color=CARD_BG,
            button_color=CARD_SUB,
            button_hover_color=HOVER_SUB,
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color=HOVER_SUB,
            dropdown_text_color=TEXT_PRIMARY,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.device_menu.pack(side="left", padx=(0, 8))

        self.scan_btn = ctk.CTkButton(
            top_inner,
            text="Поиск",
            width=76,
            height=36,
            corner_radius=18,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_scan_clicked,
        )
        self.scan_btn.pack(side="left", padx=(0, 6))

        self.connect_btn = ctk.CTkButton(
            top_inner,
            text="Подключить",
            width=112,
            height=36,
            corner_radius=18,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_connect_clicked,
        )
        self.connect_btn.pack(side="left", padx=(0, 10))

        self.var_show_all_ble = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            top_inner,
            text="Все BLE",
            variable=self.var_show_all_ble,
            width=72,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=5,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            border_color=BORDER,
            text_color=TEXT_SECONDARY,
            checkmark_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(side="left")

        self.power_btn = ctk.CTkButton(
            top_inner,
            text="⏻  Выкл",
            width=102,
            height=36,
            corner_radius=18,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self._on_power_toggle,
        )
        self.power_btn.pack(side="right")

        # Subtle horizontal divider under topbar
        ctk.CTkFrame(main_col, height=1, corner_radius=0, fg_color=BORDER).pack(fill="x")

        # Content container
        self.body_frame = ctk.CTkFrame(main_col, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=22, pady=18)

    def _build_pages(self) -> None:
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_adjust_page()
        self._build_mode_page()
        self._build_music_page()
        self._build_mic_page()
        self._build_schedule_page()

    # ------------------------------------------------------------------ Theme Switching

    def _card_surface_hex(self) -> str:
        return CARD_BG[1] if self.cfg.theme == "dark" else CARD_BG[0]

    def _border_hex(self) -> str:
        return BORDER[1] if self.cfg.theme == "dark" else BORDER[0]

    def _on_theme_changed(self, value: str) -> None:
        new_theme = "dark" if value == "Тёмная" else "light"
        if new_theme == self.cfg.theme:
            return
        self.cfg.theme = new_theme
        save_config(self.cfg)
        ctk.set_appearance_mode(new_theme)
        self.wheel.set_theme_colors(self._card_surface_hex(), self._border_hex())
        _set_windows_titlebar_dark(self, new_theme == "dark")
        if self._settings_win is not None and self._settings_win.winfo_exists():
            _set_windows_titlebar_dark(self._settings_win, new_theme == "dark")
        self._refresh_preset_borders()

    # ------------------------------------------------------------------ Page 1: Color

    def _build_adjust_page(self) -> None:
        page = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.pages["adjust"] = page

        page.grid_columnconfigure(0, weight=5)
        page.grid_columnconfigure(1, weight=6)
        page.grid_rowconfigure(0, weight=1)

        # Left card: Color wheel & quick whites
        left_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ctk.CTkLabel(
            left_card,
            text="Цветовая палитра",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 6))

        self.wheel = ColorWheelCanvas(
            left_card,
            size=266,
            bg_color=self._card_surface_hex(),
            ring_neutral=self._border_hex(),
            initial_hue=self.cfg.hue,
            initial_sat=self.cfg.saturation,
            on_change=self._on_wheel_color,
        )
        self.wheel.pack(pady=(6, 10))

        # Minimalist color readout pill
        readout = ctk.CTkFrame(left_card, fg_color=CARD_SUB, corner_radius=18)
        readout.pack(fill="x", padx=22, pady=(4, 14))

        self.swatch_box = ctk.CTkFrame(
            readout,
            width=26,
            height=26,
            corner_radius=13,
            fg_color="#1A73E8",
            border_width=1,
            border_color=BORDER,
        )
        self.swatch_box.pack(side="left", padx=(10, 10), pady=8)

        self.color_info_label = ctk.CTkLabel(
            readout,
            text="#1A73E8",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.color_info_label.pack(side="left", padx=(0, 10))

        # 3 clean Google white temperature pills
        white_row = ctk.CTkFrame(left_card, fg_color="transparent")
        white_row.pack(fill="x", padx=22, pady=(0, 20))
        for label, hex_val in [
            ("Тёплый", "#FFD194"),
            ("Нейтральный", "#FFF4E4"),
            ("Холодный", "#FFFFFF"),
        ]:
            ctk.CTkButton(
                white_row,
                text=label,
                width=70,
                height=34,
                corner_radius=17,
                fg_color=CARD_SUB,
                hover_color=HOVER_SUB,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                command=lambda h=hex_val: self._apply_preset_hex(h),
            ).pack(side="left", fill="x", expand=True, padx=3)

        # Right column stack
        right_col = ctk.CTkFrame(page, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # Brightness card
        bri_card = ctk.CTkFrame(
            right_col, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        bri_card.pack(fill="x", pady=(0, 12))

        bri_head = ctk.CTkFrame(bri_card, fg_color="transparent")
        bri_head.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            bri_head,
            text="Яркость",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.bri_val_label = ctk.CTkLabel(
            bri_head,
            text=f"{self.cfg.brightness}%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=PRIMARY,
        )
        self.bri_val_label.pack(side="right")

        bri_row = ctk.CTkFrame(bri_card, fg_color="transparent")
        bri_row.pack(fill="x", padx=18, pady=(2, 18))
        self.bri_slider_adjust = ctk.CTkSlider(
            bri_row,
            from_=1,
            to=100,
            number_of_steps=99,
            height=18,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_brightness_slider,
        )
        self.bri_slider_adjust.set(self.cfg.brightness)
        self.bri_slider_adjust.pack(fill="x", expand=True)

        # Unified Palette card (Presets + Classic)
        pal_card = ctk.CTkFrame(
            right_col, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        pal_card.pack(fill="x", pady=(0, 12))

        pre_head = ctk.CTkFrame(pal_card, fg_color="transparent")
        pre_head.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            pre_head,
            text="Сохранённые цвета",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(
            pre_head,
            text="ПКМ — сохранить текущий",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_SECONDARY,
        ).pack(side="right")

        pre_row = ctk.CTkFrame(pal_card, fg_color="transparent")
        pre_row.pack(fill="x", padx=16, pady=(0, 14))
        for idx, hex_col in enumerate(self.cfg.presets[:6]):
            btn = ctk.CTkButton(
                pre_row,
                text="",
                width=40,
                height=40,
                corner_radius=20,
                fg_color=hex_col,
                hover_color=hex_col,
                border_width=2,
                border_color=PRIMARY if idx == self._selected_preset_slot else BORDER,
                command=lambda i=idx: self._on_preset_click(i),
            )
            btn.pack(side="left", expand=True, padx=4)
            btn.bind("<Button-3>", lambda _e, i=idx: self._on_preset_save(i))
            self._preset_buttons.append(btn)

        ctk.CTkFrame(pal_card, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(
            pal_card,
            text="Базовая палитра",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=20, pady=(0, 8))

        cls_row = ctk.CTkFrame(pal_card, fg_color="transparent")
        cls_row.pack(fill="x", padx=16, pady=(0, 18))
        for _name, hex_col in CLASSIC_COLORS:
            ctk.CTkButton(
                cls_row,
                text="",
                width=36,
                height=36,
                corner_radius=18,
                fg_color=hex_col,
                hover_color=hex_col,
                border_width=1,
                border_color=BORDER,
                command=lambda h=hex_col: self._apply_preset_hex(h),
            ).pack(side="left", expand=True, padx=3)

        # LED points card
        pts_card = ctk.CTkFrame(
            right_col, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        pts_card.pack(fill="x")

        pts_head = ctk.CTkFrame(pts_card, fg_color="transparent")
        pts_head.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            pts_head,
            text="Настройка точек (светодиоды)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.pts_val_label = ctk.CTkLabel(
            pts_head,
            text=f"{self.cfg.led_count} шт.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=PRIMARY,
        )
        self.pts_val_label.pack(side="right")

        pts_row = ctk.CTkFrame(pts_card, fg_color="transparent")
        pts_row.pack(fill="x", padx=18, pady=(4, 18))
        self.pts_slider = ctk.CTkSlider(
            pts_row,
            from_=8,
            to=300,
            number_of_steps=292,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_pts_slider,
        )
        self.pts_slider.set(self.cfg.led_count)
        self.pts_slider.pack(side="left", fill="x", expand=True, padx=(0, 12))

        ctk.CTkButton(
            pts_row,
            text="Применить",
            width=102,
            height=34,
            corner_radius=17,
            fg_color=TONAL_BG,
            hover_color=TONAL_HOVER,
            text_color=TONAL_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._apply_led_count,
        ).pack(side="right")

        self._update_color_readout(self.cfg.hue, self.cfg.saturation)

    # ------------------------------------------------------------------ Page 2: Modes

    def _build_mode_page(self) -> None:
        page = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.pages["mode"] = page

        # Filter chips row
        chips_bar = ctk.CTkFrame(page, fg_color="transparent")
        chips_bar.pack(fill="x", pady=(0, 12))

        self.cat_buttons: dict[str, ctk.CTkButton] = {}
        short_labels = {
            "Базовый": "Базовый",
            "Открытие и закрытие": "Открытие",
            "Переход": "Переход",
            "Бегущая вода": "Вода",
            "Шлейф": "Шлейф",
            "Бег": "Бег",
            "Все (1–117)": "Все 1–117",
        }
        for cat in EFFECT_CATEGORIES:
            btn = ctk.CTkButton(
                chips_bar,
                text=short_labels.get(cat, cat),
                width=50,
                height=34,
                corner_radius=17,
                fg_color=CARD_BG,
                hover_color=HOVER_SUB,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                command=lambda c=cat: self._select_category(c),
            )
            btn.pack(side="left", expand=True, fill="x", padx=3)
            self.cat_buttons[cat] = btn

        # Effects list card
        list_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        list_card.pack(fill="both", expand=True, pady=(0, 12))

        list_head = ctk.CTkFrame(list_card, fg_color="transparent")
        list_head.pack(fill="x", padx=20, pady=(16, 10))

        ctk.CTkLabel(
            list_head,
            text="Анимации",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self.var_direction = ctk.BooleanVar(value=self.cfg.direction_forward)
        self.dir_switch = ctk.CTkSwitch(
            list_head,
            text="Направление P",
            variable=self.var_direction,
            progress_color=PRIMARY,
            button_color=("#FFFFFF", "#E3E3E3"),
            fg_color=BORDER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_direction_toggle,
        )
        self.dir_switch.pack(side="right")

        direct_row = ctk.CTkFrame(list_head, fg_color="transparent")
        direct_row.pack(side="right", padx=(0, 18))
        ctk.CTkLabel(
            direct_row,
            text="№ (1–117):",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        ).pack(side="left", padx=(0, 6))
        self.direct_mode_entry = ctk.CTkEntry(
            direct_row,
            width=58,
            height=30,
            corner_radius=15,
            fg_color=CARD_SUB,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            justify="center",
        )
        self.direct_mode_entry.insert(0, str(self.cfg.last_effect))
        self.direct_mode_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            direct_row,
            text="Пуск",
            width=62,
            height=30,
            corner_radius=15,
            fg_color=TONAL_BG,
            hover_color=TONAL_HOVER,
            text_color=TONAL_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._apply_direct_effect_num,
        ).pack(side="left")

        self.effects_scroll = ctk.CTkScrollableFrame(
            list_card,
            fg_color=CARD_SUB,
            corner_radius=16,
            scrollbar_button_color=BORDER,
        )
        self.effects_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Bottom controls: Speed & Brightness
        sliders_grid = ctk.CTkFrame(page, fg_color="transparent")
        sliders_grid.pack(fill="x")
        sliders_grid.grid_columnconfigure(0, weight=1)
        sliders_grid.grid_columnconfigure(1, weight=1)

        # Speed Card
        spd_card = ctk.CTkFrame(
            sliders_grid, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        spd_card.grid(row=0, column=0, sticky="ew", padx=(0, 7))

        spd_head = ctk.CTkFrame(spd_card, fg_color="transparent")
        spd_head.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(
            spd_head,
            text="Скорость",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.spd_val_label = ctk.CTkLabel(
            spd_head,
            text=f"{self.cfg.speed}%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PRIMARY,
        )
        self.spd_val_label.pack(side="right")

        spd_row = ctk.CTkFrame(spd_card, fg_color="transparent")
        spd_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            spd_row,
            text="−",
            width=30,
            height=30,
            corner_radius=15,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            command=lambda: self._nudge_speed(-5),
        ).pack(side="left", padx=(0, 8))
        self.spd_slider = ctk.CTkSlider(
            spd_row,
            from_=1,
            to=100,
            number_of_steps=99,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_speed_slider,
        )
        self.spd_slider.set(self.cfg.speed)
        self.spd_slider.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            spd_row,
            text="+",
            width=30,
            height=30,
            corner_radius=15,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            command=lambda: self._nudge_speed(5),
        ).pack(side="right", padx=(8, 0))

        # Brightness Card
        mbri_card = ctk.CTkFrame(
            sliders_grid, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        mbri_card.grid(row=0, column=1, sticky="ew", padx=(7, 0))

        mbri_head = ctk.CTkFrame(mbri_card, fg_color="transparent")
        mbri_head.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(
            mbri_head,
            text="Яркость",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.mbri_val_label = ctk.CTkLabel(
            mbri_head,
            text=f"{self.cfg.brightness}%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PRIMARY,
        )
        self.mbri_val_label.pack(side="right")

        mbri_row = ctk.CTkFrame(mbri_card, fg_color="transparent")
        mbri_row.pack(fill="x", padx=16, pady=(0, 14))
        self.bri_slider_mode = ctk.CTkSlider(
            mbri_row,
            from_=1,
            to=100,
            number_of_steps=99,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_brightness_slider,
        )
        self.bri_slider_mode.set(self.cfg.brightness)
        self.bri_slider_mode.pack(fill="x", expand=True)

        self._select_category(self._active_category)

    # ------------------------------------------------------------------ Page 3: Music & Screen

    def _build_music_page(self) -> None:
        page = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.pages["music"] = page

        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(0, weight=1)

        # Left: PC Audio Sync
        audio_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        audio_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ctk.CTkLabel(
            audio_card,
            text="Светомузыка с ПК",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 4))

        ctk.CTkLabel(
            audio_card,
            text="Захват системного звука (WASAPI Loopback) или микрофона компьютера.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_SECONDARY,
        ).pack(anchor="w", padx=22, pady=(0, 14))

        src_row = ctk.CTkFrame(audio_card, fg_color="transparent")
        src_row.pack(fill="x", padx=22, pady=(0, 14))
        self.audio_dev_var = ctk.StringVar(value="Загрузка...")
        self.audio_dev_menu = ctk.CTkOptionMenu(
            src_row,
            variable=self.audio_dev_var,
            values=["Загрузка..."],
            width=240,
            height=36,
            dynamic_resizing=False,
            corner_radius=18,
            fg_color=CARD_SUB,
            button_color=HOVER_SUB,
            button_hover_color=BORDER,
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color=HOVER_SUB,
            dropdown_text_color=TEXT_PRIMARY,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.audio_dev_menu.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            src_row,
            text="Обновить",
            width=92,
            height=36,
            corner_radius=18,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._refresh_audio_devices,
        ).pack(side="right")

        self.audio_mode_seg = ctk.CTkSegmentedButton(
            audio_card,
            values=["Энергия (Бас)", "Спектр", "Бит-строб"],
            height=36,
            corner_radius=18,
            fg_color=CARD_SUB,
            selected_color=TONAL_BG,
            selected_hover_color=TONAL_HOVER,
            unselected_color=CARD_SUB,
            unselected_hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_audio_mode_changed,
        )
        self.audio_mode_seg.set("Энергия (Бас)")
        self.audio_mode_seg.pack(fill="x", padx=22, pady=(0, 14))

        sens_head = ctk.CTkFrame(audio_card, fg_color="transparent")
        sens_head.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(
            sens_head,
            text="Чувствительность",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.audio_sens_label = ctk.CTkLabel(
            sens_head,
            text="1.0x",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=PRIMARY,
        )
        self.audio_sens_label.pack(side="right")

        self.audio_sens_slider = ctk.CTkSlider(
            audio_card,
            from_=0.3,
            to=3.0,
            number_of_steps=27,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_audio_sens,
        )
        self.audio_sens_slider.set(1.0)
        self.audio_sens_slider.pack(fill="x", padx=22, pady=(0, 16))

        # Google 4-color live spectrum bars
        meters = ctk.CTkFrame(audio_card, fg_color=CARD_SUB, corner_radius=16)
        meters.pack(fill="x", padx=22, pady=(0, 18))
        self.meter_bars: dict[str, ctk.CTkProgressBar] = {}
        for key, label, col in [
            ("level", "Громкость", "#4285F4"),
            ("bass", "Бас", "#EA4335"),
            ("mid", "Средние", "#FBBC04"),
            ("high", "Высокие", "#34A853"),
        ]:
            row = ctk.CTkFrame(meters, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=6)
            ctk.CTkLabel(
                row,
                text=label,
                width=80,
                anchor="w",
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            ).pack(side="left")
            bar = ctk.CTkProgressBar(
                row, progress_color=col, fg_color=CARD_BG, height=8, corner_radius=4
            )
            bar.set(0)
            bar.pack(side="left", fill="x", expand=True)
            self.meter_bars[key] = bar

        self.audio_toggle_btn = ctk.CTkButton(
            audio_card,
            text="Запустить светомузыку",
            height=44,
            corner_radius=22,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self._toggle_audio_sync,
        )
        self.audio_toggle_btn.pack(fill="x", padx=22, side="bottom", pady=(0, 20))

        # Right: Screen Ambilight
        screen_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        screen_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        ctk.CTkLabel(
            screen_card,
            text="Амбилайт экрана",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 4))

        ctk.CTkLabel(
            screen_card,
            text="Синхронизирует оттенок лампы с доминирующим цветом на мониторе.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_SECONDARY,
            wraplength=260,
            justify="left",
        ).pack(anchor="w", padx=22, pady=(0, 16))

        self.screen_preview = ctk.CTkFrame(
            screen_card,
            height=145,
            corner_radius=18,
            fg_color=CARD_SUB,
            border_width=1,
            border_color=BORDER,
        )
        self.screen_preview.pack(fill="x", padx=22, pady=(0, 16))
        self.screen_preview.pack_propagate(False)
        self.screen_preview_label = ctk.CTkLabel(
            self.screen_preview,
            text="Предпросмотр",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_SECONDARY,
        )
        self.screen_preview_label.place(relx=0.5, rely=0.5, anchor="center")

        sat_head = ctk.CTkFrame(screen_card, fg_color="transparent")
        sat_head.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(
            sat_head,
            text="Насыщенность",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.screen_sat_label = ctk.CTkLabel(
            sat_head,
            text="1.25x",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=PRIMARY,
        )
        self.screen_sat_label.pack(side="right")

        self.screen_sat_slider = ctk.CTkSlider(
            screen_card,
            from_=0.8,
            to=2.0,
            number_of_steps=12,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_SUB,
            command=self._on_screen_sat,
        )
        self.screen_sat_slider.set(1.25)
        self.screen_sat_slider.pack(fill="x", padx=22, pady=(0, 18))

        self.screen_toggle_btn = ctk.CTkButton(
            screen_card,
            text="Запустить Амбилайт",
            height=44,
            corner_radius=22,
            fg_color=TONAL_BG,
            hover_color=TONAL_HOVER,
            text_color=TONAL_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self._toggle_screen_sync,
        )
        self.screen_toggle_btn.pack(fill="x", padx=22, side="bottom", pady=(0, 20))

    # ------------------------------------------------------------------ Page 4: Hardware Mic

    def _build_mic_page(self) -> None:
        page = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.pages["mic"] = page

        card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        card.pack(fill="both", expand=True, padx=24, pady=6)

        ctk.CTkLabel(
            card,
            text="Встроенный микрофон лампы",
            font=ctk.CTkFont(family=FONT_FAMILY, size=17, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=24, pady=(22, 6))

        ctk.CTkLabel(
            card,
            text="Управляет датчиком звука внутри контроллера лампы (BC 0F / BC 11 / BC 12).\n"
            "Если ваша модель не имеет встроенного микрофона, выберите микрофон ПК во вкладке «Музыка и Экран».",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_SECONDARY,
            justify="left",
        ).pack(anchor="w", padx=24, pady=(0, 20))

        pwr_row = ctk.CTkFrame(card, fg_color=CARD_SUB, corner_radius=18)
        pwr_row.pack(fill="x", padx=24, pady=(0, 14))
        ctk.CTkLabel(
            pwr_row,
            text="Аппаратный режим микрофона",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=18, pady=16)

        ctk.CTkButton(
            pwr_row,
            text="Выключить",
            width=108,
            height=34,
            corner_radius=17,
            fg_color=CARD_BG,
            hover_color=DANGER_BG,
            text_color=TEXT_PRIMARY,
            border_width=1,
            border_color=BORDER,
            command=lambda: self._send_hw_mic_power(False),
        ).pack(side="right", padx=(6, 16))
        ctk.CTkButton(
            pwr_row,
            text="Включить",
            width=108,
            height=34,
            corner_radius=17,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=lambda: self._send_hw_mic_power(True),
        ).pack(side="right", padx=6)

        eq_card = ctk.CTkFrame(card, fg_color=CARD_SUB, corner_radius=18)
        eq_card.pack(fill="x", padx=24, pady=(0, 14))
        ctk.CTkLabel(
            eq_card,
            text="Режим эквалайзера",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(14, 10))

        eq_row = ctk.CTkFrame(eq_card, fg_color="transparent")
        eq_row.pack(fill="x", padx=16, pady=(0, 16))
        for idx, name in [(1, "Классика"), (2, "Мягкий"), (3, "Динамика"), (4, "Диско")]:
            ctk.CTkButton(
                eq_row,
                text=name,
                width=60,
                height=36,
                corner_radius=18,
                fg_color=CARD_BG,
                hover_color=TONAL_BG,
                text_color=TEXT_PRIMARY,
                border_width=1,
                border_color=BORDER,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                command=lambda n=idx: self._send_hw_mic_eq(n),
            ).pack(side="left", expand=True, fill="x", padx=4)

        sens_card = ctk.CTkFrame(card, fg_color=CARD_SUB, corner_radius=18)
        sens_card.pack(fill="x", padx=24, pady=(0, 20))
        sens_head = ctk.CTkFrame(sens_card, fg_color="transparent")
        sens_head.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(
            sens_head,
            text="Чувствительность датчика",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self.hw_mic_sens_label = ctk.CTkLabel(
            sens_head,
            text="60%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PRIMARY,
        )
        self.hw_mic_sens_label.pack(side="right")

        self.hw_mic_slider = ctk.CTkSlider(
            sens_card,
            from_=1,
            to=100,
            number_of_steps=99,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
            progress_color=PRIMARY,
            fg_color=CARD_BG,
            command=self._on_hw_mic_sens,
        )
        self.hw_mic_slider.set(60)
        self.hw_mic_slider.pack(fill="x", padx=18, pady=(4, 18))

    # ------------------------------------------------------------------ Page 5: Schedule

    def _build_schedule_page(self) -> None:
        page = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.pages["schedule"] = page

        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(0, weight=1)

        # Hardware Schedule Card
        hw_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        hw_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ctk.CTkLabel(
            hw_card,
            text="Встроенное расписание лампы",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 10))

        ctk.CTkButton(
            hw_card,
            text="Синхронизировать часы лампы с ПК",
            height=38,
            corner_radius=19,
            fg_color=CARD_SUB,
            hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._on_sync_clock,
        ).pack(fill="x", padx=22, pady=(0, 16))

        action_row = ctk.CTkFrame(hw_card, fg_color="transparent")
        action_row.pack(fill="x", padx=22, pady=(0, 14))
        ctk.CTkLabel(
            action_row,
            text="Действие",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 14))
        self.timer_action_seg = ctk.CTkSegmentedButton(
            action_row,
            values=["Включить", "Выключить"],
            height=34,
            corner_radius=17,
            fg_color=CARD_SUB,
            selected_color=TONAL_BG,
            selected_hover_color=TONAL_HOVER,
            unselected_color=CARD_SUB,
            unselected_hover_color=HOVER_SUB,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        )
        self.timer_action_seg.set("Включить" if self.cfg.timer_power_on else "Выключить")
        self.timer_action_seg.pack(side="left")

        time_row = ctk.CTkFrame(hw_card, fg_color="transparent")
        time_row.pack(fill="x", padx=22, pady=(0, 14))
        ctk.CTkLabel(
            time_row,
            text="Время (ЧЧ : ММ)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 14))
        self.timer_hour_entry = ctk.CTkEntry(
            time_row,
            width=58,
            height=36,
            corner_radius=12,
            fg_color=CARD_SUB,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            justify="center",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
        )
        self.timer_hour_entry.insert(0, f"{self.cfg.timer_hour:02d}")
        self.timer_hour_entry.pack(side="left")
        ctk.CTkLabel(
            time_row,
            text=":",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=6)
        self.timer_min_entry = ctk.CTkEntry(
            time_row,
            width=58,
            height=36,
            corner_radius=12,
            fg_color=CARD_SUB,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            justify="center",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
        )
        self.timer_min_entry.insert(0, f"{self.cfg.timer_minute:02d}")
        self.timer_min_entry.pack(side="left")

        ctk.CTkLabel(
            hw_card,
            text="Дни недели",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=TEXT_SECONDARY,
        ).pack(anchor="w", padx=22, pady=(4, 8))
        days_row = ctk.CTkFrame(hw_card, fg_color="transparent")
        days_row.pack(fill="x", padx=22, pady=(0, 18))
        for idx, day_name in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
            var = ctk.BooleanVar(value=self.cfg.timer_weekdays[idx])
            self._weekday_vars.append(var)
            ctk.CTkCheckBox(
                days_row,
                text=day_name,
                variable=var,
                width=48,
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=6,
                fg_color=PRIMARY,
                hover_color=PRIMARY_HOVER,
                border_color=BORDER,
                text_color=TEXT_PRIMARY,
                checkmark_color=ON_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            ).pack(side="left", expand=True)

        btn_row = ctk.CTkFrame(hw_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, side="bottom", pady=(0, 20))
        ctk.CTkButton(
            btn_row,
            text="Задать таймер",
            height=42,
            corner_radius=21,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=ON_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._send_hw_timer(True),
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            btn_row,
            text="Сбросить",
            height=42,
            corner_radius=21,
            fg_color=CARD_SUB,
            hover_color=DANGER_BG,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            command=lambda: self._send_hw_timer(False),
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        # PC Sleep Timer Card
        pc_card = ctk.CTkFrame(
            page, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER
        )
        pc_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        ctk.CTkLabel(
            pc_card,
            text="Таймер сна на ПК",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=22, pady=(20, 4))

        ctk.CTkLabel(
            pc_card,
            text="Выключит лампу автоматически по окончании отсчёта.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_SECONDARY,
            wraplength=260,
            justify="left",
        ).pack(anchor="w", padx=22, pady=(0, 14))

        self.sleep_status_label = ctk.CTkLabel(
            pc_card,
            text="Не активен",
            font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            text_color=PRIMARY,
        )
        self.sleep_status_label.pack(pady=(6, 16))

        quick_grid = ctk.CTkFrame(pc_card, fg_color="transparent")
        quick_grid.pack(fill="x", padx=22)
        for mins in (15, 30, 60, 120):
            ctk.CTkButton(
                quick_grid,
                text=f"Выкл через {mins} мин",
                height=38,
                corner_radius=19,
                fg_color=CARD_SUB,
                hover_color=TONAL_BG,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                command=lambda m=mins: self._start_sleep_timer(m),
            ).pack(fill="x", pady=4)

        ctk.CTkButton(
            pc_card,
            text="Отменить таймер",
            height=40,
            corner_radius=20,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER,
            hover_color=DANGER_BG,
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._cancel_sleep_timer,
        ).pack(fill="x", padx=22, side="bottom", pady=(0, 20))

    # ------------------------------------------------------------------ Navigation & Categories

    def select_tab(self, key: str) -> None:
        self._active_tab = key
        for name, frame in self.pages.items():
            if name == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for name, btn in self.nav_buttons.items():
            if name == key:
                btn.configure(fg_color=TONAL_BG, hover_color=TONAL_HOVER, text_color=TONAL_TEXT)
            else:
                btn.configure(fg_color="transparent", hover_color=HOVER_SUB, text_color=TEXT_SECONDARY)

    def _select_category(self, category: str) -> None:
        self._active_category = category
        for cat, btn in self.cat_buttons.items():
            if cat == category:
                btn.configure(
                    fg_color=TONAL_BG,
                    hover_color=TONAL_HOVER,
                    text_color=TONAL_TEXT,
                    border_color=TONAL_BG,
                )
            else:
                btn.configure(
                    fg_color=CARD_BG,
                    hover_color=HOVER_SUB,
                    text_color=TEXT_SECONDARY,
                    border_color=BORDER,
                )

        for widget in self.effects_scroll.winfo_children():
            widget.destroy()
        self._effect_buttons.clear()

        items: list[EffectItem] = get_effects_for_category(category)
        for item in items:
            is_active = item.index == self._active_effect_idx
            btn = ctk.CTkButton(
                self.effects_scroll,
                text=f"  {item.index:03d}   {item.name}  ·  {item.ru_name}",
                anchor="w",
                height=38,
                corner_radius=12,
                fg_color=TONAL_BG if is_active else "transparent",
                hover_color=TONAL_HOVER if is_active else HOVER_SUB,
                text_color=TONAL_TEXT if is_active else TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold" if is_active else "normal"),
                command=lambda idx=item.index: self._on_effect_clicked(idx),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self._effect_buttons[item.index] = btn

    # ------------------------------------------------------------------ BLE Scanning & Connection

    def _format_saved_device_label(self) -> str:
        name = self.cfg.last_name or "Лампа"
        return f"★ {name} ({self.cfg.last_mac})"

    def _startup_scan_and_connect(self) -> None:
        if self.cfg.auto_connect and self.cfg.last_mac:
            self._connect_to(self.cfg.last_mac, self.cfg.last_name)
        else:
            self._on_scan_clicked()

    def _on_scan_clicked(self) -> None:
        self.scan_btn.configure(state="disabled", text="Ищу...")
        include_all = self.var_show_all_ble.get()
        fut = self.ble.scan(timeout=5.0, include_all=include_all)

        def _done(_f: object) -> None:
            try:
                devices = fut.result()
            except Exception as exc:
                self._on_ble_log_bg(f"Ошибка сканирования: {exc}")
                devices = []
            if not self._closing:
                self.after(0, lambda: self._populate_scan_results(devices))

        fut.add_done_callback(_done)

    def _populate_scan_results(self, devices: list[DiscoveredLamp]) -> None:
        self.scan_btn.configure(state="normal", text="Поиск")
        self._discovered = devices
        if not devices:
            hint = "Не найдено (отключите телефон)"
            self.device_menu.configure(values=[hint])
            if not self.cfg.last_mac:
                self.device_var.set(hint)
            return

        labels = [d.display_label() for d in devices]
        self.device_menu.configure(values=labels)
        self.device_var.set(labels[0])

    def _resolve_selected_device(self) -> tuple[str, str]:
        selected = self.device_var.get()
        for d in self._discovered:
            if d.display_label() == selected:
                return d.address, d.name
        if self.cfg.last_mac and self.cfg.last_mac in selected:
            return self.cfg.last_mac, self.cfg.last_name
        return "", ""

    def _on_connect_clicked(self) -> None:
        if self.ble.is_connected:
            self.connect_btn.configure(state="disabled", text="Откл...")
            fut = self.ble.disconnect()
            fut.add_done_callback(
                lambda _f: self.after(0, lambda: self.connect_btn.configure(state="normal"))
                if not self._closing
                else None
            )
            return

        address, name = self._resolve_selected_device()
        if not address:
            messagebox.showinfo(
                "Устройство не выбрано",
                "Нажмите «Поиск» и убедитесь, что лампа включена и отключена от приложения на телефоне.",
                parent=self,
            )
            return
        self._connect_to(address, name)

    def _connect_to(self, address: str, name: str) -> None:
        self.connect_btn.configure(state="disabled", text="Коннект...")
        fut = self.ble.connect(address, name)

        def _done(_f: object) -> None:
            err: str | None = None
            try:
                fut.result()
            except Exception as exc:
                err = str(exc)
            if not self._closing:
                self.after(0, lambda: self._after_connect(address, name, err))

        fut.add_done_callback(_done)

    def _after_connect(self, address: str, name: str, err: str | None) -> None:
        self.connect_btn.configure(state="normal")
        if err is not None:
            self.connect_btn.configure(
                text="Подключить", fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY
            )
            self._on_ble_log_bg(f"Не удалось подключиться: {err}")
            return

        self.cfg.last_mac = address
        self.cfg.last_name = name or self.ble.connected_name
        save_config(self.cfg)
        self.connect_btn.configure(
            text="Отключить", fg_color=CARD_SUB, hover_color=HOVER_SUB, text_color=TEXT_PRIMARY
        )

    # ------------------------------------------------------------------ Lamp Commands

    def _stop_live_sync_modes(self) -> None:
        if self.audio_sync.is_running:
            self.audio_sync.stop()
            self.audio_toggle_btn.configure(
                text="Запустить светомузыку",
                fg_color=PRIMARY,
                hover_color=PRIMARY_HOVER,
                text_color=ON_PRIMARY,
            )
        if self.screen_sync.is_running:
            self.screen_sync.stop()
            self.screen_toggle_btn.configure(
                text="Запустить Амбилайт",
                fg_color=TONAL_BG,
                hover_color=TONAL_HOVER,
                text_color=TONAL_TEXT,
            )

    def _ensure_powered_on(self) -> None:
        if self.cfg.auto_power_on and not self._is_powered_on and self.ble.is_connected:
            self._is_powered_on = True
            self._refresh_power_btn()
            self.ble.send_immediate(build_power(True))

    def _refresh_power_btn(self) -> None:
        if self._is_powered_on:
            self.power_btn.configure(
                text="⏻  Вкл",
                fg_color=POWER_ON_BG,
                hover_color=POWER_ON_HOVER,
                text_color=POWER_ON_TEXT,
                border_color=POWER_ON_BG,
            )
        else:
            self.power_btn.configure(
                text="⏻  Выкл",
                fg_color=CARD_SUB,
                hover_color=HOVER_SUB,
                text_color=TEXT_PRIMARY,
                border_color=BORDER,
            )

    def _on_power_toggle(self) -> None:
        self._is_powered_on = not self._is_powered_on
        if not self._is_powered_on:
            self._stop_live_sync_modes()
        self._refresh_power_btn()
        self.ble.send_immediate(build_power(self._is_powered_on))

    def _on_wheel_color(self, hue_deg: float, sat_pct: float, is_final: bool) -> None:
        self._stop_live_sync_modes()
        self._ensure_powered_on()
        self.cfg.hue = hue_deg
        self.cfg.saturation = sat_pct
        self._update_color_readout(hue_deg, sat_pct)
        frame = build_hs_color(hue_deg, sat_pct)
        if is_final:
            self.ble.send_immediate(frame)
            save_config(self.cfg)
        else:
            self.ble.send_throttled("color", frame, min_interval=0.065)

    def _update_color_readout(self, hue_deg: float, sat_pct: float) -> None:
        r, g, b = hs_to_rgb(hue_deg, sat_pct)
        hx = rgb_to_hex(r, g, b)
        self.swatch_box.configure(fg_color=hx)
        self.color_info_label.configure(
            text=f"{hx}   ·   RGB ({r}, {g}, {b})   ·   H {round(hue_deg)}°  S {round(sat_pct)}%"
        )

    def _apply_preset_hex(self, hex_color: str) -> None:
        r, g, b = hex_to_rgb(hex_color)
        hue, sat = rgb_to_hs(r, g, b)
        self._stop_live_sync_modes()
        self._ensure_powered_on()
        self.cfg.hue = float(hue)
        self.cfg.saturation = float(sat)
        self.wheel.set_hs(hue, sat)
        self._update_color_readout(hue, sat)
        self.ble.send_immediate(build_hs_color(hue, sat))
        save_config(self.cfg)

    def _refresh_preset_borders(self) -> None:
        for idx, btn in enumerate(self._preset_buttons):
            btn.configure(border_color=PRIMARY if idx == self._selected_preset_slot else BORDER)

    def _on_preset_click(self, slot: int) -> None:
        self._selected_preset_slot = slot
        self._refresh_preset_borders()
        self._apply_preset_hex(self.cfg.presets[slot])

    def _on_preset_save(self, slot: int) -> None:
        r, g, b = hs_to_rgb(self.cfg.hue, self.cfg.saturation)
        hx = rgb_to_hex(r, g, b)
        self.cfg.presets[slot] = hx
        self._preset_buttons[slot].configure(fg_color=hx, hover_color=hx)
        save_config(self.cfg)
        self._on_ble_log_bg(f"Цвет {hx} сохранён в слот #{slot + 1}")

    def _on_brightness_slider(self, value: float) -> None:
        if self._syncing_ui:
            return
        pct = max(1, min(100, round(value)))
        self.cfg.brightness = pct
        self._syncing_ui = True
        self.bri_slider_adjust.set(pct)
        self.bri_slider_mode.set(pct)
        self._syncing_ui = False
        self.bri_val_label.configure(text=f"{pct}%")
        self.mbri_val_label.configure(text=f"{pct}%")
        self._ensure_powered_on()
        self.ble.send_throttled(
            "brightness",
            build_brightness(pct, scale_1000=self.cfg.brightness_scale_1000),
            min_interval=0.065,
        )

    def _on_pts_slider(self, value: float) -> None:
        count = max(8, min(300, round(value)))
        self.cfg.led_count = count
        self.pts_val_label.configure(text=f"{count} шт.")

    def _apply_led_count(self) -> None:
        count = max(8, min(300, round(self.pts_slider.get())))
        self.cfg.led_count = count
        save_config(self.cfg)
        self.ble.send_immediate(build_length(count))

    def _on_effect_clicked(self, idx: int) -> None:
        self._stop_live_sync_modes()
        self._ensure_powered_on()
        self._active_effect_idx = idx
        self.cfg.last_effect = idx
        self.direct_mode_entry.delete(0, "end")
        self.direct_mode_entry.insert(0, str(idx))
        for eff_id, btn in self._effect_buttons.items():
            active = eff_id == idx
            btn.configure(
                fg_color=TONAL_BG if active else "transparent",
                hover_color=TONAL_HOVER if active else HOVER_SUB,
                text_color=TONAL_TEXT if active else TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold" if active else "normal"),
            )
        fwd = self._effective_direction_forward()
        self.ble.send_immediate(build_effect(idx), build_direction(fwd))
        save_config(self.cfg)

    def _apply_direct_effect_num(self) -> None:
        try:
            idx = int(self.direct_mode_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Неверный номер", "Введите число от 1 до 117.", parent=self)
            return
        self._on_effect_clicked(max(1, min(117, idx)))

    def _effective_direction_forward(self) -> bool:
        val = self.var_direction.get()
        return (not val) if self.cfg.reverse_direction_polarity else val

    def _on_direction_toggle(self) -> None:
        self.cfg.direction_forward = self.var_direction.get()
        save_config(self.cfg)
        self.ble.send_immediate(build_direction(self._effective_direction_forward()))

    def _on_speed_slider(self, value: float) -> None:
        spd = max(1, min(100, round(value)))
        self.cfg.speed = spd
        self.spd_val_label.configure(text=f"{spd}%")
        self.ble.send_throttled("speed", build_speed(spd), min_interval=0.065)

    def _nudge_speed(self, delta: int) -> None:
        spd = max(1, min(100, self.cfg.speed + delta))
        self.spd_slider.set(spd)
        self._on_speed_slider(spd)
        save_config(self.cfg)

    # ------------------------------------------------------------------ Audio & Screen Sync

    def _refresh_audio_devices(self) -> None:
        try:
            self._audio_devices = list_audio_devices()
        except Exception as exc:
            self._audio_devices = []
            self._on_ble_log_bg(f"Ошибка перечисления аудиоустройств: {exc}")

        if not self._audio_devices:
            self.audio_dev_menu.configure(values=["Аудиоустройства не найдены"])
            self.audio_dev_var.set("Аудиоустройства не найдены")
            return

        labels = [d.label() for d in self._audio_devices]
        self.audio_dev_menu.configure(values=labels)
        self.audio_dev_var.set(labels[0])

    def _on_audio_mode_changed(self, value: str) -> None:
        mapping = {"Энергия (Бас)": "energy", "Спектр": "spectrum", "Бит-строб": "strobe"}
        self.audio_sync.mode = mapping.get(value, "energy")

    def _on_audio_sens(self, value: float) -> None:
        self.audio_sync.sensitivity = float(value)
        self.audio_sens_label.configure(text=f"{value:.1f}x")

    def _toggle_audio_sync(self) -> None:
        if self.audio_sync.is_running:
            self.audio_sync.stop()
            self.audio_toggle_btn.configure(
                text="Запустить светомузыку",
                fg_color=PRIMARY,
                hover_color=PRIMARY_HOVER,
                text_color=ON_PRIMARY,
            )
            return

        if not self.ble.is_connected:
            messagebox.showwarning("Нет подключения", "Сначала подключитесь к лампе.", parent=self)
            return

        label = self.audio_dev_var.get()
        selected = next((d for d in self._audio_devices if d.label() == label), None)
        if selected is None:
            messagebox.showwarning("Нет источника", "Выберите аудиоустройство.", parent=self)
            return

        if self.screen_sync.is_running:
            self.screen_sync.stop()
            self.screen_toggle_btn.configure(
                text="Запустить Амбилайт",
                fg_color=TONAL_BG,
                hover_color=TONAL_HOVER,
                text_color=TONAL_TEXT,
            )

        self._ensure_powered_on()
        self.audio_sync.start(selected)
        self.audio_toggle_btn.configure(
            text="Остановить светомузыку",
            fg_color=DANGER_BG,
            hover_color=DANGER_HOVER,
            text_color=DANGER_TEXT,
        )

    def _on_screen_sat(self, value: float) -> None:
        self.screen_sync.saturation_boost = float(value)
        self.screen_sat_label.configure(text=f"{value:.2f}x")

    def _toggle_screen_sync(self) -> None:
        if self.screen_sync.is_running:
            self.screen_sync.stop()
            self.screen_toggle_btn.configure(
                text="Запустить Амбилайт",
                fg_color=TONAL_BG,
                hover_color=TONAL_HOVER,
                text_color=TONAL_TEXT,
            )
            return

        if not self.ble.is_connected:
            messagebox.showwarning("Нет подключения", "Сначала подключитесь к лампе.", parent=self)
            return

        if self.audio_sync.is_running:
            self.audio_sync.stop()
            self.audio_toggle_btn.configure(
                text="Запустить светомузыку",
                fg_color=PRIMARY,
                hover_color=PRIMARY_HOVER,
                text_color=ON_PRIMARY,
            )

        self._ensure_powered_on()
        self.screen_sync.start()
        self.screen_toggle_btn.configure(
            text="Остановить Амбилайт",
            fg_color=DANGER_BG,
            hover_color=DANGER_HOVER,
            text_color=DANGER_TEXT,
        )

    # ------------------------------------------------------------------ Hardware Mic & Schedule

    def _send_hw_mic_power(self, on: bool) -> None:
        self._stop_live_sync_modes()
        if on:
            self._ensure_powered_on()
        self.ble.send_immediate(build_mic_power(on))

    def _send_hw_mic_eq(self, eq_index: int) -> None:
        self._stop_live_sync_modes()
        self._ensure_powered_on()
        self.ble.send_immediate(build_mic_power(True), build_mic_eq(eq_index))

    def _on_hw_mic_sens(self, value: float) -> None:
        pct = max(1, min(100, round(value)))
        self.hw_mic_sens_label.configure(text=f"{pct}%")
        self.ble.send_throttled(
            "mic_sens",
            build_mic_sensitivity(pct, use_alt_cmd=self.cfg.mic_alt_cmd),
            min_interval=0.08,
        )

    def _on_sync_clock(self) -> None:
        if not self.ble.is_connected:
            messagebox.showwarning("Нет подключения", "Сначала подключитесь к лампе.", parent=self)
            return
        self.ble.send_immediate(build_time_sync())

    def _send_hw_timer(self, enable: bool) -> None:
        if not self.ble.is_connected:
            messagebox.showwarning("Нет подключения", "Сначала подключитесь к лампе.", parent=self)
            return
        try:
            hour = max(0, min(23, int(self.timer_hour_entry.get().strip())))
            minute = max(0, min(59, int(self.timer_min_entry.get().strip())))
        except ValueError:
            messagebox.showwarning("Ошибка времени", "Введите часы (0–23) и минуты (0–59).", parent=self)
            return

        power_on = self.timer_action_seg.get() == "Включить"
        weekdays = [v.get() for v in self._weekday_vars]
        self.cfg.timer_hour = hour
        self.cfg.timer_minute = minute
        self.cfg.timer_power_on = power_on
        self.cfg.timer_weekdays = weekdays
        save_config(self.cfg)

        self.ble.send_immediate(build_time_sync(), build_timer(power_on, enable, weekdays, hour, minute))

    def _start_sleep_timer(self, minutes: int) -> None:
        self._sleep_deadline = time.monotonic() + minutes * 60
        self._update_sleep_label()

    def _cancel_sleep_timer(self) -> None:
        self._sleep_deadline = None
        self._update_sleep_label()

    def _update_sleep_label(self) -> None:
        if self._closing:
            return
        if self._sleep_deadline is None:
            self.sleep_status_label.configure(text="Не активен", text_color=TEXT_SECONDARY)
        else:
            rem = int(self._sleep_deadline - time.monotonic())
            if rem <= 0:
                self._sleep_deadline = None
                self.sleep_status_label.configure(text="Выключено", text_color=POWER_ON_TEXT)
                self._stop_live_sync_modes()
                self._is_powered_on = False
                self._refresh_power_btn()
                self.ble.send_immediate(build_power(False))
            else:
                mm, ss = divmod(rem, 60)
                hh, mm = divmod(mm, 60)
                text = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
                self.sleep_status_label.configure(text=text, text_color=PRIMARY)
        self.after(1000, self._update_sleep_label)

    # ------------------------------------------------------------------ Background Callbacks

    def _send_sync_color_bg(self, hue_deg: float, sat_pct: float) -> None:
        self.ble.send_throttled("sync_color", build_hs_color(hue_deg, sat_pct), min_interval=0.065)

    def _send_sync_brightness_bg(self, pct: int) -> None:
        self.ble.send_throttled(
            "sync_bri",
            build_brightness(pct, scale_1000=self.cfg.brightness_scale_1000),
            min_interval=0.065,
        )

    def _on_audio_level_bg(self, level: float, bass: float, mid: float, high: float) -> None:
        if self._closing:
            return
        self.after(0, lambda: self._update_audio_meters(level, bass, mid, high))

    def _update_audio_meters(self, level: float, bass: float, mid: float, high: float) -> None:
        if self._closing:
            return
        self.meter_bars["level"].set(max(0.0, min(1.0, level)))
        self.meter_bars["bass"].set(max(0.0, min(1.0, bass)))
        self.meter_bars["mid"].set(max(0.0, min(1.0, mid)))
        self.meter_bars["high"].set(max(0.0, min(1.0, high)))

    def _on_screen_preview_bg(self, r: int, g: int, b: int) -> None:
        if self._closing:
            return
        hx = rgb_to_hex(r, g, b)
        self.after(0, lambda: self._update_screen_preview(hx))

    def _update_screen_preview(self, hx: str) -> None:
        if self._closing:
            return
        self.screen_preview.configure(fg_color=hx)
        self.screen_preview_label.configure(text=hx, text_color=_contrast_fg(hx))

    def _on_sync_error_bg(self, msg: str) -> None:
        self._on_ble_log_bg(msg)
        if not self._closing:
            self.after(0, self._stop_live_sync_modes)

    def _on_ble_status_bg(self, connected: bool, detail: str) -> None:
        if self._closing:
            return
        self.after(0, lambda: self._update_ble_status_ui(connected, detail))

    def _update_ble_status_ui(self, connected: bool, detail: str) -> None:
        if self._closing:
            return
        if connected:
            short = detail.split(" (")[0]
            self.status_badge.configure(
                text=f"●  {short}", fg_color=POWER_ON_BG, text_color=POWER_ON_TEXT
            )
            self.connect_btn.configure(
                text="Отключить", fg_color=CARD_SUB, hover_color=HOVER_SUB, text_color=TEXT_PRIMARY
            )
        else:
            self._stop_live_sync_modes()
            self.status_badge.configure(
                text="●  Отключено", fg_color=CARD_SUB, text_color=TEXT_SECONDARY
            )
            self.connect_btn.configure(
                text="Подключить", fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY
            )

    def _on_ble_log_bg(self, line: str) -> None:
        self._log_lines.append(line)
        if not self._closing and self._settings_win is not None and self._settings_win.winfo_exists():
            self.after(0, self._settings_win.refresh_log)

    def _open_settings(self) -> None:
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsWindow(self)

    def _on_close(self) -> None:
        self._closing = True
        save_config(self.cfg)
        self.audio_sync.stop()
        self.screen_sync.stop()
        self.ble.shutdown()
        self.destroy()


def run_app() -> None:
    app = LampControlApp()
    app.mainloop()
