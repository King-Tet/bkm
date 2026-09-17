/* ══════════════════════════════════════════════════════════
   BT-KBM Dashboard — app.js
   Full SPA logic: WebSocket, virtual keyboard, trackpad,
   mirror mode, macro builder, device/wifi/settings management.
══════════════════════════════════════════════════════════ */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
const STATE = {
  ws:            null,
  connected:     false,
  btConnected:   false,
  btMac:         null,
  btDiscoverable:false,
  wifiSSID:      null,
  wifiIP:        null,
  wifiAP:        false,
  currentPage:   'overview',
  mirrorActive:  false,
  mirrorKeys:    0,
  mirrorMouse:   0,
  mirrorStart:   null,
  mirrorTimer:   null,
  macros:        [],
  devices:       [],
  heldModifiers: 0,
  mouseButtons:  0,
  currentMacroId:null,
  editSteps:     [],
  settings:      {},
};

// HID modifier map (matches hid_keycodes.py)
const MOD = {
  Control:  0x01, Shift: 0x02, Alt: 0x04, Meta: 0x08,
};
const KEYMAP = buildKeymap();

// ─── Navigation ───────────────────────────────────────────────────────────────
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const el = document.getElementById(`page-${page}`);
  if (el) el.classList.add('active');
  const nav = document.getElementById(`nav-${page}`);
  if (nav) nav.classList.add('active');
  STATE.currentPage = page;

  // Lazy-load content
  if (page === 'macros')  loadMacros();
  if (page === 'devices') loadDevices();
  if (page === 'wifi')    loadWifi();
  if (page === 'settings')loadSettings();
  if (page === 'logs')    loadLogs();
}

