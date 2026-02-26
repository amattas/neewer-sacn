"""Color changes on beat detection."""
name = "Beat Flash"
fps = 30


def render(tick, lights, params, audio=None):
    if not audio or not audio.beat:
        return None  # no update
    hue = (tick * 37) % 360
    return {"all": {"mode": "hsi", "hue": hue, "sat": 100, "brightness": 90}}
