"""
WiFi Manager — handles saved networks, open network scanning, AP mode fallback.

Boot priority:
  1. Saved networks (highest priority first)
  2. Open networks with verified internet access
  3. WiFi AP mode (fallback so user can configure from web UI)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state_mgr import StateManager

log = logging.getLogger(__name__)

WPA_CONF  = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
HOSTAPD_CONF    = Path("/etc/hostapd/hostapd.conf")
DNSMASQ_CONF    = Path("/etc/dnsmasq.conf")
HOSTAPD_DEFAULT = Path("/etc/default/hostapd")
IFACE = "wlan0"
PING_HOST = "1.1.1.1"
PING_TIMEOUT = 4  # seconds
CONNECT_TIMEOUT = 20  # seconds to wait for association
AP_IP = "192.168.50.1"
AP_SUBNET = "192.168.50.0/24"
AP_DHCP_START = "192.168.50.10"
AP_DHCP_END   = "192.168.50.50"


@dataclass
class ScanResult:
    ssid:    str
    bssid:   str
    signal:  int   # dBm
    open:    bool


class WiFiManager:
    def __init__(self, state: "StateManager") -> None:
        self.state = state
        self._ap_active = False
        self._connected_ssid: str | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def ap_active(self) -> bool:
        return self._ap_active

    @property
    def connected_ssid(self) -> str | None:
        return self._connected_ssid

    async def start(self) -> bool:
        """
        Boot-time connectivity logic.
        Returns True if WiFi is up (normal mode), False if AP mode was started.
        """
        log.info("WiFiManager: starting connectivity sequence")

        # 1. Try saved networks
        saved = await self.state.list_wifi_networks()
        if saved:
            for net in sorted(saved, key=lambda n: -n["priority"]):
                ok = await self._try_connect(net["ssid"], net["psk"])
                if ok:
                    await self.state.mark_wifi_used(net["ssid"])
                    self._connected_ssid = net["ssid"]
                    log.info("Connected to saved network: %s", net["ssid"])
                    return True

        # 2. Try open networks with internet
        auto = await self.state.get_setting("open_network_autoconnect", "1")
        if auto == "1":
            log.info("Scanning for open networks…")
            scans = await self.scan()
            open_nets = sorted(
                [s for s in scans if s.open], key=lambda s: -s.signal
            )
            for net in open_nets:
                ok = await self._try_connect(net.ssid, None)
                if ok and await self._check_internet():
                    self._connected_ssid = net.ssid
                    log.info("Connected to open network: %s", net.ssid)
                    return True
                elif ok:
                    log.info("Open network %s has no internet", net.ssid)
                    await self._disconnect()

        # 3. Fall back to AP mode
        log.warning("No networks found — starting AP mode")
        await self.start_ap()
        return False

    async def connect(self, ssid: str, psk: str | None = None) -> bool:
        """Connect to a WiFi network and persist it."""
        ok = await self._try_connect(ssid, psk)
        if ok:
            await self.state.add_wifi_network(ssid, psk, priority=10)
            await self.state.mark_wifi_used(ssid)
            self._connected_ssid = ssid
            if self._ap_active:
                await self.stop_ap()
        return ok

    async def disconnect(self) -> None:
        await self._disconnect()
        self._connected_ssid = None

    async def scan(self) -> list[ScanResult]:
        """Return visible WiFi networks."""
        try:
            raw = await _run(["sudo", "iwlist", IFACE, "scan"])
            return _parse_iwlist(raw)
        except Exception as exc:
            log.error("Scan failed: %s", exc)
            return []

    async def start_ap(self) -> None:
        if self._ap_active:
            return
        ssid = await self.state.get_setting("ap_ssid", "BT-KBM-AP")
        pwd  = await self.state.get_setting("ap_password", "bt-kbm-setup")
        ch   = await self.state.get_setting("ap_channel", "6")
        await self._write_hostapd_conf(ssid, pwd, ch)
        await self._write_dnsmasq_conf()
        await _run(["sudo", "ifconfig", IFACE, AP_IP])
        await _run(["sudo", "systemctl", "start", "hostapd"])
        await _run(["sudo", "systemctl", "start", "dnsmasq"])
        self._ap_active = True
        log.info("AP mode started: ssid=%s", ssid)

    async def stop_ap(self) -> None:
        if not self._ap_active:
            return
        await _run(["sudo", "systemctl", "stop", "hostapd"])
        await _run(["sudo", "systemctl", "stop", "dnsmasq"])
        self._ap_active = False
        log.info("AP mode stopped")

    async def get_status(self) -> dict:
        ip = await self._get_ip()
        return {
            "ap_active":       self._ap_active,
            "connected_ssid":  self._connected_ssid,
            "ip_address":      ip,
            "ap_ip":           AP_IP if self._ap_active else None,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _try_connect(self, ssid: str, psk: str | None) -> bool:
        try:
            await self._write_wpa_conf(ssid, psk)
            await _run(["sudo", "wpa_cli", "-i", IFACE, "reconfigure"])
            deadline = time.monotonic() + CONNECT_TIMEOUT
            while time.monotonic() < deadline:
                await asyncio.sleep(1)
                status = await _run(["wpa_cli", "-i", IFACE, "status"])
                if "wpa_state=COMPLETED" in status:
                    await _run(["sudo", "dhclient", "-1", IFACE])
                    return True
            return False
        except Exception as exc:
            log.error("Connection attempt failed (%s): %s", ssid, exc)
            return False

    async def _disconnect(self) -> None:
        try:
            await _run(["sudo", "wpa_cli", "-i", IFACE, "disconnect"])
        except Exception:
            pass

    async def _check_internet(self) -> bool:
        try:
            result = await _run(
                ["ping", "-c", "1", "-W", str(PING_TIMEOUT), PING_HOST]
            )
            return "1 received" in result or "1 packets transmitted, 1 received" in result
        except Exception:
            return False

    async def _get_ip(self) -> str:
        try:
            out = await _run(["hostname", "-I"])
            ips = out.strip().split()
            return ips[0] if ips else ""
        except Exception:
            return ""

    async def _write_wpa_conf(self, ssid: str, psk: str | None) -> None:
        country = "US"
        try:
            existing = WPA_CONF.read_text()
            m = re.search(r"country=(\w+)", existing)
            if m:
                country = m.group(1)
        except Exception:
            pass

        lines = [
            f"country={country}",
            "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev",
            "update_config=1",
            "network={",
        ]
        lines.append(f'    ssid="{ssid}"')
        if psk:
            lines.append(f'    psk="{psk}"')
        else:
            lines.append("    key_mgmt=NONE")
        lines.append("    priority=1")
        lines.append("}")
        content = "\n".join(lines) + "\n"
        proc = await asyncio.create_subprocess_exec(
            "sudo", "tee", str(WPA_CONF),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(content.encode())

    async def _write_hostapd_conf(self, ssid: str, password: str, channel: str) -> None:
        conf = (
            f"interface={IFACE}\n"
            f"driver=nl80211\n"
            f"ssid={ssid}\n"
            f"hw_mode=g\n"
            f"channel={channel}\n"
            f"wpa=2\n"
            f"wpa_passphrase={password}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"wpa_pairwise=TKIP\n"
            f"rsn_pairwise=CCMP\n"
            f"ieee80211n=1\n"
            f"wmm_enabled=1\n"
        )
        proc = await asyncio.create_subprocess_exec(
            "sudo", "tee", str(HOSTAPD_CONF),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(conf.encode())

    async def _write_dnsmasq_conf(self) -> None:
        conf = (
            f"interface={IFACE}\n"
            f"dhcp-range={AP_DHCP_START},{AP_DHCP_END},255.255.255.0,24h\n"
            f"address=/#/{AP_IP}\n"  # captive portal: all DNS → AP IP
        )
        proc = await asyncio.create_subprocess_exec(
            "sudo", "tee", str(DNSMASQ_CONF),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(conf.encode())


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip())
    return stdout.decode()


def _parse_iwlist(raw: str) -> list[ScanResult]:
    results = []
    cells = re.split(r"Cell \d+ -", raw)
    for cell in cells[1:]:
        ssid_m  = re.search(r'ESSID:"([^"]*)"', cell)
        bssid_m = re.search(r"Address: ([\w:]+)", cell)
        sig_m   = re.search(r"Signal level=(-?\d+)", cell)
        enc_m   = re.search(r"Encryption key:(on|off)", cell)
        if not ssid_m or not bssid_m:
            continue
        ssid  = ssid_m.group(1)
        bssid = bssid_m.group(1)
        sig   = int(sig_m.group(1)) if sig_m else -100
        enc   = enc_m.group(1) == "off" if enc_m else True
        results.append(ScanResult(ssid=ssid, bssid=bssid, signal=sig, open=enc))
    return results
