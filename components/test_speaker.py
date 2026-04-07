import asyncio
import base64
import math
import struct

import bot


async def main():
    await asyncio.sleep(0.5)  # wait for speaker to connect

    freq = 880
    duration = 0.5
    rate = 16000
    n_samples = int(rate * duration)

    samples = struct.pack(
        f"<{n_samples}h",
        *(int(16000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n_samples))
    )

    # duplicate mono to stereo (L+R) — MAX98357A requires 2 channels
    mono = struct.unpack(f"<{n_samples}h", samples)
    stereo = struct.pack(f"<{n_samples * 2}h", *[s for s in mono for _ in range(2)])

    await bot.publish("/s/speaker/audio", {
        "format": "S16_LE",
        "channels": 2,
        "rate": rate,
        "data": base64.b64encode(stereo).decode(),
    })
    print(f"Sent {freq} Hz beep for {duration}s")


if __name__ == "__main__":
    bot.run(main())
