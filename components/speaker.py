import asyncio
import base64
import re

import bot

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
                return f"plughw:{m.group(1)},{m.group(2)}"
    return "default"


async def main():
    device = await _find_device()
    print(f"Speaker ready (MAX98357A on {device})", flush=True)

    proc = None
    current_cfg = None

    async def open_aplay(cfg):
        rate, channels, fmt = cfg
        return await asyncio.create_subprocess_exec(
            "aplay",
            "-D", device,
            "-f", fmt,
            "-c", str(channels),
            "-r", str(rate),
            "-t", "raw",
            "--buffer-size", "12000",
            "--period-size", "1200",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def close_aplay():
        nonlocal proc
        if proc and proc.returncode is None:
            try:
                proc.stdin.close()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                proc.kill()
                try:
                    await proc.wait()
                except ProcessLookupError:
                    pass
        proc = None

    try:
        async for msg in bot.subscribe("/s/speaker/audio"):
            audio_bytes = base64.b64decode(msg["data"])
            cfg = (
                int(msg.get("rate", RATE)),
                int(msg.get("channels", CHANNELS)),
                msg.get("format", SAMPLE_FORMAT),
            )

            if proc is None or proc.returncode is not None or cfg != current_cfg:
                await close_aplay()
                proc = await open_aplay(cfg)
                current_cfg = cfg
                print(f"[speaker] aplay started ({cfg[0]} Hz, {cfg[1]}ch, {cfg[2]})", flush=True)

            try:
                proc.stdin.write(audio_bytes)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                print("[speaker] aplay pipe closed; restarting on next chunk", flush=True)
                await close_aplay()
    finally:
        await close_aplay()


if __name__ == "__main__":
    bot.run(main())
