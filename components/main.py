import asyncio
import base64
import json
import math
import struct

import bot

HTTP_PORT = 8000

# Latest state from all streams
_camera_frame: bytes | None = None
_screen_frame: bytes | None = None
_audio_level = {"rms": 0.0, "db": 0.0}
_motor_state = {"left": 0.0, "right": 0.0}
_speaker_active = False
_button_states = {i: False for i in range(6)}

_sse_clients: list[asyncio.Queue] = []


# ── Stream subscribers ──────────────────────────────────────────────

async def _sub_camera():
    global _camera_frame
    async for msg in bot.subscribe("/s/camera/frame"):
        _camera_frame = base64.b64decode(msg["data"])


async def _sub_screen():
    global _screen_frame
    async for msg in bot.subscribe("/s/screen/display"):
        if msg.get("type") == "image":
            _screen_frame = base64.b64decode(msg["data"])


async def _sub_microphone():
    global _audio_level
    async for msg in bot.subscribe("/s/microphone/audio"):
        raw = base64.b64decode(msg["data"])
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        if samples:
            rms = math.sqrt(sum(s * s for s in samples) / len(samples))
            db = 20 * math.log10(max(rms, 1))
            _audio_level = {"rms": min(rms / 8000.0, 1.0), "db": round(db, 1)}
            await _broadcast_sse("audio", _audio_level)


async def _sub_motor():
    global _motor_state
    async for msg in bot.subscribe("/c/motor/drive"):
        _motor_state = {"left": msg.get("left", 0), "right": msg.get("right", 0)}
        await _broadcast_sse("motor", _motor_state)



async def _sub_speaker():
    global _speaker_active
    async for msg in bot.subscribe("/s/speaker/audio"):
        _speaker_active = True
        await _broadcast_sse("speaker", {"active": True})
        await asyncio.sleep(0.5)
        _speaker_active = False
        await _broadcast_sse("speaker", {"active": False})


async def _sub_buttons():
    async for msg in bot.subscribe("/s/buttons/event"):
        btn = msg["button"]
        _button_states[btn] = msg["pressed"]
        await _broadcast_sse("buttons", {
            "button": btn,
            "gpio": msg["gpio"],
            "pressed": msg["pressed"],
            "states": _button_states,
        })


# ── SSE broadcasting ────────────────────────────────────────────────

async def _broadcast_sse(event_type: str, data: dict):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_clients.remove(q)


# ── HTTP server ─────────────────────────────────────────────────────

async def _handle_http(reader, writer):
    try:
        raw = await asyncio.wait_for(reader.read(8192), timeout=5.0)
        line = raw.split(b"\r\n", 1)[0].decode()
        parts = line.split(" ", 2)
        method = parts[0] if parts else "GET"
        path = parts[1] if len(parts) >= 2 else "/"

        if method == "GET" and path == "/stream/camera":
            await _serve_mjpeg(writer, "camera")
        elif method == "GET" and path == "/stream/screen":
            await _serve_mjpeg(writer, "screen")
        elif method == "GET" and path == "/events":
            await _serve_sse(writer)
        elif method == "POST" and path == "/api/motor":
            body = _parse_body(raw)
            await _handle_motor_post(writer, body)
        elif method == "POST" and path == "/api/screen/text":
            body = _parse_body(raw)
            await _handle_screen_text(writer, body)
        elif method == "POST" and path == "/api/speaker/beep":
            body = _parse_body(raw)
            await _handle_beep(writer, body)
        elif method == "GET" and path == "/api/state":
            await _serve_state(writer)
        else:
            await _serve_page(writer)
    except Exception:
        await _close(writer)


def _parse_body(raw: bytes) -> dict:
    try:
        parts = raw.split(b"\r\n\r\n", 1)
        if len(parts) == 2:
            return json.loads(parts[1])
    except Exception:
        pass
    return {}


async def _serve_page(writer):
    page = HTML_PAGE.encode()
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: " + str(len(page)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + page
    )
    await writer.drain()
    await _close(writer)


async def _serve_mjpeg(writer, source):
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
        b"Cache-Control: no-cache, no-store\r\n"
        b"Connection: keep-alive\r\n\r\n"
    )
    await writer.drain()
    try:
        while True:
            frame = _camera_frame if source == "camera" else _screen_frame
            if frame is not None:
                writer.write(
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                    b"\r\n" + frame + b"\r\n"
                )
                await writer.drain()
            await asyncio.sleep(0.1)
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        await _close(writer)


