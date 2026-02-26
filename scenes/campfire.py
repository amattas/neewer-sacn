"""Campfire flicker — warm random brightness and temperature variation."""
import random

name = "Campfire"
fps = 15


def render(tick, lights, params, audio=None):
    base_bri = params.get("brightness", 60)
    result = {}
    for role in lights:
        bri = max(10, base_bri + random.randint(-25, 15))
        temp = 2700 + random.randint(-200, 400)
        result[role] = {"mode": "cct", "brightness": bri, "temp": temp, "gm": 0}
    return result
