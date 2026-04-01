import asyncio
import base64
import io
import random

import bot
from PIL import Image, ImageDraw

WIDTH = 320
HEIGHT = 240

BG_COLOR = (0, 200, 180)
EYE_COLOR = (20, 20, 20)
MOUTH_COLOR = (20, 20, 20)
HIGHLIGHT_COLOR = (180, 255, 240)


def _draw_face(blink=False, expression="normal"):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    cx = WIDTH // 2
    cy = HEIGHT // 2 - 15

    if blink:
        draw.line([(cx - 55, cy), (cx - 25, cy)], fill=EYE_COLOR, width=3)
        draw.line([(cx + 25, cy), (cx + 55, cy)], fill=EYE_COLOR, width=3)
    elif expression == "happy":
        draw.arc([(cx - 60, cy - 18), (cx - 24, cy + 18)], 200, 360, fill=EYE_COLOR, width=3)
        draw.arc([(cx + 24, cy - 18), (cx + 60, cy + 18)], 200, 360, fill=EYE_COLOR, width=3)
    else:
        draw.ellipse([(cx - 58, cy - 14), (cx - 28, cy + 14)], fill=EYE_COLOR)
        draw.ellipse([(cx + 28, cy - 14), (cx + 58, cy + 14)], fill=EYE_COLOR)
        draw.ellipse([(cx - 53, cy - 9), (cx - 40, cy - 2)], fill=HIGHLIGHT_COLOR)
        draw.ellipse([(cx + 33, cy - 9), (cx + 46, cy - 2)], fill=HIGHLIGHT_COLOR)

    mouth_y = cy + 45
    if expression == "happy":
        draw.arc([(cx - 30, mouth_y - 15), (cx + 30, mouth_y + 15)], 0, 180, fill=MOUTH_COLOR, width=3)
    elif expression == "surprised":
        draw.ellipse([(cx - 14, mouth_y - 12), (cx + 14, mouth_y + 12)], outline=MOUTH_COLOR, width=3)
    else:
        draw.line([(cx - 22, mouth_y), (cx + 22, mouth_y)], fill=MOUTH_COLOR, width=3)

    return img


def _image_to_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def main():
    expressions = ["normal", "happy", "surprised"]
    current_expr = "normal"
    ticks = 0
    expr_duration = random.randint(30, 60)

    while True:
        blink = random.random() < 0.08

        if ticks >= expr_duration:
            current_expr = random.choice(expressions)
            expr_duration = random.randint(30, 60)
            ticks = 0

        frame = _draw_face(blink=blink, expression=current_expr)
        data = _image_to_b64(frame)

        await bot.publish("/s/screen/display", {
            "type": "image",
            "data": data,
        })

        ticks += 1
        await asyncio.sleep(0.15)


if __name__ == "__main__":
    bot.run(main())
