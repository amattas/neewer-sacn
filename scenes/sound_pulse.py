"""Brightness follows audio amplitude."""
name = "Sound Pulse"
fps = 30


def render(tick, lights, params, audio=None):
    if not audio:
        return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
    bri = max(5, int(audio.amplitude * 100))
    temp = params.get("temp", 5000)
    return {"all": {"mode": "cct", "brightness": bri, "temp": temp}}
