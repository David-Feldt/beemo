import asyncio
import base64
import re

import bot

CHANNELS = 1
RATE = 16000
CHUNK = 4096
SAMPLE_BYTES = 2
FRAME_SIZE = CHANNELS * SAMPLE_BYTES
PERIOD_BYTES = CHUNK * FRAME_SIZE

_mic_enabled = True


async def _find_device():
    proc = await asyncio.create_subprocess_exec(
        "arecord", "-l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode().splitlines():
        m = re.match(r"card\s+(\d+).*device\s+(\d+)", line, re.IGNORECASE)
        if m:
            return f"plughw:{m.group(1)},{m.group(2)}"
    return "default"


async def _watch_enabled():
    """Listen for /s/audio/mic_enabled and update the publish gate."""
    global _mic_enabled
    async for msg in bot.subscribe("/s/audio/mic_enabled"):
        new_state = bool(msg.get("enabled", True))
        if new_state != _mic_enabled:
            _mic_enabled = new_state
            print(f"[mic] {'ENABLED' if new_state else 'MUTED'}", flush=True)


async def main():
    device = await _find_device()
    print(f"USB mic ready (capturing from {device} @ {RATE} Hz mono)", flush=True)

    asyncio.create_task(_watch_enabled())

    proc = await asyncio.create_subprocess_exec(
        "arecord",
        "-D", device,
        "-f", "S16_LE",
        "-c", str(CHANNELS),
        "-r", str(RATE),
        "-t", "raw",
        "--buffer-size", str(CHUNK * 4),
        "--period-size", str(CHUNK),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    try:
        while True:
            data = await proc.stdout.readexactly(PERIOD_BYTES)
            if not _mic_enabled:
                continue

            audio_b64 = base64.b64encode(data).decode("utf-8")
            await bot.publish("/s/microphone/audio", {
                "format": "pcm_s16le",
                "channels": CHANNELS,
                "rate": RATE,
                "samples": CHUNK,
                "data": audio_b64,
            })
    finally:
        proc.kill()
        await proc.wait()


if __name__ == "__main__":
    bot.run(main())
