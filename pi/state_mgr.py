"""
State Manager — SQLite-backed persistence for BT-KBM.
Manages devices, macros, WiFi networks, settings, and audit log.
Thread-safe via aiosqlite.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = Path("/var/lib/bt-kbm/state.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS devices (
    mac         TEXT PRIMARY KEY,
    nickname    TEXT,
    trusted     INTEGER NOT NULL DEFAULT 1,
    auto_connect INTEGER NOT NULL DEFAULT 1,
    last_seen   REAL,
    first_seen  REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    conn_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS macros (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT 'General',
    icon        TEXT NOT NULL DEFAULT '⌨️',
    color       TEXT NOT NULL DEFAULT '#6366f1',
    hotkey      TEXT NOT NULL DEFAULT '',
    steps_json  TEXT NOT NULL DEFAULT '[]',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    updated_at  REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE TABLE IF NOT EXISTS wifi_networks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ssid        TEXT NOT NULL UNIQUE,
    psk         TEXT,          -- NULL means open network
    priority    INTEGER NOT NULL DEFAULT 0,
    added_at    REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    last_used   REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    action      TEXT NOT NULL,
    details     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_macros_cat ON macros(category);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "bt_device_name":          "BT-KBM",
    "bt_discoverable_timeout": "120",   # seconds; 0 = unlimited
    "led_brightness":          "100",   # percent
    "device_token":            "",      # generated on first run
    "ap_ssid":                 "BT-KBM-AP",
    "ap_password":             "bt-kbm-setup",
    "ap_channel":              "6",
    "open_network_autoconnect":"1",
    "pairing_button_gpio":     "18",
    "led_green_gpio":          "17",
    "led_blue_gpio":           "27",
    "led_yellow_gpio":         "22",
    "dashboard_username":      "admin",
    "dashboard_password_hash": "",      # bcrypt hash; set by install.sh
    "web_port":                "8080",
    "cf_tunnel_token":         "",
    "auto_reconnect_bt":       "1",
}


class StateManager:
    """Async SQLite state manager. Must be used as an async context manager."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "StateManager":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._init_defaults()
        await self._db.commit()
        log.info("StateManager opened: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ── Private helpers ──────────────────────────────────────────────────────

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StateManager not opened")
        return self._db

    async def _init_defaults(self) -> None:
        for key, val in DEFAULT_SETTINGS.items():
            await self.db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, val),
            )
        # Generate device token if missing
        async with self.db.execute(
            "SELECT value FROM settings WHERE key='device_token'"
        ) as cur:
            row = await cur.fetchone()
        if row and not row["value"]:
            token = str(uuid.uuid4())
            await self.db.execute(
                "UPDATE settings SET value=? WHERE key='device_token'",
                (token,),
            )
            log.info("Generated new device token: %s", token)

    # ── Settings ─────────────────────────────────────────────────────────────

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        async with self.db.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def update_settings(self, updates: dict[str, str]) -> None:
        async with self.db.executemany(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            list(updates.items()),
        ):
            pass
        await self.db.commit()

    # ── BT Devices ───────────────────────────────────────────────────────────

    async def upsert_device(self, mac: str, **kwargs: Any) -> None:
        """Insert or update a device record."""
        existing = await self.get_device(mac)
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [mac]
            await self.db.execute(
                f"UPDATE devices SET {sets} WHERE mac=?", vals
            )
        else:
            kwargs.setdefault("first_seen", time.time())
            cols = "mac, " + ", ".join(kwargs.keys())
            phs = "?, " + ", ".join("?" * len(kwargs))
            await self.db.execute(
                f"INSERT INTO devices ({cols}) VALUES ({phs})",
                [mac] + list(kwargs.values()),
            )
        await self.db.commit()

    async def device_connected(self, mac: str) -> None:
        """Record a new connection for mac."""
        await self.db.execute(
            """
            INSERT INTO devices(mac, last_seen, conn_count)
            VALUES (?, ?, 1)
            ON CONFLICT(mac) DO UPDATE SET
                last_seen = excluded.last_seen,
                conn_count = conn_count + 1
            """,
            (mac, time.time()),
        )
        await self.db.commit()

    async def get_device(self, mac: str) -> dict | None:
        async with self.db.execute(
            "SELECT * FROM devices WHERE mac=?", (mac,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_devices(self) -> list[dict]:
        async with self.db.execute(
            "SELECT * FROM devices ORDER BY last_seen DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_device(self, mac: str, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        sets = ", ".join(f"{k}=?" for k in kwargs)
        await self.db.execute(
            f"UPDATE devices SET {sets} WHERE mac=?",
            list(kwargs.values()) + [mac],
        )
        await self.db.commit()
        return self.db.total_changes > 0

    async def delete_device(self, mac: str) -> bool:
        await self.db.execute("DELETE FROM devices WHERE mac=?", (mac,))
        await self.db.commit()
        return self.db.total_changes > 0

    # ── Macros ───────────────────────────────────────────────────────────────

    async def list_macros(self, category: str | None = None) -> list[dict]:
        if category:
            async with self.db.execute(
                "SELECT * FROM macros WHERE category=? ORDER BY name", (category,)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute(
                "SELECT * FROM macros ORDER BY category, name"
            ) as cur:
                rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["steps"] = json.loads(d.pop("steps_json", "[]"))
            result.append(d)
        return result

    async def get_macro(self, macro_id: str) -> dict | None:
        async with self.db.execute(
            "SELECT * FROM macros WHERE id=?", (macro_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = json.loads(d.pop("steps_json", "[]"))
        return d

    async def create_macro(self, data: dict) -> str:
        macro_id = data.get("id") or str(uuid.uuid4())
        steps = json.dumps(data.get("steps", []))
        now = time.time()
        await self.db.execute(
            """
            INSERT INTO macros
                (id, name, description, category, icon, color, hotkey, steps_json, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                macro_id,
                data.get("name", "Untitled"),
                data.get("description", ""),
                data.get("category", "General"),
                data.get("icon", "⌨️"),
                data.get("color", "#6366f1"),
                data.get("hotkey", ""),
                steps,
                int(data.get("enabled", True)),
                now, now,
            ),
        )
        await self.db.commit()
        return macro_id

    async def update_macro(self, macro_id: str, data: dict) -> bool:
        fields: dict[str, Any] = {}
        for k in ("name", "description", "category", "icon", "color", "hotkey", "enabled"):
            if k in data:
                fields[k] = data[k]
        if "steps" in data:
            fields["steps_json"] = json.dumps(data["steps"])
        fields["updated_at"] = time.time()
        if not fields:
            return False
        sets = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE macros SET {sets} WHERE id=?",
            list(fields.values()) + [macro_id],
        )
        await self.db.commit()
        return True

    async def delete_macro(self, macro_id: str) -> bool:
        await self.db.execute("DELETE FROM macros WHERE id=?", (macro_id,))
        await self.db.commit()
        return self.db.total_changes > 0

    async def list_macro_categories(self) -> list[str]:
        async with self.db.execute(
            "SELECT DISTINCT category FROM macros ORDER BY category"
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    # ── WiFi Networks ─────────────────────────────────────────────────────────

    async def list_wifi_networks(self) -> list[dict]:
        async with self.db.execute(
            "SELECT * FROM wifi_networks ORDER BY priority DESC, added_at"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def add_wifi_network(self, ssid: str, psk: str | None = None, priority: int = 0) -> int:
        async with self.db.execute(
            "INSERT OR REPLACE INTO wifi_networks(ssid, psk, priority) VALUES (?, ?, ?)",
            (ssid, psk, priority),
        ) as cur:
            rowid = cur.lastrowid
        await self.db.commit()
        return rowid or 0

    async def remove_wifi_network(self, ssid: str) -> bool:
        await self.db.execute("DELETE FROM wifi_networks WHERE ssid=?", (ssid,))
        await self.db.commit()
        return self.db.total_changes > 0

    async def update_wifi_priority(self, priorities: list[tuple[str, int]]) -> None:
        await self.db.executemany(
            "UPDATE wifi_networks SET priority=? WHERE ssid=?",
            [(p, s) for s, p in priorities],
        )
        await self.db.commit()

    async def mark_wifi_used(self, ssid: str) -> None:
        await self.db.execute(
            "UPDATE wifi_networks SET last_used=? WHERE ssid=?",
            (time.time(), ssid),
        )
        await self.db.commit()

    # ── Audit Log ─────────────────────────────────────────────────────────────

    async def log_action(self, action: str, details: dict | None = None) -> None:
        await self.db.execute(
            "INSERT INTO audit_log(action, details) VALUES (?, ?)",
            (action, json.dumps(details or {})),
        )
        await self.db.commit()

    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        async with self.db.execute(
            "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d.get("details", "{}"))
            result.append(d)
        return result

    async def prune_audit_log(self, keep: int = 1000) -> None:
        await self.db.execute(
            "DELETE FROM audit_log WHERE id NOT IN "
            "(SELECT id FROM audit_log ORDER BY ts DESC LIMIT ?)",
            (keep,),
        )
        await self.db.commit()