async def _serve_sse(writer):
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/event-stream\r\n"
        b"Cache-Control: no-cache\r\n"
        b"Connection: keep-alive\r\n"
        b"Access-Control-Allow-Origin: *\r\n\r\n"
    )
    await writer.drain()

    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_clients.append(q)
    try:
        while True:
            payload = await q.get()
            writer.write(payload.encode())
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        if q in _sse_clients:
            _sse_clients.remove(q)
        await _close(writer)


async def _serve_state(writer):
    state = json.dumps({
        "motor": _motor_state,
        "audio": _audio_level,
        "speaker": {"active": _speaker_active},

        "buttons": _button_states,
        "camera": _camera_frame is not None,
        "screen": _screen_frame is not None,
    }).encode()
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(state)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + state
    )
    await writer.drain()
    await _close(writer)


async def _handle_motor_post(writer, body):
    left = float(body.get("left", 0))
    right = float(body.get("right", 0))
    left = max(-1.0, min(1.0, left))
    right = max(-1.0, min(1.0, right))
    await bot.publish("/c/motor/drive", {"left": left, "right": right})
    await _json_response(writer, {"ok": True, "left": left, "right": right})


async def _handle_beep(writer, body):
    freq = int(body.get("freq", 880))
    duration = float(body.get("duration", 0.3))
    duration = max(0.05, min(2.0, duration))
    rate = 16000
    n_samples = int(rate * duration)
    mono = [int(16000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n_samples)]
    stereo = struct.pack(f"<{n_samples * 2}h", *[s for s in mono for _ in range(2)])
    await bot.publish("/s/speaker/audio", {
        "format": "S16_LE",
        "channels": 2,
        "rate": rate,
        "data": base64.b64encode(stereo).decode("utf-8"),
    })
    await _json_response(writer, {"ok": True})


async def _handle_screen_text(writer, body):
    text = str(body.get("text", ""))
    await bot.publish("/s/screen/display", {"type": "text", "data": text})
    await _json_response(writer, {"ok": True})


async def _json_response(writer, data, status=200):
    body = json.dumps(data).encode()
    writer.write(
        f"HTTP/1.1 {status} OK\r\n".encode()
        + b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )
    await writer.drain()
    await _close(writer)


async def _close(writer):
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


