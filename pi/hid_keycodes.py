"""
HID Keycode Tables
Full mapping of key names → HID usage codes for keyboard, modifier keys,
consumer/media keys, and mouse buttons.
"""

# ── Modifier bitmasks (byte 0 of keyboard report) ──────────────────────────
MOD_NONE       = 0x00
MOD_LCTRL      = 0x01
MOD_LSHIFT     = 0x02
MOD_LALT       = 0x04
MOD_LMETA      = 0x08  # Win / Cmd
MOD_RCTRL      = 0x10
MOD_RSHIFT     = 0x20
MOD_RALT       = 0x40  # AltGr
MOD_RMETA      = 0x80

# ── Keyboard HID usage codes (byte 2-7 of keyboard report) ─────────────────
KEY_NONE       = 0x00
KEY_ERR_OVF    = 0x01

KEY_A          = 0x04
KEY_B          = 0x05
KEY_C          = 0x06
KEY_D          = 0x07
KEY_E          = 0x08
KEY_F          = 0x09
KEY_G          = 0x0A
KEY_H          = 0x0B
KEY_I          = 0x0C
KEY_J          = 0x0D
KEY_K          = 0x0E
KEY_L          = 0x0F
KEY_M          = 0x10
KEY_N          = 0x11
KEY_O          = 0x12
KEY_P          = 0x13
KEY_Q          = 0x14
KEY_R          = 0x15
KEY_S          = 0x16
KEY_T          = 0x17
KEY_U          = 0x18
KEY_V          = 0x19
KEY_W          = 0x1A
KEY_X          = 0x1B
KEY_Y          = 0x1C
KEY_Z          = 0x1D

KEY_1          = 0x1E
KEY_2          = 0x1F
KEY_3          = 0x20
KEY_4          = 0x21
KEY_5          = 0x22
KEY_6          = 0x23
KEY_7          = 0x24
KEY_8          = 0x25
KEY_9          = 0x26
KEY_0          = 0x27

KEY_ENTER      = 0x28
KEY_ESC        = 0x29
KEY_BACKSPACE  = 0x2A
KEY_TAB        = 0x2B
KEY_SPACE      = 0x2C
KEY_MINUS      = 0x2D   # -/_
KEY_EQUAL      = 0x2E   # =/+
KEY_LEFTBRACE  = 0x2F   # [/{
KEY_RIGHTBRACE = 0x30   # ]/}
KEY_BACKSLASH  = 0x31   # \/|
KEY_HASHTILDE  = 0x32   # Non-US #/~
KEY_SEMICOLON  = 0x33   # ;/:
KEY_APOSTROPHE = 0x34   # '/"
KEY_GRAVE      = 0x35   # `/~
KEY_COMMA      = 0x36   # ,/<
KEY_DOT        = 0x37   # ./>
KEY_SLASH      = 0x38   # //?

KEY_CAPSLOCK   = 0x39

KEY_F1         = 0x3A
KEY_F2         = 0x3B
KEY_F3         = 0x3C
KEY_F4         = 0x3D
KEY_F5         = 0x3E
KEY_F6         = 0x3F
KEY_F7         = 0x40
KEY_F8         = 0x41
KEY_F9         = 0x42
KEY_F10        = 0x43
KEY_F11        = 0x44
KEY_F12        = 0x45
KEY_F13        = 0x68
KEY_F14        = 0x69
KEY_F15        = 0x6A
KEY_F16        = 0x6B
KEY_F17        = 0x6C
KEY_F18        = 0x6D
KEY_F19        = 0x6E
KEY_F20        = 0x6F
KEY_F21        = 0x70
KEY_F22        = 0x71
KEY_F23        = 0x72
KEY_F24        = 0x73

