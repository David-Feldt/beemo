import asyncio
import base64

import bot

_latest_frame: bytes | None = None
HTTP_PORT = 8080

HTML_PAGE = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>beemoAI - Camera</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0a0a;
    color: #e0e0e0;
    font-family: system-ui, -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 1.5rem;
  }
  h1 {
    font-size: 1.1rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 1.2rem;
  }
  .stream-container {
    position: relative;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    border: 1px solid #1a1a1a;
    background: #111;
    line-height: 0;
  }
  .stream-container img {
    display: block;
    max-width: 100%;
    height: auto;
    min-width: 320px;
    min-height: 240px;
  }
  .badge {
    position: absolute;
    top: 10px;
    left: 10px;
    background: rgba(220, 38, 38, 0.85);
    color: white;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .badge::before {
    content: "";
    width: 6px;
    height: 6px;
    background: white;
    border-radius: 50%;
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
  }
</style>
</head>
<body>
  <h1>beemoAI</h1>
  <div class="stream-container">
    <img src="/stream" alt="Live camera feed">
    <div class="badge">LIVE</div>
  </div>
</body>
</html>"""


async def _subscribe_frames():
    global _latest_frame
    async for msg in bot.subscribe("/s/camera/frame"):
        _latest_frame = base64.b64decode(msg["data"])


async def _handle_http(reader, writer):
    try:
        raw = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        parts = raw.split(b" ", 2)
        path = parts[1].decode() if len(parts) >= 2 else "/"

        if path == "/stream":
            await _serve_mjpeg(writer)
        elif path == "/snapshot":
            await _serve_snapshot(writer)
        else:
            await _serve_page(writer)
    except Exception:
        await _close(writer)


async def _serve_page(writer):
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: " + str(len(HTML_PAGE)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + HTML_PAGE
    )
    await writer.drain()
    await _close(writer)


async def _serve_mjpeg(writer):
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
        b"Cache-Control: no-cache, no-store\r\n"
        b"Connection: keep-alive\r\n\r\n"
    )
    await writer.drain()

    try:
        while True:
            frame = _latest_frame
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


async def _serve_snapshot(writer):
    frame = _latest_frame
    if frame is not None:
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + frame
        )
    else:
        body = b"No frame available yet"
        writer.write(
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: text/plain\r\n"
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


async def main():
    http = await asyncio.start_server(_handle_http, "0.0.0.0", HTTP_PORT)
    print(f"Stream display running on http://0.0.0.0:{HTTP_PORT}")
    await asyncio.gather(_subscribe_frames(), http.serve_forever())


if __name__ == "__main__":
    bot.run(main())
