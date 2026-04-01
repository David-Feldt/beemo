import asyncio
import base64
import json
import os

import botos
from vosk import Model, KaldiRecognizer

RATE = 16000
WAKE_WORD = "beemo"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "vosk-small-en")


async def main():
    if os.path.exists(MODEL_PATH):
        model = Model(MODEL_PATH)
    else:
        model = Model(lang="en-us")

    rec = KaldiRecognizer(model, RATE)

    async for msg in botos.subscribe("/s/microphone/audio"):
        raw = base64.b64decode(msg["data"])

        if rec.AcceptWaveform(raw):
            result = json.loads(rec.Result())
            text = result.get("text", "").lower()
        else:
            partial = json.loads(rec.PartialResult())
            text = partial.get("partial", "").lower()

        if WAKE_WORD in text:
            print("listening")
            await botos.publish("/s/wake/detected", {
                "wake_word": WAKE_WORD,
                "transcript": text,
            })
            rec.Reset()


if __name__ == "__main__":
    botos.run(main())
