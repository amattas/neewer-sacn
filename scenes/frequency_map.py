"""Map frequency bands to light parameters."""
name = "Frequency Map"
fps = 30


def render(tick, lights, params, audio=None):
    if not audio:
        return {"all": {"mode": "hsi", "hue": 0, "sat": 50, "brightness": 30}}
    bass, mid, treble = audio.bands
    hue = int(treble * 360) % 360
    sat = max(20, int(mid * 100))
    bri = max(5, int(bass * 100))
    return {"all": {"mode": "hsi", "hue": hue, "sat": sat, "brightness": bri}}
