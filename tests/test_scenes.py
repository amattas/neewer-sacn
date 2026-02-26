"""Tests for neewer_scenes.py — scene engine."""
import os
import tempfile
import yaml
from neewer import scenes as neewer_scenes


def _write_yaml(content):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(content, f)
    return path


def test_load_yaml_scene():
    data = {
        "name": "Test Scene",
        "duration": "10s",
        "loop": False,
        "targets": ["all"],
        "steps": [
            {"at": "0s", "all": {"mode": "cct", "brightness": 80, "temp": 5600}},
            {"at": "5s", "all": {"fade": {"brightness": 20, "temp": 3200}}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)
    assert scene.name == "Test Scene"
    assert scene.duration == 10.0
    assert scene.loop is False
    assert len(scene.steps) == 2
    assert scene.steps[0].time == 0.0
    assert scene.steps[1].time == 5.0
    os.unlink(path)


def test_parse_duration():
    assert neewer_scenes.parse_duration("10s") == 10.0
    assert neewer_scenes.parse_duration("1.5s") == 1.5
    assert neewer_scenes.parse_duration("2m") == 120.0
    assert neewer_scenes.parse_duration("0.5m") == 30.0
    assert neewer_scenes.parse_duration("30") == 30.0


def test_load_generative_scene():
    code = '''
name = "Test Gen"
fps = 20

def render(tick, lights, params, audio=None):
    return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
'''
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    scene = neewer_scenes.load_scene(path)
    assert scene.name == "Test Gen"
    assert scene.fps == 20
    assert scene.generative is True
    result = scene.render(0, ["key", "fill"], {})
    assert result["all"]["brightness"] == 50
    os.unlink(path)


def test_interpolate_values():
    a = {"brightness": 80, "temp": 5600}
    b = {"brightness": 20, "temp": 3200}
    mid = neewer_scenes.interpolate(a, b, 0.5)
    assert mid["brightness"] == 50
    assert mid["temp"] == 4400


def test_interpolate_hue_wraps():
    a = {"hue": 350, "sat": 100, "brightness": 80}
    b = {"hue": 10, "sat": 100, "brightness": 80}
    mid = neewer_scenes.interpolate(a, b, 0.5)
    assert mid["hue"] == 0  # shortest path wraps through 360


def test_step_targets():
    data = {
        "name": "Multi",
        "duration": "5s",
        "targets": ["key", "fill"],
        "steps": [
            {"at": "0s", "key": {"mode": "cct", "brightness": 80, "temp": 5600},
                         "fill": {"mode": "cct", "brightness": 40, "temp": 4200}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)
    step = scene.steps[0]
    assert "key" in step.targets
    assert "fill" in step.targets
    assert step.targets["key"]["brightness"] == 80
    os.unlink(path)


# --- Task 7: Scene Runner ---

import asyncio


class FakeLight:
    """Mock light for testing scene runner."""
    def __init__(self, role):
        self.role = role
        self.commands = []

    async def send(self, mode, params):
        self.commands.append((mode, dict(params)))


def test_scene_runner_generative():
    code = '''
name = "Gen Test"
fps = 100

def render(tick, lights, params, audio=None):
    return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
'''
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    scene = neewer_scenes.load_scene(path)

    light = FakeLight("key")
    runner = neewer_scenes.SceneRunner(scene, {"key": light}, max_ticks=5)
    asyncio.get_event_loop().run_until_complete(runner.run())

    assert len(light.commands) == 5
    assert all(c[1]["brightness"] == 50 for c in light.commands)
    os.unlink(path)


def test_scene_runner_scripted():
    data = {
        "name": "Quick Test",
        "duration": "0.2s",
        "loop": False,
        "targets": ["all"],
        "steps": [
            {"at": "0s", "all": {"mode": "cct", "brightness": 80, "temp": 5600}},
            {"at": "0.1s", "all": {"mode": "cct", "brightness": 40, "temp": 3200}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)

    light = FakeLight("key")
    runner = neewer_scenes.SceneRunner(scene, {"key": light})
    asyncio.get_event_loop().run_until_complete(runner.run())

    # Should have received at least 2 commands (one per step)
    assert len(light.commands) >= 2
    os.unlink(path)


def test_list_scenes_empty(tmp_path):
    result = neewer_scenes.list_scenes(dirs=[str(tmp_path)])
    assert result == []


def test_list_scenes_finds_files(tmp_path):
    (tmp_path / "test.yaml").write_text("name: test")
    (tmp_path / "gen.py").write_text("name = 'gen'")
    (tmp_path / "_hidden.py").write_text("skip")
    (tmp_path / "readme.txt").write_text("skip")
    result = neewer_scenes.list_scenes(dirs=[str(tmp_path)])
    basenames = [os.path.basename(p) for p in result]
    assert "test.yaml" in basenames
    assert "gen.py" in basenames
    assert "_hidden.py" not in basenames
    assert "readme.txt" not in basenames
