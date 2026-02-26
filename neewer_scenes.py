"""Scene engine for Neewer lights.

Supports two scene types:
- Scripted (YAML): timed steps with per-role targets and fade interpolation
- Generative (Python): render() callback called each frame

Usage:
    scene = load_scene("scenes/sunset-fade.yaml")
    scene = load_scene("scenes/rainbow_chase.py")
"""
import importlib.util
import os
import re

import yaml


def parse_duration(s):
    """Parse duration string like '10s', '2m', '30' to float seconds."""
    s = str(s).strip()
    m = re.match(r'^([\d.]+)(s|m)?$', s)
    if not m:
        raise ValueError(f"Invalid duration: {s}")
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return val * 60.0
    return val


class SceneStep:
    """A single timed step in a scripted scene."""

    def __init__(self, time, targets):
        self.time = time
        self.targets = targets


class Scene:
    """Loaded scene (scripted or generative)."""

    def __init__(self):
        self.name = "Untitled"
        self.duration = 0.0
        self.loop = False
        self.target_roles = []
        self.steps = []
        self.generative = False
        self.fps = 20
        self.render = None
        self.source_path = None


def load_scene(path):
    """Load a scene from YAML or Python file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        return _load_yaml(path)
    elif ext == ".py":
        return _load_generative(path)
    else:
        raise ValueError(f"Unknown scene file type: {ext}")


def _load_yaml(path):
    with open(path) as f:
        data = yaml.safe_load(f)

    scene = Scene()
    scene.source_path = path
    scene.name = data.get("name", os.path.basename(path))
    scene.duration = parse_duration(data.get("duration", "10s"))
    scene.loop = data.get("loop", False)
    scene.target_roles = data.get("targets", ["all"])

    for step_data in data.get("steps", []):
        time = parse_duration(step_data.get("at", "0s"))
        targets = {}
        for key, val in step_data.items():
            if key != "at":
                targets[key] = val
        scene.steps.append(SceneStep(time, targets))

    scene.steps.sort(key=lambda s: s.time)
    return scene


def _load_generative(path):
    spec = importlib.util.spec_from_file_location("_scene", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    scene = Scene()
    scene.source_path = path
    scene.generative = True
    scene.name = getattr(mod, "name", os.path.basename(path))
    scene.fps = getattr(mod, "fps", 20)
    scene.render = mod.render
    scene.loop = True
    return scene


def interpolate(a, b, t):
    """Interpolate between two param dicts. Handles hue wrap-around."""
    result = {}
    all_keys = set(list(a.keys()) + list(b.keys()))
    for key in all_keys:
        va = a.get(key, 0)
        vb = b.get(key, va)
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            result[key] = vb if t >= 0.5 else va
            continue
        if key == "hue":
            diff = (vb - va + 540) % 360 - 180
            result[key] = int(va + diff * t) % 360
        else:
            result[key] = int(va + (vb - va) * t)
    return result


def list_scenes(dirs=None):
    """List available scene files from the given directories."""
    if dirs is None:
        dirs = ["scenes"]
        home_scenes = os.path.expanduser("~/.neewer/scenes")
        if os.path.isdir(home_scenes):
            dirs.append(home_scenes)

    scenes = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.endswith((".yaml", ".yml", ".py")) and not fname.startswith("_"):
                scenes.append(os.path.join(d, fname))
    return scenes
