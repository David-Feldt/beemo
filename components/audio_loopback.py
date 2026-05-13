import asyncio
import base64
import math
import struct

import bot

MIC_CHANNELS = 1
SPEAKER_CHANNELS = 2
RATE = 16000
_count = 0


async def main():
    global _count
    print("Audio loopback ready (mic -> speaker)")

    async for msg in bot.subscribe("/s/microphone/audio"):
        mono = base64.b64decode(msg["data"])

        # Log levels every ~1 second (16000/4096 ≈ 4 chunks/sec)
        _count += 1
        if _count % 4 == 0:
            samples = struct.unpack(f"<{len(mono) // 2}h", mono)
            peak = max(abs(s) for s in samples)
            rms = math.sqrt(sum(s * s for s in samples) / len(samples))
            print(f"MIC peak={peak} rms={rms:.0f} (max=32767)")

        # Convert mono to stereo by duplicating each sample
        samples = struct.unpack(f"<{len(mono) // 2}h", mono)
        stereo = struct.pack(f"<{len(samples) * 2}h", *[s for s in samples for _ in range(2)])

        await bot.publish("/s/speaker/audio", {
            "format": "S16_LE",
            "channels": SPEAKER_CHANNELS,
            "rate": RATE,
            "data": base64.b64encode(stereo).decode("utf-8"),
        })


if __name__ == "__main__":
    bot.run(main())
