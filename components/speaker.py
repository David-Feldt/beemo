import asyncio
import base64
import re

import bot

# MAX98357A I2S Amplifier
# BCLK -> GPIO 25
# LRC  -> GPIO 7
# DIN  -> GPIO 1

CHANNELS = 2
RATE = 16000
SAMPLE_FORMAT = "S16_LE"


async def _find_device():
    proc = await asyncio.create_subprocess_exec(
        "aplay", "-l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode().splitlines():
        if "hifiberry" in line.lower():
            m = re.match(r"card\s+(\d+).*device\s+(\d+)", line, re.IGNORECASE)
            if m:
                return f"hw:{m.group(1)},{m.group(2)}"
    return "default"


async def main():
    device = await _find_device()
    print(f"Speaker ready (MAX98357A on {device})")

    async for msg in bot.subscribe("/s/speaker/audio"):
        audio_bytes = base64.b64decode(msg["data"])
        rate = msg.get("rate", RATE)
        channels = msg.get("channels", CHANNELS)
        fmt = msg.get("format", SAMPLE_FORMAT)

        proc = await asyncio.create_subprocess_exec(
            "aplay",
            "-D", device,
            "-f", fmt,
            "-c", str(channels),
            "-r", str(rate),
            "-t", "raw",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc.stdin.write(audio_bytes)
        proc.stdin.close()
        await proc.wait()


if __name__ == "__main__":
    bot.run(main())
