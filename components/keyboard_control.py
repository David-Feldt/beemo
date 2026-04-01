import asyncio
import sys
import termios
import tty

import bot

SPEED_DEFAULT = 0.6
SPEED_STEP = 0.1
SPEED_MIN = 0.1
SPEED_MAX = 1.0

DRIVE_RATE = 0.05

KEYMAP = {
    "w": ("forward",),
    "s": ("backward",),
    "a": ("left",),
    "d": ("right",),
    " ": ("stop",),
    "+": ("speed_up",),
    "=": ("speed_up",),
    "-": ("speed_down",),
    "q": ("quit",),
    # Arrow keys (ANSI escape: \x1b[A/B/C/D)
    "\x1b[A": ("forward",),
    "\x1b[B": ("backward",),
    "\x1b[D": ("left",),
    "\x1b[C": ("right",),
}


def _read_key(fd):
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        ch2 = sys.stdin.read(1)
        ch3 = sys.stdin.read(1)
        return ch + ch2 + ch3
    return ch


def _banner(speed):
    sys.stdout.write(
        "\x1b[2J\x1b[H"
        "╔══════════════════════════════════╗\n"
        "║     beemoAI Keyboard Control     ║\n"
        "╠══════════════════════════════════╣\n"
        "║                                  ║\n"
        "║          W / ↑  Forward          ║\n"
        "║    A / ←  Stop  D / →            ║\n"
        "║          S / ↓  Backward         ║\n"
        "║                                  ║\n"
        "║    Space = Stop   Q = Quit       ║\n"
        "║    +/- = Adjust speed            ║\n"
        "║                                  ║\n"
        f"║    Speed: {speed:.0%}                     ║\n"
        "╚══════════════════════════════════╝\n"
        "\n"
    )
    sys.stdout.flush()


def _status(label, left, right, speed):
    sys.stdout.write(
        f"\r\x1b[K  {label:<10s}  L={left:+.2f}  R={right:+.2f}  speed={speed:.0%}"
    )
    sys.stdout.flush()


async def main():
    speed = SPEED_DEFAULT
    left = 0.0
    right = 0.0
    action = "stop"
    dirty = True

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    loop = asyncio.get_event_loop()

    _banner(speed)
    _status("Stopped", 0, 0, speed)

    try:
        while True:
            key = await loop.run_in_executor(None, _read_key, fd)
            entry = KEYMAP.get(key.lower() if len(key) == 1 else key)

            if entry is None:
                continue

            action = entry[0]

            if action == "quit":
                left, right = 0.0, 0.0
                await bot.publish("/c/motor/drive", {"left": 0, "right": 0})
                break
            elif action == "speed_up":
                speed = min(SPEED_MAX, round(speed + SPEED_STEP, 2))
                _banner(speed)
                dirty = True
            elif action == "speed_down":
                speed = max(SPEED_MIN, round(speed - SPEED_STEP, 2))
                _banner(speed)
                dirty = True
            elif action == "forward":
                left, right = speed, speed
                dirty = True
            elif action == "backward":
                left, right = -speed, -speed
                dirty = True
            elif action == "left":
                left, right = -speed, speed
                dirty = True
            elif action == "right":
                left, right = speed, -speed
                dirty = True
            elif action == "stop":
                left, right = 0.0, 0.0
                dirty = True

            if dirty:
                await bot.publish("/c/motor/drive", {"left": left, "right": right})
                label = action.capitalize() if action != "stop" else "Stopped"
                _status(label, left, right, speed)
                dirty = False
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\n")


if __name__ == "__main__":
    bot.run(main())
