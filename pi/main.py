"""
BT-KBM Main Orchestrator — starts all services and coordinates state.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/bt-kbm.log"),
    ],
)
log = logging.getLogger("bt-kbm")

from state_mgr    import StateManager
from gpio_mgr     import GPIOManager, BlueState, GreenState, WifiState
from wifi_mgr     import WiFiManager
from bt_hid       import BtHIDDaemon
from macro_engine import MacroEngine
from web_server   import WebServer


async def main() -> None:
    log.info("═══ BT-KBM starting ═══")

    async with StateManager() as state:
        # ── Read GPIO config from settings ────────────────────────────────────
        pin_green  = int(await state.get_setting("led_green_gpio",      "17"))
        pin_blue   = int(await state.get_setting("led_blue_gpio",       "27"))
        pin_yellow = int(await state.get_setting("led_yellow_gpio",     "22"))
        pin_button = int(await state.get_setting("pairing_button_gpio", "18"))
        brightness = int(await state.get_setting("led_brightness",      "100")) / 100

        # ── GPIO ──────────────────────────────────────────────────────────────
        gpio = GPIOManager(pin_green, pin_blue, pin_yellow, pin_button, brightness)
        await gpio.start()
        await gpio.set_green_state(GreenState.STATE_CHANGE)

        # ── Components ────────────────────────────────────────────────────────
        hid = BtHIDDaemon(state)
        wifi = WiFiManager(state)
        macros = MacroEngine(hid, state)

        # ── Web Server (Start first so dashboard is immediately accessible) ───
        server = WebServer(state, hid, gpio, wifi, macros)
        await server.start()
        log.info("Web server listening on port 8080")

        # ── GPIO Button callback ──────────────────────────────────────────────
        async def button_pressed(press_type: str) -> None:
            if press_type == "short":
                if hid.discoverable:
                    await hid.stop_pairing()
                    await gpio.set_bluetooth_state(BlueState.IDLE)
                    log.info("Button: stopped pairing")
                else:
                    await hid.start_pairing()
                    await gpio.set_bluetooth_state(BlueState.DISCOVERABLE)
                    log.info("Button: started pairing")
            await server.broadcast({
                "type": "bt_state",
                "discoverable": hid.discoverable,
                "connected": hid.connected,
            })

        gpio.set_button_callback(button_pressed)

        # ── WiFi init ─────────────────────────────────────────────────────────
        try:
            wifi_ok = await wifi.start()
            if wifi_ok:
                await gpio.set_wifi_state(WifiState.NORMAL)
                log.info("WiFi connected: %s", wifi.connected_ssid)
            else:
                await gpio.set_wifi_state(WifiState.AP_MODE)
                log.info("WiFi AP mode active")
        except Exception as exc:
            log.error("WiFi startup warning: %s", exc)

        # ── Bluetooth HID init ────────────────────────────────────────────────
        try:
            async def on_bt_event(event: str, mac: str | None) -> None:
                if event == "connected":
                    await gpio.set_bluetooth_state(BlueState.CONNECTED)
                    await state.log_action("bt_connected", {"mac": mac})
                    await server.broadcast({
                        "type": "bt_state",
                        "connected": True,
                        "mac": mac,
                        "discoverable": False,
                    })
                    log.info("BT connected: %s", mac)
                    dev = await state.get_device(mac or "")
                    if dev:
                        await server.broadcast({"type": "device_update", "device": dev})

                elif event == "disconnected":
                    await gpio.set_bluetooth_state(BlueState.IDLE)
                    await state.log_action("bt_disconnected", {"mac": mac})
                    await server.broadcast({"type": "bt_state", "connected": False, "mac": mac})
                    log.info("BT disconnected: %s", mac)
                    auto = await state.get_setting("auto_reconnect_bt", "1")
                    if auto == "1" and mac:
                        dev = await state.get_device(mac)
                        if dev and dev.get("auto_connect"):
                            log.info("Auto-reconnecting to %s…", mac)
                            asyncio.create_task(_auto_reconnect(hid, mac))

                elif event == "pairing_started":
                    await gpio.set_bluetooth_state(BlueState.DISCOVERABLE)

            hid.on_connection(on_bt_event)
            hid.on_disconnection(on_bt_event)
            await hid.start()
            await gpio.set_bluetooth_state(BlueState.IDLE)
        except Exception as exc:
            log.error("Bluetooth HID startup warning: %s", exc)

        # ── All up — green solid ──────────────────────────────────────────────
        await gpio.set_green_state(GreenState.ON)
        log.info("═══ BT-KBM ready ═══")

        # ── Cloudflare tunnel (if token configured) ───────────────────────────
        cf_token = await state.get_setting("cf_tunnel_token", "")
        if cf_token:
            asyncio.create_task(_run_tunnel(cf_token))

        # ── State broadcast loop ──────────────────────────────────────────────
        asyncio.create_task(_state_broadcast_loop(server))

        # ── Run forever ───────────────────────────────────────────────────────
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("Shutting down…")
        finally:
            await server.stop()
            await hid.stop()
            await gpio.stop()
            await state.prune_audit_log()
            log.info("BT-KBM stopped cleanly")


async def _auto_reconnect(hid: "BtHIDDaemon", mac: str, retries: int = 5) -> None:
    for i in range(retries):
        await asyncio.sleep(5 * (i + 1))
        if hid.connected:
            return
        log.info("Auto-reconnect attempt %d/%d to %s", i + 1, retries, mac)
        ok = await hid.reconnect(mac)
        if ok:
            return
    log.info("Auto-reconnect gave up for %s", mac)


async def _state_broadcast_loop(server: "WebServer") -> None:
    """Broadcast state to all WS clients every 15 seconds."""
    while True:
        await asyncio.sleep(15)
        try:
            state = await server._build_state()
            await server.broadcast({"type": "state", "data": state})
        except Exception as exc:
            log.warning("State broadcast error: %s", exc)


async def _run_tunnel(token: str) -> None:
    """Start cloudflared tunnel with the stored token."""
    log.info("Starting Cloudflare tunnel…")
    proc = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--no-autoupdate", "run",
        "--token", token,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        log.info("[cloudflared] %s", line.decode().rstrip())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
