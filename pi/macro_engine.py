"""
Macro Engine — advanced multi-step macro runner for BT-KBM.

Step types:
  TYPE         — type a string character by character
  KEY          — send a key combo (e.g. "Ctrl+Shift+T")
  KEY_DOWN     — hold a key (no release)
  KEY_UP       — release a held key
  MOUSE_MOVE   — relative mouse movement
  MOUSE_CLICK  — mouse button click (with optional hold/release)
  MOUSE_SCROLL — scroll wheel
  DELAY        — wait N milliseconds (supports jitter)
  LOOP         — repeat enclosed steps N times (or infinite)
  LOOP_END     — marks end of a LOOP
  CONDITION    — if/else based on a variable
  CONDITION_ELSE / CONDITION_END
  SHELL        — run a shell command, store stdout in variable
  SET_VAR      — set a macro variable
  CONSUMER     — send a media/consumer key

Built-in variables: $DATE, $TIME, $TIMESTAMP, $DEVICE_NAME, $CONNECTED_MAC
User variables: any $VARNAME set with SET_VAR
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
import shlex
import subprocess
from typing import TYPE_CHECKING, Any

from hid_keycodes import (
    parse_combo, char_to_hid,
    CONSUMER_NAME_MAP,
    MOUSE_BTN_LEFT, MOUSE_BTN_RIGHT, MOUSE_BTN_MIDDLE,
)

if TYPE_CHECKING:
    from bt_hid import BtHIDDaemon
    from state_mgr import StateManager

log = logging.getLogger(__name__)

STEP_TYPE_MAP = {
    "TYPE", "KEY", "KEY_DOWN", "KEY_UP",
    "MOUSE_MOVE", "MOUSE_CLICK", "MOUSE_SCROLL",
    "DELAY", "LOOP", "LOOP_END",
    "CONDITION", "CONDITION_ELSE", "CONDITION_END",
    "SHELL", "SET_VAR", "CONSUMER",
}

CHAR_DELAY_MS   = 30   # default ms between typed characters
KEY_HOLD_MS     = 50   # default key hold time


class MacroEngine:
    def __init__(self, hid: "BtHIDDaemon", state: "StateManager") -> None:
        self.hid   = hid
        self.state = state
        self._running: dict[str, asyncio.Task] = {}  # macro_id → task
        self._stop_flags: dict[str, bool] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, macro_id: str) -> bool:
        """Run a macro by ID. Returns False if macro not found or already running."""
        if macro_id in self._running:
            log.warning("Macro %s already running", macro_id)
            return False
        macro = await self.state.get_macro(macro_id)
        if not macro:
            log.error("Macro %s not found", macro_id)
            return False
        self._stop_flags[macro_id] = False
        task = asyncio.create_task(self._execute(macro_id, macro))
        self._running[macro_id] = task
        task.add_done_callback(lambda _: self._running.pop(macro_id, None))
        await self.state.log_action("macro_run", {"id": macro_id, "name": macro["name"]})
        return True

    async def stop(self, macro_id: str) -> None:
        """Signal a running macro to stop."""
        self._stop_flags[macro_id] = True
        task = self._running.get(macro_id)
        if task:
            task.cancel()

    async def stop_all(self) -> None:
        for mid in list(self._running):
            await self.stop(mid)

    def is_running(self, macro_id: str) -> bool:
        return macro_id in self._running

    def running_macros(self) -> list[str]:
        return list(self._running.keys())

    # ── Execution engine ──────────────────────────────────────────────────────

    async def _execute(self, macro_id: str, macro: dict) -> None:
        steps: list[dict] = macro.get("steps", [])
        vars_: dict[str, str] = {}
        try:
            await self._run_steps(steps, vars_, macro_id)
        except asyncio.CancelledError:
            log.info("Macro %s cancelled", macro_id)
        except Exception as exc:
            log.exception("Macro %s error: %s", macro_id, exc)
        finally:
            # Release any held keys on exit
            self.hid.send_keyboard_release()
            self._stop_flags.pop(macro_id, None)

    async def _run_steps(
        self, steps: list[dict], vars_: dict[str, str], macro_id: str
    ) -> None:
        i = 0
        while i < len(steps):
            if self._stop_flags.get(macro_id):
                return
            step = steps[i]
            stype = step.get("type", "").upper()

            if stype == "TYPE":
                text = self._resolve_vars(step.get("text", ""), vars_)
                delay = step.get("delay_ms", CHAR_DELAY_MS)
                await self._type_text(text, delay)

            elif stype == "KEY":
                combo = self._resolve_vars(step.get("combo", ""), vars_)
                hold = step.get("hold_ms", KEY_HOLD_MS)
                await self._send_combo(combo, hold)

            elif stype == "KEY_DOWN":
                combo = self._resolve_vars(step.get("combo", ""), vars_)
                mod, kc = parse_combo(combo)
                self.hid.send_keyboard(mod, [kc] if kc else [])

            elif stype == "KEY_UP":
                self.hid.send_keyboard_release()

            elif stype == "MOUSE_MOVE":
                x = int(self._resolve_vars(str(step.get("x", 0)), vars_))
                y = int(self._resolve_vars(str(step.get("y", 0)), vars_))
                steps_n = step.get("steps", 1)
                await self._mouse_move(x, y, steps_n)

            elif stype == "MOUSE_CLICK":
                btn_name = step.get("button", "left").lower()
                btn = {"left": MOUSE_BTN_LEFT, "right": MOUSE_BTN_RIGHT,
                       "middle": MOUSE_BTN_MIDDLE}.get(btn_name, MOUSE_BTN_LEFT)
                double = step.get("double", False)
                hold_ms = step.get("hold_ms", 50)
                await self._mouse_click(btn, hold_ms, double)

            elif stype == "MOUSE_SCROLL":
                amount = int(self._resolve_vars(str(step.get("amount", 3)), vars_))
                direction = step.get("direction", "down")
                wheel = -amount if direction == "down" else amount
                self.hid.send_mouse(0, 0, 0, wheel)

            elif stype == "DELAY":
                ms = int(self._resolve_vars(str(step.get("ms", 100)), vars_))
                jitter = int(step.get("jitter_ms", 0))
                if jitter > 0:
                    import random
                    ms += random.randint(-jitter, jitter)
                await asyncio.sleep(max(0, ms) / 1000)

            elif stype == "LOOP":
                count = step.get("count", 1)
                if count == 0:
                    count = 999_999  # "infinite" (use stop to break)
                # Find matching LOOP_END
                end_idx = self._find_loop_end(steps, i)
                inner = steps[i + 1:end_idx]
                for _ in range(count):
                    if self._stop_flags.get(macro_id):
                        return
                    await self._run_steps(inner, vars_, macro_id)
                i = end_idx  # skip past LOOP_END

            elif stype == "CONDITION":
                var_name  = step.get("var", "")
                operator  = step.get("op", "eq")
                value     = self._resolve_vars(step.get("value", ""), vars_)
                actual    = vars_.get(var_name, "")
                condition_true = self._eval_condition(actual, operator, value)
                # Find CONDITION_ELSE and CONDITION_END
                else_idx, end_idx = self._find_condition_bounds(steps, i)
                if condition_true:
                    branch = steps[i + 1 : else_idx if else_idx >= 0 else end_idx]
                else:
                    branch = steps[else_idx + 1 : end_idx] if else_idx >= 0 else []
                await self._run_steps(branch, vars_, macro_id)
                i = end_idx

            elif stype == "SHELL":
                cmd = self._resolve_vars(step.get("cmd", ""), vars_)
                out_var = step.get("output_var", "")
                timeout = step.get("timeout_s", 10)
                try:
                    result = subprocess.run(
                        shlex.split(cmd), capture_output=True, text=True, timeout=timeout
                    )
                    output = result.stdout.strip()
                except subprocess.TimeoutExpired:
                    output = ""
                if out_var:
                    vars_[out_var] = output

            elif stype == "SET_VAR":
                name  = step.get("name", "")
                value = self._resolve_vars(step.get("value", ""), vars_)
                if name:
                    vars_[name] = value

            elif stype == "CONSUMER":
                key_name = step.get("key", "").lower().replace(" ", "").replace("_", "")
                bitmask = CONSUMER_NAME_MAP.get(key_name, 0)
                if bitmask:
                    self.hid.send_consumer(bitmask)
                    await asyncio.sleep(0.1)
                    self.hid.send_consumer_release()

            i += 1

    # ── HID helpers ───────────────────────────────────────────────────────────

    async def _type_text(self, text: str, delay_ms: int = CHAR_DELAY_MS) -> None:
        for ch in text:
            mod, kc = char_to_hid(ch)
            if kc:
                self.hid.send_keyboard(mod, [kc])
                await asyncio.sleep(0.05)
                self.hid.send_keyboard_release()
            await asyncio.sleep(delay_ms / 1000)

    async def _send_combo(self, combo: str, hold_ms: int = KEY_HOLD_MS) -> None:
        mod, kc = parse_combo(combo)
        self.hid.send_keyboard(mod, [kc] if kc else [])
        await asyncio.sleep(hold_ms / 1000)
        self.hid.send_keyboard_release()
        await asyncio.sleep(0.02)

    async def _mouse_move(self, x: int, y: int, steps: int = 1) -> None:
        """Smoothly move mouse by x, y in `steps` increments."""
        if steps < 1:
            steps = 1
        dx = x // steps
        dy = y // steps
        for _ in range(steps):
            self.hid.send_mouse(0, dx, dy)
            await asyncio.sleep(0.01)

    async def _mouse_click(self, button: int, hold_ms: int, double: bool) -> None:
        clicks = 2 if double else 1
        for _ in range(clicks):
            self.hid.send_mouse(button, 0, 0)
            await asyncio.sleep(hold_ms / 1000)
            self.hid.send_mouse(0, 0, 0)
            await asyncio.sleep(0.05)

    # ── Variable resolution ───────────────────────────────────────────────────

    def _resolve_vars(self, text: str, local_vars: dict[str, str]) -> str:
        """Replace $VAR references with values. Built-ins take priority."""
        now = datetime.datetime.now()
        builtins = {
            "DATE":         now.strftime("%Y-%m-%d"),
            "TIME":         now.strftime("%H:%M:%S"),
            "TIMESTAMP":    str(int(now.timestamp())),
            "DEVICE_NAME":  self.hid.connected_mac or "none",
            "CONNECTED_MAC": self.hid.connected_mac or "none",
        }
        all_vars = {**local_vars, **builtins}

        def replace(m: re.Match) -> str:
            name = m.group(1)
            return all_vars.get(name, m.group(0))

        return re.sub(r"\$(\w+)", replace, text)

    # ── Structural helpers ────────────────────────────────────────────────────

    @staticmethod
    def _find_loop_end(steps: list[dict], loop_idx: int) -> int:
        depth = 0
        for i in range(loop_idx, len(steps)):
            t = steps[i].get("type", "").upper()
            if t == "LOOP":
                depth += 1
            elif t == "LOOP_END":
                depth -= 1
                if depth == 0:
                    return i
        return len(steps) - 1

    @staticmethod
    def _find_condition_bounds(steps: list[dict], cond_idx: int) -> tuple[int, int]:
        """Returns (else_idx, end_idx). else_idx=-1 if no ELSE."""
        depth = 0
        else_idx = -1
        for i in range(cond_idx, len(steps)):
            t = steps[i].get("type", "").upper()
            if t == "CONDITION":
                depth += 1
            elif t == "CONDITION_ELSE" and depth == 1:
                else_idx = i
            elif t == "CONDITION_END":
                depth -= 1
                if depth == 0:
                    return else_idx, i
        return else_idx, len(steps) - 1

    @staticmethod
    def _eval_condition(actual: str, op: str, value: str) -> bool:
        try:
            a, b = float(actual), float(value)
            numeric = True
        except ValueError:
            a, b = actual, value
            numeric = False

        if op in ("eq", "=="):
            return actual == value
        if op in ("ne", "!="):
            return actual != value
        if op in ("contains",):
            return value.lower() in actual.lower()
        if op in ("startswith",):
            return actual.startswith(value)
        if op in ("endswith",):
            return actual.endswith(value)
        if numeric:
            if op in ("gt", ">"):  return a > b
            if op in ("lt", "<"):  return a < b
            if op in ("gte", ">="): return a >= b
            if op in ("lte", "<="): return a <= b
        return False
