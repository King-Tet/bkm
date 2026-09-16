"""
Bluetooth HID Daemon — BlueZ D-Bus Bluetooth keyboard+mouse emulator.

Registers a combined HID profile with BlueZ, handles:
- Pairing / discoverable mode
- Multi-device tracking (one active at a time)
- Keyboard reports (Report ID 1)
- Mouse reports   (Report ID 2)
- Consumer/media  (Report ID 3)
- Auto-reconnect to last trusted device
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

if TYPE_CHECKING:
    from state_mgr import StateManager

log = logging.getLogger(__name__)

# BlueZ D-Bus constants
BUS_NAME        = "org.bluez"
AGENT_IFACE     = "org.bluez.Agent1"
ADAPTER_IFACE   = "org.bluez.Adapter1"
DEVICE_IFACE    = "org.bluez.Device1"
PROFILE_IFACE   = "org.bluez.Profile1"
PROFILE_MGR_IFACE = "org.bluez.ProfileManager1"

HID_UUID = "00001124-0000-1000-8000-00805f9b34fb"

# HID L2CAP PSMs
PSM_CTRL  = 17
PSM_INTR  = 19

# Report IDs
RPT_KEYBOARD  = 0x01
RPT_MOUSE     = 0x02
RPT_CONSUMER  = 0x03

# Combined HID Report Descriptor for keyboard + mouse + consumer
HID_REPORT_DESCRIPTOR = bytes([
    # ── Keyboard (Report ID 1) ──────────────────────────────────────────────
    0x05, 0x01,        # Usage Page (Generic Desktop Ctrls)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)
    # Modifier keys (8 bits)
    0x05, 0x07,        #   Usage Page (Kbrd/Keypad)
    0x19, 0xE0,        #   Usage Minimum (Keyboard Left Control)
    0x29, 0xE7,        #   Usage Maximum (Keyboard Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data, Var, Abs)
    # Reserved byte
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x08,        #   Report Size (8)
    0x81, 0x01,        #   Input (Const, Array, Abs)
    # 6-key rollover
    0x95, 0x06,        #   Report Count (6)
    0x75, 0x08,        #   Report Size (8)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x65,        #   Logical Maximum (101)
    0x05, 0x07,        #   Usage Page (Kbrd/Keypad)
    0x19, 0x00,        #   Usage Minimum (0)
    0x29, 0x65,        #   Usage Maximum (101)
    0x81, 0x00,        #   Input (Data, Array, Abs)
    0xC0,              # End Collection

    # ── Mouse (Report ID 2) ─────────────────────────────────────────────────
    0x05, 0x01,        # Usage Page (Generic Desktop Ctrls)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x02,        #   Report ID (2)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    # 3 buttons
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (Button 1 - Left)
    0x29, 0x03,        #     Usage Maximum (Button 3 - Middle)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x75, 0x01,        #     Report Size (1)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x02,        #     Input (Data, Var, Abs)
    # Padding to byte boundary
    0x75, 0x05,        #     Report Size (5)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x01,        #     Input (Const, Array, Abs)
    # X, Y, Wheel (relative, -127..127)
    0x05, 0x01,        #     Usage Page (Generic Desktop Ctrls)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x06,        #     Input (Data, Var, Rel)
    0xC0,              #   End Collection
    0xC0,              # End Collection

    # ── Consumer / Media (Report ID 3) ──────────────────────────────────────
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x03,        #   Report ID (3)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x10,        #   Report Count (16)
    0x09, 0xB5,        #   Usage (Scan Next Track)
    0x09, 0xB6,        #   Usage (Scan Previous Track)
    0x09, 0xB7,        #   Usage (Stop)
    0x09, 0xCD,        #   Usage (Play/Pause)
    0x09, 0xE2,        #   Usage (Mute)
    0x09, 0xE9,        #   Usage (Volume Increment)
    0x09, 0xEA,        #   Usage (Volume Decrement)
    0x09, 0xB8,        #   Usage (Eject)
    0x09, 0xB3,        #   Usage (Fast Forward)
    0x09, 0xB4,        #   Usage (Rewind)
    0x09, 0x83,        #   Usage (AL Consumer Control Config)
    0x09, 0x92,        #   Usage (AL Calculator)
    0x09, 0x94,        #   Usage (AL Local Machine Browser)
    0x09, 0x8A,        #   Usage (AL Email Reader)
    0x09, 0x221,       #   Usage (AC Search) -- 2 bytes
    0x81, 0x02,        #   Input (Data, Var, Abs)
    0xC0,              # End Collection
])

SDP_RECORD_PATH = Path(__file__).parent / "sdp_record.xml"


class BtHIDDaemon:
    """
    Manages the Bluetooth HID peripheral role via BlueZ D-Bus.
    """

    def __init__(self, state: "StateManager") -> None:
        self.state = state
        self._ctrl_sock: socket.socket | None = None
        self._intr_sock: socket.socket | None = None
        self._ctrl_conn: socket.socket | None = None
        self._intr_conn: socket.socket | None = None
        self._connected_mac: str | None = None
        self._discoverable = False
        self._running = False
        self._connection_callbacks: list[Callable] = []
        self._disconnection_callbacks: list[Callable] = []

        # BlueZ D-Bus objects (set up in start())
        self._bus: dbus.SystemBus | None = None
        self._adapter = None
        self._adapter_props = None
        self._device_name = "BT-KBM"
        self._mainloop: GLib.MainLoop | None = None
        self._glib_thread: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SystemBus()
        self._device_name = await self.state.get_setting("bt_device_name", "BT-KBM")

        await self._configure_adapter()
        await self._register_sdp()
        await asyncio.to_thread(self._setup_sockets)
        self._running = True
        asyncio.create_task(self._accept_loop())
        log.info("BtHIDDaemon started, device name: %s", self._device_name)

    async def stop(self) -> None:
        self._running = False
        self._close_connection()
        if self._ctrl_sock:
            self._ctrl_sock.close()
        if self._intr_sock:
            self._intr_sock.close()
        log.info("BtHIDDaemon stopped")

    # ── Pairing control ───────────────────────────────────────────────────────

    async def start_pairing(self, timeout: int | None = None) -> None:
        """Make device discoverable and pairable."""
        if timeout is None:
            timeout = int(await self.state.get_setting("bt_discoverable_timeout", "120"))
        await asyncio.to_thread(self._set_adapter_props, {
            "Discoverable": dbus.Boolean(True),
            "Pairable":     dbus.Boolean(True),
            "DiscoverableTimeout": dbus.UInt32(timeout),
        })
        self._discoverable = True
        log.info("Bluetooth pairing started (timeout=%ds)", timeout)
        for cb in self._connection_callbacks:
            asyncio.create_task(cb("pairing_started", None))

    async def stop_pairing(self) -> None:
        await asyncio.to_thread(self._set_adapter_props, {
            "Discoverable": dbus.Boolean(False),
            "Pairable":     dbus.Boolean(False),
        })
        self._discoverable = False
        log.info("Bluetooth pairing stopped")

    async def disconnect_device(self) -> None:
        """Disconnect the currently connected HID client."""
        if self._connected_mac:
            try:
                obj = self._bus.get_object(BUS_NAME, self._mac_to_path(self._connected_mac))
                dev = dbus.Interface(obj, DEVICE_IFACE)
                await asyncio.to_thread(dev.Disconnect)
            except Exception as exc:
                log.warning("Disconnect error: %s", exc)
        self._close_connection()

    async def reconnect(self, mac: str) -> bool:
        """Try to reconnect to a previously paired device."""
        try:
            obj = self._bus.get_object(BUS_NAME, self._mac_to_path(mac))
            dev = dbus.Interface(obj, DEVICE_IFACE)
            await asyncio.to_thread(dev.Connect)
            return True
        except Exception as exc:
            log.warning("Reconnect failed (%s): %s", mac, exc)
            return False

    # ── HID Report senders ────────────────────────────────────────────────────

    def send_keyboard(self, modifier: int, keycodes: list[int]) -> bool:
        """
        Send a keyboard HID report.
        modifier: bitmask of modifier keys
        keycodes: list of up to 6 HID usage codes
        """
        if not self._intr_conn:
            return False
        keys = (keycodes + [0, 0, 0, 0, 0, 0])[:6]
        report = bytes([0xA1, RPT_KEYBOARD, modifier, 0x00] + keys)
        return self._send_report(report)

    def send_keyboard_release(self) -> bool:
        """Release all keys."""
        return self.send_keyboard(0, [])

    def send_mouse(self, buttons: int, x: int, y: int, wheel: int = 0) -> bool:
        """
        Send a mouse HID report.
        buttons: bitmask (1=left, 2=right, 4=middle)
        x, y, wheel: relative movement (-127..127)
        """
        if not self._intr_conn:
            return False
        x     = max(-127, min(127, x))
        y     = max(-127, min(127, y))
        wheel = max(-127, min(127, wheel))
        report = struct.pack("BBBBBBB",
            0xA1, RPT_MOUSE, buttons,
            x & 0xFF, y & 0xFF, wheel & 0xFF, 0x00  # pad
        )
        return self._send_report(report)

    def send_consumer(self, bitmask: int) -> bool:
        """
        Send a consumer/media key report.
        bitmask: 16-bit bitmask from hid_keycodes.CONS_* constants
        """
        if not self._intr_conn:
            return False
        lo = bitmask & 0xFF
        hi = (bitmask >> 8) & 0xFF
        report = bytes([0xA1, RPT_CONSUMER, lo, hi])
        return self._send_report(report)

    def send_consumer_release(self) -> bool:
        return self.send_consumer(0)

    def _send_report(self, data: bytes) -> bool:
        try:
            self._intr_conn.sendall(data)
            return True
        except OSError as exc:
            log.error("HID send error: %s", exc)
            self._close_connection()
            return False

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_connection(self, cb: Callable) -> None:
        self._connection_callbacks.append(cb)

    def on_disconnection(self, cb: Callable) -> None:
        self._disconnection_callbacks.append(cb)

    @property
    def connected(self) -> bool:
        return self._intr_conn is not None

    @property
    def connected_mac(self) -> str | None:
        return self._connected_mac

    @property
    def discoverable(self) -> bool:
        return self._discoverable

    # ── Internal: BlueZ setup ─────────────────────────────────────────────────

    async def _configure_adapter(self) -> None:
        """Find the adapter, set name, power it on."""
        manager = dbus.Interface(
            self._bus.get_object(BUS_NAME, "/"),
            "org.freedesktop.DBus.ObjectManager",
        )
        objects = await asyncio.to_thread(manager.GetManagedObjects)
        adapter_path = None
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces:
                adapter_path = path
                break
        if not adapter_path:
            raise RuntimeError("No Bluetooth adapter found via D-Bus")

        self._adapter = dbus.Interface(
            self._bus.get_object(BUS_NAME, adapter_path), ADAPTER_IFACE
        )
        self._adapter_props = dbus.Interface(
            self._bus.get_object(BUS_NAME, adapter_path),
            "org.freedesktop.DBus.Properties",
        )
        await asyncio.to_thread(self._set_adapter_props, {
            "Powered": dbus.Boolean(True),
            "Alias":   dbus.String(self._device_name),
            "Discoverable": dbus.Boolean(False),
            "Pairable": dbus.Boolean(False),
        })
        log.info("BT adapter configured at %s", adapter_path)

    def _set_adapter_props(self, props: dict) -> None:
        for k, v in props.items():
            self._adapter_props.Set(ADAPTER_IFACE, k, v)

    async def _register_sdp(self) -> None:
        """Register HID SDP record using sdptool (BlueZ compat mode)."""
        if not SDP_RECORD_PATH.exists():
            log.warning("SDP record not found at %s — skipping", SDP_RECORD_PATH)
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "sdptool", "add", "--handle=0x00010001",
                "--sdp-record", str(SDP_RECORD_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.warning("sdptool error: %s", stderr.decode())
            else:
                log.info("SDP record registered")
        except FileNotFoundError:
            log.warning("sdptool not found — SDP record not registered")

    def _setup_sockets(self) -> None:
        """Open raw L2CAP sockets on PSM 17 and 19."""
        for sock_attr, psm in (("_ctrl_sock", PSM_CTRL), ("_intr_sock", PSM_INTR)):
            s = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_SEQPACKET,
                socket.BTPROTO_L2CAP,
            )
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", psm))
            s.listen(1)
            s.setblocking(False)
            setattr(self, sock_attr, s)
        log.info("L2CAP sockets listening on PSM %d (ctrl) and %d (intr)", PSM_CTRL, PSM_INTR)

    # ── Internal: connection loop ─────────────────────────────────────────────

    async def _accept_loop(self) -> None:
        loop = asyncio.get_event_loop()
        log.info("HID accept loop running")
        while self._running:
            try:
                ctrl_conn, ctrl_addr = await loop.sock_accept(self._ctrl_sock)
                intr_conn, intr_addr = await loop.sock_accept(self._intr_sock)
                mac = ctrl_addr[0]
                log.info("HID connection from %s", mac)
                self._ctrl_conn = ctrl_conn
                self._intr_conn = intr_conn
                self._connected_mac = mac
                self._discoverable = False

                # Record in DB
                await self.state.device_connected(mac)
                await self.state.log_action("bt_connected", {"mac": mac})

                for cb in self._connection_callbacks:
                    asyncio.create_task(cb("connected", mac))

                # Monitor for disconnection
                asyncio.create_task(self._monitor_connection(mac))
            except OSError as exc:
                if self._running:
                    log.error("Accept error: %s", exc)
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    async def _monitor_connection(self, mac: str) -> None:
        """Watch for HID client disconnect."""
        loop = asyncio.get_event_loop()
        try:
            while self._running:
                try:
                    data = await loop.sock_recv(self._ctrl_conn, 256)
                    if not data:
                        break
                except OSError:
                    break
                await asyncio.sleep(0.1)
        finally:
            log.info("HID client %s disconnected", mac)
            self._close_connection()
            await self.state.log_action("bt_disconnected", {"mac": mac})
            for cb in self._disconnection_callbacks:
                asyncio.create_task(cb("disconnected", mac))

    def _close_connection(self) -> None:
        for attr in ("_ctrl_conn", "_intr_conn"):
            sock = getattr(self, attr, None)
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, attr, None)
        self._connected_mac = None

    @staticmethod
    def _mac_to_path(mac: str) -> str:
        return "/org/bluez/hci0/dev_" + mac.replace(":", "_")
