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
            return f"hw:{m.group(1)},{m.group(2)}"
    return "default"


async def main():
    device = await _find_device()

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