KEY_SYSRQ      = 0x46   # Print Screen
KEY_SCROLLLOCK = 0x47
KEY_PAUSE      = 0x48
KEY_INSERT     = 0x49
KEY_HOME       = 0x4A
KEY_PAGEUP     = 0x4B
KEY_DELETE     = 0x4C
KEY_END        = 0x4D
KEY_PAGEDOWN   = 0x4E
KEY_RIGHT      = 0x4F
KEY_LEFT       = 0x50
KEY_DOWN       = 0x51
KEY_UP         = 0x52

KEY_NUMLOCK    = 0x53
KEY_KP_SLASH   = 0x54
KEY_KP_STAR    = 0x55
KEY_KP_MINUS   = 0x56
KEY_KP_PLUS    = 0x57
KEY_KP_ENTER   = 0x58
KEY_KP_1       = 0x59
KEY_KP_2       = 0x5A
KEY_KP_3       = 0x5B
KEY_KP_4       = 0x5C
KEY_KP_5       = 0x5D
KEY_KP_6       = 0x5E
KEY_KP_7       = 0x5F
KEY_KP_8       = 0x60
KEY_KP_9       = 0x61
KEY_KP_0       = 0x62
KEY_KP_DOT     = 0x63

KEY_COMPOSE    = 0x65   # Application key
KEY_POWER      = 0x66
KEY_KP_EQUAL   = 0x67

KEY_MENU       = 0x76

# ── Modifier key codes (also usable as regular keycodes in byte 2-7) ────────
KEY_LEFTCTRL   = 0xE0
KEY_LEFTSHIFT  = 0xE1
KEY_LEFTALT    = 0xE2
KEY_LEFTMETA   = 0xE3
KEY_RIGHTCTRL  = 0xE4
KEY_RIGHTSHIFT = 0xE5
KEY_RIGHTALT   = 0xE6
KEY_RIGHTMETA  = 0xE7

# ── Consumer / Media key bitmasks (Report ID 3, 2-byte bitmap) ──────────────
# Bit positions for the consumer report
CONS_NEXT_TRACK     = (1 << 0)
CONS_PREV_TRACK     = (1 << 1)
CONS_STOP           = (1 << 2)
CONS_PLAY_PAUSE     = (1 << 3)
CONS_MUTE           = (1 << 4)
CONS_VOL_UP         = (1 << 5)
CONS_VOL_DOWN       = (1 << 6)
CONS_EJECT          = (1 << 7)
CONS_FAST_FORWARD   = (1 << 8)
CONS_REWIND         = (1 << 9)
CONS_STOP_EJECT     = (1 << 10)  # AL Consumer Control Config
CONS_CALCULATOR     = (1 << 11)
CONS_BROWSER        = (1 << 12)
CONS_EMAIL          = (1 << 13)  # AL Email Reader
CONS_PAUSE          = (1 << 14)  # Pause (not Play/Pause)
CONS_RECORD         = (1 << 15)

# ── Mouse button bitmasks (byte 0 of mouse report) ──────────────────────────
MOUSE_BTN_LEFT   = 0x01
MOUSE_BTN_RIGHT  = 0x02
MOUSE_BTN_MIDDLE = 0x04

