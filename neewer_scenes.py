"""Scene engine for Neewer lights.

Supports two scene types:
- Scripted (YAML): timed steps with per-role targets and fade interpolation
- Generative (Python): render() callback called each frame

Usage:
    scene = load_scene("scenes/sunset-fade.yaml")
    scene = load_scene("scenes/rainbow_chase.py")
"""
import asyncio
import importlib.util
import os
import re
import time

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


class SceneRunner:
    """Runs a scene against a dict of {role: light} objects.

    Each light must have an async send(mode, params) method.
    For generative scenes, max_ticks limits iterations (None = run until cancelled).
    """

    def __init__(self, scene, lights, max_ticks=None, audio_source=None):
        self.scene = scene
        self.lights = lights
        self.max_ticks = max_ticks
        self.audio_source = audio_source
        self._stop = False

    def stop(self):
        self._stop = True

    async def run(self):
        if self.scene.generative:
            await self._run_generative()
        else:
            await self._run_scripted()

    async def _run_generative(self):
        interval = 1.0 / self.scene.fps
        tick = 0
        roles = list(self.lights.keys())
        while not self._stop:
            if self.max_ticks is not None and tick >= self.max_ticks:
                break
            audio = None
            if self.audio_source:
                audio = self.audio_source.read()
            result = self.scene.render(tick, roles, {}, audio=audio)
            await self._apply(result)
            tick += 1
            await asyncio.sleep(interval)

    async def _run_scripted(self):
        steps = self.scene.steps
        if not steps:
            return
        duration = self.scene.duration
        start = time.monotonic()

        while not self._stop:
            elapsed = time.monotonic() - start
            if elapsed >= duration:
                if self.scene.loop:
                    start = time.monotonic()
                    elapsed = 0.0
                else:
                    # Apply final step before exiting
                    await self._apply_step(steps[-1])
                    break

            # Find surrounding steps for interpolation
            prev_step = steps[0]
            next_step = None
            for s in steps:
                if s.time <= elapsed:
                    prev_step = s
                else:
                    next_step = s
                    break

            if next_step is None:
                await self._apply_step(prev_step)
            else:
                # Interpolate between prev and next
                span = next_step.time - prev_step.time
                t = (elapsed - prev_step.time) / span if span > 0 else 1.0
                await self._apply_interpolated(prev_step, next_step, t)

            await asyncio.sleep(1.0 / 30)  # 30 fps update rate for scripted

    async def _apply_step(self, step):
        for role, params in step.targets.items():
            if "fade" in params:
                actual = dict(params)
                actual.update(actual.pop("fade"))
                params = actual
            await self._send_to_role(role, params)

    async def _apply_interpolated(self, prev_step, next_step, t):
        for role in prev_step.targets:
            a = prev_step.targets[role]
            # Unwrap fade targets
            if "fade" in a:
                a = dict(a)
                a.update(a.pop("fade"))

            b = next_step.targets.get(role)
            if b is None:
                await self._send_to_role(role, a)
                continue
            if "fade" in b:
                b = dict(b)
                b.update(b.pop("fade"))

            merged = interpolate(a, b, t)
            await self._send_to_role(role, merged)

    async def _apply(self, result):
        for role, params in result.items():
            await self._send_to_role(role, params)

    async def _send_to_role(self, role, params):
        mode = params.get("mode", "cct")
        if role == "all":
            for light in self.lights.values():
                await light.send(mode, params)
        elif role in self.lights:
            await self.lights[role].send(mode, params)


class BLELight:
    """Adapter: scene runner -> BLE protocol commands via channel mode."""

    def __init__(self, client, nid, ch, proto, mac_bytes, write_uuid):
        self.client = client
        self.nid = nid
        self.ch = ch
        self.proto = proto
        self.mac_bytes = mac_bytes
        self.write_uuid = write_uuid

    async def send(self, mode, params):
        import neewer
        bri = params.get("brightness", 50)

        if mode == "cct":
            temp = params.get("temp", 5000)
            gm = params.get("gm", 0)
            if self.ch is not None:
                pkt = neewer.ch_cmd_cct(self.nid, self.ch, bri, temp, gm)
            else:
                pkt = neewer.build_cct(self.proto, self.mac_bytes, bri, temp, gm)
        elif mode == "hsi":
            hue = params.get("hue", 0)
            sat = params.get("sat", 100)
            if self.ch is not None:
                pkt = neewer.ch_cmd_hsi(self.nid, self.ch, hue, sat, bri)
            else:
                pkt = neewer.build_hsi(self.proto, self.mac_bytes, hue, sat, bri)
        elif mode == "scene":
            effect = params.get("effect", "lightning")
            eid = neewer.EFFECTS.get(effect, 0x01) if isinstance(effect, str) else effect
            speed = params.get("speed", 5)
            if self.ch is not None:
                pkt = neewer.ch_cmd_scene(self.nid, self.ch, eid, bri, speed)
            else:
                pkt = neewer.build_scene(self.proto, self.mac_bytes, eid, bri, speed)
        else:
            return

        await self.client.write_gatt_char(self.write_uuid, pkt, response=False)