# ── HTML Dashboard ──────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>beemoAI - Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0a0a; color: #e0e0e0;
    font-family: system-ui, -apple-system, sans-serif;
    padding: 1rem;
  }
  h1 {
    font-size: 1.1rem; font-weight: 500; letter-spacing: 0.08em;
    text-transform: uppercase; color: #666; text-align: center;
    margin-bottom: 1rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 1rem; max-width: 1400px; margin: 0 auto;
  }
  .card {
    background: #111; border: 1px solid #222; border-radius: 10px;
    overflow: hidden;
  }
  .card-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.7rem 1rem; border-bottom: 1px solid #1a1a1a;
  }
  .card-header h2 {
    font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; color: #888;
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #333; flex-shrink: 0;
  }
  .status-dot.active { background: #22c55e; box-shadow: 0 0 6px #22c55e88; }
  .card-body { padding: 1rem; }
  .stream-img {
    width: 100%; border-radius: 6px; background: #000;
    min-height: 180px; display: block;
  }
  .no-signal {
    display: flex; align-items: center; justify-content: center;
    min-height: 180px; color: #444; font-size: 0.85rem;
  }

  /* Audio meter */
  .meter { margin: 0.5rem 0; }
  .meter-bar {
    height: 20px; background: #1a1a1a; border-radius: 4px;
    overflow: hidden; position: relative;
  }
  .meter-fill {
    height: 100%; background: linear-gradient(90deg, #22c55e, #eab308, #ef4444);
    border-radius: 4px; transition: width 0.08s linear; width: 0%;
  }
  .meter-label {
    font-size: 0.75rem; color: #666; margin-top: 0.3rem;
    font-variant-numeric: tabular-nums;
  }

  /* Motor control */
  .motor-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 0.4rem; max-width: 200px; margin: 0 auto;
  }
  .motor-grid button {
    padding: 0.6rem; background: #1a1a1a; border: 1px solid #333;
    border-radius: 6px; color: #ccc; font-size: 1rem; cursor: pointer;
    transition: background 0.15s;
  }
  .motor-grid button:hover { background: #2a2a2a; }
  .motor-grid button:active, .motor-grid button.active {
    background: #0ea5e9; color: #fff; border-color: #0ea5e9;
  }
  .motor-grid button.stop { background: #7f1d1d; border-color: #991b1b; }
  .motor-grid button.stop:hover { background: #991b1b; }
  .motor-values {
    text-align: center; margin-top: 0.6rem; font-size: 0.75rem;
    color: #666; font-variant-numeric: tabular-nums;
  }
  .speed-control {
    display: flex; align-items: center; justify-content: center;
    gap: 0.5rem; margin-top: 0.6rem;
  }
  .speed-control label { font-size: 0.75rem; color: #666; }
  .speed-control input[type=range] { width: 120px; accent-color: #0ea5e9; }
  .speed-control .speed-val { font-size: 0.75rem; color: #aaa; width: 2.5em; }

/* Speaker */
  .speaker-vis {
    display: flex; align-items: center; gap: 0.6rem;
    min-height: 50px;
  }
  .speaker-icon {
    font-size: 1.5rem; opacity: 0.3; transition: opacity 0.2s;
  }
  .speaker-icon.active { opacity: 1; }
  .speaker-label { font-size: 0.8rem; color: #666; flex: 1; }
  .speaker-controls {
    display: flex; align-items: center; gap: 0.5rem; margin-top: 0.6rem;
  }
  .speaker-controls select, .speaker-controls button {
    padding: 0.4rem 0.7rem; background: #1a1a1a; border: 1px solid #333;
    border-radius: 6px; color: #ccc; font-size: 0.8rem; cursor: pointer;
  }
  .speaker-controls button {
    background: #0ea5e9; border-color: #0ea5e9; color: #fff;
  }
  .speaker-controls button:hover { background: #0284c7; }

  /* Buttons */
  .btn-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem; max-width: 240px; margin: 0 auto;
  }
  .btn-cell {
    padding: 0.7rem 0.4rem; background: #1a1a1a; border: 1px solid #333;
    border-radius: 8px; text-align: center; font-size: 0.75rem;
    color: #666; transition: all 0.15s;
  }
  .btn-cell.pressed {
    background: #22c55e; border-color: #22c55e; color: #fff;
    box-shadow: 0 0 8px #22c55e66;
  }
  .btn-cell .btn-id { font-weight: 600; font-size: 0.9rem; color: #ccc; }
  .btn-cell.pressed .btn-id { color: #fff; }
  .btn-cell .btn-gpio { font-size: 0.65rem; color: #555; margin-top: 0.2rem; }
  .btn-cell.pressed .btn-gpio { color: #ffffffaa; }

  /* Screen text */
  .screen-text-form {
    display: flex; gap: 0.4rem; margin-top: 0.7rem;
  }
  .screen-text-form input {
    flex: 1; padding: 0.4rem 0.6rem; background: #1a1a1a;
    border: 1px solid #333; border-radius: 6px; color: #e0e0e0;
    font-size: 0.8rem; outline: none;
  }
  .screen-text-form input:focus { border-color: #0ea5e9; }
  .screen-text-form button {
    padding: 0.4rem 0.8rem; background: #0ea5e9; border: none;
    border-radius: 6px; color: #fff; font-size: 0.8rem; cursor: pointer;
  }
</style>
</head>
<body>

<h1>beemoAI Dashboard</h1>

<div class="grid">

  <!-- Camera -->
  <div class="card">
    <div class="card-header">
      <h2>Camera</h2>
      <div class="status-dot" id="cam-status"></div>
    </div>
    <div class="card-body">
      <img class="stream-img" id="cam-img" src="/stream/camera" alt="Camera feed"
           onerror="this.style.display='none';document.getElementById('cam-nosig').style.display='flex'"
           onload="this.style.display='block';document.getElementById('cam-nosig').style.display='none';document.getElementById('cam-status').classList.add('active')">
      <div class="no-signal" id="cam-nosig">No signal</div>
    </div>
  </div>

  <!-- Screen Display -->
  <div class="card">
    <div class="card-header">
      <h2>Screen Display</h2>
      <div class="status-dot" id="screen-status"></div>
    </div>
    <div class="card-body">
      <img class="stream-img" id="screen-img" src="/stream/screen" alt="Screen display"
           onerror="this.style.display='none';document.getElementById('screen-nosig').style.display='flex'"
           onload="this.style.display='block';document.getElementById('screen-nosig').style.display='none';document.getElementById('screen-status').classList.add('active')">
      <div class="no-signal" id="screen-nosig">No signal</div>
      <div class="screen-text-form">
        <input type="text" id="screen-text" placeholder="Send text to screen...">
        <button onclick="sendScreenText()">Send</button>
      </div>
    </div>
  </div>

  <!-- Microphone / Audio -->
  <div class="card">
    <div class="card-header">
      <h2>Microphone</h2>
      <div class="status-dot" id="mic-status"></div>
    </div>
    <div class="card-body">
      <div class="meter">
        <div class="meter-bar"><div class="meter-fill" id="mic-fill"></div></div>
        <div class="meter-label" id="mic-label">-- dB</div>
      </div>
    </div>
  </div>

  <!-- Motor Control -->
  <div class="card">
    <div class="card-header">
      <h2>Motor Control</h2>
      <div class="status-dot" id="motor-status"></div>
    </div>
    <div class="card-body">
      <div class="motor-grid">
        <div></div>
        <button onmousedown="drive('forward')" onmouseup="drive('stop')" ontouchstart="drive('forward')" ontouchend="drive('stop')">&#9650;</button>
        <div></div>
        <button onmousedown="drive('left')" onmouseup="drive('stop')" ontouchstart="drive('left')" ontouchend="drive('stop')">&#9664;</button>
        <button class="stop" onclick="drive('stop')">&#9632;</button>
        <button onmousedown="drive('right')" onmouseup="drive('stop')" ontouchstart="drive('right')" ontouchend="drive('stop')">&#9654;</button>
        <div></div>
        <button onmousedown="drive('backward')" onmouseup="drive('stop')" ontouchstart="drive('backward')" ontouchend="drive('stop')">&#9660;</button>
        <div></div>
      </div>
      <div class="speed-control">
        <label>Speed</label>
        <input type="range" id="speed-slider" min="10" max="100" value="60">
        <span class="speed-val" id="speed-val">60%</span>
      </div>
      <div class="motor-values" id="motor-values">L: 0.00 &nbsp; R: 0.00</div>
    </div>
  </div>

<!-- Speaker -->
  <div class="card">
    <div class="card-header">
      <h2>Speaker</h2>
      <div class="status-dot" id="speaker-status"></div>
    </div>
    <div class="card-body">
      <div class="speaker-vis">
        <div class="speaker-icon" id="speaker-icon">&#128266;</div>
        <div class="speaker-label" id="speaker-label">Idle</div>
      </div>
      <div class="speaker-controls">
        <select id="beep-freq">
          <option value="440">440 Hz</option>
          <option value="660">660 Hz</option>
          <option value="880" selected>880 Hz</option>
          <option value="1200">1200 Hz</option>
        </select>
        <button onclick="playBeep()">Play Sound</button>
      </div>
    </div>
  </div>

  <!-- Buttons -->
  <div class="card">
    <div class="card-header">
      <h2>Buttons</h2>
      <div class="status-dot" id="btn-status"></div>
    </div>
    <div class="card-body">
      <div class="btn-grid">
        <div class="btn-cell" id="btn-0"><div class="btn-id">0</div><div class="btn-gpio">GPIO 4</div></div>
        <div class="btn-cell" id="btn-1"><div class="btn-id">1</div><div class="btn-gpio">GPIO 5</div></div>
        <div class="btn-cell" id="btn-2"><div class="btn-id">2</div><div class="btn-gpio">GPIO 12</div></div>
        <div class="btn-cell" id="btn-3"><div class="btn-id">3</div><div class="btn-gpio">GPIO 14</div></div>
        <div class="btn-cell" id="btn-4"><div class="btn-id">4</div><div class="btn-gpio">GPIO 15</div></div>
        <div class="btn-cell" id="btn-5"><div class="btn-id">5</div><div class="btn-gpio">GPIO 16</div></div>
      </div>
    </div>
  </div>

</div>

<script>
const speedSlider = document.getElementById('speed-slider');
const speedVal = document.getElementById('speed-val');
speedSlider.oninput = () => { speedVal.textContent = speedSlider.value + '%'; };

function getSpeed() { return speedSlider.value / 100; }

function drive(dir) {
  const s = getSpeed();
  let left = 0, right = 0;
  if (dir === 'forward')  { left = s; right = s; }
  if (dir === 'backward') { left = -s; right = -s; }
  if (dir === 'left')     { left = -s; right = s; }
  if (dir === 'right')    { left = s; right = -s; }
  fetch('/api/motor', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({left, right})
  });
}

function sendScreenText() {
  const input = document.getElementById('screen-text');
  const text = input.value.trim();
  if (!text) return;
  fetch('/api/screen/text', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text})
  });
  input.value = '';
}
document.getElementById('screen-text').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendScreenText();
});

function playBeep() {
  const freq = parseInt(document.getElementById('beep-freq').value);
  fetch('/api/speaker/beep', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({freq, duration: 0.3})
  });
}

// Keyboard shortcuts for motor
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  const map = {w:'forward', ArrowUp:'forward', s:'backward', ArrowDown:'backward',
               a:'left', ArrowLeft:'left', d:'right', ArrowRight:'right', ' ':'stop'};
  if (map[e.key]) { e.preventDefault(); drive(map[e.key]); }
});
document.addEventListener('keyup', e => {
  if (e.target.tagName === 'INPUT') return;
  const moving = ['w','s','a','d','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];
  if (moving.includes(e.key)) { drive('stop'); }
});

// SSE for real-time updates
const es = new EventSource('/events');

es.addEventListener('audio', e => {
  const d = JSON.parse(e.data);
  document.getElementById('mic-fill').style.width = (d.rms * 100) + '%';
  document.getElementById('mic-label').textContent = d.db.toFixed(1) + ' dB';
  document.getElementById('mic-status').classList.add('active');
});

es.addEventListener('motor', e => {
  const d = JSON.parse(e.data);
  document.getElementById('motor-values').textContent =
    'L: ' + d.left.toFixed(2) + '   R: ' + d.right.toFixed(2);
  document.getElementById('motor-status').classList.add('active');
});

es.addEventListener('speaker', e => {
  const d = JSON.parse(e.data);
  const icon = document.getElementById('speaker-icon');
  const label = document.getElementById('speaker-label');
  const dot = document.getElementById('speaker-status');
  if (d.active) {
    icon.classList.add('active'); label.textContent = 'Playing'; dot.classList.add('active');
  } else {
    icon.classList.remove('active'); label.textContent = 'Idle'; dot.classList.remove('active');
  }
});

es.addEventListener('buttons', e => {
  const d = JSON.parse(e.data);
  document.getElementById('btn-status').classList.add('active');
  for (const [id, pressed] of Object.entries(d.states)) {
    const el = document.getElementById('btn-' + id);
    if (el) el.classList.toggle('pressed', pressed);
  }
});

// Initial state
fetch('/api/state').then(r => r.json()).then(d => {
  if (d.camera) document.getElementById('cam-status').classList.add('active');
  if (d.screen) document.getElementById('screen-status').classList.add('active');
  if (d.audio) {
    document.getElementById('mic-fill').style.width = (d.audio.rms * 100) + '%';
    document.getElementById('mic-label').textContent = d.audio.db.toFixed(1) + ' dB';
    document.getElementById('mic-status').classList.add('active');
  }
  document.getElementById('motor-values').textContent =
    'L: ' + d.motor.left.toFixed(2) + '   R: ' + d.motor.right.toFixed(2);
  if (d.buttons) {
    for (const [id, pressed] of Object.entries(d.buttons)) {
      const el = document.getElementById('btn-' + id);
      if (el) el.classList.toggle('pressed', pressed);
    }
  }
}).catch(() => {});
</script>

</body>
</html>"""


# ── Entry point ─────────────────────────────────────────────────────

async def main():
    http = await asyncio.start_server(_handle_http, "0.0.0.0", HTTP_PORT)
    print(f"Dashboard running on http://0.0.0.0:{HTTP_PORT}")
    await asyncio.gather(
        http.serve_forever(),
        _sub_camera(),
        _sub_screen(),
        _sub_microphone(),
        _sub_motor(),

        _sub_speaker(),
        _sub_buttons(),
    )


if __name__ == "__main__":
    bot.run(main())
