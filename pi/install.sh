#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  BT-KBM Installer — Run on a fresh Raspberry Pi OS Lite (64-bit, Bookworm)
#  Usage: sudo bash install.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

INSTALL_DIR="/opt/bt-kbm"
DATA_DIR="/var/lib/bt-kbm"
LOG_FILE="/var/log/bt-kbm.log"
SERVICE_NAME="bt-kbm"
WEB_PORT=8080
DEFAULT_ADMIN_PASS="changeme123"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }

# ── Must be root ──────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Run as root: sudo bash install.sh"
    exit 1
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   BT-KBM Installer — Pi Zero W Edition  ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: System packages ───────────────────────────────────────────────────
info "Updating package lists…"
apt-get update -qq

info "Installing system packages…"
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    python3-dbus python3-gi python3-gi-cairo \
    bluetooth bluez bluez-tools \
    hostapd dnsmasq \
    wpasupplicant \
    libglib2.0-dev \
    git curl wget \
    iw wireless-tools \
    iptables \
    rfkill

success "System packages installed"

# ── Step 2: Stop conflicting services ─────────────────────────────────────────
info "Stopping conflicting services…"
systemctl stop hostapd  2>/dev/null || true
systemctl stop dnsmasq  2>/dev/null || true
# Unmask first (Bookworm/Trixie ships hostapd masked by default)
systemctl unmask hostapd 2>/dev/null || true
systemctl unmask dnsmasq 2>/dev/null || true
systemctl disable hostapd 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true

# ── Step 3: Configure BlueZ for HID peripheral role ───────────────────────────
info "Configuring BlueZ…"

# Patch main.conf to enable compat mode and correct plugins
cat > /etc/bluetooth/main.conf << 'EOF'
[General]
Name = BT-KBM
Class = 0x000540
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = device

[Policy]
AutoEnable = true

[GATT]
KeySize = 16
ExchangeMTU = 23
Channels = 3
EOF

# Patch bluetoothd to start with --compat (needed for sdptool)
BLUETOOTH_DEFAULTS="/etc/default/bluetooth"
if ! grep -q "\-\-compat" "$BLUETOOTH_DEFAULTS" 2>/dev/null; then
    sed -i 's/^DAEMON_OPTS.*/DAEMON_OPTS="--compat --noplugin=sap"/' "$BLUETOOTH_DEFAULTS" 2>/dev/null || \
    echo 'DAEMON_OPTS="--compat --noplugin=sap"' >> "$BLUETOOTH_DEFAULTS"
fi

# Also patch the systemd unit to ensure --compat
if [ -f /lib/systemd/system/bluetooth.service ]; then
    sed -i 's|ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --compat --noplugin=sap|' \
        /lib/systemd/system/bluetooth.service
fi

systemctl daemon-reload
systemctl restart bluetooth
sleep 2

# Enable the BT adapter
rfkill unblock bluetooth 2>/dev/null || true
hciconfig hci0 up 2>/dev/null || true

success "BlueZ configured"

# ── Step 4: Install cloudflared ───────────────────────────────────────────────
info "Installing cloudflared…"
if [ "$(uname -m)" = "armv6l" ]; then
    info "Detected ARMv6 architecture (Pi Zero W) — using standalone ARM binary…"
    if wget -q -O /usr/local/bin/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm" 2>/dev/null; then
        chmod +x /usr/local/bin/cloudflared
        ln -sf /usr/local/bin/cloudflared /usr/bin/cloudflared 2>/dev/null || true
        success "cloudflared installed (/usr/local/bin/cloudflared)"
    else
        warn "cloudflared download failed — you can install it manually later"
    fi
else
    ARCH=$(dpkg --print-architecture)
    CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
    if wget -q -O /tmp/cloudflared.deb "$CF_URL" 2>/dev/null; then
        dpkg -i /tmp/cloudflared.deb 2>/dev/null || true
        success "cloudflared installed"
    else
        warn "cloudflared download failed — you can install it manually later"
    fi
fi

# ── Step 5: Create directories ────────────────────────────────────────────────
info "Creating directories…"
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$DATA_DIR/web"
touch "$LOG_FILE"
chmod 755 "$DATA_DIR"
chmod 644 "$LOG_FILE"

