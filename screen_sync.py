"""Screen dominant-color Ambilight sync using Pillow ImageGrab + numpy."""

from __future__ import annotations

import colorsys
import threading
import time
from typing import Callable

import numpy as np
from PIL import ImageGrab


class ScreenSyncEngine:
    """Samples desktop screen colors and updates lamp HSV+brightness smoothly."""

    def __init__(
        self,
        send_color_cb: Callable[[float, float], None],
        send_brightness_cb: Callable[[int], None],
        on_preview: Callable[[int, int, int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._send_color_cb = send_color_cb
        self._send_brightness_cb = send_brightness_cb
        self._on_preview = on_preview
        self._on_error = on_error

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.saturation_boost: float = 1.25

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ScreenSyncWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _run(self) -> None:
        ema_r, ema_g, ema_b = 128.0, 128.0, 128.0
        consecutive_errors = 0
        try:
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                try:
                    img = ImageGrab.grab().resize((48, 27))
                    consecutive_errors = 0
                except OSError as exc:
                    consecutive_errors += 1
                    if consecutive_errors >= 10:
                        raise RuntimeError(f"Экран недоступен для захвата ({exc})") from exc
                    self._stop_event.wait(0.4)
                    continue
                arr = np.asarray(img, dtype=np.float32).reshape(-1, 3)

                # Weight vivid, non-black pixels more strongly so letterbox bars don't wash out color
                max_ch = arr.max(axis=1)
                min_ch = arr.min(axis=1)
                chroma = max_ch - min_ch
                weights = (max_ch / 255.0) * (0.25 + (chroma / 255.0) * 2.5) + 0.02
                avg = np.average(arr, axis=0, weights=weights)

                ema_r = ema_r * 0.65 + float(avg[0]) * 0.35
                ema_g = ema_g * 0.65 + float(avg[1]) * 0.35
                ema_b = ema_b * 0.65 + float(avg[2]) * 0.35

                r_i = max(0, min(255, int(ema_r)))
                g_i = max(0, min(255, int(ema_g)))
                b_i = max(0, min(255, int(ema_b)))

                h, s, v = colorsys.rgb_to_hsv(r_i / 255.0, g_i / 255.0, b_i / 255.0)
                s_boosted = min(1.0, s * self.saturation_boost)
                hue_deg = (h * 360.0) % 360.0
                sat_pct = s_boosted * 100.0
                bri_pct = max(12, min(100, int(15 + v * 85)))

                self._send_color_cb(hue_deg, sat_pct)
                self._send_brightness_cb(bri_pct)
                if self._on_preview:
                    pr, pg, pb = colorsys.hsv_to_rgb(h, s_boosted, max(0.2, v))
                    self._on_preview(int(pr * 255), int(pg * 255), int(pb * 255))

                elapsed = time.monotonic() - t0
                sleep_time = max(0.02, 0.09 - elapsed)
                self._stop_event.wait(sleep_time)
        except Exception as exc:
            if self._on_error:
                self._on_error(f"Ошибка захвата экрана: {exc}")
