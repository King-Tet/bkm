# BT-KBM — Bluetooth Virtual Keyboard & Mouse
### Raspberry Pi Zero W → `kbm.play-tap.com`

A complete Bluetooth HID peripheral system. The Pi presents itself as a combined wireless keyboard + mouse to any Bluetooth host device, controlled through a premium web dashboard accessible from anywhere via Cloudflare Tunnel.

---

## Hardware Requirements

| Part | Notes |
|---|---|
| Raspberry Pi Zero W | Built-in BT 4.1 + 2.4GHz WiFi |
| MicroSD card | ≥8GB, Class 10 or better |
| Green LED + 220Ω resistor | Power/state indicator |
| Blue LED + 220Ω resistor | Bluetooth state |
| Yellow LED + 220Ω resistor | WiFi AP mode indicator |
| Tactile push button | Pairing trigger |
| 5V micro-USB power supply | Min 1A |

### Wiring (default GPIO — changeable in Settings)

```
GPIO 17  → Green LED (+ → 220Ω → LED → GND)
GPIO 27  → Blue LED
GPIO 22  → Yellow LED
GPIO 18  → Button (one leg to GPIO 18, other to GND)
```

---

## OS Setup

> **Required OS:** Raspberry Pi OS Lite, 64-bit (Bookworm)
> Download from: https://www.raspberrypi.com/software/

1. Flash the image to your SD card using Raspberry Pi Imager
2. In Imager settings (⚙ icon), set:
   - Hostname: `bt-kbm`
   - Enable SSH
   - Set your WiFi SSID + password (so Pi can connect on first boot)
   - Set username/password (e.g. `pi` / your password)
3. Boot the Pi, SSH in: `ssh pi@bt-kbm.local`

---

## Installation

```bash
# Clone this repo to the Pi
git clone https://github.com/YOUR_USER/bt-kbm.git
cd bt-kbm/pi

# Run the installer (takes ~3 minutes)
sudo bash install.sh
```

The installer will:
- Install all system packages (`bluez`, `hostapd`, `dnsmasq`, `cloudflared`, etc.)
- Configure BlueZ for HID peripheral mode (with `--compat` flag)
- Create Python venv at `/opt/bt-kbm/venv`
- Set up the database with default admin credentials
- Install and enable the `bt-kbm` systemd service
- Print your Pi's IP addresses

**Default dashboard login:** `admin` / `changeme123`  
⚠️ Change the password immediately in Settings!

---

## Cloudflare Tunnel Setup (to access `kbm.play-tap.com`)

Two methods — choose one:

### Method A: Token (Easiest)
1. Log into Cloudflare Zero Trust → Networks → Tunnels → **Create a tunnel**
2. Name it `bt-kbm`
3. Copy the tunnel token shown on screen
4. Open the dashboard at `http://<pi-ip>:8080`
5. Go to **Settings → Cloudflare Tunnel Token** and paste it
6. Click **Save All Settings**
7. In the Cloudflare tunnel config, add a **Public Hostname**:
   - Subdomain: `kbm`, Domain: `play-tap.com`
   - Service: `http://localhost:8080`

### Method B: CLI
```bash
cloudflared tunnel login
cloudflared tunnel create bt-kbm
cloudflared tunnel route dns bt-kbm kbm.play-tap.com
# Then edit ~/cloudflared/config.yml with your tunnel UUID
cloudflared service install
systemctl start cloudflared
```

After setup, the dashboard is available at `https://kbm.play-tap.com`.

---

## Dashboard Features

### Overview
Real-time status: Bluetooth connection, WiFi info, LED states, activity log.

### Keyboard Page
- Full virtual keyboard (F1–F24, numpad, modifier keys, arrows, nav cluster, media keys)
- Hold-key mode for modifier combos
- **Send Text** — type a string and it's sent character by character
- Media key buttons (play/pause, volume, next/prev, etc.)

### Mouse Page
- Trackpad with configurable speed
- Left / Middle / Right click buttons
- Scroll up/down buttons
- Touch-friendly (works on mobile)

### Mirror Mode
- Captures your browser's keyboard and mouse events
- Forwards everything to the connected Bluetooth device in real time
- Configurable key filter (block certain keys from forwarding)
- Adjustable mouse sensitivity
- Live event log + statistics (keys sent, mouse events, duration)

### Macros
Fully advanced macro builder with:

| Step Type | Description |
|---|---|
| `TYPE` | Type a string (per-char delay, variable interpolation) |
| `KEY` | Send a key combo (e.g. `Ctrl+Shift+T`) |
| `KEY_DOWN` / `KEY_UP` | Hold / release a key |
| `MOUSE_MOVE` | Relative mouse movement with smooth steps |
| `MOUSE_CLICK` | Click left/right/middle (with double-click + hold duration) |
| `MOUSE_SCROLL` | Scroll wheel up/down |
| `DELAY` | Wait N ms (with optional ±jitter) |
| `LOOP` / `LOOP_END` | Repeat steps N times (0 = infinite) |
| `CONDITION` / `CONDITION_ELSE` / `CONDITION_END` | If/else branching |
| `SHELL` | Run a shell command, capture output to variable |
| `SET_VAR` | Set a macro variable |
| `CONSUMER` | Send a media/consumer key |