# ── String → keycode lookup (for macro text-to-key parsing) ─────────────────
KEY_NAME_MAP: dict[str, tuple[int, int]] = {
    # Format: "name": (modifier_bitmask, keycode)

    # Letters (lowercase = no mod, uppercase = shift)
    "a": (MOD_NONE, KEY_A),   "A": (MOD_LSHIFT, KEY_A),
    "b": (MOD_NONE, KEY_B),   "B": (MOD_LSHIFT, KEY_B),
    "c": (MOD_NONE, KEY_C),   "C": (MOD_LSHIFT, KEY_C),
    "d": (MOD_NONE, KEY_D),   "D": (MOD_LSHIFT, KEY_D),
    "e": (MOD_NONE, KEY_E),   "E": (MOD_LSHIFT, KEY_E),
    "f": (MOD_NONE, KEY_F),   "F": (MOD_LSHIFT, KEY_F),
    "g": (MOD_NONE, KEY_G),   "G": (MOD_LSHIFT, KEY_G),
    "h": (MOD_NONE, KEY_H),   "H": (MOD_LSHIFT, KEY_H),
    "i": (MOD_NONE, KEY_I),   "I": (MOD_LSHIFT, KEY_I),
    "j": (MOD_NONE, KEY_J),   "J": (MOD_LSHIFT, KEY_J),
    "k": (MOD_NONE, KEY_K),   "K": (MOD_LSHIFT, KEY_K),
    "l": (MOD_NONE, KEY_L),   "L": (MOD_LSHIFT, KEY_L),
    "m": (MOD_NONE, KEY_M),   "M": (MOD_LSHIFT, KEY_M),
    "n": (MOD_NONE, KEY_N),   "N": (MOD_LSHIFT, KEY_N),
    "o": (MOD_NONE, KEY_O),   "O": (MOD_LSHIFT, KEY_O),
    "p": (MOD_NONE, KEY_P),   "P": (MOD_LSHIFT, KEY_P),
    "q": (MOD_NONE, KEY_Q),   "Q": (MOD_LSHIFT, KEY_Q),
    "r": (MOD_NONE, KEY_R),   "R": (MOD_LSHIFT, KEY_R),
    "s": (MOD_NONE, KEY_S),   "S": (MOD_LSHIFT, KEY_S),
    "t": (MOD_NONE, KEY_T),   "T": (MOD_LSHIFT, KEY_T),
    "u": (MOD_NONE, KEY_U),   "U": (MOD_LSHIFT, KEY_U),
    "v": (MOD_NONE, KEY_V),   "V": (MOD_LSHIFT, KEY_V),
    "w": (MOD_NONE, KEY_W),   "W": (MOD_LSHIFT, KEY_W),
    "x": (MOD_NONE, KEY_X),   "X": (MOD_LSHIFT, KEY_X),
    "y": (MOD_NONE, KEY_Y),   "Y": (MOD_LSHIFT, KEY_Y),
    "z": (MOD_NONE, KEY_Z),   "Z": (MOD_LSHIFT, KEY_Z),

    # Numbers
    "1": (MOD_NONE, KEY_1),  "!": (MOD_LSHIFT, KEY_1),
    "2": (MOD_NONE, KEY_2),  "@": (MOD_LSHIFT, KEY_2),
    "3": (MOD_NONE, KEY_3),  "#": (MOD_LSHIFT, KEY_3),
    "4": (MOD_NONE, KEY_4),  "$": (MOD_LSHIFT, KEY_4),
    "5": (MOD_NONE, KEY_5),  "%": (MOD_LSHIFT, KEY_5),
    "6": (MOD_NONE, KEY_6),  "^": (MOD_LSHIFT, KEY_6),
    "7": (MOD_NONE, KEY_7),  "&": (MOD_LSHIFT, KEY_7),
    "8": (MOD_NONE, KEY_8),  "*": (MOD_LSHIFT, KEY_8),
    "9": (MOD_NONE, KEY_9),  "(": (MOD_LSHIFT, KEY_9),
    "0": (MOD_NONE, KEY_0),  ")": (MOD_LSHIFT, KEY_0),

    # Symbols
    " ":  (MOD_NONE,   KEY_SPACE),
    "\n": (MOD_NONE,   KEY_ENTER),
    "\t": (MOD_NONE,   KEY_TAB),
    "-":  (MOD_NONE,   KEY_MINUS),  "_": (MOD_LSHIFT, KEY_MINUS),
    "=":  (MOD_NONE,   KEY_EQUAL),  "+": (MOD_LSHIFT, KEY_EQUAL),
    "[":  (MOD_NONE,   KEY_LEFTBRACE),  "{": (MOD_LSHIFT, KEY_LEFTBRACE),
    "]":  (MOD_NONE,   KEY_RIGHTBRACE), "}": (MOD_LSHIFT, KEY_RIGHTBRACE),
    "\\": (MOD_NONE,   KEY_BACKSLASH),  "|": (MOD_LSHIFT, KEY_BACKSLASH),
    ";":  (MOD_NONE,   KEY_SEMICOLON),  ":": (MOD_LSHIFT, KEY_SEMICOLON),
    "'":  (MOD_NONE,   KEY_APOSTROPHE), "\"": (MOD_LSHIFT, KEY_APOSTROPHE),
    "`":  (MOD_NONE,   KEY_GRAVE),      "~": (MOD_LSHIFT, KEY_GRAVE),
    ",":  (MOD_NONE,   KEY_COMMA),      "<": (MOD_LSHIFT, KEY_COMMA),
    ".":  (MOD_NONE,   KEY_DOT),        ">": (MOD_LSHIFT, KEY_DOT),
    "/":  (MOD_NONE,   KEY_SLASH),      "?": (MOD_LSHIFT, KEY_SLASH),
}

