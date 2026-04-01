import asyncio
import time

import bot
from gpiozero import Motor

IN1 = 27  # Left motor forward
IN2 = 22  # Left motor backward
IN3 = 23  # Right motor forward
IN4 = 24  # Right motor backward

COMMAND_TIMEOUT = 0.5

_last_cmd_time = 0.0


def _drive(motor: Motor, value: float):
    value = max(-1.0, min(1.0, value))
    if value > 0:
        motor.forward(value)
    elif value < 0:
        motor.backward(-value)
    else:
        motor.stop()


async def _watchdog(left: Motor, right: Motor):
    """Stop motors if no command received within the timeout (dead-man's switch)."""
    while True:
        await asyncio.sleep(0.1)
        if _last_cmd_time > 0 and (time.monotonic() - _last_cmd_time) > COMMAND_TIMEOUT:
            left.stop()
            right.stop()


async def main():
    global _last_cmd_time

    left = Motor(forward=IN1, backward=IN2)
    right = Motor(forward=IN3, backward=IN4)

    asyncio.get_event_loop().create_task(_watchdog(left, right))

    print(f"Motor driver ready (L: IN1={IN1}/IN2={IN2}, R: IN3={IN3}/IN4={IN4})")

    try:
        async for msg in bot.subscribe("/c/motor/drive"):
            l = float(msg.get("left", 0))
            r = float(msg.get("right", 0))
            _drive(left, l)
            _drive(right, r)
            _last_cmd_time = time.monotonic()
    finally:
        left.stop()
        right.stop()
        left.close()
        right.close()


if __name__ == "__main__":
    bot.run(main())