**Built-in variables:** `$DATE`, `$TIME`, `$TIMESTAMP`, `$DEVICE_NAME`, `$CONNECTED_MAC`

Macros can be imported/exported as JSON.

### Devices
- Lists all previously paired Bluetooth devices
- Add nicknames to each device
- Toggle trusted / auto-connect per device
- Manual reconnect button
- Forget device

### WiFi
- Saved networks list (with priority ordering)
- Live network scanner
- Add networks (open or secured)
- One-click connect to scanned networks
- AP Mode configuration (SSID, password, channel)
- Toggle auto-connect to open networks with internet

### Settings
- BT device name (what shows up when pairing)
- Pairing timeout (seconds, 0 = unlimited)
- Auto-reconnect toggle
- LED brightness
- GPIO pin assignments (all 3 LEDs + button)
- Dashboard username/password change
- Web server port
- Cloudflare Tunnel token

---

## LED Reference

| LED | Color | State | Meaning |
|---|---|---|---|
| Green | 🟢 | Solid | System running normally |
| Green | 🟢 | Blinking | System state changing |
| Blue | 🔵 | Solid | Bluetooth device connected |
| Blue | 🔵 | Slow blink | Bluetooth on, no device |
| Blue | 🔵 | Rapid blink | Discoverable / pairing mode |
| Yellow | 🟡 | Solid | WiFi AP mode active |
| Yellow | 🟡 | Off | Normal WiFi mode |

---

## Physical Button

**Short press:** Toggle pairing mode (start / stop discoverable)

---

## File Layout

```
bt-kbm/
├── pi/
│   ├── main.py           # Async orchestrator
│   ├── bt_hid.py         # BlueZ Bluetooth HID daemon
│   ├── gpio_mgr.py       # LED + button manager
│   ├── wifi_mgr.py       # WiFi / AP manager
│   ├── web_server.py     # aiohttp web server + WebSocket
│   ├── macro_engine.py   # Advanced macro runner
│   ├── state_mgr.py      # SQLite persistence
│   ├── hid_keycodes.py   # Full HID keycode table
│   ├── sdp_record.xml    # Bluetooth SDP record
│   ├── requirements.txt
│   ├── install.sh        # One-command installer
│   ├── systemd/
│   │   └── bt-kbm.service
│   └── web/
│       ├── index.html    # Dashboard SPA
│       ├── style.css     # Premium dark UI
│       └── app.js        # Full SPA logic
├── cloudflare/
│   └── tunnel_config.yml # Cloudflare tunnel config + instructions
└── README.md
```

---

## Runtime Paths

| Path | Purpose |
|---|---|
| `/opt/bt-kbm/` | Application files |
| `/var/lib/bt-kbm/` | Database + web assets |
| `/var/lib/bt-kbm/state.db` | SQLite database |
| `/var/log/bt-kbm.log` | Log file |

---

## Useful Commands

```bash
# Check service status
systemctl status bt-kbm

# View live logs
journalctl -u bt-kbm -f

# Restart
systemctl restart bt-kbm

# Check Bluetooth adapter
hciconfig
bluetoothctl show

# Check open port
ss -tlnp | grep 8080
```

---

## Troubleshooting

**Bluetooth pairing not working?**
- Make sure you pressed the physical button OR clicked "Start Pairing" in the dashboard
- Check BlueZ is running: `systemctl status bluetooth`
- Verify adapter is up: `hciconfig hci0 up`

**Dashboard not loading?**
- Check the service: `systemctl status bt-kbm`
- Check the port: `curl http://localhost:8080`
- Check logs: `journalctl -u bt-kbm -f`

**Cloudflare tunnel not working?**
- Verify `cloudflared` is running: `systemctl status cloudflared`
- Check the token is correct in Settings
- Make sure the public hostname is configured in Cloudflare Zero Trust

**WiFi not connecting?**
- If stuck in AP mode, connect to `BT-KBM-AP` WiFi (password: `bt-kbm-setup`)
- Open `http://192.168.50.1:8080` and add your network in WiFi settings

---

## Security Notes

- Change the default admin password immediately after install
- The device token (in Settings) authenticates the Pi to the Cloudflare tunnel — keep it secret
- Cloudflare Tunnel provides TLS termination, so all traffic to `kbm.play-tap.com` is encrypted
- The local web server (port 8080) uses HTTP Basic Auth even on local network
