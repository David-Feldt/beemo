import asyncio
import botos


async def main():
    counter = 0
    while True:
        await botos.publish("/s/example/data", {{"count": counter}})
        counter += 1
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    botos.run(main())
