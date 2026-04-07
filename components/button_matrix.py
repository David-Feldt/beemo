import asyncio

import bot
import gpiod
from gpiod.line import Direction, Bias

BUTTON_PINS = [4, 5, 12, 14, 15, 16]

POLL_INTERVAL = 0.05
DEBOUNCE_TIME = 0.05


async def main():
    chip = gpiod.Chip("/dev/gpiochip4")
    lines = chip.request_lines(
        config={
            pin: gpiod.LineSettings(
                direction=Direction.INPUT,
                bias=Bias.PULL_UP,
            )
            for pin in BUTTON_PINS
        },
    )

    prev = {pin: True for pin in BUTTON_PINS}
    debounce = {pin: 0.0 for pin in BUTTON_PINS}

    print(f"Button matrix ready (GPIOs {BUTTON_PINS})")

    try:
        while True:
            now = asyncio.get_event_loop().time()
            for i, pin in enumerate(BUTTON_PINS):
                val = bool(lines.get_value(pin))
                if val != prev[pin] and (now - debounce[pin]) > DEBOUNCE_TIME:
                    debounce[pin] = now
                    prev[pin] = val
                    pressed = not val  # active low with pull-up
                    await bot.publish("/s/buttons/event", {
                        "button": i,
                        "gpio": pin,
                        "pressed": pressed,
                    })
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        lines.release()
        chip.close()


if __name__ == "__main__":
    bot.run(main())
