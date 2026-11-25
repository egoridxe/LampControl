"""Anti-aliased HSV color wheel widget with Light/Dark theme surface sync."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

import numpy as np
from PIL import Image, ImageTk

from protocol import hs_to_rgb


class ColorWheelCanvas(tk.Canvas):
    """Interactive circular HSV wheel (Hue by angle, Saturation by radius)."""

    def __init__(
        self,
        master: tk.Misc,
        size: int = 264,
        bg_color: str = "#FFFFFF",
        ring_neutral: str = "#E0E3EB",
        initial_hue: float = 217.0,
        initial_sat: float = 89.0,
        on_change: Callable[[float, float, bool], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.size = size
        self.bg_color = bg_color
        self.ring_neutral = ring_neutral
        self.on_change = on_change

        self.padding = 12
        self.radius = (size / 2.0) - self.padding
        self.center = size / 2.0
        self.hue = initial_hue % 360.0
        self.sat = max(0.0, min(100.0, initial_sat))

        self._wheel_photo = self._render_wheel_image(size, self.radius, bg_color)
        self._wheel_img_id = self.create_image(0, 0, image=self._wheel_photo, anchor="nw")

        self._ring_id = self.create_oval(
            self.padding - 3,
            self.padding - 3,
            size - self.padding + 3,
            size - self.padding + 3,
            outline=ring_neutral,
            width=2,
        )
        self._cursor_shadow = self.create_oval(0, 0, 18, 18, outline="#3C4043", fill="", width=2)
        self._cursor_dot = self.create_oval(0, 0, 16, 16, outline="#FFFFFF", fill="#1A73E8", width=3)
        self._update_cursor()

        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_theme_colors(self, bg_color: str, ring_neutral: str) -> None:
        """Update canvas background and anti-aliased edge for Light/Dark mode."""
        self.bg_color = bg_color
        self.ring_neutral = ring_neutral
        self.configure(bg=bg_color)
        self._wheel_photo = self._render_wheel_image(self.size, self.radius, bg_color)
        self.itemconfigure(self._wheel_img_id, image=self._wheel_photo)
        self._update_cursor()

    @staticmethod
    def _render_wheel_image(size: int, radius: float, bg_hex: str) -> ImageTk.PhotoImage:
        """Render a 2x supersampled HSV wheel for crisp anti-aliased edges."""
        scale = 2
        hi_size = size * scale
        hi_center = hi_size / 2.0
        hi_radius = radius * scale

        yy, xx = np.mgrid[0:hi_size, 0:hi_size]
        dx = xx - hi_center
        dy = yy - hi_center
        dist = np.sqrt(dx * dx + dy * dy)
        inside = dist <= hi_radius

        sat = np.clip(dist / hi_radius, 0.0, 1.0)
        angle = np.degrees(np.arctan2(-dy, dx)) % 360.0
        h6 = angle / 60.0
        i = np.floor(h6).astype(np.int32) % 6
        f = h6 - np.floor(h6)
        p = 1.0 - sat
        q = 1.0 - sat * f
        t = 1.0 - sat * (1.0 - f)

        r = np.ones_like(sat)
        g = np.ones_like(sat)
        b = np.ones_like(sat)

        m0 = i == 0
        m1 = i == 1
        m2 = i == 2
        m3 = i == 3
        m4 = i == 4
        m5 = i == 5

        r[m0], g[m0], b[m0] = 1.0, t[m0], p[m0]
        r[m1], g[m1], b[m1] = q[m1], 1.0, p[m1]
        r[m2], g[m2], b[m2] = p[m2], 1.0, t[m2]
        r[m3], g[m3], b[m3] = p[m3], q[m3], 1.0
        r[m4], g[m4], b[m4] = t[m4], p[m4], 1.0
        r[m5], g[m5], b[m5] = 1.0, p[m5], q[m5]

        bg_clean = bg_hex.lstrip("#")
        bg_r = int(bg_clean[0:2], 16)
        bg_g = int(bg_clean[2:4], 16)
        bg_b = int(bg_clean[4:6], 16)

        rgb = np.empty((hi_size, hi_size, 3), dtype=np.uint8)
        rgb[..., 0] = np.where(inside, np.clip(r * 255.0, 0, 255), bg_r).astype(np.uint8)
        rgb[..., 1] = np.where(inside, np.clip(g * 255.0, 0, 255), bg_g).astype(np.uint8)
        rgb[..., 2] = np.where(inside, np.clip(b * 255.0, 0, 255), bg_b).astype(np.uint8)

        img = Image.fromarray(rgb, mode="RGB").resize((size, size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def set_hs(self, hue_deg: float, sat_pct: float) -> None:
        """Update selector position programmatically without firing callback."""
        self.hue = hue_deg % 360.0
        self.sat = max(0.0, min(100.0, sat_pct))
        self._update_cursor()

    def _update_cursor(self) -> None:
        rad = math.radians(self.hue)
        dist = (self.sat / 100.0) * self.radius
        cx = self.center + dist * math.cos(rad)
        cy = self.center - dist * math.sin(rad)
        r_dot = 8
        r_sh = 9.5
        self.coords(self._cursor_shadow, cx - r_sh, cy - r_sh, cx + r_sh, cy + r_sh)
        self.coords(self._cursor_dot, cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot)

        r, g, b = hs_to_rgb(self.hue, self.sat)
        color_hex = f"#{r:02x}{g:02x}{b:02x}"
        self.itemconfigure(self._cursor_dot, fill=color_hex)
        ring_col = color_hex if self.sat >= 15.0 else self.ring_neutral
        self.itemconfigure(self._ring_id, outline=ring_col)

    def _handle_pointer(self, x: float, y: float, is_final: bool) -> None:
        dx = x - self.center
        dy = y - self.center
        dist = math.hypot(dx, dy)
        clamped_dist = min(dist, self.radius)
        self.sat = (clamped_dist / self.radius) * 100.0
        if clamped_dist > 1.0:
            self.hue = math.degrees(math.atan2(-dy, dx)) % 360.0
        self._update_cursor()
        if self.on_change:
            self.on_change(self.hue, self.sat, is_final)

    def _on_press(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._handle_pointer(event.x, event.y, is_final=False)

    def _on_drag(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._handle_pointer(event.x, event.y, is_final=False)

    def _on_release(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._handle_pointer(event.x, event.y, is_final=True)
