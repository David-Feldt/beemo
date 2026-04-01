import asyncio
import bot


async def main():
    counter = 0
    while True:
        await bot.publish("/s/example/data", {{"count": counter}})
        counter += 1
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    bot.run(main())
