"""Rainbow chase — rotating hue offset across lights."""
name = "Rainbow Chase"
fps = 20


def render(tick, lights, params, audio=None):
    speed = params.get("speed", 2)
    bri = params.get("brightness", 70)
    result = {}
    for i, role in enumerate(lights):
        hue = (tick * speed + i * 60) % 360
        result[role] = {"mode": "hsi", "hue": hue, "sat": 100, "brightness": bri}
    return result