// ─── WebSocket ────────────────────────────────────────────────────────────────
let wsRetry = 1000;

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  // Pass auth token via query (the server checks device_token or password hash)
  const token = sessionStorage.getItem('ws_token') || '';
  const url = `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(url);
  STATE.ws = ws;

  ws.onopen = () => {
    wsRetry = 1000;
    setWsIndicator(true);
  };

  ws.onclose = () => {
    STATE.connected = false;
    setWsIndicator(false);
    // Auto-reconnect
    setTimeout(connectWS, wsRetry);
    wsRetry = Math.min(wsRetry * 1.5, 15000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleWsMessage(msg);
    } catch (_) {}
  };
}

function wsSend(obj) {
  if (STATE.ws && STATE.ws.readyState === WebSocket.OPEN) {
    STATE.ws.send(JSON.stringify(obj));
    return true;
  }
  return false;
}

function handleWsMessage(msg) {
  switch (msg.type) {
    case 'state':
      applyState(msg.data);
      break;
    case 'bt_state':
      updateBTState(msg);
      break;
    case 'device_update':
      if (STATE.currentPage === 'devices') loadDevices();
      break;
    case 'mirror_active':
      STATE.mirrorActive = msg.active;
      updateMirrorUI();
      break;
    case 'pong':
      break;
  }
}

function applyState(data) {
  if (!data) return;
  const bt = data.bt || {};
  STATE.btConnected    = bt.connected;
  STATE.btMac          = bt.mac;
  STATE.btDiscoverable = bt.discoverable;

  const wifi = data.wifi || {};
  STATE.wifiSSID = wifi.connected_ssid;
  STATE.wifiIP   = wifi.ip_address;
  STATE.wifiAP   = wifi.ap_active;

  updateStatusBar();
  updateLEDs(data.led || {});
}

function updateBTState(msg) {
  STATE.btConnected    = msg.connected ?? STATE.btConnected;
  STATE.btMac          = msg.mac ?? STATE.btMac;
  STATE.btDiscoverable = msg.discoverable ?? STATE.btDiscoverable;
  updateStatusBar();
}

// ─── Status Bar ───────────────────────────────────────────────────────────────
function setWsIndicator(up) {
  STATE.connected = up;
  const el = document.getElementById('ws-indicator');
  if (!el) return;
  el.className = `status-pill ${up ? 'bt-on' : 'bt-off'}`;
}

function updateStatusBar() {
  // BT pill
  const btPill = document.getElementById('bt-pill');
  const btText = document.getElementById('bt-pill-text');
  if (btPill && btText) {
    if (STATE.btConnected) {
      btPill.className = 'status-pill bt-on';
      btText.textContent = STATE.btMac || 'Connected';
    } else if (STATE.btDiscoverable) {
      btPill.className = 'status-pill bt-disc';
      btText.textContent = 'Pairing…';
    } else {
      btPill.className = 'status-pill bt-off';
      btText.textContent = 'BT Idle';
    }
  }

  // WiFi pill
  const wifiPill = document.getElementById('wifi-pill');
  const wifiText = document.getElementById('wifi-pill-text');
  if (wifiPill && wifiText) {
    if (STATE.wifiAP) {
      wifiPill.className = 'status-pill wifi-ap';
      wifiText.textContent = 'AP Mode';
    } else if (STATE.wifiSSID) {
      wifiPill.className = 'status-pill wifi-on';
      wifiText.textContent = STATE.wifiSSID;
    } else {
      wifiPill.className = 'status-pill wifi-ap';
      wifiText.textContent = 'No WiFi';
    }
  }

  // Overview cards
  setText('bt-device-name-label', STATE.btConnected
    ? (STATE.devices.find(d => d.mac === STATE.btMac)?.nickname || STATE.btMac || 'Connected')
    : 'No device connected');
  setText('bt-mac-label', STATE.btConnected ? STATE.btMac : '');
  setEl('bt-status-badge', el => {
    el.className = `badge ${STATE.btConnected ? 'badge-green' : STATE.btDiscoverable ? 'badge-indigo' : 'badge-red'}`;
    el.textContent = STATE.btConnected ? 'Connected' : STATE.btDiscoverable ? 'Pairing' : 'Idle';
  });

  setText('btn-pair', STATE.btDiscoverable ? 'Stop Pairing' : 'Start Pairing');
  setEl('btn-pair', el => {
    el.className = `btn ${STATE.btDiscoverable ? 'btn-danger' : 'btn-primary'}`;
  });

  // WiFi overview
  setEl('wifi-status-badge', el => {
    el.className = `badge ${STATE.wifiSSID ? 'badge-green' : 'badge-red'}`;
    el.textContent = STATE.wifiAP ? 'AP Mode' : STATE.wifiSSID ? 'Connected' : 'Disconnected';
  });
  setText('wifi-ssid-label', STATE.wifiSSID || 'Not connected');
  setText('wifi-ip-label', STATE.wifiIP || '—');

  // WiFi page
  setText('wifi-mode-label', STATE.wifiAP ? '🟡 AP Mode' : '🟢 Normal');
  setText('wifi-cur-ssid', STATE.wifiSSID || '—');
  setText('wifi-cur-ip', STATE.wifiIP || '—');
}

function updateLEDs(led) {
  const ledMap = {
    'ov-led-green':  ['GREEN_ON', 'green', led.green],
    'ov-led-blue':   ['CONNECTED', 'blue', led.blue],
    'ov-led-yellow': ['AP_MODE', 'yellow', led.yellow],
  };
  for (const [id, [solidState, color, state]] of Object.entries(ledMap)) {
    setEl(id, el => {
      el.className = 'led-dot';
      if (!state || state === 'OFF') {
        el.classList.add('led-off');
      } else {
        el.classList.add(`led-${color}`);
        if (state === 'CONNECTED' || state === 'ON' || state === 'AP_MODE') {
          el.classList.add('on');
        } else if (state === 'DISCOVERABLE') {
          el.classList.add('led-blink-rapid');
        } else {
          el.classList.add('led-blink-slow');
        }
      }
    });
  }
  // Topbar LEDs
  updateTopbarLED('led-green', led.green, 'green');
  updateTopbarLED('led-blue',  led.blue,  'blue');
  updateTopbarLED('led-yellow',led.yellow,'yellow');
}

function updateTopbarLED(id, state, color) {
  setEl(id, el => {
    el.className = 'led-dot';
    if (!state || state === 'OFF') { el.classList.add('led-off'); return; }
    el.classList.add(`led-${color}`, 'on');
    if (state === 'DISCOVERABLE') el.classList.add('led-blink-rapid');
    else if (state === 'IDLE' || state === 'STATE_CHANGE') el.classList.add('led-blink-slow');
  });
}

// ─── API helpers ──────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const token = sessionStorage.getItem('ws_token') || '';
  try {
    const opts = {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
      },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (r.status === 401) {
      sessionStorage.removeItem('ws_token');
      showLoginOverlay();
      throw new Error('Session expired — please log in again');
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    toast('error', `API error: ${e.message}`);
    return null;
  }
}

// ─── Login overlay ─────────────────────────────────────────────────────

function showLoginOverlay() {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'flex';
}

function hideLoginOverlay() {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'none';
}

async function doLogin() {
  const username = (document.getElementById('login-username')?.value || '').trim();
  const password = document.getElementById('login-password')?.value || '';
  const errEl = document.getElementById('login-error');
  const btn   = document.getElementById('login-btn');
  if (errEl) errEl.textContent = '';
  if (btn) { btn.disabled = true; btn.textContent = 'Signing in…'; }

  try {
    const r = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      if (errEl) errEl.textContent = d.message || 'Invalid username or password.';
      return;
    }
    const data = await r.json();
    sessionStorage.setItem('ws_token', data.token);
    hideLoginOverlay();
    connectWS();
    api('GET', '/api/status').then(d => { if (d) applyState(d); });
    loadLogs();
  } catch (e) {
    if (errEl) errEl.textContent = 'Login failed: ' + e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Sign in →'; }
  }
}

// ─── Bluetooth ────────────────────────────────────────────────────────────────
async function togglePairing() {
  if (STATE.btDiscoverable) {
    await api('POST', '/api/bt/stop-pair');
    toast('info', 'Pairing stopped');
  } else {
    await api('POST', '/api/bt/pair', { timeout: 120 });
    toast('info', 'Now discoverable for 120s…');
  }
}

async function btDisconnect() {
  if (!STATE.btConnected) return;
  await api('POST', '/api/bt/disconnect');
  toast('info', 'Disconnected');
}

// ─── Virtual Keyboard ─────────────────────────────────────────────────────────
function buildVirtualKeyboard() {
  const container = document.getElementById('virtual-keyboard');
  if (!container || container.dataset.built) return;
  container.dataset.built = '1';

  const rows = [
    // Row 0: Esc + F1-F12 + F13-F24 (hidden by default) + special
    ['Esc','F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12','PrtSc','ScrLk','Pause'],
    // Row 1: ` 1-0 -=  Backspace
    ['`','1','2','3','4','5','6','7','8','9','0','-','=',{label:'Backspace',cls:'w2',code:'Backspace'}],
    // Row 2: Tab Q-P [ ] \
    [{label:'Tab',cls:'w15',code:'Tab'},'Q','W','E','R','T','Y','U','I','O','P','[',']','\\'],
    // Row 3: CapsLk A-L ; ' Enter
    [{label:'CapsLk',cls:'w175',code:'CapsLock'},'A','S','D','F','G','H','J','K','L',';',"'",{label:'Enter',cls:'w225',code:'Enter'}],
    // Row 4: Shift Z-M , . / Shift
    [{label:'⇧Shift',cls:'w225',code:'ShiftLeft',mod:true},'Z','X','C','V','B','N','M',',','.','/',{label:'⇧Shift',cls:'w275',code:'ShiftRight',mod:true}],
    // Row 5: Ctrl Win Alt Space AltGr Win Menu Ctrl + arrows
    [
      {label:'Ctrl',cls:'w15',code:'ControlLeft',mod:true},
      {label:'⊞Win',cls:'w15',code:'MetaLeft',mod:true},
      {label:'Alt',cls:'w15',code:'AltLeft',mod:true},
      {label:'',cls:'w6',code:'Space'},
      {label:'AltGr',cls:'w15',code:'AltRight',mod:true},
      {label:'⊞Win',cls:'w15',code:'MetaRight',mod:true},
      {label:'Menu',cls:'w15',code:'ContextMenu'},
      {label:'Ctrl',cls:'w15',code:'ControlRight',mod:true},
      {label:'◀',cls:'',code:'ArrowLeft'},
      {label:'▼',cls:'',code:'ArrowDown'},
      {label:'▶',cls:'',code:'ArrowRight'},
    ],
    // Row 6: arrows up separate row
    [null,null,null,null,null,null,null,null,{label:'▲',cls:'',code:'ArrowUp'}],
    // Numpad
    [
      {label:'Num',cls:'',code:'NumLock'},{label:'/',cls:'',code:'NumpadDivide'},
      {label:'*',cls:'',code:'NumpadMultiply'},{label:'−',cls:'',code:'NumpadSubtract'},
    ],
    [
      {label:'7',cls:'',code:'Numpad7'},{label:'8',cls:'',code:'Numpad8'},
      {label:'9',cls:'',code:'Numpad9'},{label:'+',cls:'w2',code:'NumpadAdd'},
    ],
    [
      {label:'4',cls:'',code:'Numpad4'},{label:'5',cls:'',code:'Numpad5'},
      {label:'6',cls:'',code:'Numpad6'},
    ],
    [
      {label:'1',cls:'',code:'Numpad1'},{label:'2',cls:'',code:'Numpad2'},
      {label:'3',cls:'',code:'Numpad3'},{label:'⏎',cls:'w2',code:'NumpadEnter'},
    ],
    [
      {label:'0',cls:'w2',code:'Numpad0'},{label:'.',cls:'',code:'NumpadDecimal'},
    ],
  ];

  // Navigation cluster
  const navCluster = [
    {label:'Ins',code:'Insert'},{label:'Home',code:'Home'},{label:'PgUp',code:'PageUp'},
    {label:'Del',code:'Delete'},{label:'End',code:'End'},{label:'PgDn',code:'PageDown'},
  ];

  // Build main rows
  rows.forEach((rowDef, ri) => {
    if (ri === 7) { // separator
      const sep = document.createElement('div');
      sep.style.cssText = 'height:8px;border-top:1px solid var(--border);margin:4px 0';
      container.appendChild(sep);
    }
    const rowEl = document.createElement('div');
    rowEl.className = 'vkb-row';
    rowDef.forEach(keyDef => {
      if (!keyDef) return;
      const k = typeof keyDef === 'string' ? {label: keyDef, code: keyDef} : keyDef;
      const el = makeKey(k);
      rowEl.appendChild(el);
    });
    container.appendChild(rowEl);
  });

  // Nav cluster
  const navRow = document.createElement('div');
  navRow.className = 'vkb-row';
  navRow.style.marginTop = '4px';
  navCluster.forEach(k => navRow.appendChild(makeKey(k)));
  container.appendChild(navRow);
}

