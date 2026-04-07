import bot


async def main():
    print("Button reader ready, waiting for button events...")
    async for msg in bot.subscribe("/s/buttons/event"):
        if msg["pressed"]:
            print(f"Button {msg['button']} (GPIO {msg['gpio']}) PRESSED")
        else:
            print(f"Button {msg['button']} (GPIO {msg['gpio']}) released")


if __name__ == "__main__":
    bot.run(main())