# Named key lookup (for macro step "KEY" type, e.g. "Ctrl+Shift+T")
NAMED_KEY_MAP: dict[str, int] = {
    "enter": KEY_ENTER, "return": KEY_ENTER,
    "esc": KEY_ESC, "escape": KEY_ESC,
    "backspace": KEY_BACKSPACE, "bksp": KEY_BACKSPACE,
    "tab": KEY_TAB,
    "space": KEY_SPACE,
    "capslock": KEY_CAPSLOCK, "caps": KEY_CAPSLOCK,
    "f1":  KEY_F1,  "f2":  KEY_F2,  "f3":  KEY_F3,  "f4":  KEY_F4,
    "f5":  KEY_F5,  "f6":  KEY_F6,  "f7":  KEY_F7,  "f8":  KEY_F8,
    "f9":  KEY_F9,  "f10": KEY_F10, "f11": KEY_F11, "f12": KEY_F12,
    "f13": KEY_F13, "f14": KEY_F14, "f15": KEY_F15, "f16": KEY_F16,
    "f17": KEY_F17, "f18": KEY_F18, "f19": KEY_F19, "f20": KEY_F20,
    "f21": KEY_F21, "f22": KEY_F22, "f23": KEY_F23, "f24": KEY_F24,
    "printscreen": KEY_SYSRQ, "prtsc": KEY_SYSRQ, "sysrq": KEY_SYSRQ,
    "scrolllock": KEY_SCROLLLOCK,
    "pause": KEY_PAUSE, "break": KEY_PAUSE,
    "insert": KEY_INSERT, "ins": KEY_INSERT,
    "home": KEY_HOME,
    "pageup": KEY_PAGEUP, "pgup": KEY_PAGEUP,
    "delete": KEY_DELETE, "del": KEY_DELETE,
    "end": KEY_END,
    "pagedown": KEY_PAGEDOWN, "pgdn": KEY_PAGEDOWN,
    "right": KEY_RIGHT, "rightarrow": KEY_RIGHT,
    "left":  KEY_LEFT,  "leftarrow":  KEY_LEFT,
    "down":  KEY_DOWN,  "downarrow":  KEY_DOWN,
    "up":    KEY_UP,    "uparrow":    KEY_UP,
    "numlock": KEY_NUMLOCK,
    "kpslash": KEY_KP_SLASH,
    "kpstar":  KEY_KP_STAR,
    "kpminus": KEY_KP_MINUS,
    "kpplus":  KEY_KP_PLUS,
    "kpenter": KEY_KP_ENTER,
    "kp0": KEY_KP_0, "kp1": KEY_KP_1, "kp2": KEY_KP_2,
    "kp3": KEY_KP_3, "kp4": KEY_KP_4, "kp5": KEY_KP_5,
    "kp6": KEY_KP_6, "kp7": KEY_KP_7, "kp8": KEY_KP_8,
    "kp9": KEY_KP_9, "kpdot": KEY_KP_DOT, "kpequal": KEY_KP_EQUAL,
    "menu": KEY_MENU, "app": KEY_COMPOSE, "compose": KEY_COMPOSE,
    "power": KEY_POWER,
    # Modifier names (for use in combos)
    "ctrl":  KEY_LEFTCTRL,  "control": KEY_LEFTCTRL,
    "shift": KEY_LEFTSHIFT,
    "alt":   KEY_LEFTALT,
    "win":   KEY_LEFTMETA,  "meta": KEY_LEFTMETA, "cmd": KEY_LEFTMETA,
    "rctrl": KEY_RIGHTCTRL,
    "rshift": KEY_RIGHTSHIFT,
    "ralt":  KEY_RIGHTALT,  "altgr": KEY_RIGHTALT,
    "rwin":  KEY_RIGHTMETA, "rmeta": KEY_RIGHTMETA,
}