function makeKey(k) {
  const el = document.createElement('div');
  el.className = `key${k.cls ? ' ' + k.cls : ''}${k.mod ? ' mod' : ''}`;
  if (k.code && k.code.startsWith('F') && parseInt(k.code.slice(1)) > 12) el.classList.add('fn');
  el.textContent = k.label || k.code || '';
  el.title = k.code || k.label || '';
  el.dataset.code = k.code || k.label;
  el.id = `vk-${k.code || k.label}`;

  el.addEventListener('mousedown', e => {
    e.preventDefault();
    const code = el.dataset.code;
    const holdMode = document.getElementById('key-hold-mode')?.checked;

    if (code.startsWith('Shift') || code.startsWith('Control') ||
        code.startsWith('Alt') || code.startsWith('Meta')) {
      // Toggle modifier
      const modBit = {
        ShiftLeft: 0x02, ShiftRight: 0x20,
        ControlLeft: 0x01, ControlRight: 0x10,
        AltLeft: 0x04, AltRight: 0x40,
        MetaLeft: 0x08, MetaRight: 0x80,
      }[code] || 0;
      STATE.heldModifiers ^= modBit;
      el.classList.toggle('pressed');
      sendKeyboardReport();
    } else {
      el.classList.add('pressed');
      const kc = KEYMAP[code] || 0;
      wsSend({ type: 'keyboard', modifier: STATE.heldModifiers, keycodes: [kc] });
      if (!holdMode) {
        setTimeout(() => {
          el.classList.remove('pressed');
          wsSend({ type: 'keyboard_release' });
          // Clear non-sticky modifiers
          STATE.heldModifiers = 0;
          document.querySelectorAll('.key.pressed').forEach(k2 => k2.classList.remove('pressed'));
        }, 80);
      }
    }
  });
  return el;
}

function sendKeyboardReport() {
  wsSend({ type: 'keyboard', modifier: STATE.heldModifiers, keycodes: [] });
}

// ─── Mirror Mode ──────────────────────────────────────────────────────────────
let mirrorKeydownHandler = null;
let mirrorMousemoveHandler = null;
let mirrorWheelHandler = null;

function toggleMirror() {
  if (STATE.mirrorActive) {
    stopMirror();
  } else {
    startMirror();
  }
}

function startMirror() {
  wsSend({ type: 'mirror_start' });
  STATE.mirrorActive = true;
  STATE.mirrorKeys = 0;
  STATE.mirrorMouse = 0;
  STATE.mirrorStart = Date.now();

  mirrorKeydownHandler = (e) => {
    if (!STATE.mirrorActive) return;
    e.preventDefault();
    const kc = KEYMAP[e.code] || 0;
    const mod = getModBits(e);
    const blocked = getBlockedKeys();
    if (blocked.includes(e.code) || blocked.includes(e.key)) return;
    wsSend({ type: 'mirror_key', modifier: mod, keycodes: [kc], pressed: true });
    logMirrorEvent(`KEY ↓ ${e.key} (mod:${mod.toString(16)})`);
    STATE.mirrorKeys++;
    setText('mirror-keys-sent', STATE.mirrorKeys);
  };

  mirrorMousemoveHandler = (() => {
    let lastX = null, lastY = null;
    return (e) => {
      if (!STATE.mirrorActive) return;
      if (lastX === null) { lastX = e.clientX; lastY = e.clientY; return; }
      const sens = parseFloat(document.getElementById('mirror-sensitivity')?.value || 5);
      const dx = Math.round((e.clientX - lastX) * sens * 0.3);
      const dy = Math.round((e.clientY - lastY) * sens * 0.3);
      lastX = e.clientX; lastY = e.clientY;
      if (dx !== 0 || dy !== 0) {
        wsSend({ type: 'mirror_mouse', dx, dy, buttons: 0, wheel: 0 });
        STATE.mirrorMouse++;
        setText('mirror-mouse-events', STATE.mirrorMouse);
      }
    };
  })();

  mirrorWheelHandler = (e) => {
    if (!STATE.mirrorActive) return;
    e.preventDefault();
    const wheel = e.deltaY > 0 ? -3 : 3;
    wsSend({ type: 'mirror_mouse', dx: 0, dy: 0, buttons: 0, wheel });
    STATE.mirrorMouse++;
  };

  document.addEventListener('keydown', mirrorKeydownHandler, { capture: true });
  document.addEventListener('mousemove', mirrorMousemoveHandler);
  document.addEventListener('wheel', mirrorWheelHandler, { passive: false });

  STATE.mirrorTimer = setInterval(() => {
    const secs = Math.round((Date.now() - STATE.mirrorStart) / 1000);
    setText('mirror-duration', secs + 's');
  }, 1000);

  updateMirrorUI();
  toast('success', 'Mirror mode active — your inputs are being forwarded');
}

