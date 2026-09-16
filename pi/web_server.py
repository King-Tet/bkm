"""
Web Server — aiohttp server exposing REST API + WebSocket for the BT-KBM dashboard.
Serves the SPA from /var/lib/bt-kbm/web/ (or ./web/ relative to this file).
Authentication: HTTP Basic Auth (configured via settings).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web, WSMsgType

if TYPE_CHECKING:
    from bt_hid import BtHIDDaemon
    from gpio_mgr import GPIOManager, BlueState, WifiState
    from macro_engine import MacroEngine
    from state_mgr import StateManager
    from wifi_mgr import WiFiManager

log = logging.getLogger(__name__)

_var_web = Path("/var/lib/bt-kbm/web")
_local_web = Path(__file__).parent / "web"
WEB_DIR = _var_web if _var_web.exists() and (_var_web / "index.html").exists() else _local_web
WS_CLIENTS: set[web.WebSocketResponse] = set()


class WebServer:
    def __init__(
        self,
        state:  "StateManager",
        hid:    "BtHIDDaemon",
        gpio:   "GPIOManager",
        wifi:   "WiFiManager",
        macros: "MacroEngine",
    ) -> None:
        self.state  = state
        self.hid    = hid
        self.gpio   = gpio
        self.wifi   = wifi
        self.macros = macros
        self._app   = web.Application(middlewares=[self._auth_middleware])
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._mirror_sessions: set[web.WebSocketResponse] = set()
        self._setup_routes()

    # ── Start / Stop ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        port = int(await self.state.get_setting("web_port", "8080"))
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", port)
        await self._site.start()
        log.info("Web server listening on http://0.0.0.0:%d", port)

    async def stop(self) -> None:
        # Close all open WS connections
        for ws in list(WS_CLIENTS):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    # ── Auth middleware ───────────────────────────────────────────────────────

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        # Skip auth for static SPA assets (but not API)
        if request.path.startswith("/static/") or request.path == "/favicon.ico":
            return await handler(request)

        # WebSocket upgrade: check token in query param OR Basic Auth
        if request.headers.get("Upgrade", "").lower() == "websocket":
            token = request.rel_url.query.get("token", "")
            if await self._check_token(token):
                return await handler(request)
            return web.Response(status=401, text="Unauthorized")

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode()
                username, password = decoded.split(":", 1)
                if await self._check_credentials(username, password):
                    return await handler(request)
            except Exception:
                pass
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="BT-KBM Dashboard"'},
            text="Unauthorized",
        )

    async def _check_credentials(self, username: str, password: str) -> bool:
        stored_user = await self.state.get_setting("dashboard_username", "admin")
        stored_hash = await self.state.get_setting("dashboard_password_hash", "")
        if username != stored_user:
            return False
        ph = hashlib.sha256(password.encode()).hexdigest()
        return ph == stored_hash

    async def _check_token(self, token: str) -> bool:
        """Check WebSocket upgrade token (session token from prior Basic Auth)."""
        stored = await self.state.get_setting("dashboard_password_hash", "")
        # Simple: accept device_token for Pi clients, or a session token
        device_tok = await self.state.get_setting("device_token", "")
        return token == device_tok or token == stored

    # ── Route setup ───────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        r = self._app.router
        # SPA shell
        r.add_get("/",        self._handle_index)
        r.add_get("/static/{filename:.*}", self._handle_static)

        # WebSocket hub
        r.add_get("/ws",      self._handle_ws)

        # API — status
        r.add_get("/api/status",         self._api_status)

        # API — Bluetooth
        r.add_post("/api/bt/pair",        self._api_bt_pair)
        r.add_post("/api/bt/stop-pair",   self._api_bt_stop_pair)
        r.add_post("/api/bt/disconnect",  self._api_bt_disconnect)
        r.add_post("/api/bt/reconnect",   self._api_bt_reconnect)

        # API — HID input
        r.add_post("/api/hid/keyboard",   self._api_hid_keyboard)
        r.add_post("/api/hid/mouse",      self._api_hid_mouse)
        r.add_post("/api/hid/consumer",   self._api_hid_consumer)
        r.add_post("/api/hid/text",       self._api_hid_text)

        # API — Devices
        r.add_get("/api/devices",         self._api_list_devices)
        r.add_patch("/api/devices/{mac}", self._api_update_device)
        r.add_delete("/api/devices/{mac}",self._api_delete_device)

        # API — Macros
        r.add_get("/api/macros",          self._api_list_macros)
        r.add_post("/api/macros",         self._api_create_macro)
        r.add_get("/api/macros/{id}",     self._api_get_macro)
        r.add_put("/api/macros/{id}",     self._api_update_macro)
        r.add_delete("/api/macros/{id}",  self._api_delete_macro)
        r.add_post("/api/macros/{id}/run",self._api_run_macro)
        r.add_post("/api/macros/{id}/stop",self._api_stop_macro)
        r.add_get("/api/macros/categories",self._api_macro_categories)
        r.add_post("/api/macros/import",  self._api_import_macros)
        r.add_get("/api/macros/export",   self._api_export_macros)

        # API — WiFi
        r.add_get("/api/wifi",            self._api_list_wifi)
        r.add_post("/api/wifi",           self._api_add_wifi)
        r.add_delete("/api/wifi/{ssid}",  self._api_delete_wifi)
        r.add_put("/api/wifi/order",      self._api_wifi_order)
        r.add_post("/api/wifi/scan",      self._api_wifi_scan)
        r.add_post("/api/wifi/connect",   self._api_wifi_connect)
        r.add_post("/api/wifi/disconnect",self._api_wifi_disconnect)
        r.add_get("/api/wifi/status",     self._api_wifi_status)

        # API — Settings
        r.add_get("/api/settings",        self._api_get_settings)
        r.add_put("/api/settings",        self._api_update_settings)

        # API — Audit Log
        r.add_get("/api/logs",            self._api_get_logs)

        # API — System
        r.add_post("/api/system/reboot",  self._api_reboot)

    # ── Static files ──────────────────────────────────────────────────────────

    async def _handle_index(self, _: web.Request) -> web.Response:
        p = WEB_DIR / "index.html"
        if not p.exists():
            for candidate in (Path("/var/lib/bt-kbm/web/index.html"), Path(__file__).parent / "web" / "index.html"):
                if candidate.exists():
                    p = candidate
                    break
        if not p.exists():
            return web.Response(status=500, text="BT-KBM dashboard static files (index.html) not found.")
        return web.Response(body=p.read_bytes(), content_type="text/html")

    async def _handle_static(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        p = WEB_DIR / filename
        if not p.exists() or not p.is_relative_to(WEB_DIR):
            raise web.HTTPNotFound()
        ctype = {
            ".css":  "text/css",
            ".js":   "application/javascript",
            ".png":  "image/png",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
            ".woff2":"font/woff2",
        }.get(p.suffix, "application/octet-stream")
        return web.Response(body=p.read_bytes(), content_type=ctype)

    # ── WebSocket hub ─────────────────────────────────────────────────────────

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        WS_CLIENTS.add(ws)
        log.info("WS client connected (%d total)", len(WS_CLIENTS))

        # Send current state to new client
        await ws.send_json({"type": "state", "data": await self._build_state()})

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_message(ws, msg.data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            WS_CLIENTS.discard(ws)
            self._mirror_sessions.discard(ws)
            log.info("WS client disconnected (%d remaining)", len(WS_CLIENTS))
        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        mtype = msg.get("type", "")

        if mtype == "keyboard":
            modifier = msg.get("modifier", 0)
            keycodes = msg.get("keycodes", [])
            self.hid.send_keyboard(modifier, keycodes)

        elif mtype == "keyboard_release":
            self.hid.send_keyboard_release()

        elif mtype == "mouse":
            self.hid.send_mouse(
                msg.get("buttons", 0),
                msg.get("x", 0),
                msg.get("y", 0),
                msg.get("wheel", 0),
            )

        elif mtype == "consumer":
            bitmask = msg.get("bitmask", 0)
            self.hid.send_consumer(bitmask)

        elif mtype == "text":
            text = msg.get("text", "")
            asyncio.create_task(self._type_text_ws(text))

        elif mtype == "mirror_start":
            self._mirror_sessions.add(ws)
            await ws.send_json({"type": "mirror_active", "active": True})

        elif mtype == "mirror_stop":
            self._mirror_sessions.discard(ws)
            self.hid.send_keyboard_release()
            await ws.send_json({"type": "mirror_active", "active": False})

        elif mtype == "mirror_key":
            # Mirror mode: browser-captured key event
            if ws in self._mirror_sessions:
                modifier = msg.get("modifier", 0)
                keycodes = msg.get("keycodes", [])
                pressed  = msg.get("pressed", True)
                if pressed:
                    self.hid.send_keyboard(modifier, keycodes)
                else:
                    self.hid.send_keyboard_release()

        elif mtype == "mirror_mouse":
            if ws in self._mirror_sessions:
                self.hid.send_mouse(
                    msg.get("buttons", 0),
                    msg.get("dx", 0),
                    msg.get("dy", 0),
                    msg.get("wheel", 0),
                )

        elif mtype == "macro_run":
            await self.macros.run(msg.get("id", ""))

        elif mtype == "macro_stop":
            await self.macros.stop(msg.get("id", ""))

        elif mtype == "pair":
            await self.hid.start_pairing(msg.get("timeout"))

        elif mtype == "ping":
            await ws.send_json({"type": "pong", "ts": time.time()})

    async def _type_text_ws(self, text: str) -> None:
        from hid_keycodes import char_to_hid
        for ch in text:
            mod, kc = char_to_hid(ch)
            if kc:
                self.hid.send_keyboard(mod, [kc])
                await asyncio.sleep(0.03)
                self.hid.send_keyboard_release()
            await asyncio.sleep(0.03)

    # ── Broadcast helpers ─────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        """Send a message to all connected WebSocket clients."""
        dead = set()
        for ws in WS_CLIENTS:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        WS_CLIENTS -= dead

    async def _build_state(self) -> dict:
        wifi_status = await self.wifi.get_status()
        devices     = await self.state.list_devices()
        settings    = await self.state.get_all_settings()
        return {
            "bt": {
                "connected":     self.hid.connected,
                "mac":           self.hid.connected_mac,
                "discoverable":  self.hid.discoverable,
            },
            "wifi": wifi_status,
            "devices": devices,
            "macros_running": self.macros.running_macros(),
            "uptime":  int(time.time()),
            "led": {
                "green":  self.gpio._green_state.name,
                "blue":   self.gpio._blue_state.name,
                "yellow": self.gpio._wifi_state.name,
            },
            "settings": {
                k: settings.get(k, "")
                for k in ("bt_device_name", "web_port", "ap_ssid", "led_brightness",
                          "open_network_autoconnect", "auto_reconnect_bt")
            },
        }

    # ── API: Status ───────────────────────────────────────────────────────────

    async def _api_status(self, _: web.Request) -> web.Response:
        return _json(await self._build_state())

    # ── API: Bluetooth ────────────────────────────────────────────────────────

    async def _api_bt_pair(self, request: web.Request) -> web.Response:
        body = await _body(request)
        timeout = body.get("timeout", None)
        await self.hid.start_pairing(timeout)
        await self.state.log_action("pair_start", {"timeout": timeout})
        await self.broadcast({"type": "bt_state", "discoverable": True})
        return _ok("Pairing started")

    async def _api_bt_stop_pair(self, _: web.Request) -> web.Response:
        await self.hid.stop_pairing()
        await self.broadcast({"type": "bt_state", "discoverable": False})
        return _ok("Pairing stopped")

    async def _api_bt_disconnect(self, _: web.Request) -> web.Response:
        mac = self.hid.connected_mac
        await self.hid.disconnect_device()
        await self.state.log_action("bt_disconnect", {"mac": mac})
        return _ok("Disconnected")

    async def _api_bt_reconnect(self, request: web.Request) -> web.Response:
        body = await _body(request)
        mac = body.get("mac", "")
        ok = await self.hid.reconnect(mac)
        return _json({"success": ok})

    # ── API: HID Input ────────────────────────────────────────────────────────

    async def _api_hid_keyboard(self, request: web.Request) -> web.Response:
        body = await _body(request)
        self.hid.send_keyboard(body.get("modifier", 0), body.get("keycodes", []))
        return _ok()

    async def _api_hid_mouse(self, request: web.Request) -> web.Response:
        body = await _body(request)
        self.hid.send_mouse(
            body.get("buttons", 0), body.get("x", 0),
            body.get("y", 0), body.get("wheel", 0),
        )
        return _ok()

    async def _api_hid_consumer(self, request: web.Request) -> web.Response:
        body = await _body(request)
        self.hid.send_consumer(body.get("bitmask", 0))
        return _ok()

    async def _api_hid_text(self, request: web.Request) -> web.Response:
        body = await _body(request)
        asyncio.create_task(self._type_text_ws(body.get("text", "")))
        return _ok()

    # ── API: Devices ──────────────────────────────────────────────────────────

    async def _api_list_devices(self, _: web.Request) -> web.Response:
        return _json(await self.state.list_devices())

    async def _api_update_device(self, request: web.Request) -> web.Response:
        mac  = request.match_info["mac"]
        body = await _body(request)
        allowed = ("nickname", "trusted", "auto_connect")
        update  = {k: v for k, v in body.items() if k in allowed}
        ok = await self.state.update_device(mac, **update)
        return _json({"success": ok})

    async def _api_delete_device(self, request: web.Request) -> web.Response:
        mac = request.match_info["mac"]
        ok  = await self.state.delete_device(mac)
        return _json({"success": ok})

    # ── API: Macros ───────────────────────────────────────────────────────────

    async def _api_list_macros(self, request: web.Request) -> web.Response:
        cat = request.rel_url.query.get("category")
        return _json(await self.state.list_macros(cat))

    async def _api_create_macro(self, request: web.Request) -> web.Response:
        body = await _body(request)
        mid = await self.state.create_macro(body)
        return _json({"id": mid}, status=201)

    async def _api_get_macro(self, request: web.Request) -> web.Response:
        m = await self.state.get_macro(request.match_info["id"])
        if not m:
            raise web.HTTPNotFound()
        return _json(m)

    async def _api_update_macro(self, request: web.Request) -> web.Response:
        ok = await self.state.update_macro(request.match_info["id"], await _body(request))
        return _json({"success": ok})

    async def _api_delete_macro(self, request: web.Request) -> web.Response:
        ok = await self.state.delete_macro(request.match_info["id"])
        return _json({"success": ok})

    async def _api_run_macro(self, request: web.Request) -> web.Response:
        ok = await self.macros.run(request.match_info["id"])
        return _json({"success": ok})

    async def _api_stop_macro(self, request: web.Request) -> web.Response:
        await self.macros.stop(request.match_info["id"])
        return _ok()

    async def _api_macro_categories(self, _: web.Request) -> web.Response:
        return _json(await self.state.list_macro_categories())

    async def _api_import_macros(self, request: web.Request) -> web.Response:
        body = await _body(request)
        macros_list = body if isinstance(body, list) else body.get("macros", [])
        ids = []
        for m in macros_list:
            m.pop("id", None)  # assign new ID
            mid = await self.state.create_macro(m)
            ids.append(mid)
        return _json({"imported": len(ids), "ids": ids}, status=201)

    async def _api_export_macros(self, _: web.Request) -> web.Response:
        macros = await self.state.list_macros()
        return _json(macros)

    # ── API: WiFi ─────────────────────────────────────────────────────────────

    async def _api_list_wifi(self, _: web.Request) -> web.Response:
        return _json(await self.state.list_wifi_networks())

    async def _api_add_wifi(self, request: web.Request) -> web.Response:
        body = await _body(request)
        nid = await self.state.add_wifi_network(
            body["ssid"], body.get("psk"), body.get("priority", 0)
        )
        return _json({"id": nid}, status=201)

    async def _api_delete_wifi(self, request: web.Request) -> web.Response:
        ssid = request.match_info["ssid"]
        ok   = await self.state.remove_wifi_network(ssid)
        return _json({"success": ok})

    async def _api_wifi_order(self, request: web.Request) -> web.Response:
        body = await _body(request)  # list of {ssid, priority}
        pairs = [(item["ssid"], item["priority"]) for item in body]
        await self.state.update_wifi_priority(pairs)
        return _ok()

    async def _api_wifi_scan(self, _: web.Request) -> web.Response:
        results = await self.wifi.scan()
        return _json([
            {"ssid": r.ssid, "bssid": r.bssid, "signal": r.signal, "open": r.open}
            for r in results
        ])

    async def _api_wifi_connect(self, request: web.Request) -> web.Response:
        body = await _body(request)
        ok = await self.wifi.connect(body["ssid"], body.get("psk"))
        await self.state.log_action("wifi_connect", {"ssid": body["ssid"], "ok": ok})
        return _json({"success": ok})

    async def _api_wifi_disconnect(self, _: web.Request) -> web.Response:
        await self.wifi.disconnect()
        return _ok()

    async def _api_wifi_status(self, _: web.Request) -> web.Response:
        return _json(await self.wifi.get_status())

    # ── API: Settings ─────────────────────────────────────────────────────────

    async def _api_get_settings(self, _: web.Request) -> web.Response:
        settings = await self.state.get_all_settings()
        # Never expose password hash over API
        settings.pop("dashboard_password_hash", None)
        settings.pop("device_token", None)
        return _json(settings)

    async def _api_update_settings(self, request: web.Request) -> web.Response:
        body = await _body(request)
        # Handle password change specially
        new_pw = body.pop("dashboard_password", None)
        if new_pw:
            body["dashboard_password_hash"] = hashlib.sha256(new_pw.encode()).hexdigest()
        PROTECTED = {"dashboard_password_hash", "device_token"}
        safe = {k: str(v) for k, v in body.items() if k not in PROTECTED}
        await self.state.update_settings(safe)
        await self.state.log_action("settings_updated", {"keys": list(safe.keys())})
        return _ok()

    # ── API: Logs ─────────────────────────────────────────────────────────────

    async def _api_get_logs(self, request: web.Request) -> web.Response:
        limit = int(request.rel_url.query.get("limit", "100"))
        return _json(await self.state.get_audit_log(limit))

    # ── API: System ───────────────────────────────────────────────────────────

    async def _api_reboot(self, _: web.Request) -> web.Response:
        await self.state.log_action("system_reboot", {})
        asyncio.create_task(_delayed_reboot())
        return _ok("Rebooting in 3 seconds…")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        body=json.dumps(data, default=str).encode(),
        content_type="application/json",
    )


def _ok(msg: str = "OK") -> web.Response:
    return _json({"ok": True, "message": msg})


async def _body(request: web.Request) -> dict | list:
    try:
        return await request.json()
    except Exception:
        return {}


async def _delayed_reboot() -> None:
    await asyncio.sleep(3)
    import subprocess
    subprocess.run(["sudo", "reboot"])
