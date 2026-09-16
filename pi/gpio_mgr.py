"""
GPIO Manager — async LED patterns and button handling for BT-KBM.

LEDs:
  GREEN  (GPIO 17) — Power/State: solid=on, blink=state change
  BLUE   (GPIO 27) — Bluetooth:   solid=connected,
                                   slow_blink=idle/bt_off,
                                   rapid_blink=discoverable
  YELLOW (GPIO 22) — WiFi AP mode: solid=AP active, off=normal

Button:
  GPIO 18 — active-low with internal pull-up; short press = toggle pair
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Callable

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available — running in simulation mode")


class BlueState(Enum):
    OFF             = auto()  # BT radio off
    IDLE            = auto()  # BT on, no device connected
    DISCOVERABLE    = auto()  # Advertising / pairing
    CONNECTED       = auto()  # Device connected


class WifiState(Enum):
    NORMAL  = auto()  # Connected to a regular AP
    AP_MODE = auto()  # Acting as its own AP


class GreenState(Enum):
    ON           = auto()  # Solid: system nominal
    STATE_CHANGE = auto()  # Blinking: transition in progress


# Blink timing constants (seconds)
_SLOW_ON  = 1.0
_SLOW_OFF = 1.0
_RAPID_ON  = 0.15
_RAPID_OFF = 0.15
_STATE_ON  = 0.3
_STATE_OFF = 0.3


class GPIOManager:
    """Async GPIO manager for 3 LEDs + 1 button."""

    def __init__(
        self,
        pin_green:  int = 17,
        pin_blue:   int = 27,
        pin_yellow: int = 22,
        pin_button: int = 18,
        brightness: float = 1.0,
    ) -> None:
        self.pin_green  = pin_green
        self.pin_blue   = pin_blue
        self.pin_yellow = pin_yellow
        self.pin_button = pin_button
        self.brightness = max(0.0, min(1.0, brightness))

        self._blue_state:  BlueState  = BlueState.IDLE
        self._wifi_state:  WifiState  = WifiState.NORMAL
        self._green_state: GreenState = GreenState.ON

        self._led_tasks: dict[str, asyncio.Task] = {}
        self._button_callback: Callable | None = None
        self._running = False
        self._last_button_time = 0.0

    # ── Setup / Teardown ──────────────────────────────────────────────────────

    async def start(self) -> None:
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for pin in (self.pin_green, self.pin_blue, self.pin_yellow):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(self.pin_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._running = True
        asyncio.create_task(self._button_monitor())
        await self._refresh_all()
        log.info("GPIOManager started")

    async def stop(self) -> None:
        self._running = False
        for task in self._led_tasks.values():
            task.cancel()
        if GPIO_AVAILABLE:
            for pin in (self.pin_green, self.pin_blue, self.pin_yellow):
                GPIO.output(pin, GPIO.LOW)
            GPIO.cleanup()
        log.info("GPIOManager stopped")

    # ── State setters ─────────────────────────────────────────────────────────

    async def set_bluetooth_state(self, state: BlueState) -> None:
        if state == self._blue_state:
            return
        self._blue_state = state
        await self._restart_led("blue")

    async def set_wifi_state(self, state: WifiState) -> None:
        if state == self._wifi_state:
            return
        self._wifi_state = state
        await self._restart_led("yellow")

    async def set_green_state(self, state: GreenState) -> None:
        if state == self._green_state:
            return
        self._green_state = state
        await self._restart_led("green")

    def set_button_callback(self, cb: Callable) -> None:
        self._button_callback = cb

    # ── LED coroutines ────────────────────────────────────────────────────────

    async def _led_solid(self, pin: int) -> None:
        self._set_pin(pin, True)
        await asyncio.sleep(9999999)

    async def _led_off(self, pin: int) -> None:
        self._set_pin(pin, False)
        await asyncio.sleep(9999999)

    async def _led_blink(self, pin: int, on_t: float, off_t: float) -> None:
        while True:
            self._set_pin(pin, True)
            await asyncio.sleep(on_t)
            self._set_pin(pin, False)
            await asyncio.sleep(off_t)

    def _set_pin(self, pin: int, high: bool) -> None:
        if GPIO_AVAILABLE:
            GPIO.output(pin, GPIO.HIGH if high else GPIO.LOW)
        # else: simulation — log only at debug level to avoid spam
        # log.debug("PIN %d → %s", pin, "HIGH" if high else "LOW")

    async def _restart_led(self, name: str) -> None:
        old = self._led_tasks.get(name)
        if old and not old.done():
            old.cancel()
        coro = self._led_coro(name)
        self._led_tasks[name] = asyncio.create_task(coro)

    async def _refresh_all(self) -> None:
        for name in ("green", "blue", "yellow"):
            await self._restart_led(name)

    async def _led_coro(self, name: str) -> None:
        try:
            if name == "green":
                pin = self.pin_green
                if self._green_state == GreenState.ON:
                    await self._led_solid(pin)
                else:
                    await self._led_blink(pin, _STATE_ON, _STATE_OFF)

            elif name == "blue":
                pin = self.pin_blue
                if self._blue_state == BlueState.CONNECTED:
                    await self._led_solid(pin)
                elif self._blue_state == BlueState.DISCOVERABLE:
                    await self._led_blink(pin, _RAPID_ON, _RAPID_OFF)
                elif self._blue_state in (BlueState.IDLE, BlueState.OFF):
                    await self._led_blink(pin, _SLOW_ON, _SLOW_OFF)

            elif name == "yellow":
                pin = self.pin_yellow
                if self._wifi_state == WifiState.AP_MODE:
                    await self._led_solid(pin)
                else:
                    await self._led_off(pin)
        except asyncio.CancelledError:
            if GPIO_AVAILABLE:
                GPIO.output(
                    {"green": self.pin_green, "blue": self.pin_blue, "yellow": self.pin_yellow}[name],
                    GPIO.LOW,
                )

    # ── Button monitor ────────────────────────────────────────────────────────

    async def _button_monitor(self) -> None:
        """Poll the button pin (debounced). Calls callback on short press."""
        was_pressed = False
        press_start = 0.0
        DEBOUNCE = 0.05   # 50 ms
        LONG_PRESS = 2.0  # not currently used but reserved

        while self._running:
            await asyncio.sleep(DEBOUNCE)
            if not GPIO_AVAILABLE:
                continue
            pressed = GPIO.input(self.pin_button) == GPIO.LOW
            now = time.monotonic()

            if pressed and not was_pressed:
                press_start = now
                was_pressed = True
            elif not pressed and was_pressed:
                duration = now - press_start
                was_pressed = False
                # Guard: ignore spurious sub-50ms releases
                if duration < DEBOUNCE:
                    continue
                if self._button_callback:
                    try:
                        result = self._button_callback(
                            "long" if duration >= LONG_PRESS else "short"
                        )
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        log.exception("Button callback error: %s", exc)
