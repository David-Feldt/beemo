import asyncio
import base64
import io

import bot
from picamera2 import Picamera2


async def main():
    camera = Picamera2()
    camera.configure(camera.create_still_configuration(main={"size": (640, 480)}))
    camera.start()

    try:
        while True:
            buf = io.BytesIO()
            camera.capture_file(buf, format="jpeg")
            frame_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            await bot.publish("/s/camera/frame", {
                "format": "jpeg",
                "width": 640,
                "height": 480,
                "data": frame_b64,
            })

            await asyncio.sleep(0.1)
    finally:
        camera.stop()


if __name__ == "__main__":
    bot.run(main())