# ── Step 6: Copy project files ────────────────────────────────────────────────
info "Copying project files…"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r "$SCRIPT_DIR/"*.py "$INSTALL_DIR/"
cp    "$SCRIPT_DIR/sdp_record.xml" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/web" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/web/"* "$DATA_DIR/web/"

success "Files copied to $INSTALL_DIR"

# ── Step 7: Python virtual environment ───────────────────────────────────────
info "Creating Python virtual environment…"
python3 -m venv "$INSTALL_DIR/venv" --system-site-packages
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet \
    aiohttp aiosqlite websockets

success "Python environment ready"

# ── Step 8: Generate admin password hash ─────────────────────────────────────
info "Setting up dashboard credentials…"
PW_HASH=$("$INSTALL_DIR/venv/bin/python3" -c \
    "import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" \
    "$DEFAULT_ADMIN_PASS")

# Write initial settings into SQLite
"$INSTALL_DIR/venv/bin/python3" << PYEOF
import sys, asyncio, hashlib
sys.path.insert(0, '$INSTALL_DIR')
from pathlib import Path
sys.path.insert(0, str(Path('$INSTALL_DIR')))

async def setup():
    import aiosqlite
    db_path = '$DATA_DIR/state.db'
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        settings = {
            'dashboard_password_hash': '$PW_HASH',
            'dashboard_username':      'admin',
            'web_port':                '$WEB_PORT',
        }
        await db.executemany(
            'INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',
            list(settings.items())
        )
        await db.commit()

asyncio.run(setup())
PYEOF

success "Dashboard credentials set (user: admin, pass: $DEFAULT_ADMIN_PASS)"

# ── Step 9: WiFi AP dependencies ──────────────────────────────────────────────
info "Configuring hostapd defaults…"
cat > /etc/default/hostapd << 'EOF'
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF

# Enable IP forwarding (for AP mode internet sharing)
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-bt-kbm.conf
sysctl -p /etc/sysctl.d/99-bt-kbm.conf 2>/dev/null || true

# ── Step 10: systemd service ──────────────────────────────────────────────────
info "Installing systemd service…"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=BT-KBM Bluetooth Virtual Keyboard & Mouse
After=network.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
success "systemd service installed and enabled"

# ── Step 11: Firewall / permissions ───────────────────────────────────────────
info "Setting up permissions…"
# Allow Python to bind to L2CAP sockets without CAP_NET_ADMIN always needed
setcap 'cap_net_raw+eip cap_net_admin+eip' \
    "$(readlink -f "$INSTALL_DIR/venv/bin/python3")" 2>/dev/null || \
    warn "setcap failed — service runs as root anyway"

# Give the data dir proper ownership
chown -R root:root "$INSTALL_DIR" "$DATA_DIR"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            BT-KBM Installation Complete!             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
info "Starting the service now…"
systemctl start "$SERVICE_NAME"
sleep 2
systemctl status "$SERVICE_NAME" --no-pager || true

echo ""
echo -e "${CYAN}Next steps:${NC}"
echo -e "  1. Dashboard will be at: ${YELLOW}http://<pi-ip>:${WEB_PORT}${NC}"
echo -e "     Default login: ${YELLOW}admin / ${DEFAULT_ADMIN_PASS}${NC} (change in Settings!)"
echo ""
echo -e "  2. To expose via Cloudflare tunnel:"
echo -e "     ${CYAN}cloudflared tunnel login${NC}"
echo -e "     ${CYAN}cloudflared tunnel create bt-kbm${NC}"
echo -e "     ${CYAN}cloudflared tunnel route dns bt-kbm kbm.play-tap.com${NC}"
echo -e "     Then paste the token in the dashboard Settings page."
echo ""
echo -e "  3. Logs: ${CYAN}journalctl -u bt-kbm -f${NC}"
echo -e "  4. Restart: ${CYAN}systemctl restart bt-kbm${NC}"
echo ""
echo -e "Your Pi's IP addresses:"
hostname -I | tr ' ' '\n' | grep -v '^$' | while read -r ip; do
    echo -e "  ${YELLOW}http://${ip}:${WEB_PORT}${NC}"
done
echo ""
