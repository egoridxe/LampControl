"""Real-time PC system audio (WASAPI loopback) and microphone reactive sync."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio


@dataclass(frozen=True)
class AudioDeviceOption:
    """Selectable Windows audio capture device."""

    index: int
    name: str
    is_loopback: bool
    channels: int
    sample_rate: int

    def label(self) -> str:
        tag = "[Звук ПК]" if self.is_loopback else "[Микрофон]"
        return f"{tag} {self.name}"


def list_audio_devices() -> list[AudioDeviceOption]:
    """Enumerate active WASAPI loopback output devices and input microphones."""
    options: list[AudioDeviceOption] = []
    pa = pyaudio.PyAudio()
    try:
        try:
            default_loopback = pa.get_default_wasapi_loopback()
            default_lb_idx = int(default_loopback["index"])
        except Exception:
            default_lb_idx = -1

        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            wasapi_idx = int(wasapi_info["index"])
        except Exception:
            wasapi_idx = -1

        for idx in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(idx)
            max_in = int(info.get("maxInputChannels", 0))
            if max_in <= 0:
                continue
            is_lb = bool(info.get("isLoopbackDevice", False))
            host_idx = int(info.get("hostApi", -1))
            if not is_lb and wasapi_idx != -1 and host_idx != wasapi_idx:
                continue
            options.append(
                AudioDeviceOption(
                    index=idx,
                    name=str(info.get("name", f"Device {idx}")),
                    is_loopback=is_lb,
                    channels=min(2, max_in),
                    sample_rate=int(info.get("defaultSampleRate", 48000)),
                )
            )

        # Put default loopback device first, then other loopbacks, then mics
        options.sort(
            key=lambda d: (
                d.index != default_lb_idx,
                not d.is_loopback,
                d.name.lower(),
            )
        )
    finally:
        pa.terminate()
    return options


class AudioSyncEngine:
    """Captures PC audio / mic and streams reactive HSV+brightness frames."""

    def __init__(
        self,
        send_color_cb: Callable[[float, float], None],
        send_brightness_cb: Callable[[int], None],
        on_level: Callable[[float, float, float, float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._send_color_cb = send_color_cb
        self._send_brightness_cb = send_brightness_cb
        self._on_level = on_level
        self._on_error = on_error

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.mode: str = "energy"  # energy | spectrum | strobe
        self.sensitivity: float = 1.0  # 0.2 .. 3.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, device: AudioDeviceOption) -> None:
        """Start audio capture loop on the chosen device."""
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(device,),
            name="AudioSyncWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop audio capture loop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _run(self, device: AudioDeviceOption) -> None:
        pa = pyaudio.PyAudio()
        stream = None
        try:
            chunk = 1024
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=device.channels,
                rate=device.sample_rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=chunk,
            )

            freqs = np.fft.rfftfreq(chunk, d=1.0 / device.sample_rate)
            bass_mask = (freqs >= 20) & (freqs <= 180)
            mid_mask = (freqs > 180) & (freqs <= 2000)
            high_mask = (freqs > 2000) & (freqs <= 9000)
            window = np.hanning(chunk)

            peak_env = 0.05
            prev_bass = 0.0
            hue = 0.0
            strobe_palette = [0.0, 35.0, 120.0, 185.0, 240.0, 300.0]
            strobe_idx = 0
            last_beat_time = 0.0
            last_tx = 0.0

            while not self._stop_event.is_set():
                raw = stream.read(chunk, exception_on_overflow=False)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                if device.channels > 1:
                    samples = samples.reshape(-1, device.channels).mean(axis=1)
                samples /= 32768.0

                rms = float(np.sqrt(np.mean(samples * samples)))
                spectrum = np.abs(np.fft.rfft(samples * window))
                bass_raw = float(np.mean(spectrum[bass_mask])) if np.any(bass_mask) else 0.0
                mid_raw = float(np.mean(spectrum[mid_mask])) if np.any(mid_mask) else 0.0
                high_raw = float(np.mean(spectrum[high_mask])) if np.any(high_mask) else 0.0

                total_energy = (bass_raw * 0.6 + mid_raw * 0.3 + high_raw * 0.1) * self.sensitivity
                peak_env = max(total_energy, peak_env * 0.96, 0.02)

                bass = min(1.0, (bass_raw * self.sensitivity) / peak_env)
                mid = min(1.0, (mid_raw * self.sensitivity) / peak_env)
                high = min(1.0, (high_raw * self.sensitivity) / peak_env)
                level = min(1.0, (rms * 4.5 * self.sensitivity) / max(0.15, peak_env * 0.25))

                if self._on_level:
                    self._on_level(level, bass, mid, high)

                now = time.monotonic()
                is_beat = (bass - prev_bass) > 0.24 and bass > 0.45 and (now - last_beat_time) > 0.18
                prev_bass = bass

                if is_beat:
                    last_beat_time = now

                if now - last_tx < 0.065:
                    continue
                last_tx = now

                if rms < 0.0015:
                    # Silence: dim softly without rapid noise jumps
                    self._send_brightness_cb(8)
                    continue

                if self.mode == "energy":
                    if is_beat:
                        hue = (hue + 48.0) % 360.0
                    else:
                        hue = (hue + 2.5 + mid * 4.0) % 360.0
                    sat = 100.0
                    bri = int(max(10, min(100, 15 + bass * 85)))
                    self._send_color_cb(hue, sat)
                    self._send_brightness_cb(bri)
                elif self.mode == "spectrum":
                    band_sum = bass + mid + high + 1e-6
                    target_hue = (bass * 15.0 + mid * 140.0 + high * 265.0) / band_sum
                    hue = hue * 0.55 + target_hue * 0.45
                    bri = int(max(10, min(100, 12 + level * 88)))
                    self._send_color_cb(hue % 360.0, 100.0)
                    self._send_brightness_cb(bri)
                else:  # strobe
                    if is_beat:
                        strobe_idx = (strobe_idx + 1) % len(strobe_palette)
                        hue = strobe_palette[strobe_idx]
                    bri = 100 if is_beat else int(max(10, min(95, 10 + bass * 65)))
                    self._send_color_cb(hue, 100.0)
                    self._send_brightness_cb(bri)

        except Exception as exc:
            if self._on_error:
                self._on_error(f"Ошибка аудио-синхронизации: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            pa.terminate()