function stopMirror() {
  wsSend({ type: 'mirror_stop' });
  STATE.mirrorActive = false;
  if (mirrorKeydownHandler) document.removeEventListener('keydown', mirrorKeydownHandler, { capture: true });
  if (mirrorMousemoveHandler) document.removeEventListener('mousemove', mirrorMousemoveHandler);
  if (mirrorWheelHandler) document.removeEventListener('wheel', mirrorWheelHandler);
  clearInterval(STATE.mirrorTimer);
  updateMirrorUI();
  toast('info', 'Mirror mode stopped');
}

function updateMirrorUI() {
  const badge = document.getElementById('mirror-badge');
  const btn   = document.getElementById('btn-mirror-toggle');
  if (badge) {
    badge.className = `badge ${STATE.mirrorActive ? 'badge-green' : 'badge-red'}`;
    badge.textContent = STATE.mirrorActive ? 'Active' : 'Inactive';
  }
  if (btn) {
    btn.textContent = STATE.mirrorActive ? 'Stop Mirror Mode' : 'Activate Mirror Mode';
    btn.className   = `btn ${STATE.mirrorActive ? 'btn-danger' : 'btn-primary'}`;
  }
}

function getBlockedKeys() {
  const val = document.getElementById('mirror-key-filter')?.value || '';
  return val.split(',').map(k => k.trim()).filter(Boolean);
}

