"""Asynchronous BLE manager running on a dedicated background event loop."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
import threading
import time
from typing import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from protocol import (
    KNOWN_LOCAL_NAMES,
    NOTIFY_CHAR_UUID,
    SERVICE_UUIDS,
    WRITE_CHAR_UUID,
)


@dataclass(frozen=True)
class DiscoveredLamp:
    """BLE advertisement entry surfaced in the UI."""

    address: str
    name: str
    rssi: int
    is_probable_lamp: bool
    service_uuids: list[str] = field(default_factory=list)

    def display_label(self) -> str:
        prefix = "★ " if self.is_probable_lamp else ""
        rssi_str = f"{self.rssi} dBm" if self.rssi is not None else "?"
        return f"{prefix}{self.name} ({self.address}) [{rssi_str}]"


def _is_probable_lamp(name: str, service_uuids: list[str]) -> bool:
    upper = name.upper()
    if any(token in upper for token in KNOWN_LOCAL_NAMES):
        return True
    norm_uuids = {u.lower() for u in service_uuids}
    return any(target in norm_uuids for target in SERVICE_UUIDS)


class BLEManager:
    """Manages BLE scanning, persistent connection, and throttled command dispatch."""

    def __init__(
        self,
        on_status: Callable[[bool, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self._on_status = on_status
        self._on_log = on_log

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="BLEWorker", daemon=True)
        self._thread.start()

        self._client: BleakClient | None = None
        self._write_char: BleakGATTCharacteristic | None = None
        self._write_with_response: bool = False
        self._connected_address: str = ""
        self._connected_name: str = ""
        self._devices_cache: dict[str, BLEDevice] = {}

        self._send_lock: asyncio.Lock | None = None
        self._wake_event: asyncio.Event | None = None
        self._immediate_queue: asyncio.Queue[bytes] | None = None
        self._throttled_slots: dict[str, tuple[bytes, float]] = {}
        self._last_sent_at: dict[str, float] = {}
        self._sender_task: asyncio.Task[None] | None = None
        self._wake_handle: asyncio.TimerHandle | None = None

        self._init_async_primitives()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _init_async_primitives(self) -> None:
        def _setup() -> None:
            self._send_lock = asyncio.Lock()
            self._wake_event = asyncio.Event()
            self._immediate_queue = asyncio.Queue()
            self._sender_task = self._loop.create_task(self._sender_worker())

        fut = asyncio.run_coroutine_threadsafe(self._noop_setup(_setup), self._loop)
        fut.result(timeout=5)

    @staticmethod
    async def _noop_setup(fn: Callable[[], None]) -> None:
        fn()

    def _log(self, message: str) -> None:
        if self._on_log:
            ts = datetime.now().strftime("%H:%M:%S")
            self._on_log(f"[{ts}] {message}")

    def _emit_status(self, connected: bool, detail: str) -> None:
        if self._on_status:
            self._on_status(connected, detail)

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected and self._write_char is not None)

    @property
    def connected_address(self) -> str:
        return self._connected_address if self.is_connected else ""

    @property
    def connected_name(self) -> str:
        return self._connected_name if self.is_connected else ""

    def scan(self, timeout: float = 5.0, include_all: bool = False) -> Future[list[DiscoveredLamp]]:
        """Start an async BLE scan and return a concurrent Future."""
        return asyncio.run_coroutine_threadsafe(
            self._scan_async(timeout=timeout, include_all=include_all),
            self._loop,
        )

    async def _scan_async(self, timeout: float, include_all: bool) -> list[DiscoveredLamp]:
        self._log(f"Поиск BLE устройств ({timeout:.0f} сек)...")
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        lamps: list[DiscoveredLamp] = []
        for device, adv in discovered.values():
            self._devices_cache[device.address] = device
            name = (device.name or adv.local_name or "").strip() or "Без имени"
            uuids = list(adv.service_uuids or [])
            probable = _is_probable_lamp(name, uuids)
            if not include_all and not probable:
                continue
            lamps.append(
                DiscoveredLamp(
                    address=device.address,
                    name=name,
                    rssi=adv.rssi if adv.rssi is not None else -100,
                    is_probable_lamp=probable,
                    service_uuids=uuids,
                )
            )
        lamps.sort(key=lambda item: (not item.is_probable_lamp, -item.rssi, item.name))
        self._log(f"Найдено устройств: {len(lamps)}")
        return lamps

    def connect(self, address: str, name: str = "") -> Future[None]:
        """Connect to a lamp by BLE address."""
        return asyncio.run_coroutine_threadsafe(
            self._connect_async(address=address, name=name),
            self._loop,
        )

    async def _connect_async(self, address: str, name: str) -> None:
        await self._disconnect_async(silent=True)
        self._log(f"Подключение к {name or address} ({address})...")

        target: BLEDevice | str = self._devices_cache.get(address) or address
        if isinstance(target, str):
            found = await BleakScanner.find_device_by_address(address, timeout=6.0)
            if found is not None:
                target = found
                self._devices_cache[address] = found

        client = BleakClient(
            target,
            disconnected_callback=self._handle_disconnected,
            timeout=12.0,
        )
        await client.connect()

        write_char, use_resp = self._resolve_write_characteristic(client)
        if write_char is None:
            await client.disconnect()
            raise RuntimeError(
                "Не найдена BLE-характеристика записи (0000fff3). "
                "Убедитесь, что выбрана именно лампа."
            )

        self._client = client
        self._write_char = write_char
        self._write_with_response = use_resp
        self._connected_address = address
        self._connected_name = name or getattr(target, "name", "") or address

        self._log(
            f"Подключено! Характеристика: {write_char.uuid} "
            f"(response={use_resp})"
        )
        await self._try_subscribe_notify(client)
        self._emit_status(True, f"{self._connected_name} ({address})")

    def _resolve_write_characteristic(
        self, client: BleakClient
    ) -> tuple[BleakGATTCharacteristic | None, bool]:
        """Find 0000fff3 write characteristic, or suitable writable fallback."""
        for service in client.services:
            chars_desc = ", ".join(
                f"{c.uuid}[{','.join(c.properties)}]" for c in service.characteristics
            )
            self._log(f"GATT сервис {service.uuid}: {chars_desc}")

        exact = client.services.get_characteristic(WRITE_CHAR_UUID)
        if exact is not None:
            props = set(exact.properties)
            use_resp = "write-without-response" not in props
            return exact, use_resp

        for service in client.services:
            if service.uuid.lower() in SERVICE_UUIDS:
                for char in service.characteristics:
                    props = set(char.properties)
                    if "write-without-response" in props:
                        return char, False
                    if "write" in props:
                        return char, True

        return None, False

    async def _try_subscribe_notify(self, client: BleakClient) -> None:
        notify_char = client.services.get_characteristic(NOTIFY_CHAR_UUID)
        if notify_char is None or "notify" not in notify_char.properties:
            return
        try:
            await client.start_notify(
                notify_char,
                lambda _sender, data: self._log(f"RX <- {bytes(data).hex(' ').upper()}"),
            )
        except Exception as exc:
            self._log(f"Уведомления fff4 недоступны ({exc})")

    def _handle_disconnected(self, _client: BleakClient) -> None:
        if self._client is None:
            return
        addr = self._connected_address
        self._client = None
        self._write_char = None
        self._connected_address = ""
        self._connected_name = ""
        self._throttled_slots.clear()
        self._log(f"Соединение разорвано ({addr})")
        self._emit_status(False, "Отключено")

    def disconnect(self) -> Future[None]:
        """Disconnect cleanly from the lamp."""
        return asyncio.run_coroutine_threadsafe(self._disconnect_async(silent=False), self._loop)

    async def _disconnect_async(self, silent: bool) -> None:
        client = self._client
        self._client = None
        self._write_char = None
        self._connected_address = ""
        self._connected_name = ""
        self._throttled_slots.clear()
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except Exception as exc:
                self._log(f"Ошибка при отключении: {exc}")
        if not silent:
            self._log("Отключено пользователем")
            self._emit_status(False, "Отключено")

    def send_immediate(self, *frames: bytes) -> None:
        """Queue one or more packets for immediate sequential transmission."""
        if not frames or not self.is_connected:
            return

        def _enqueue() -> None:
            assert self._immediate_queue is not None
            assert self._wake_event is not None
            for frame in frames:
                self._immediate_queue.put_nowait(frame)
            self._wake_event.set()

        self._loop.call_soon_threadsafe(_enqueue)

    def send_throttled(self, channel: str, frame: bytes, min_interval: float = 0.07) -> None:
        """Queue latest packet for a channel, coalescing intermediate updates."""
        if not self.is_connected:
            return

        def _enqueue() -> None:
            assert self._wake_event is not None
            self._throttled_slots[channel] = (frame, min_interval)
            self._wake_event.set()

        self._loop.call_soon_threadsafe(_enqueue)

    async def _write_packet(self, frame: bytes) -> None:
        client = self._client
        char = self._write_char
        if client is None or char is None or not client.is_connected:
            return
        try:
            await client.write_gatt_char(char, frame, response=self._write_with_response)
            self._log(f"TX -> {frame.hex(' ').upper()}")
        except Exception as exc:
            self._log(f"Ошибка отправки {frame.hex(' ').upper()}: {exc}")

    async def _sender_worker(self) -> None:
        assert self._immediate_queue is not None
        assert self._wake_event is not None
        assert self._send_lock is not None

        while True:
            await self._wake_event.wait()
            self._wake_event.clear()

            # 1. Drain discrete immediate commands first
            while not self._immediate_queue.empty():
                frame = self._immediate_queue.get_nowait()
                async with self._send_lock:
                    await self._write_packet(frame)
                await asyncio.sleep(0.03)

            # 2. Dispatch throttled channels if their interval has elapsed
            now = time.monotonic()
            next_due: float | None = None
            for channel in list(self._throttled_slots.keys()):
                entry = self._throttled_slots.get(channel)
                if entry is None:
                    continue
                frame, interval = entry
                elapsed = now - self._last_sent_at.get(channel, 0.0)
                if elapsed >= interval:
                    del self._throttled_slots[channel]
                    self._last_sent_at[channel] = time.monotonic()
                    async with self._send_lock:
                        await self._write_packet(frame)
                    await asyncio.sleep(0.015)
                else:
                    wait_for = interval - elapsed
                    if next_due is None or wait_for < next_due:
                        next_due = wait_for

            if next_due is not None:
                if self._wake_handle is not None:
                    self._wake_handle.cancel()
                self._wake_handle = self._loop.call_later(next_due, self._wake_event.set)

    async def _shutdown_async(self) -> None:
        await self._disconnect_async(silent=True)
        if self._wake_handle is not None:
            self._wake_handle.cancel()
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks(self._loop) if t is not current and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def shutdown(self) -> None:
        """Disconnect and stop the BLE worker thread cleanly."""
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop).result(timeout=3.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