MODIFIER_KEY_SET = {
    "ctrl", "control", "shift", "alt", "win", "meta", "cmd",
    "rctrl", "rshift", "ralt", "altgr", "rwin", "rmeta",
}

MODIFIER_NAME_MAP: dict[str, int] = {
    "ctrl":    MOD_LCTRL,   "control": MOD_LCTRL,
    "shift":   MOD_LSHIFT,
    "alt":     MOD_LALT,
    "win":     MOD_LMETA,   "meta": MOD_LMETA,  "cmd": MOD_LMETA,
    "rctrl":   MOD_RCTRL,
    "rshift":  MOD_RSHIFT,
    "ralt":    MOD_RALT,    "altgr": MOD_RALT,
    "rwin":    MOD_RMETA,   "rmeta": MOD_RMETA,
}

CONSUMER_NAME_MAP: dict[str, int] = {
    "nexttrack":     CONS_NEXT_TRACK,
    "prevtrack":     CONS_PREV_TRACK,
    "stop":          CONS_STOP,
    "playpause":     CONS_PLAY_PAUSE,
    "mute":          CONS_MUTE,
    "volumeup":      CONS_VOL_UP,
    "volumedown":    CONS_VOL_DOWN,
    "eject":         CONS_EJECT,
    "fastforward":   CONS_FAST_FORWARD,
    "rewind":        CONS_REWIND,
    "calculator":    CONS_CALCULATOR,
    "browser":       CONS_BROWSER,
    "email":         CONS_EMAIL,
    "pause":         CONS_PAUSE,
    "record":        CONS_RECORD,
}


def parse_combo(combo: str) -> tuple[int, int]:
    """
    Parse a key combo string like "Ctrl+Shift+T" into (modifier_mask, keycode).
    Also handles consumer key names like "PlayPause".
    Returns (modifier_mask, keycode). For consumer keys returns (0, consumer_bitmask)
    but tagged differently — caller should check.
    """
    parts = [p.strip().lower() for p in combo.split("+")]
    modifier = MOD_NONE
    keycode = KEY_NONE

    for part in parts:
        if part in MODIFIER_NAME_MAP:
            modifier |= MODIFIER_NAME_MAP[part]
        elif part in NAMED_KEY_MAP:
            keycode = NAMED_KEY_MAP[part]
        elif len(part) == 1 and part in KEY_NAME_MAP:
            mod_extra, keycode = KEY_NAME_MAP[part]
            modifier |= mod_extra
        else:
            # Try as single character
            if len(part) == 1:
                ch = combo.split("+")[-1]  # preserve case for single char
                if ch in KEY_NAME_MAP:
                    mod_extra, keycode = KEY_NAME_MAP[ch]
                    modifier |= mod_extra
    return modifier, keycode


def char_to_hid(ch: str) -> tuple[int, int]:
    """Convert a single character to (modifier, keycode)."""
    if ch in KEY_NAME_MAP:
        return KEY_NAME_MAP[ch]
    return MOD_NONE, KEY_NONE