function logMirrorEvent(text) {
  const feed = document.getElementById('mirror-event-log');
  if (!feed) return;
  const el = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `<span class="log-ts">${ts()}</span><span class="log-action">${esc(text)}</span>`;
  feed.prepend(el);
  if (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

// ─── Trackpad ─────────────────────────────────────────────────────────────────
function setupTrackpad() {
  const tp = document.getElementById('trackpad');
  const cursor = document.getElementById('trackpad-cursor');
  if (!tp || tp.dataset.setup) return;
  tp.dataset.setup = '1';

  let lastX = null, lastY = null;
  let pressed = false;

  const speed = () => parseFloat(document.getElementById('mouse-speed')?.value || 5);

  const moveCursor = (cx, cy) => {
    const rect = tp.getBoundingClientRect();
    cursor.style.left = (cx - rect.left) + 'px';
    cursor.style.top  = (cy - rect.top) + 'px';
  };

  tp.addEventListener('pointerdown', e => {
    tp.setPointerCapture(e.pointerId);
    pressed = true;
    lastX = e.clientX; lastY = e.clientY;
    moveCursor(e.clientX, e.clientY);
    e.preventDefault();
  });

  tp.addEventListener('pointermove', e => {
    moveCursor(e.clientX, e.clientY);
    if (!pressed) return;
    if (lastX === null) { lastX = e.clientX; lastY = e.clientY; return; }
    const dx = Math.round((e.clientX - lastX) * speed() * 0.5);
    const dy = Math.round((e.clientY - lastY) * speed() * 0.5);
    lastX = e.clientX; lastY = e.clientY;
    if (dx !== 0 || dy !== 0) {
      wsSend({ type: 'mouse', buttons: STATE.mouseButtons, x: dx, y: dy, wheel: 0 });
    }
  });

  tp.addEventListener('pointerup', () => { pressed = false; lastX = null; lastY = null; });
  tp.addEventListener('pointerleave', () => { if (!pressed) { lastX = null; lastY = null; } });
  tp.addEventListener('wheel', e => {
    e.preventDefault();
    const wheel = e.deltaY > 0 ? -3 : 3;
    wsSend({ type: 'mouse', buttons: 0, x: 0, y: 0, wheel });
  }, { passive: false });
}

function mouseButtonDown(btn) {
  STATE.mouseButtons = btn;
  wsSend({ type: 'mouse', buttons: btn, x: 0, y: 0, wheel: 0 });
}
function mouseButtonUp() {
  STATE.mouseButtons = 0;
  wsSend({ type: 'mouse', buttons: 0, x: 0, y: 0, wheel: 0 });
}
function sendScroll(amount) {
  wsSend({ type: 'mouse', buttons: 0, x: 0, y: 0, wheel: amount });
}

// ─── Text send ────────────────────────────────────────────────────────────────
function sendText(withEnter = false) {
  const input = document.getElementById('text-input');
  if (!input) return;
  let text = input.value;
  if (withEnter) text += '\n';
  if (!text) return;
  wsSend({ type: 'text', text });
  toast('success', `Sent: ${text.slice(0, 30)}${text.length > 30 ? '…' : ''}`);
  input.value = '';
}

// ─── Consumer keys ────────────────────────────────────────────────────────────
const CONSUMER_MAP = {
  nexttrack: 0x01,  prevtrack: 0x02,  stop: 0x04,
  playpause: 0x08,  mute: 0x10,       volumeup: 0x20,
  volumedown: 0x40, eject: 0x80,      fastforward: 0x100,
  rewind: 0x200,    calculator: 0x800, browser: 0x1000,
  email: 0x2000,    pause: 0x4000,    record: 0x8000,
};
function sendConsumer(name) {
  const bitmask = CONSUMER_MAP[name] || 0;
  if (!bitmask) return;
  wsSend({ type: 'consumer', bitmask });
  setTimeout(() => wsSend({ type: 'consumer', bitmask: 0 }), 100);
}

// ─── Macros ───────────────────────────────────────────────────────────────────
async function loadMacros() {
  const cat = document.getElementById('macro-category-filter')?.value || '';
  const url = `/api/macros${cat ? '?category=' + encodeURIComponent(cat) : ''}`;
  const data = await api('GET', url);
  if (!data) return;
  STATE.macros = data;
  renderMacros(data);
  await loadMacroCategories();
}

async function loadMacroCategories() {
  const cats = await api('GET', '/api/macros/categories');
  if (!cats) return;
  const sel = document.getElementById('macro-category-filter');
  const list = document.getElementById('category-list');
  if (sel) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">All Categories</option>' +
      cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    sel.value = cur;
  }
  if (list) list.innerHTML = cats.map(c => `<option value="${esc(c)}"/>`).join('');
}

function filterMacros() { loadMacros(); }

function renderMacros(macros) {
  const container = document.getElementById('macro-list');
  if (!container) return;
  if (!macros.length) {
    container.innerHTML = `<div class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
      <p>No macros yet. Click "+ New Macro" to create one.</p>
    </div>`;
    return;
  }
  container.innerHTML = macros.map(m => `
    <div class="macro-card" onclick="openMacroEditor('${m.id}')">
      <div class="macro-icon" style="background:${m.color}22;border:1px solid ${m.color}44">${m.icon || '⌨️'}</div>
      <div class="macro-info">
        <div class="macro-name">${esc(m.name)}</div>
        <div class="macro-meta">
          <span class="macro-badge">${esc(m.category)}</span>
          <span>${m.steps?.length || 0} steps</span>
          ${m.hotkey ? `<span class="macro-hotkey">${esc(m.hotkey)}</span>` : ''}
        </div>
        <div class="text-sm text-muted">${esc(m.description || '')}</div>
      </div>
      <div class="row" onclick="event.stopPropagation()">
        <button class="btn btn-success btn-sm" onclick="runMacro('${m.id}')">▶ Run</button>
        <button class="btn btn-outline btn-sm" onclick="openMacroEditor('${m.id}')">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteMacro('${m.id}')">Delete</button>
      </div>
    </div>
  `).join('');
}

async function runMacro(id) {
  const r = await api('POST', `/api/macros/${id}/run`);
  if (r?.success) toast('success', 'Macro running…');
  else toast('error', 'Failed to start macro');
}

async function deleteMacro(id) {
  if (!confirm('Delete this macro?')) return;
  await api('DELETE', `/api/macros/${id}`);
  loadMacros();
  toast('info', 'Macro deleted');
}

// ─── Macro Editor ─────────────────────────────────────────────────────────────
async function openMacroEditor(id) {
  STATE.currentMacroId = id;
  STATE.editSteps = [];
  const modal = document.getElementById('macro-modal');
  document.getElementById('macro-modal-title').textContent = id ? 'Edit Macro' : 'New Macro';

  if (id) {
    const m = await api('GET', `/api/macros/${id}`);
    if (!m) return;
    setVal('m-name', m.name);
    setVal('m-category', m.category);
    setVal('m-icon', m.icon);
    document.getElementById('m-color').value = m.color || '#6366f1';
    setVal('m-hotkey', m.hotkey);
    setVal('m-description', m.description);
    STATE.editSteps = JSON.parse(JSON.stringify(m.steps || []));
  } else {
    setVal('m-name', '');
    setVal('m-category', 'General');
    setVal('m-icon', '⌨️');
    document.getElementById('m-color').value = '#6366f1';
    setVal('m-hotkey', '');
    setVal('m-description', '');
    STATE.editSteps = [];
  }
  renderStepList();
  modal.classList.add('open');
}

function closeMacroModal() {
  document.getElementById('macro-modal').classList.remove('open');
}

async function saveMacro() {
  const data = {
    name:        document.getElementById('m-name').value,
    category:    document.getElementById('m-category').value || 'General',
    icon:        document.getElementById('m-icon').value || '⌨️',
    color:       document.getElementById('m-color').value,
    hotkey:      document.getElementById('m-hotkey').value,
    description: document.getElementById('m-description').value,
    steps:       STATE.editSteps,
  };
  if (STATE.currentMacroId) {
    await api('PUT', `/api/macros/${STATE.currentMacroId}`, data);
    toast('success', 'Macro saved');
  } else {
    await api('POST', '/api/macros', data);
    toast('success', 'Macro created');
  }
  closeMacroModal();
  loadMacros();
}

function addStep() {
  const type = document.getElementById('step-type-select')?.value || 'TYPE';
  const step = buildDefaultStep(type);
  STATE.editSteps.push(step);
  renderStepList();
}

function buildDefaultStep(type) {
  const defaults = {
    TYPE:            { type, text: '', delay_ms: 30 },
    KEY:             { type, combo: 'Ctrl+C', hold_ms: 50 },
    KEY_DOWN:        { type, combo: '' },
    KEY_UP:          { type },
    MOUSE_MOVE:      { type, x: 0, y: 0, steps: 5 },
    MOUSE_CLICK:     { type, button: 'left', hold_ms: 50, double: false },
    MOUSE_SCROLL:    { type, direction: 'down', amount: 3 },
    DELAY:           { type, ms: 500, jitter_ms: 0 },
    LOOP:            { type, count: 3 },
    LOOP_END:        { type },
    CONDITION:       { type, var: '', op: 'eq', value: '' },
    CONDITION_ELSE:  { type },
    CONDITION_END:   { type },
    SHELL:           { type, cmd: '', output_var: '', timeout_s: 10 },
    SET_VAR:         { type, name: '', value: '' },
    CONSUMER:        { type, key: 'playpause' },
  };
  return defaults[type] || { type };
}

function renderStepList() {
  const list = document.getElementById('step-list');
  if (!list) return;
  if (!STATE.editSteps.length) {
    list.innerHTML = '<div class="text-muted text-sm" style="padding:12px;text-align:center">No steps yet. Use the dropdown above to add steps.</div>';
    return;
  }
  list.innerHTML = STATE.editSteps.map((step, i) => {
    const t = step.type;
    const typeClass = `stype-${t.toLowerCase().split('_')[0]}`;
    const params = renderStepParams(step);
    return `
      <div class="step-item" data-idx="${i}">
        <span class="step-drag-handle">⠿</span>
        <span class="step-type-badge ${typeClass}">${t}</span>
        <div class="step-params">${params}</div>
        <div class="step-actions">
          <button class="btn btn-outline btn-sm btn-icon" onclick="editStep(${i})" title="Edit">✎</button>
          <button class="btn btn-danger btn-sm btn-icon" onclick="removeStep(${i})" title="Delete">✕</button>
          ${i > 0 ? `<button class="btn btn-outline btn-sm btn-icon" onclick="moveStep(${i},-1)" title="Move up">↑</button>` : ''}
          ${i < STATE.editSteps.length-1 ? `<button class="btn btn-outline btn-sm btn-icon" onclick="moveStep(${i},1)" title="Move down">↓</button>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function renderStepParams(step) {
  switch (step.type) {
    case 'TYPE':        return `Type: <code>${esc(step.text || '')}</code> (${step.delay_ms}ms/char)`;
    case 'KEY':         return `Combo: <code>${esc(step.combo || '')}</code> hold ${step.hold_ms}ms`;
    case 'KEY_DOWN':    return `Hold: <code>${esc(step.combo || '')}</code>`;
    case 'KEY_UP':      return `Release all keys`;
    case 'MOUSE_MOVE':  return `Move x:<code>${step.x}</code> y:<code>${step.y}</code> in ${step.steps} steps`;
    case 'MOUSE_CLICK': return `${step.double?'Double-c':'C'}lick <code>${step.button}</code> for ${step.hold_ms}ms`;
    case 'MOUSE_SCROLL':return `Scroll <code>${step.direction}</code> × ${step.amount}`;
    case 'DELAY':       return `Wait <code>${step.ms}ms</code>${step.jitter_ms ? ` ±${step.jitter_ms}ms` : ''}`;
    case 'LOOP':        return `Repeat ${step.count === 0 ? '∞' : step.count} times`;
    case 'LOOP_END':    return `End of loop`;
    case 'CONDITION':   return `If <code>$${step.var}</code> ${step.op} <code>${esc(step.value)}</code>`;
    case 'CONDITION_ELSE': return `Else`;
    case 'CONDITION_END':  return `End condition`;
    case 'SHELL':       return `<code>${esc(step.cmd || '')}</code>${step.output_var ? ` → $${step.output_var}` : ''}`;
    case 'SET_VAR':     return `$${step.name} = <code>${esc(step.value || '')}</code>`;
    case 'CONSUMER':    return `Media: <code>${step.key}</code>`;
    default:            return JSON.stringify(step);
  }
}

function editStep(idx) {
  const step = STATE.editSteps[idx];
  const val = prompt('Edit step JSON (advanced):', JSON.stringify(step, null, 2));
  if (val === null) return;
  try {
    STATE.editSteps[idx] = JSON.parse(val);
    renderStepList();
  } catch (e) {
    toast('error', 'Invalid JSON');
  }
}

function removeStep(idx) {
  STATE.editSteps.splice(idx, 1);
  renderStepList();
}

function moveStep(idx, dir) {
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= STATE.editSteps.length) return;
  [STATE.editSteps[idx], STATE.editSteps[newIdx]] = [STATE.editSteps[newIdx], STATE.editSteps[idx]];
  renderStepList();
}

async function importMacros() {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = '.json';
  input.onchange = async (e) => {
    try {
      const text = await e.target.files[0].text();
      const data = JSON.parse(text);
      const r = await api('POST', '/api/macros/import', data);
      toast('success', `Imported ${r?.imported || 0} macros`);
      loadMacros();
    } catch (err) {
      toast('error', 'Import failed: ' + err.message);
    }
  };
  input.click();
}

async function exportMacros() {
  const data = await api('GET', '/api/macros/export');
  if (!data) return;
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'bt-kbm-macros.json';
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Devices ──────────────────────────────────────────────────────────────────
async function loadDevices() {
  const data = await api('GET', '/api/devices');
  if (!data) return;
  STATE.devices = data;
  const container = document.getElementById('device-list');
  if (!container) return;
  if (!data.length) {
    container.innerHTML = `<div class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      <p>No devices paired yet. Press "Pair New" to get started.</p>
    </div>`;
    return;
  }
  container.innerHTML = data.map(d => `
    <div class="device-item">
      <div class="device-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11M12 2v20"/></svg>
      </div>
      <div class="device-info">
        <div class="device-name">${esc(d.nickname || d.mac)}</div>
        <div class="device-mac">${esc(d.mac)}</div>
        <div class="device-meta">
          Last seen: ${d.last_seen ? new Date(d.last_seen * 1000).toLocaleString() : 'Never'} ·
          Connections: ${d.conn_count || 0}
          ${d.mac === STATE.btMac ? ' · <span class="badge badge-green">Active</span>' : ''}
        </div>
      </div>
      <div class="device-actions">
        <button class="btn btn-outline btn-sm" onclick="openDeviceModal('${esc(d.mac)}','${esc(d.nickname||'')}',${d.trusted},${d.auto_connect})">Edit</button>
        <button class="btn btn-outline btn-sm" onclick="reconnectDevice('${esc(d.mac)}')">Reconnect</button>
        <button class="btn btn-danger btn-sm" onclick="forgetDevice('${esc(d.mac)}')">Forget</button>
      </div>
    </div>
  `).join('');
}

function openDeviceModal(mac, nickname, trusted, auto) {
  document.getElementById('d-mac').value = mac;
  document.getElementById('d-nickname').value = nickname;
  document.getElementById('d-trusted').checked = !!trusted;
  document.getElementById('d-auto-connect').checked = !!auto;
  document.getElementById('device-modal').classList.add('open');
}
function closeDeviceModal() { document.getElementById('device-modal').classList.remove('open'); }

async function saveDevice() {
  const mac = document.getElementById('d-mac').value;
  await api('PATCH', `/api/devices/${encodeURIComponent(mac)}`, {
    nickname:     document.getElementById('d-nickname').value,
    trusted:      document.getElementById('d-trusted').checked ? 1 : 0,
    auto_connect: document.getElementById('d-auto-connect').checked ? 1 : 0,
  });
  closeDeviceModal();
  loadDevices();
  toast('success', 'Device updated');
}

async function forgetDevice(mac) {
  if (!confirm('Forget this device? It will need to be paired again.')) return;
  await api('DELETE', `/api/devices/${encodeURIComponent(mac)}`);
  loadDevices();
  toast('info', 'Device forgotten');
}

async function reconnectDevice(mac) {
  const r = await api('POST', '/api/bt/reconnect', { mac });
  toast(r?.success ? 'success' : 'error', r?.success ? 'Reconnecting…' : 'Reconnect failed');
}

// ─── WiFi ─────────────────────────────────────────────────────────────────────
async function loadWifi() {
  const [saved, status] = await Promise.all([
    api('GET', '/api/wifi'),
    api('GET', '/api/wifi/status'),
  ]);
  if (saved) renderSavedNetworks(saved);
  if (status) {
    STATE.wifiSSID = status.connected_ssid;
    STATE.wifiIP   = status.ip_address;
    STATE.wifiAP   = status.ap_active;
    updateStatusBar();
  }
}

function renderSavedNetworks(nets) {
  const container = document.getElementById('wifi-saved-list');
  if (!container) return;
  if (!nets.length) {
    container.innerHTML = '<div class="text-muted text-sm" style="padding:12px">No saved networks</div>';
    return;
  }
  container.innerHTML = nets.map(n => `
    <div class="wifi-item">
      <div class="wifi-signal">${wifiSignalBars(null, n.ssid === STATE.wifiSSID)}</div>
      <div class="wifi-info">
        <div class="wifi-ssid">${esc(n.ssid)}</div>
        <div class="wifi-meta">
          Priority: ${n.priority}
          ${n.psk === null ? ' · <span class="wifi-badge-open">Open</span>' : ' · <span class="wifi-badge-secured">🔒 Secured</span>'}
          ${n.last_used ? ' · Last used: ' + new Date(n.last_used * 1000).toLocaleDateString() : ''}
          ${n.ssid === STATE.wifiSSID ? ' · <span class="badge badge-green">Connected</span>' : ''}
        </div>
      </div>
      <div class="row">
        <button class="btn btn-outline btn-sm" onclick="connectWifi('${esc(n.ssid)}')">Connect</button>
        <button class="btn btn-danger btn-sm" onclick="removeWifi('${esc(n.ssid)}')">Remove</button>
      </div>
    </div>
  `).join('');
}

function wifiSignalBars(signal, connected) {
  const bars = [4, 8, 12, 16];
  return bars.map((h, i) => `<div class="wifi-bar ${connected || i < 2 ? 'active' : ''}" style="height:${h}px"></div>`).join('');
}

async function wifiScan() {
  const btn = document.getElementById('btn-scan');
  if (btn) { btn.textContent = '…Scanning'; btn.disabled = true; }
  const data = await api('POST', '/api/wifi/scan');
  if (btn) { btn.textContent = '🔍 Scan'; btn.disabled = false; }
  if (!data) return;
  const container = document.getElementById('wifi-scan-list');
  if (!container) return;
  if (!data.length) {
    container.innerHTML = '<div class="text-muted text-sm" style="padding:12px">No networks found</div>';
    return;
  }
  const sorted = data.sort((a, b) => b.signal - a.signal);
  container.innerHTML = sorted.map(n => `
    <div class="wifi-item">
      <div class="wifi-signal">${wifiSignalBars(n.signal, n.ssid === STATE.wifiSSID)}</div>
      <div class="wifi-info">
        <div class="wifi-ssid">${esc(n.ssid)}</div>
        <div class="wifi-meta">
          ${n.signal} dBm ·
          ${n.open ? '<span class="wifi-badge-open">Open</span>' : '<span class="wifi-badge-secured">🔒 Secured</span>'}
          ${n.ssid === STATE.wifiSSID ? ' · <span class="badge badge-green">Connected</span>' : ''}
        </div>
      </div>
      <button class="btn btn-outline btn-sm" onclick="connectToScanned('${esc(n.ssid)}',${n.open})">Connect</button>
    </div>
  `).join('');
}

async function connectWifi(ssid) {
  await api('POST', '/api/wifi/connect', { ssid });
  toast('info', `Connecting to ${ssid}…`);
}

async function connectToScanned(ssid, open) {
  let psk = null;
  if (!open) {
    psk = prompt(`Password for "${ssid}":`);
    if (psk === null) return;
  }
  const r = await api('POST', '/api/wifi/connect', { ssid, psk });
  toast(r?.success ? 'success' : 'error', r?.success ? `Connected to ${ssid}` : `Failed to connect`);
  if (r?.success) loadWifi();
}

async function removeWifi(ssid) {
  if (!confirm(`Remove "${ssid}"?`)) return;
  await api('DELETE', `/api/wifi/${encodeURIComponent(ssid)}`);
  loadWifi();
}

async function wifiDisconnect() {
  await api('POST', '/api/wifi/disconnect');
  toast('info', 'Disconnected from WiFi');
}

function openAddWifi() { document.getElementById('wifi-modal').classList.add('open'); }
function closeWifiModal() { document.getElementById('wifi-modal').classList.remove('open'); }

async function addWifiNetwork() {
  const ssid = document.getElementById('wifi-add-ssid').value;
  const psk  = document.getElementById('wifi-add-psk').value || null;
  const prio = parseInt(document.getElementById('wifi-add-priority').value) || 0;
  const now  = document.getElementById('wifi-connect-now').checked;
  if (!ssid) { toast('error', 'SSID required'); return; }
  await api('POST', '/api/wifi', { ssid, psk, priority: prio });
  if (now) await api('POST', '/api/wifi/connect', { ssid, psk });
  closeWifiModal();
  loadWifi();
  toast('success', `Network "${ssid}" saved`);
}

async function saveWifiSettings() {
  await api('PUT', '/api/settings', {
    ap_ssid:                document.getElementById('ap-ssid').value,
    ap_password:            document.getElementById('ap-password').value,
    ap_channel:             document.getElementById('ap-channel').value,
    open_network_autoconnect: document.getElementById('auto-open-net').checked ? '1' : '0',
  });
  toast('success', 'WiFi settings saved');
}

// ─── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
  const data = await api('GET', '/api/settings');
  if (!data) return;
  STATE.settings = data;
  setVal('s-bt-name',      data.bt_device_name || 'BT-KBM');
  setVal('s-bt-timeout',   data.bt_discoverable_timeout || '120');
  document.getElementById('s-auto-reconnect').checked = data.auto_reconnect_bt !== '0';
  setVal('s-led-brightness', data.led_brightness || '100');
  setVal('s-pin-green',   data.led_green_gpio  || '17');
  setVal('s-pin-blue',    data.led_blue_gpio   || '27');
  setVal('s-pin-yellow',  data.led_yellow_gpio || '22');
  setVal('s-pin-button',  data.pairing_button_gpio || '18');
  setVal('s-dashboard-user', data.dashboard_username || 'admin');
  setVal('s-web-port',    data.web_port || '8080');
  setVal('s-cf-token',    data.cf_tunnel_token || '');
  setVal('ap-ssid',       data.ap_ssid || 'BT-KBM-AP');
  setVal('ap-channel',    data.ap_channel || '6');
  const ao = document.getElementById('auto-open-net');
  if (ao) ao.checked = data.open_network_autoconnect !== '0';
}

async function saveSettings() {
  const pw = document.getElementById('s-dashboard-pw').value;
  const body = {
    bt_device_name:          document.getElementById('s-bt-name').value,
    bt_discoverable_timeout: document.getElementById('s-bt-timeout').value,
    auto_reconnect_bt:       document.getElementById('s-auto-reconnect').checked ? '1' : '0',
    led_brightness:          document.getElementById('s-led-brightness').value,
    led_green_gpio:          document.getElementById('s-pin-green').value,
    led_blue_gpio:           document.getElementById('s-pin-blue').value,
    led_yellow_gpio:         document.getElementById('s-pin-yellow').value,
    pairing_button_gpio:     document.getElementById('s-pin-button').value,
    dashboard_username:      document.getElementById('s-dashboard-user').value,
    web_port:                document.getElementById('s-web-port').value,
    cf_tunnel_token:         document.getElementById('s-cf-token').value,
  };
  if (pw) body.dashboard_password = pw;
  await api('PUT', '/api/settings', body);
  toast('success', 'Settings saved — some changes require reboot');
}

async function reboot() {
  await api('POST', '/api/system/reboot');
  toast('warning', 'Rebooting in 3 seconds…');
}

// ─── Logs ─────────────────────────────────────────────────────────────────────
async function loadLogs() {
  const limit = document.getElementById('log-limit')?.value || 100;
  const data  = await api('GET', `/api/logs?limit=${limit}`);
  if (!data) return;

  const containers = [
    document.getElementById('log-feed'),
    document.getElementById('activity-log'),
  ];
  const html = data.map(e => `
    <div class="log-entry">
      <span class="log-ts">${ts(e.ts)}</span>
      <span class="log-action">${esc(e.action)}</span>
      <span class="log-detail">${esc(JSON.stringify(e.details || {}))}</span>
    </div>
  `).join('');

  containers.forEach(c => { if (c) c.innerHTML = html; });
}

// ─── HID Keymap (browser KeyboardEvent.code → HID usage) ─────────────────────
function buildKeymap() {
  return {
    'KeyA':0x04,'KeyB':0x05,'KeyC':0x06,'KeyD':0x07,'KeyE':0x08,'KeyF':0x09,
    'KeyG':0x0A,'KeyH':0x0B,'KeyI':0x0C,'KeyJ':0x0D,'KeyK':0x0E,'KeyL':0x0F,
    'KeyM':0x10,'KeyN':0x11,'KeyO':0x12,'KeyP':0x13,'KeyQ':0x14,'KeyR':0x15,
    'KeyS':0x16,'KeyT':0x17,'KeyU':0x18,'KeyV':0x19,'KeyW':0x1A,'KeyX':0x1B,
    'KeyY':0x1C,'KeyZ':0x1D,
    'Digit1':0x1E,'Digit2':0x1F,'Digit3':0x20,'Digit4':0x21,'Digit5':0x22,
    'Digit6':0x23,'Digit7':0x24,'Digit8':0x25,'Digit9':0x26,'Digit0':0x27,
    'Enter':0x28,'Escape':0x29,'Backspace':0x2A,'Tab':0x2B,'Space':0x2C,
    'Minus':0x2D,'Equal':0x2E,'BracketLeft':0x2F,'BracketRight':0x30,
    'Backslash':0x31,'Semicolon':0x33,'Quote':0x34,'Backquote':0x35,
    'Comma':0x36,'Period':0x37,'Slash':0x38,'CapsLock':0x39,
    'F1':0x3A,'F2':0x3B,'F3':0x3C,'F4':0x3D,'F5':0x3E,'F6':0x3F,
    'F7':0x40,'F8':0x41,'F9':0x42,'F10':0x43,'F11':0x44,'F12':0x45,
    'F13':0x68,'F14':0x69,'F15':0x6A,'F16':0x6B,'F17':0x6C,'F18':0x6D,
    'F19':0x6E,'F20':0x6F,'F21':0x70,'F22':0x71,'F23':0x72,'F24':0x73,
    'PrintScreen':0x46,'ScrollLock':0x47,'Pause':0x48,
    'Insert':0x49,'Home':0x4A,'PageUp':0x4B,'Delete':0x4C,'End':0x4D,'PageDown':0x4E,
    'ArrowRight':0x4F,'ArrowLeft':0x50,'ArrowDown':0x51,'ArrowUp':0x52,
    'NumLock':0x53,'NumpadDivide':0x54,'NumpadMultiply':0x55,'NumpadSubtract':0x56,
    'NumpadAdd':0x57,'NumpadEnter':0x58,
    'Numpad1':0x59,'Numpad2':0x5A,'Numpad3':0x5B,'Numpad4':0x5C,'Numpad5':0x5D,
    'Numpad6':0x5E,'Numpad7':0x5F,'Numpad8':0x60,'Numpad9':0x61,'Numpad0':0x62,
    'NumpadDecimal':0x63,'ContextMenu':0x76,
    // Direct label aliases for virtual keyboard
    'Esc':0x29,'Backspace':0x2A,'Tab':0x2B,'CapsLock':0x39,'CapsLk':0x39,
    'PrtSc':0x46,'ScrLk':0x47,'Num':0x53,'⏎':0x58,
    'ArrowLeft':0x50,'ArrowDown':0x51,'ArrowRight':0x4F,'ArrowUp':0x52,
    '◀':0x50,'▼':0x51,'▶':0x4F,'▲':0x52,
    'ShiftLeft':0xE1,'ShiftRight':0xE5,
    'ControlLeft':0xE0,'ControlRight':0xE4,
    'AltLeft':0xE2,'AltRight':0xE6,
    'MetaLeft':0xE3,'MetaRight':0xE7,
  };
}

function getModBits(e) {
  let mod = 0;
  if (e.ctrlKey)  mod |= 0x01;
  if (e.shiftKey) mod |= 0x02;
  if (e.altKey)   mod |= 0x04;
  if (e.metaKey)  mod |= 0x08;
  return mod;
}

// ─── Toast notifications ──────────────────────────────────────────────────────
function toast(type, message, duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = { success:'✓', error:'✕', info:'ℹ', warning:'⚠' }[type] || '';
  el.innerHTML = `<span>${icon}</span><span>${esc(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    el.style.transition = 'opacity .3s, transform .3s';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ─── DOM helpers ──────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}
function setEl(id, fn) {
  const el = document.getElementById(id);
  if (el) fn(el);
}
function ts(unix) {
  const d = unix ? new Date(unix * 1000) : new Date();
  return d.toLocaleTimeString();
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  buildVirtualKeyboard();
  setupTrackpad();
  connectWS();

  // Fetch initial state via REST (before WS connects)
  api('GET', '/api/status').then(data => {
    if (data) applyState(data);
  });
  loadLogs();

  // Ping WS every 30s
  setInterval(() => wsSend({ type: 'ping' }), 30000);

  console.log('%cBT-KBM Dashboard loaded', 'color:#6366f1;font-weight:bold;font-size:1.1em');
});
