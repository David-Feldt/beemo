import asyncio
import base64
import struct
import math

import botos

CHUNK = 4096


def _rms(raw):
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    if not samples:
        return 0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _bar(level, width=40):
    filled = int(level * width)
    return "█" * filled + "░" * (width - filled)


async def main():
    async for msg in botos.subscribe("/s/microphone/audio"):
        raw = base64.b64decode(msg["data"])
        level = min(_rms(raw) / 8000.0, 1.0)
        db = 20 * math.log10(max(_rms(raw), 1)) 
        bar = _bar(level)
        print(f"\r  {db:5.1f} dB |{bar}|", end="", flush=True)


if __name__ == "__main__":
    botos.run(main())
